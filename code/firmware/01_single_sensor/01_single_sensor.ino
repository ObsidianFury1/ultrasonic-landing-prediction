/*
 * 01_single_sensor.ino — incremental firmware sketch 1 of 5
 * 3D Ultrasonic Projectile Landing-Prediction System (CLAUDE.md S3-S4)
 *
 * Purpose: prove one HC-SR04 sensor + the wiring + the constants are correct.
 *          One sensor (S1) on TRIG=D2, ECHO=D3. Fire once per 100 ms. Print the
 *          raw echo time (us) and a DISPLAY-ONLY distance computed at an assumed
 *          v = 343 m/s. The distance is for the human at the bench only; the real
 *          distance math (with the session temperature) happens in Python, never
 *          on the Arduino (CLAUDE.md S0.4).
 *
 * BENCH PASS CRITERION (CLAUDE.md S4, sketch 01 — hand-check after upload):
 *   Flat wall at tape-measured 0.50 / 1.00 / 1.50 m reads within +/- 1 cm.
 *   (The tape validates CORRECTNESS — round-trip /2, constants, unit slips —
 *   not mm accuracy; real accuracy/noise numbers come from the S7 static
 *   characterization.)
 *
 * Firmware rules (CLAUDE.md S4): plain digitalWrite/pulseIn/micros() only, no
 *   interrupts, no timer libraries. TRIG pulse LOW 2us -> HIGH 10us -> LOW.
 *   Serial 115200 baud (do NOT raise — see CLAUDE.md S12 audit disposition).
 *
 * NOTE: this sketch deliberately uses delay(100) and a generous pulseIn timeout.
 *   The 18 ms slot + 12500 us timeout DISCIPLINE is the increment introduced in
 *   sketch 02; here we only check basic ranging correctness.
 */

const uint8_t S1_TRIG = 2;   // S1 TRIG -> D2  (CLAUDE.md S3 pin map, do not deviate)
const uint8_t S1_ECHO = 3;   // S1 ECHO -> D3

// Generous timeout for the bench check only. A 1.5 m wall round-trips in
// ~8.75 ms at 343 m/s; 25000 us (~4.3 m) leaves ample margin. Sketch 02
// tightens this to the 12500 us flight value.
const unsigned long TIMEOUT_US = 25000UL;

void setup() {
  Serial.begin(115200);
  pinMode(S1_TRIG, OUTPUT);
  pinMode(S1_ECHO, INPUT);
  digitalWrite(S1_TRIG, LOW);
}

void loop() {
  // --- trigger pulse: LOW 2us -> HIGH 10us -> LOW ---
  digitalWrite(S1_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(S1_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(S1_TRIG, LOW);

  // pulseIn returns the echo HIGH width in us, or 0 on timeout (no echo).
  unsigned long echo_us = pulseIn(S1_ECHO, HIGH, TIMEOUT_US);

  // Display-only distance at v = 343 m/s: d = v * t / 2 = echo_us * 0.0001715 m.
  float d_m = echo_us * 0.0001715f;

  Serial.print("echo_us=");
  Serial.print(echo_us);
  Serial.print("  d=");
  Serial.print(d_m, 3);
  Serial.println(" m");

  delay(100);   // ~10 readings/s; timing discipline arrives in sketch 02
}
