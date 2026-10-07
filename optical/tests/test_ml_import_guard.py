"""Import-guard test (WO-OPT-2 Stage 1, Optical.md §0.1/§10).

Proves the CORE pipeline never depends on the optional ML stack: in a child process where
importing `ultralytics`/`torch`/`torchvision` raises ImportError, (a) `optical.detect_ml`
still imports, (b) instantiating `YoloDetector` raises the clear `MLDetectorUnavailable`
(not a bare deep ImportError), and (c) the ENTIRE core test suite still collects and passes.

Runs in a subprocess so the import block cannot contaminate this process's already-imported
modules; the child re-runs pytest over `tests/` with the two ML-only test files excluded.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Child program: install an import hook that blocks the ML stack, prove detect_ml degrades
# cleanly, then run the core suite (ML test files excluded) and exit with its return code.
_CHILD = textwrap.dedent(
    """
    import builtins, sys
    _real_import = builtins.__import__
    _BLOCKED = {"ultralytics", "torch", "torchvision"}
    def _guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in _BLOCKED:
            raise ImportError("blocked by import-guard test: " + name)
        return _real_import(name, *args, **kwargs)
    builtins.__import__ = _guarded_import

    # sanity: torch is genuinely unreachable now
    try:
        import torch
        print("GUARD-FAIL: torch was importable"); sys.exit(3)
    except ImportError:
        pass

    # (a) detect_ml imports WITHOUT the ML stack (import is lazy, inside the constructor)
    import optical.detect_ml as dm

    # (b) instantiating raises the clear, specific error - not a bare ImportError
    try:
        dm.YoloDetector(model="yolo11n.pt")
        print("GUARD-FAIL: YoloDetector instantiated without ultralytics"); sys.exit(4)
    except dm.MLDetectorUnavailable:
        pass
    except ImportError:
        print("GUARD-FAIL: bare ImportError surfaced instead of MLDetectorUnavailable")
        sys.exit(5)

    # (c) the core suite still collects and passes with the ML stack blocked
    import pytest
    rc = pytest.main([
        "tests", "-q", "-p", "no:cacheprovider",
        "--ignore=tests/test_detect_ml.py",
        "--ignore=tests/test_ml_import_guard.py",
    ])
    sys.exit(int(rc))
    """
)


def test_core_suite_passes_without_ultralytics():
    proc = subprocess.run([sys.executable, "-c", _CHILD], cwd=str(ROOT),
                          capture_output=True, text=True)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
    print("\n[import-guard] child output tail:\n" + tail)
    assert "GUARD-FAIL" not in proc.stdout, tail
    assert proc.returncode == 0, f"core suite failed with ML blocked (rc={proc.returncode}):\n{tail}"
    assert "passed" in proc.stdout
