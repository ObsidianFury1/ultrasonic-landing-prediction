/*
 * 03_three_sequential.ino — incremental firmware sketch 3 of 5
 * 3D Ultrasonic Projectile Landing-Prediction System (CLAUDE.md S3-S4)
 *
 * Purpose: drive all THREE sensors from ONE absolute scheduler. The schedule is
 *          round-robin, one sensor per 18 ms slot:
 *            slot 0 -> S1 (t),  slot 1 -> S2 (t+18ms),  slot 2 -> S3 (t+36ms),
 *          repeating with a full-triplet period of 54 ms. A single scheduler
 *          (one next_slot_us advanced by 18 ms each slot) — NOT three
 *          independent ones — guarantees the fixed inter-sensor offsets.
 *
 *   Pin map (CLAUDE.md S3, do not deviate):
 *     S1 TRIG=D2 ECHO=D3 | S2 TRIG=D4 ECHO=D5 | S3 TRIG=D6 ECHO=D7
 *
 * BENCH PASS CRITERION (CLAUDE.md S4, sketch 03 — hand-check after upload):
 *   Readings change independently per sensor; the firing order is verifiable by
 *   blocking each sensor's beam in turn and watching ONLY that sensor's reading
 *   change (sensor=1/2/3 lines). A swapped sensor identity here would silently
 *   corrupt trilateration later, so confirm each label maps to the right pod.
 *
 * Firmware rules (CLAUDE.md S4): plain digitalWrite/pulseIn/micros() only, no
 *   interrupts, no timer libraries. TRIG pulse LOW 2us -> HIGH 10us -> LOW.
 *   Rigid equal 18 ms slots (do NOT jitter — A2). Serial 115200 baud.
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
  digitalWrite(TRIG_PIN[s], HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN[s], LOW);

  unsigned long echo_us = pulseIn(ECHO_PIN[s], HIGH, TIMEOUT_US);  // 0 on timeout

  Serial.print("sensor=");
  Serial.print(s + 1);          // 1-based sensor id (S1/S2/S3)
  Serial.print("  echo=");
  Serial.println(echo_us);

  s = (s + 1) % N_SENSORS;       // advance round-robin S1 -> S2 -> S3 -> S1
  next_slot_us += SLOT_US;       // schedule the next 18 ms boundary (no drift)
}
