/*
 * 02_timeout_discipline.ino — incremental firmware sketch 2 of 5
 * 3D Ultrasonic Projectile Landing-Prediction System (CLAUDE.md S3-S4)
 *
 * Purpose: introduce the 18 ms SLOT and the bounded timeout. Same single sensor
 *          as sketch 01 (S1 on TRIG=D2, ECHO=D3), but:
 *            - pulseIn timeout = 12500 us (the flight value, CLAUDE.md A1);
 *            - each reading owns an exact 18 ms slot, held by an ABSOLUTE
 *              scheduler (next_slot_us += 18000) with a busy-wait to the
 *              boundary — NEVER a relative delay (no cumulative drift).
 *          Point the sensor at open sky or a soft target to force timeouts and
 *          confirm the no-echo sentinel prints as a literal 0.
 *
 * BENCH PASS CRITERION (CLAUDE.md S4, sketch 02 — hand-check after upload):
 *   (a) Forced timeouts print the literal value 0.
 *   (b) Slot period over 1000 cycles = 18.000 ms with only microsecond-level
 *       jitter and NO drift. Watch the printed "dt" column (us since the
 *       previous fire): it must sit at ~18000 every line, and the absolute
 *       time after 1000 cycles must equal start + 1000 * 18000 us (no creep).
 *
 * Firmware rules (CLAUDE.md S4): plain digitalWrite/pulseIn/micros() only, no
 *   interrupts, no timer libraries. TRIG pulse LOW 2us -> HIGH 10us -> LOW.
 *   Keep the rigid, equal 18 ms slots — do NOT jitter them (A2): a fixed
 *   schedule maps any static reflector to a static, subtractable apparent range.
 *   Serial 115200 baud (do NOT raise — see CLAUDE.md S12).
 */

const uint8_t S1_TRIG = 2;          // S1 TRIG -> D2 (CLAUDE.md S3 pin map)
const uint8_t S1_ECHO = 3;          // S1 ECHO -> D3

const unsigned long SLOT_US    = 18000UL;   // 18 ms slot (CLAUDE.md S2 slot_ms)
const unsigned long TIMEOUT_US = 12500UL;   // 12.5 ms pulse timeout (CLAUDE.md A1)

unsigned long next_slot_us;         // absolute boundary of the current slot
unsigned long prev_fire_us = 0;     // micros() of the previous fire (for dt display)
unsigned long cycle = 0;            // slot counter

void setup() {
  Serial.begin(115200);
  pinMode(S1_TRIG, OUTPUT);
  pinMode(S1_ECHO, INPUT);
  digitalWrite(S1_TRIG, LOW);
  next_slot_us = micros();          // first slot boundary = now
}

void loop() {
  // --- wait for this slot's boundary (absolute, no-drift; signed cast handles
  //     the micros() 32-bit rollover correctly) ---
  while ((long)(micros() - next_slot_us) < 0) {
    /* busy-wait */
  }

  // --- trigger pulse: LOW 2us -> HIGH 10us -> LOW ---
  digitalWrite(S1_TRIG, LOW);
  delayMicroseconds(2);
  unsigned long t_fire = micros();  // fire instant (boundary-aligned)
  digitalWrite(S1_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(S1_TRIG, LOW);

  // pulseIn returns the echo width in us, or 0 on timeout — print 0 verbatim.
  unsigned long echo_us = pulseIn(S1_ECHO, HIGH, TIMEOUT_US);

  unsigned long dt = (cycle == 0) ? 0 : (t_fire - prev_fire_us);
  prev_fire_us = t_fire;

  Serial.print("echo=");
  Serial.print(echo_us);
  Serial.print("  dt=");
  Serial.print(dt);
  Serial.print("  cyc=");
  Serial.println(cycle);

  cycle++;
  next_slot_us += SLOT_US;          // schedule the next boundary (no drift)
}
