/*
  IVHM motor rig firmware (OB4) - ESP32 (Arduino core 3.x, ESP-IDF 5.x underneath)

  Sensors
    ADXL345   SPI @ 4 MHz, ODR 3200 Hz, +/-16 g full resolution, FIFO stream mode (watermark 16)
    ACS712    analog -> ADC1 continuous (DMA) @ 10 kHz, averaged in pairs -> 5 kHz
    Hall      digital pulse on HALL_PIN (1 pulse / rev), period measured in an ISR

  Streams framed binary packets over USB serial @ 921600 baud:
    0xA5 0x5A | type u8 | seq u16 | t_us u32 | n u16 | payload | crc16-ccitt (over type..payload)
    type 1 ACCEL  : n x (int16 x, int16 y, int16 z)   raw LSB (3.9 mg/LSB full-res)
    type 2 CURRENT: n x uint16 millivolts (pair-averaged)
    type 3 RPM    : uint32 last_period_us, uint32 pulse_count
    type 4 STATUS : uint32 adxl_fifo_full_events, uint32 adc_overruns, uint32 tx_drops
  t_us = device micros() at the time the block was read (end of block).

  Wiring (default pins, ESP32 DevKit V1):
    ADXL345: CS=5, SCK=18, MISO=19, MOSI=23, VCC=3V3, GND
    ACS712 : OUT -> divider (10k/20k) -> GPIO34 (ADC1_CH6); ACS712 powered from 5 V
    Hall   : A3144 OUT -> GPIO27 (10k pull-up to 3V3)
  NOT YET COMPILED OR RUN ON HARDWARE - verify with rig/check_timing.py before any recording.
*/
#include <Arduino.h>
#include <SPI.h>
#include "esp_adc/adc_continuous.h"

#define ADXL_CS   5
#define HALL_PIN  27
#define BAUD      921600
#define ADC_CH    ADC_CHANNEL_6        // GPIO34
#define ADC_RATE  10000
#define ADC_FRAME 256                  // bytes per DMA frame (SOC_ADC_DIGI_RESULT_BYTES each)

static SPISettings adxlSPI(4000000, MSBFIRST, SPI_MODE3);
static uint16_t seqNo = 0;
static volatile uint32_t hallPeriod = 0, hallCount = 0, hallLast = 0;
static uint32_t fifoFull = 0, adcOverrun = 0, txDrops = 0;
static adc_continuous_handle_t adcHandle = NULL;

// ------------------------------------------------------------------ framing
static uint16_t crc16(const uint8_t *d, size_t n, uint16_t c = 0xFFFF) {
  while (n--) { c ^= (uint16_t)(*d++) << 8; for (int i = 0; i < 8; i++) c = (c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1; }
  return c;
}
static void sendFrame(uint8_t type, const uint8_t *payload, uint16_t len, uint16_t n) {
  uint8_t hdr[11];
  uint32_t t = micros();
  hdr[0] = 0xA5; hdr[1] = 0x5A; hdr[2] = type;
  memcpy(hdr + 3, &seqNo, 2); memcpy(hdr + 5, &t, 4); memcpy(hdr + 9, &n, 2);
  uint16_t c = crc16(hdr + 2, 9);
  c = crc16(payload, len, c);
  if (Serial.availableForWrite() < (int)(len + 13)) { txDrops++; seqNo++; return; }
  Serial.write(hdr, 11); Serial.write(payload, len); Serial.write((uint8_t *)&c, 2);
  seqNo++;
}

// ------------------------------------------------------------------ ADXL345
static void adxlWrite(uint8_t reg, uint8_t v) {
  SPI.beginTransaction(adxlSPI); digitalWrite(ADXL_CS, LOW);
  SPI.transfer(reg & 0x3F); SPI.transfer(v);
  digitalWrite(ADXL_CS, HIGH); SPI.endTransaction();
}
static uint8_t adxlRead(uint8_t reg) {
  SPI.beginTransaction(adxlSPI); digitalWrite(ADXL_CS, LOW);
  SPI.transfer(0x80 | (reg & 0x3F)); uint8_t v = SPI.transfer(0);
  digitalWrite(ADXL_CS, HIGH); SPI.endTransaction();
  return v;
}
static void adxlReadXYZ(int16_t *xyz) {
  SPI.beginTransaction(adxlSPI); digitalWrite(ADXL_CS, LOW);
  SPI.transfer(0xC0 | 0x32);
  uint8_t b[6]; for (int i = 0; i < 6; i++) b[i] = SPI.transfer(0);
  digitalWrite(ADXL_CS, HIGH); SPI.endTransaction();
  xyz[0] = (int16_t)(b[1] << 8 | b[0]); xyz[1] = (int16_t)(b[3] << 8 | b[2]); xyz[2] = (int16_t)(b[5] << 8 | b[4]);
}

// ------------------------------------------------------------------ Hall ISR
void IRAM_ATTR hallISR() {
  uint32_t now = micros();
  if (hallLast) hallPeriod = now - hallLast;
  hallLast = now; hallCount++;
}

// ------------------------------------------------------------------ ADC continuous
static bool IRAM_ATTR adcOvf(adc_continuous_handle_t h, const adc_continuous_evt_data_t *e, void *u) {
  adcOverrun++; return false;
}
static void adcStart() {
  adc_continuous_handle_cfg_t hc = {.max_store_buf_size = 4096, .conv_frame_size = ADC_FRAME};
  ESP_ERROR_CHECK(adc_continuous_new_handle(&hc, &adcHandle));
  adc_digi_pattern_config_t pat = {};
  pat.atten = ADC_ATTEN_DB_12; pat.channel = ADC_CH; pat.unit = ADC_UNIT_1; pat.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
  adc_continuous_config_t cfg = {};
  cfg.pattern_num = 1; cfg.adc_pattern = &pat; cfg.sample_freq_hz = ADC_RATE;
  cfg.conv_mode = ADC_CONV_SINGLE_UNIT_1; cfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;
  ESP_ERROR_CHECK(adc_continuous_config(adcHandle, &cfg));
  adc_continuous_evt_cbs_t cbs = {}; cbs.on_pool_ovf = adcOvf;
  ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(adcHandle, &cbs, NULL));
  ESP_ERROR_CHECK(adc_continuous_start(adcHandle));
}

void setup() {
  Serial.setTxBufferSize(16384);
  Serial.begin(BAUD);
  pinMode(ADXL_CS, OUTPUT); digitalWrite(ADXL_CS, HIGH);
  SPI.begin(18, 19, 23, ADXL_CS);
  delay(10);
  if (adxlRead(0x00) != 0xE5) { while (1) { Serial.println("ADXL345 not found (DEVID != 0xE5)"); delay(1000); } }
  adxlWrite(0x2D, 0x00);      // standby
  adxlWrite(0x31, 0x0B);      // full resolution, +/-16 g
  adxlWrite(0x2C, 0x0F);      // ODR 3200 Hz
  adxlWrite(0x38, 0x80 | 16); // FIFO stream, watermark 16
  adxlWrite(0x2D, 0x08);      // measure
  pinMode(HALL_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL_PIN), hallISR, FALLING);
  adcStart();
}

void loop() {
  static int16_t acc[32 * 3];
  static uint16_t cur[256];
  static uint32_t lastRpm = 0, lastStat = 0;
  // accelerometer FIFO
  uint8_t fs = adxlRead(0x39);
  uint8_t nfifo = fs & 0x3F;
  if (nfifo >= 31) fifoFull++;
  if (nfifo >= 16) {
    for (int i = 0; i < nfifo && i < 32; i++) adxlReadXYZ(acc + 3 * i);
    sendFrame(1, (uint8_t *)acc, nfifo * 6, nfifo);
  }
  // current ADC (non-blocking read of available DMA frames)
  uint8_t buf[ADC_FRAME]; uint32_t got = 0;
  if (adc_continuous_read(adcHandle, buf, ADC_FRAME, &got, 0) == ESP_OK && got) {
    int ns = got / SOC_ADC_DIGI_RESULT_BYTES, m = 0;
    for (int i = 0; i + 1 < ns; i += 2) {
      adc_digi_output_data_t *a = (adc_digi_output_data_t *)&buf[i * SOC_ADC_DIGI_RESULT_BYTES];
      adc_digi_output_data_t *b = (adc_digi_output_data_t *)&buf[(i + 1) * SOC_ADC_DIGI_RESULT_BYTES];
      uint32_t raw = (a->type1.data + b->type1.data) / 2;
      cur[m++] = (uint16_t)((raw * 3300UL) / 4095UL);   // approx. mV; calibrate on rig
    }
    if (m) sendFrame(2, (uint8_t *)cur, m * 2, m);
  }
  uint32_t now = millis();
  if (now - lastRpm >= 100) {
    uint32_t p[2]; noInterrupts(); p[0] = hallPeriod; p[1] = hallCount; interrupts();
    sendFrame(3, (uint8_t *)p, 8, 1); lastRpm = now;
  }
  if (now - lastStat >= 1000) {
    uint32_t s[3] = {fifoFull, adcOverrun, txDrops};
    sendFrame(4, (uint8_t *)s, 12, 1); lastStat = now;
  }
}
