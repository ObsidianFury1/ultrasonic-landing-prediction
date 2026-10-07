"""Local ground-truth entry server for the HTML reports (website.md sections 6.2,
6.2.1, 6.6).

A stdlib-only HTTP server (no Flask/FastAPI) bound to 127.0.0.1 on an ephemeral
port. It serves a session's report.html in INPUT mode, accepts the two tape
readings via POST, runs the SAME audited solve the terminal uses
(run_session.solve_ground_truth), writes the ground_truth block ATOMICALLY
(append_ground_truth.update_session_ground_truth), reads it back, and regenerates
the per-throw report (now frozen) and the campaign dashboard from the re-read
values -- so the number shown on screen is provably the one on disk.

Modes (section 6.6):
  --session <id>   serve one session's input page; POST freezes it.
  --pending        serve an index of every session awaiting ground truth.

Security (section 6.2): localhost only; the client sends only the two tape floats
and a session id; the server maps the id to a directory itself and never accepts
a path from the client.

Usage (from the project root, Windows):
    .\\venv\\Scripts\\python.exe scripts\\serve_report.py --session 2026-06-11_T01
    .\\venv\\Scripts\\python.exe scripts\\serve_report.py --pending
"""

import argparse
import json
import math
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_session  # reuse solve_ground_truth + load_config
from append_ground_truth import update_session_ground_truth
from pipeline.web_report import render_campaign_report, render_session_report


# ---------------------------------------------------------------------------
# Testable core (no sockets) -- the POST logic + session helpers
# ---------------------------------------------------------------------------

def find_session_dir(sessions_root, session_id) -> Path:
    """Map a session id to its directory SAFELY: reject path separators / '..',
    require an existing session.json. Never trust a client-supplied path."""
    if (not session_id or "/" in session_id or "\\" in session_id
            or ".." in session_id):
        raise KeyError(session_id)
    d = Path(sessions_root) / session_id
    if not (d / "session.json").is_file():
        raise KeyError(session_id)
    return d


def pending_sessions(sessions_root):
    """Every session under sessions_root with a prediction and no ground truth,
    as a sorted list of (session_id, dir)."""
    root = Path(sessions_root)
    out = []
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        sj = d / "session.json"
        if not sj.is_file():
            continue
        try:
            meta = json.loads(sj.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        raw = (meta.get("prediction") or {}).get("raw")
        if raw and raw.get("x_m") is not None and not meta.get("ground_truth"):
            out.append((d.name, d))
    return out


def compute_error_mm(pred, gt):
    """2-D Euclidean error in mm from on-disk values (display arithmetic)."""
    if not pred or not gt or pred.get("x_m") is None or gt.get("x_m") is None:
        return None
    return 1000.0 * math.hypot(pred["x_m"] - gt["x_m"], pred["z_m"] - gt["z_m"])


_SENSORS = {"S1", "S2", "S3"}


def handle_ground_truth(sessions_root, session_id, L_centroid, sensors, L_a, L_b,
                        config):
    """(section 6.2, v2.3 G1) Core POST handler. Returns (http_status, body_dict).

    Centroid + 2 chosen sensors -> least-squares multilateration (no pred_z / no
    mirror). 409 if no prediction; 422 on an invalid sensor selection or a
    degenerate solve (nothing written); 500 on a write failure (nothing partial,
    section 6.2.1); 200 with values built from the RE-READ session.json on success.
    """
    try:
        session_dir = find_session_dir(sessions_root, session_id)
    except KeyError:
        return 404, {"error": f"unknown session '{session_id}'"}
    session_json = session_dir / "session.json"

    with open(session_json, encoding="utf-8") as f:
        meta = json.load(f)
    raw = (meta.get("prediction") or {}).get("raw")
    if not raw or raw.get("x_m") is None:
        return 409, {"error": "Process this throw before adding ground truth."}

    # Validate the chosen pair: exactly two distinct of {S1,S2,S3} (section 5.1).
    if (not isinstance(sensors, (list, tuple)) or len(sensors) != 2
            or sensors[0] == sensors[1] or any(s not in _SENSORS for s in sensors)):
        return 422, {"error": "choose exactly two distinct sensors of S1/S2/S3"}

    refs = [{"name": sensors[0], "L": L_a}, {"name": sensors[1], "L": L_b}]
    try:
        gt_block = run_session.solve_ground_truth(float(L_centroid), refs, config)
    except (ValueError, TypeError, KeyError) as exc:
        return 422, {"error": str(exc)}

    try:
        update_session_ground_truth(session_json, gt_block)
    except Exception as exc:                       # noqa: BLE001 (report any failure)
        return 500, {"error": f"write failed: {exc}"}

    # Read back -- do not trust the in-memory copy (section 6.2.1).
    with open(session_json, encoding="utf-8") as f:
        meta2 = json.load(f)
    gt2 = meta2["ground_truth"]
    raw2 = meta2["prediction"]["raw"]
    corr2 = meta2["prediction"].get("corrected")
    body = {
        "r": gt2["r_m"], "theta": gt2["theta_deg"],
        "x": gt2["x_m"], "z": gt2["z_m"],
        "error_mm_raw": compute_error_mm(raw2, gt2),
        "residual_m": gt2.get("ls_residual_m"),
        "cond_warn": gt2.get("cond_warn"),
        "persisted": True,
    }
    err_corr = compute_error_mm(corr2, gt2) if corr2 else None
    if err_corr is not None:
        body["error_mm_corrected"] = err_corr

    # Regenerate the now-frozen report + the campaign from the persisted state.
    # The GT is already durably written; regeneration is best-effort so a plot
    # error never reports a save as failed.
    try:
        render_session_report(session_dir, config)
        render_campaign_report(sessions_root, config)
    except Exception as exc:                       # noqa: BLE001
        print(f"  warning: report regeneration failed after a saved GT: {exc}")
    return 200, body


def pending_index_html(sessions_root) -> str:
    """A tiny self-contained index of awaiting-ground-truth sessions (section 6.6)."""
    items = pending_sessions(sessions_root)
    rows = "".join(
        f'<li><a href="/s/{sid}">{sid}</a></li>' for sid, _ in items
    ) or '<li class="none">No sessions awaiting ground truth.</li>'
    return (
        "<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<title>Pending ground truth</title><style>"
        "body{background:#070d17;color:#e9f5f6;font-family:'Segoe UI',system-ui,sans-serif;"
        "max-width:720px;margin:0 auto;padding:24px}"
        "h1{font-size:18px}a{color:#46e3c6;font-family:ui-monospace,Consolas,monospace}"
        "li{margin:6px 0}.none{color:#7e98a7;list-style:none}"
        "</style></head><body><h1>Sessions awaiting ground truth</h1>"
        f"<ul>{rows}</ul></body></html>"
    )


# ---------------------------------------------------------------------------
# HTTP shell
# ---------------------------------------------------------------------------

class ReportServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the session context the handler needs."""

    def __init__(self, addr, config, sessions_root, session_id):
        super().__init__(addr, _Handler)
        self.config = config
        self.sessions_root = Path(sessions_root)
        self.session_id = session_id
        # Set on the first successful ground-truth POST. run_session.py's --web
        # flow waits on this to know the operator finished entering GT; inert for
        # the standalone --session/--pending CLI modes (nobody waits there).
        self.gt_event = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    server_version = "ReportServer/1.0"

    def log_message(self, fmt, *args):             # quiet, ASCII-only console
        return

    # -- response helpers --
    def _send(self, status, body_bytes, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_json(self, status, obj):
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _send_html(self, status, html):
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_report(self, session_id, regenerate_input=False):
        try:
            d = find_session_dir(self.server.sessions_root, session_id)
        except KeyError:
            self._send_json(404, {"error": f"unknown session '{session_id}'"})
            return
        html_path = d / "report.html"
        if regenerate_input or not html_path.is_file():
            render_session_report(d, self.server.config)
        self._send_html(200, html_path.read_text(encoding="utf-8"))

    # -- routes --
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"ok": True,
                                  "session_id": self.server.session_id})
        elif path == "/":
            if self.server.session_id:
                self._serve_report(self.server.session_id)
            else:
                self._send_html(200, pending_index_html(self.server.sessions_root))
        elif path.startswith("/s/"):
            self._serve_report(path[3:], regenerate_input=True)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/ground-truth":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            sid = payload["session_id"]
            lc = payload["L_centroid"]
            sensors = payload["sensors"]
            l_a, l_b = payload["L_a"], payload["L_b"]
        except (ValueError, KeyError, TypeError):
            self._send_json(400, {"error": "bad request body"})
            return
        status, body = handle_ground_truth(
            self.server.sessions_root, sid, lc, sensors, l_a, l_b,
            self.server.config)
        if status == 200 and body.get("persisted"):
            self.server.gt_event.set()         # signal the live --web waiter
        self._send_json(status, body)


def start_background(sessions_root, config, session_id):
    """Bind 127.0.0.1:<ephemeral> and serve in a daemon thread; return
    (httpd, thread, url). Renders the session's input page first when a session id
    is given (so its POST target is live). The single place the server is started
    -- reused by serve() below and by run_session.py's --web flow."""
    sessions_root = Path(sessions_root)
    if session_id is not None:
        render_session_report(find_session_dir(sessions_root, session_id), config)
    httpd = ReportServer(("127.0.0.1", 0), config, sessions_root, session_id)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    return httpd, thread, url


def serve(sessions_root, config, *, session_id=None, open_browser=True):
    """Serve until Ctrl-C (the standalone CLI lifecycle), reusing start_background."""
    httpd, thread, url = start_background(sessions_root, config, session_id)
    where = f"session {session_id}" if session_id else "pending index"
    print(f"serving {where} on {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:                          # noqa: BLE001 (headless ok)
            pass
    try:
        thread.join()                              # block until Ctrl-C
    except KeyboardInterrupt:
        print("stopping server")
    finally:
        httpd.shutdown()
        httpd.server_close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", help="serve one session's input page")
    g.add_argument("--pending", action="store_true",
                   help="serve an index of sessions awaiting ground truth")
    p.add_argument("--sessions-dir", type=Path, default=Path("data") / "sessions")
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--no-browser", action="store_true",
                   help="do not open a browser window")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = run_session.load_config(args.config)
    if args.pending:
        serve(args.sessions_dir, config, session_id=None,
              open_browser=not args.no_browser)
    else:
        try:
            find_session_dir(args.sessions_dir, args.session)
        except KeyError:
            sys.exit(f"no session '{args.session}' under {args.sessions_dir}")
        serve(args.sessions_dir, config, session_id=args.session,
              open_browser=not args.no_browser)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted, exiting")
