/*
 * 05_timing_verify.ino — incremental firmware sketch 5 of 5  ===> FLIGHT FIRMWARE
 * 3D Ultrasonic Projectile Landing-Prediction System (CLAUDE.md S3-S4)
 *
 * Purpose: this is the firmware that actually FLIES. It is byte-for-byte
 *          identical to sketch 04 (final CSV protocol, one scheduler, three
 *          sensors, 18 ms / 54 ms timing, TRIG-instant timestamp) EXCEPT the
 *          startup header version is fw=05. The test for this sketch lives on
 *          the PC: scripts/verify_timing.py logs the stream and asserts the
 *          timing is exact.
 *
 *          One line per reading:   sensor_id,echo_us,timestamp_us\n
 *          timestamp_us = micros() at the TRIG instant (HIGH edge), NOT mid-echo
 *          (the mid-echo correction t_trig + echo/2 is Python's job — R3, S5.1).
 *
 *   Startup header: # fw=05,slot_ms=18,timeout_us=12500
 *   Pin map (CLAUDE.md S3): S1 D2/D3 | S2 D4/D5 | S3 D6/D7
 *
 * BENCH PASS CRITERION (CLAUDE.md S4, sketch 05 — PC-side via
 * scripts/verify_timing.py over >= 1000 logged lines):
 *   (a) per-sensor period = 54.000 ms +/- 50 us;
 *   (b) S2 - S1 = 18 ms and S3 - S1 = 36 ms, each +/- 50 us;
 *   (c) timestamps strictly monotonic after unwrapping the micros() rollover;
 *   (d) zero parse errors.
 *   verify_timing.py prints a PASS/FAIL line for each of the four checks.
 *
 * Firmware rules (CLAUDE.md S4): plain digitalWrite/pulseIn/micros() only, no
 *   interrupts, no timer libraries. TRIG pulse LOW 2us -> HIGH 10us -> LOW.
 *   Rigid equal 18 ms slots (do NOT jitter — A2). Serial 115200 baud (do NOT
 *   raise — see CLAUDE.md S12). micros() overflows after ~71.6 min; Python
 *   unwraps the rollover (R10c), the firmware just streams raw micros().
 */

const uint8_t N_SENSORS = 3;
const uint8_t TRIG_PIN[N_SENSORS] = {2, 4, 6};   // S1, S2, S3 TRIG -> D2, D4, D6
const uint8_t ECHO_PIN[N_SENSORS] = {3, 5, 7};   // S1, S2, S3 ECHO -> D3, D5, D7

const unsigned long SLOT_US    = 18000UL;   // 18 ms per sensor slot
const unsigned long TIMEOUT_US = 12500UL;   // 12.5 ms pulse timeout (CLAUDE.md A1)

unsigned long next_slot_us;     // absolute boundary of the current slot
uint8_t s = 0;                  // current sensor index 0..2 (S1..S3)

void setup() {
  Serial.begin(115200);
  // Startup header (parsed/validated by pipeline/process_throw.py against config).
  Serial.println("# fw=05,slot_ms=18,timeout_us=12500");
  for (uint8_t i = 0; i < N_SENSORS; i++) {
    pinMode(TRIG_PIN[i], OUTPUT);
    pinMode(ECHO_PIN[i], INPUT);
    digitalWrite(TRIG_PIN[i], LOW);
  }
  next_slot_us = micros();      // first slot boundary = now
}

void loop() {
  // --- wait for this slot's boundary (absolute, no-drift; signed cast handles
  //     the micros() rollover) ---
  while ((long)(micros() - next_slot_us) < 0) {
    /* busy-wait */
  }

  // --- fire the current sensor: TRIG LOW 2us -> HIGH 10us -> LOW ---
  digitalWrite(TRIG_PIN[s], LOW);
  delayMicroseconds(2);
  unsigned long t_trig = micros();   // captured just BEFORE the TRIG HIGH edge; the
                                     // ~few-us digitalWrite latency to the actual edge
                                     // is common-mode across sensors and far inside the
                                     // +/-50 us verify budget. This is the CSV timestamp.
  digitalWrite(TRIG_PIN[s], HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN[s], LOW);

  unsigned long echo_us = pulseIn(ECHO_PIN[s], HIGH, TIMEOUT_US);  // 0 on timeout

  // CSV: sensor_id,echo_us,timestamp_us  (no spaces; 1-based sensor id)
  Serial.print(s + 1);
  Serial.print(',');
  Serial.print(echo_us);
  Serial.print(',');
  Serial.println(t_trig);

  s = (s + 1) % N_SENSORS;       // advance round-robin S1 -> S2 -> S3 -> S1
  next_slot_us += SLOT_US;       // schedule the next 18 ms boundary (no drift)
}
