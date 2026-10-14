// ESP32 bearing test-rig streamer, protocol RIG2 (parsed by src/pufusion/rig.py).
// Compile-checked with arduino-cli, esp32:esp32@3.3.12 (ESP-IDF 5.x). NOT yet run on hardware.
//
// Signals
//   vibration   ADXL345 over SPI @ 4 MHz (datasheet: >= 2 MHz needed for 3200 Hz ODR, max 5 MHz),
//               ODR 3200 Hz (bandwidth 1600 Hz), +-16 g full resolution, one radial axis, FIFO stream mode
//   current     ACS712-05B -> 10k/20k divider -> GPIO34 (ADC1_CH6)
//   bus voltage 100k/22k divider -> GPIO35 (ADC1_CH7)
//               both sampled by the ADC DMA engine (hardware-paced, no busy-wait):
//               20 kHz total (ESP32 minimum for continuous mode), pattern CH6,CH7 -> 10 kHz each;
//               current is averaged in pairs -> 5 kHz output; vbus averaged per frame.
//   speed       Hall sensor on GPIO27 (pulses counted, rate computed from the measured frame time)
//   temperature DS18B20 on GPIO4, 1 Hz
//
// Timing verification: every frame carries, for each stream, the absolute index of its first
// sample and an (index, micros) pair for the newest sample taken from the sensor. The host fits count vs.
// time to obtain the real sample rate, clock drift, jitter and gaps (scripts/rig_check_timing.py).
// ADXL345 overruns, ADC DMA pool overflows and ring-buffer drops are counted, never hidden.
//
// Libraries: OneWire, DallasTemperature. Board: "ESP32 Dev Module".
#include <Arduino.h>
#include <SPI.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <atomic>
#include "esp_adc/adc_continuous.h"

// ---------------------------------------------------------------- configuration
static const int PIN_CS = 5, PIN_SCK = 18, PIN_MISO = 19, PIN_MOSI = 23;
static const int PIN_TACH = 27, PIN_TEMP = 4;
static const adc_channel_t CH_CUR = ADC_CHANNEL_6;    // GPIO34
static const adc_channel_t CH_VBUS = ADC_CHANNEL_7;   // GPIO35
static const uint32_t SPI_HZ = 4000000;
static const uint32_t ADC_TOTAL_HZ = 20000;           // SOC_ADC_SAMPLE_FREQ_THRES_LOW on ESP32
static const uint32_t FRAME_US = 250000;              // 4 frames/s
static const int PULSES_PER_REV = 1;
static const uint8_t AXIS_OFFSET = 2;                 // 0 = X, 2 = Y, 4 = Z: pick the radial axis
static const uint16_t MAX_VIB = 1200, MAX_CUR = 1800; // per-frame caps (nominal 800 / 1250)

// ---------------------------------------------------------------- ring buffers (single producer / consumer)
template <typename T, uint32_t N>
struct Ring {
  T buf[N];
  std::atomic<uint32_t> head{0}, tail{0};
  std::atomic<uint32_t> drops{0};             // samples overwritten before being sent
  std::atomic<uint32_t> last_us{0};           // time the newest sample was obtained
  void push(T v, uint32_t t_us) {
    uint32_t h = head.load(std::memory_order_relaxed);
    if (h - tail.load(std::memory_order_acquire) >= N) {   // full: drop oldest, count it
      tail.fetch_add(1, std::memory_order_acq_rel);
      drops.fetch_add(1, std::memory_order_relaxed);
    }
    buf[h % N] = v;
    last_us.store(t_us, std::memory_order_release);
    head.store(h + 1, std::memory_order_release);
  }
  // Pop up to max_n samples; *first = absolute index (since boot) of out[0].
  // A producer-side drop between the reads shows up as a jump in *first on the host.
  uint16_t pop_into(T *out, uint16_t max_n, uint32_t *first) {
    uint32_t t = tail.load(std::memory_order_acquire), h = head.load(std::memory_order_acquire);
    if (h - t > N) t = h - N;                            // producer lapped us: oldest data is gone
    uint16_t n = (uint16_t)min<uint32_t>(h - t, max_n);
    for (uint16_t i = 0; i < n; i++) out[i] = buf[(t + i) % N];
    tail.store(t + n, std::memory_order_release);
    *first = t;
    return n;
  }
  // Consistent (index, time) pair for the newest sample: retry if the producer moved in between.
  void reference(uint32_t *idx, uint32_t *us) {
    for (int k = 0; k < 4; k++) {
      uint32_t h1 = head.load(std::memory_order_acquire);
      uint32_t t = last_us.load(std::memory_order_acquire);
      if (head.load(std::memory_order_acquire) == h1) { *idx = h1 - 1; *us = t; return; }
    }
    *idx = head.load() - 1; *us = last_us.load();
  }
};
static Ring<int16_t, 8192> vibRing;
static Ring<uint16_t, 8192> curRing;

static std::atomic<uint32_t> vibOverruns{0}, adcPoolOvf{0}, adcBadChannel{0}, tachCount{0};
static std::atomic<uint32_t> vbusSum{0}, vbusN{0};
static bool adxlOk = false, adcOk = false;

// ---------------------------------------------------------------- ADXL345
static SPISettings adxl(SPI_HZ, MSBFIRST, SPI_MODE3);   // CPOL=1, CPHA=1 per datasheet

static void adxlWrite(uint8_t reg, uint8_t v) {
  SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
  SPI.transfer(reg & 0x3F); SPI.transfer(v);
  digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
}
static uint8_t adxlRead(uint8_t reg) {
  SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
  SPI.transfer(0x80 | (reg & 0x3F)); uint8_t v = SPI.transfer(0);
  digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
  return v;
}

static void vibTask(void *) {
  uint8_t b[6];
  for (;;) {
    uint8_t src = adxlRead(0x30);                         // INT_SOURCE: bit0 = Overrun
    if (src & 0x01) vibOverruns.fetch_add(1);
    delayMicroseconds(5);
    uint8_t n = adxlRead(0x39) & 0x3F;                    // FIFO_STATUS entries
    for (uint8_t i = 0; i < n; i++) {
      delayMicroseconds(5);                               // datasheet: >= 5 us between FIFO reads
      SPI.beginTransaction(adxl); digitalWrite(PIN_CS, LOW);
      SPI.transfer(0xC0 | 0x32);                          // read + multi-byte from DATAX0 (pops one entry)
      for (int k = 0; k < 6; k++) b[k] = SPI.transfer(0);
      digitalWrite(PIN_CS, HIGH); SPI.endTransaction();
      vibRing.push((int16_t)(b[AXIS_OFFSET] | (b[AXIS_OFFSET + 1] << 8)), micros());
    }
    vTaskDelay(pdMS_TO_TICKS(2));                         // FIFO (32) fills in 10 ms at 3200 Hz
  }
}

// ---------------------------------------------------------------- ADC DMA (current + bus voltage)
static adc_continuous_handle_t adcHandle = nullptr;
static const uint32_t ADC_FRAME_BYTES = 512;              // 256 results = 12.8 ms at 20 kHz

static bool IRAM_ATTR onPoolOvf(adc_continuous_handle_t, const adc_continuous_evt_data_t *, void *) {
  adcPoolOvf.fetch_add(1);
  return false;
}

static bool adcSetup() {
  adc_continuous_handle_cfg_t hcfg = {};
  hcfg.max_store_buf_size = 8 * ADC_FRAME_BYTES;
  hcfg.conv_frame_size = ADC_FRAME_BYTES;
  if (adc_continuous_new_handle(&hcfg, &adcHandle) != ESP_OK) return false;
  static adc_digi_pattern_config_t pat[2];
  const adc_channel_t chans[2] = {CH_CUR, CH_VBUS};
  for (int i = 0; i < 2; i++) {
    pat[i].atten = ADC_ATTEN_DB_12;
    pat[i].channel = chans[i];
    pat[i].unit = ADC_UNIT_1;
    pat[i].bit_width = ADC_BITWIDTH_12;
  }
  adc_continuous_config_t cfg = {};
  cfg.pattern_num = 2;
  cfg.adc_pattern = pat;
  cfg.sample_freq_hz = ADC_TOTAL_HZ;
  cfg.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  cfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;
  if (adc_continuous_config(adcHandle, &cfg) != ESP_OK) return false;
  adc_continuous_evt_cbs_t cbs = {};
  cbs.on_pool_ovf = onPoolOvf;
  if (adc_continuous_register_event_callbacks(adcHandle, &cbs, nullptr) != ESP_OK) return false;
  return adc_continuous_start(adcHandle) == ESP_OK;
}

static void adcTask(void *) {
  static uint8_t raw[ADC_FRAME_BYTES];
  int pending = -1;                                       // first current sample of a pair
  for (;;) {
    uint32_t got = 0;
    if (adc_continuous_read(adcHandle, raw, sizeof(raw), &got, 100) != ESP_OK) continue;
    uint32_t now = micros();
    for (uint32_t i = 0; i + 1 < got; i += SOC_ADC_DIGI_RESULT_BYTES) {
      adc_digi_output_data_t *d = (adc_digi_output_data_t *)&raw[i];
      uint16_t ch = d->type1.channel, v = d->type1.data;
      if (ch == CH_CUR) {
        if (pending < 0) pending = v;
        else { curRing.push((uint16_t)((pending + v + 1) / 2), now); pending = -1; }   // 10 kHz -> 5 kHz
      } else if (ch == CH_VBUS) {
        vbusSum.fetch_add(v); vbusN.fetch_add(1);
      } else {
        adcBadChannel.fetch_add(1);
      }
    }
  }
}

// ---------------------------------------------------------------- misc sensors
static OneWire ow(PIN_TEMP);
static DallasTemperature ds(&ow);
static void IRAM_ATTR onTach() { tachCount.fetch_add(1); }

// ---------------------------------------------------------------- setup / frame loop
void setup() {
  Serial.setTxBufferSize(16384);
  Serial.begin(921600);
  pinMode(PIN_CS, OUTPUT); digitalWrite(PIN_CS, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_CS);
  adxlOk = (adxlRead(0x00) == 0xE5);                      // DEVID
  adxlWrite(0x2D, 0x00);                                  // POWER_CTL: standby while configuring
  adxlWrite(0x31, 0x0B);                                  // DATA_FORMAT: 4-wire SPI, FULL_RES, +-16 g
  adxlWrite(0x2C, 0x0F);                                  // BW_RATE: 3200 Hz, normal power
  adxlWrite(0x38, 0x80);                                  // FIFO_CTL: stream mode
  adxlWrite(0x2D, 0x08);                                  // POWER_CTL: measure
  adcOk = adcSetup();
  pinMode(PIN_TACH, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_TACH), onTach, FALLING);
  ds.begin(); ds.setWaitForConversion(false); ds.requestTemperatures();
  xTaskCreatePinnedToCore(vibTask, "vib", 4096, nullptr, 5, nullptr, 0);
  if (adcOk) xTaskCreatePinnedToCore(adcTask, "adc", 4096, nullptr, 4, nullptr, 0);
}

static uint16_t sum16(const uint8_t *p, size_t n, uint16_t s) { while (n--) s += *p++; return s; }

#pragma pack(push, 1)
struct Header {                // 64 bytes, little-endian
  uint32_t seq, t_us, dt_us;
  uint32_t vib_first, vib_ref_idx, vib_ref_us;   // index of first sample in frame; (index, micros) of newest sample
  uint32_t cur_first, cur_ref_idx, cur_ref_us;
  uint16_t n_vib, n_cur;
  float rpm, temp_c, vbus_adc;
  uint16_t vib_overruns, adc_pool_ovf, vib_drops, cur_drops, adc_bad_ch, flags;
};
#pragma pack(pop)
static_assert(sizeof(Header) == 64, "RIG2 header must be 64 bytes");

static int16_t vibOut[MAX_VIB];
static uint16_t curOut[MAX_CUR];
static uint32_t seq = 0, lastFrameUs = 0, lastTempMs = 0;
static float tempC = NAN;

void loop() {
  uint32_t now = micros();
  if (lastFrameUs == 0) lastFrameUs = now;
  if ((uint32_t)(now - lastFrameUs) < FRAME_US) { delay(1); return; }
  Header h = {};
  h.seq = seq++;
  h.t_us = now;
  h.dt_us = now - lastFrameUs;
  lastFrameUs = now;
  vibRing.reference(&h.vib_ref_idx, &h.vib_ref_us);
  curRing.reference(&h.cur_ref_idx, &h.cur_ref_us);
  h.n_vib = vibRing.pop_into(vibOut, MAX_VIB, &h.vib_first);
  h.n_cur = curRing.pop_into(curOut, MAX_CUR, &h.cur_first);
  uint32_t pulses = tachCount.exchange(0);
  h.rpm = pulses * 60.0e6f / (PULSES_PER_REV * (float)h.dt_us);
  if (millis() - lastTempMs > 1000) { tempC = ds.getTempCByIndex(0); ds.requestTemperatures(); lastTempMs = millis(); }
  h.temp_c = tempC;
  uint32_t vn = vbusN.exchange(0), vs = vbusSum.exchange(0);
  h.vbus_adc = vn ? (float)vs / vn : NAN;
  h.vib_overruns = (uint16_t)min<uint32_t>(vibOverruns.load(), 65535);
  h.adc_pool_ovf = (uint16_t)min<uint32_t>(adcPoolOvf.load(), 65535);
  h.vib_drops = (uint16_t)min<uint32_t>(vibRing.drops.load(), 65535);
  h.cur_drops = (uint16_t)min<uint32_t>(curRing.drops.load(), 65535);
  h.adc_bad_ch = (uint16_t)min<uint32_t>(adcBadChannel.load(), 65535);
  h.flags = (adxlOk ? 1 : 0) | (adcOk ? 2 : 0);
  uint16_t s = sum16((const uint8_t *)&h, sizeof(h), 0);
  s = sum16((const uint8_t *)vibOut, 2u * h.n_vib, s);
  s = sum16((const uint8_t *)curOut, 2u * h.n_cur, s);
  Serial.write((const uint8_t *)"RIG2", 4);
  Serial.write((const uint8_t *)&h, sizeof(h));
  Serial.write((const uint8_t *)vibOut, 2u * h.n_vib);
  Serial.write((const uint8_t *)curOut, 2u * h.n_cur);
  Serial.write((const uint8_t *)&s, 2);
}
