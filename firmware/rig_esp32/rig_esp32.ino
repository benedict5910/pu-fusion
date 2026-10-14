// ESP32 bearing test-rig streamer. NOT COMPILED OR FLASHED YET - verify on hardware.
// Streams binary frames (format in src/pufusion/rig.py) at 921600 baud, 4 frames/s:
//   vibration  ADXL345 over SPI, 3200 Hz, one radial axis, full resolution (+-16 g)
//   current    ACS712-05B -> 10k/20k divider -> GPIO34, 5000 Hz
//   speed      Hall/IR pulse on GPIO27 (PULSES_PER_REV per revolution)
//   temperature DS18B20 on GPIO4 (1 Hz), bearing housing
//   bus voltage 100k/22k divider on GPIO35 (supply sag / motor-off detection)
// Libraries: OneWire, DallasTemperature. Board: ESP32 Dev Module (Arduino core 2.x or 3.x).
#include <SPI.h>
#include <OneWire.h>
#include <DallasTemperature.h>

const int PIN_CS = 5, PIN_CUR = 34, PIN_VBUS = 35, PIN_TACH = 27, PIN_TEMP = 4;
const int FS_CUR = 5000, N_VIB = 800, N_CUR = 1250;   // 0.25 s frames
const int PULSES_PER_REV = 1;
const float VBUS_SCALE = 3.3f / 4095.0f * (122.0f / 22.0f);
const uint8_t AXIS_OFFSET = 2;                          // 0 = X, 2 = Y, 4 = Z: pick the radial axis

// single-producer / single-consumer ring buffers
const int RV = 8192, RC = 16384;
volatile int16_t vibRing[RV]; volatile uint32_t vibHead = 0, vibTail = 0;
volatile uint16_t curRing[RC]; volatile uint32_t curHead = 0, curTail = 0;
volatile uint32_t tachCount = 0;

OneWire ow(PIN_TEMP); DallasTemperature ds(&ow);
SPISettings adxl(5000000, MSBFIRST, SPI_MODE3);

void IRAM_ATTR onTach() { tachCount++; }

void adxlWrite(uint8_t reg, uint8_t v) {
  SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
  SPI.transfer(reg); SPI.transfer(v);
  digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
}
uint8_t adxlRead(uint8_t reg) {
  SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
  SPI.transfer(reg | 0x80); uint8_t v = SPI.transfer(0);
  digitalWrite(PIN_CS, HIGH); SPI.endTransaction(); return v;
}

void vibTask(void*) {            // core 0: drain the 32-entry FIFO well before it overflows (10 ms at 3200 Hz)
  uint8_t b[6];
  for (;;) {
    uint8_t n = adxlRead(0x39) & 0x3F;
    for (uint8_t i = 0; i < n; i++) {
      SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
      SPI.transfer(0x32 | 0xC0);                 // read + multi-byte from DATAX0
      for (int k = 0; k < 6; k++) b[k] = SPI.transfer(0);
      digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
      vibRing[vibHead % RV] = (int16_t)(b[AXIS_OFFSET] | (b[AXIS_OFFSET + 1] << 8));
      vibHead++;
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

void curTask(void*) {            // core 1: paced ADC sampling at FS_CUR
  const uint32_t period = 1000000UL / FS_CUR;
  uint32_t next = micros();
  for (;;) {
    while ((int32_t)(micros() - next) < 0) {}
    curRing[curHead % RC] = analogRead(PIN_CUR);
    curHead++;
    next += period;
    if ((curHead & 1023) == 0) vTaskDelay(1);   // let the watchdog breathe (~5 Hz)
  }
}

uint16_t sum16(const uint8_t* p, size_t n, uint16_t s) { while (n--) s += *p++; return s; }

void setup() {
  Serial.begin(921600);
  pinMode(PIN_CS, OUTPUT); digitalWrite(PIN_CS, HIGH);
  SPI.begin(18, 19, 23, PIN_CS);
  adxlWrite(0x2D, 0x00);         // standby
  adxlWrite(0x31, 0x0B);         // full resolution, +-16 g (3.9 mg/LSB)
  adxlWrite(0x2C, 0x0F);         // 3200 Hz output rate
  adxlWrite(0x38, 0x80);         // FIFO stream mode
  adxlWrite(0x2D, 0x08);         // measure
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_CUR, ADC_11db);
  analogSetPinAttenuation(PIN_VBUS, ADC_11db);
  pinMode(PIN_TACH, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_TACH), onTach, FALLING);
  ds.begin(); ds.setWaitForConversion(false); ds.requestTemperatures();
  xTaskCreatePinnedToCore(vibTask, "vib", 4096, nullptr, 3, nullptr, 0);
  xTaskCreatePinnedToCore(curTask, "cur", 4096, nullptr, 3, nullptr, 1);
}

uint32_t seq = 0, lastTempMs = 0; float tempC = NAN;
int16_t vibOut[N_VIB]; uint16_t curOut[N_CUR];

void loop() {
  if (vibHead - vibTail < (uint32_t)N_VIB || curHead - curTail < (uint32_t)N_CUR) { delay(1); return; }
  for (int i = 0; i < N_VIB; i++) vibOut[i] = vibRing[(vibTail + i) % RV];
  for (int i = 0; i < N_CUR; i++) curOut[i] = curRing[(curTail + i) % RC];
  vibTail += N_VIB; curTail += N_CUR;
  if (vibHead - vibTail > RV / 2) vibTail = vibHead - N_VIB;      // fell behind: drop backlog
  if (curHead - curTail > RC / 2) curTail = curHead - N_CUR;

  uint32_t pulses = tachCount; tachCount = 0;
  float rpm = pulses * 240.0f / PULSES_PER_REV;                   // 4 frames per second
  if (millis() - lastTempMs > 1000) { tempC = ds.getTempCByIndex(0); ds.requestTemperatures(); lastTempMs = millis(); }
  float vbus = analogRead(PIN_VBUS) * VBUS_SCALE;

  uint8_t hdr[24]; uint32_t t = millis(); uint16_t nv = N_VIB, nc = N_CUR;
  memcpy(hdr, &seq, 4); memcpy(hdr + 4, &t, 4); memcpy(hdr + 8, &nv, 2); memcpy(hdr + 10, &nc, 2);
  memcpy(hdr + 12, &rpm, 4); memcpy(hdr + 16, &tempC, 4); memcpy(hdr + 20, &vbus, 4);
  uint16_t s = sum16(hdr, 24, 0);
  s = sum16((uint8_t*)vibOut, sizeof(vibOut), s);
  s = sum16((uint8_t*)curOut, sizeof(curOut), s);
  Serial.write((const uint8_t*)"RIG1", 4);
  Serial.write(hdr, 24);
  Serial.write((uint8_t*)vibOut, sizeof(vibOut));
  Serial.write((uint8_t*)curOut, sizeof(curOut));
  Serial.write((uint8_t*)&s, 2);
  seq++;
}
