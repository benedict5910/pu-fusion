"""Engineering checks for the Design-B bearing rig (reproducible numbers for docs/RIG_ENGINEERING_CHECKS_*.md).

Pure calculation, no hardware. Inputs are documented assumptions; every source is named next to it.
Run:  python scripts/design/rig_design_calcs.py  > docs/calcs/rig_design_calcs_output.txt
"""
import math

print("=" * 78)
print("1. LOAD TORQUE (bearing friction) - Palmgren/SKF simplified model")
print("=" * 78)
# 608-2Z: d=8, D=22, B=7 mm; C=3.45 kN, C0=1.37 kN (SKF catalogue). Shields (2Z) are non-contact: no seal torque.
d, D = 8.0, 22.0
dm = (d + D) / 2                      # mean diameter, mm
C0 = 1370.0                           # N
nu = 100.0                            # mm^2/s, assumed grease base-oil viscosity at ~30 C (typical 70-100 cSt @40C greases)
def m0(n, f0):                        # load-independent (grease churning) moment, N.mm ; valid for nu*n >= 2000
    return 1e-7 * f0 * (nu * n) ** (2 / 3) * dm ** 3
def m1(P):                            # load-dependent moment, N.mm ; DGBB f1 = 0.0009*(P0/C0)^0.5
    f1 = 0.0009 * (P / C0) ** 0.5
    return f1 * P * dm
L, a, F_max = 120.0, 30.0, 50.0       # support span, overhang of test bearing, max radial test load (mm, mm, N)
rows = []
for n in (900, 1500):
    for F in (20.0, 50.0):
        RB, RA = F * (1 + a / L), abs(F * a / L)
        loads = (F, RB, RA)               # test, support B, support A
        nom = sum(m0(n, 2.0) + m1(P) for P in loads) / 1000        # N.m -> mN.m: N.mm/1000 = N.m ; *1000 -> mN.m
        worst = sum(m0(n, 4.0) + m1(P) for P in loads) / 1000      # f0 doubled: cold/new grease, start-up
        rows.append((n, F, RB, RA, nom * 1000, worst * 1000))
        print(f"n={n:5d} rpm  F_test={F:4.0f} N  R_B={RB:5.1f} N  R_A={RA:5.1f} N  "
              f"T_friction nominal={nom*1000:5.2f} mN.m  worst={worst*1000:5.2f} mN.m")
# acceleration torque: Al disc D60x10 + shaft + coupling + 775 rotor (estimate)
m_disc = 2700 * math.pi * 0.03 ** 2 * 0.010
J = 0.5 * m_disc * 0.03 ** 2 + 0.5 * (7850 * math.pi * 0.004 ** 2 * 0.195) * 0.004 ** 2 + 0.6e-5 + 2.0e-5
T_acc = J * (1500 * 2 * math.pi / 60) / 2.0   # 0 -> 1500 rpm in 2 s
print(f"disc mass {m_disc*1000:.0f} g; total inertia J = {J:.2e} kg.m^2; accel torque (0->1500 rpm in 2 s) = {T_acc*1000:.2f} mN.m")

print()
print("=" * 78)
print("2. MOTOR OPERATING POINTS - representative 12 V / 4,550 rpm RS-775 winding (770-4087 datasheet row)")
print("=" * 78)
V0, n0, I0_12, Is = 12.0, 4550.0, 0.60, 14.1         # datasheet: no-load speed, no-load current, stall current @12 V
Ts = 334.1e-3                                        # stall torque N.m
R = V0 / Is                                          # terminal resistance incl. brushes
Kt = Ts / (Is - I0_12)                               # N.m/A  (= ke in V.s/rad)
print(f"R = {R:.3f} ohm ; Kt = ke = {Kt*1000:.1f} mN.m/A ; check no-load speed = {(V0 - I0_12*R)/Kt*60/(2*math.pi):.0f} rpm")
def I0(n):                                          # no-load (friction + iron) current, assumed half Coulomb, half proportional
    return 0.30 + 0.30 * n / n0
I_cc = 2.0                                           # supply current limit, A
for n, F, RB, RA, Tn, Tw in rows:
    w = n * 2 * math.pi / 60
    for tag, T in (("nominal", Tn / 1000), ("worst+accel", Tw / 1000 + T_acc)):
        I = I0(n) + T / Kt
        V = Kt * w + I * R
        print(f"n={n:5d} F={F:3.0f} N {tag:12s}: T={T*1000:5.2f} mN.m  I={I:4.2f} A  V={V:4.2f} V  "
              f"P_el={V*I:4.2f} W  Cu loss={I*I*R:4.2f} W")
T_start = Kt * (I_cc - I0(0))
print(f"start torque available at the {I_cc} A CC limit: {T_start*1000:.1f} mN.m ; worst running load "
      f"{max(r[5] for r in rows):.1f} mN.m (+{T_acc*1000:.1f} accel)")
print(f"continuous-torque margin vs datasheet nominal point (3500 rpm, 2.8 A): "
      f"{Kt*(2.8-I0_12)*1000:.1f} mN.m / {max(r[5] for r in rows)+T_acc*1000:.1f} mN.m = "
      f"{Kt*(2.8-I0_12)*1000/(max(r[5] for r in rows)+T_acc*1000):.1f}x")

print()
print("Open-loop speed sensitivities (fixed supply voltage):")
k_T = R / (Kt * Kt) * 60 / (2 * math.pi)            # rpm per N.m
print(f"  load torque  : {k_T/1000:.1f} rpm per mN.m")
for n in (900, 1500):
    Tn = [r for r in rows if r[0] == n and r[1] == 50.0][0][4]
    d_grease = -0.30 * Tn                            # grease warms, friction falls ~30 %
    dn1 = -k_T * d_grease / 1000
    dT_motor = 15.0                                  # K, assumed winding/magnet rise after warm-up at ~3 W
    dn2 = n * 0.002 * dT_motor                       # ferrite Br ~ -0.2 %/K -> ke falls -> speed rises
    I = I0(n) + Tn / 1000 / Kt
    dn3 = -(I * R * 0.0039 * dT_motor) / Kt * 60 / (2 * math.pi)   # copper resistance +0.39 %/K
    dV = 0.003                                       # V, linear supply CV stability (order of 0.01 % + 3 mV)
    dn4 = dV / Kt * 60 / (2 * math.pi)
    radial = -k_T * (m1(50) - m1(20)) / 1e6 * 3       # 20 -> 50 N change, all three bearings, rpm
    tot = dn1 + dn2 + dn3
    print(f"  {n:4d} rpm: grease warm-up {dn1:+5.1f} rpm, magnet temp {dn2:+5.1f}, copper temp {dn3:+5.1f}, "
          f"supply {dn4:+4.1f}, 20->50 N load {radial:+4.2f}  => warm-up drift {tot:+5.1f} rpm ({100*tot/n:+.1f} %)")
print("  voltage resolution of a 10 mV supply step: "
      f"{0.010/Kt*60/(2*math.pi):.1f} rpm ({0.010/Kt*60/(2*math.pi)/900*100:.2f} % at 900 rpm)")

print()
print("=" * 78)
print("3. SHAFT (8 mm h6, hardened), overhung test bearing")
print("=" * 78)
E, dS = 200e3, 8.0
I_ = math.pi * dS ** 4 / 64
Z = math.pi * dS ** 3 / 32
M = F_max * a
print(f"I = {I_:.0f} mm^4, Z = {Z:.1f} mm^3")
print(f"bending moment at support B = {M/1000:.2f} N.m ; stress = {M/Z:.1f} MPa (x2 for set-screw/collar notch = {2*M/Z:.0f} MPa)")
defl = F_max * a ** 2 * (L + a) / (3 * E * I_)
slope = F_max * a * (2 * L + 3 * a) / (6 * E * I_)
print(f"deflection at test bearing = {defl*1000:.0f} um ; slope = {slope*1000:.2f} mrad = {math.degrees(slope)*60:.1f} arcmin")
k_mid = 48 * E * I_ / L ** 3 * 1000           # N/m
wn = math.sqrt(k_mid / m_disc)
print(f"first bending critical speed (disc at mid-span, shaft mass neglected) ~ {wn*60/(2*math.pi):,.0f} rpm "
      f"= {wn*60/(2*math.pi)/1500:.0f}x the 1500 rpm operating speed")
C = 3450.0
for P in (F_max, F_max * (1 + a / L)):
    print(f"608 L10 life at P={P:.1f} N: {(C/P)**3:,.0f} million rev ({(C/P)**3*1e6/1500/60:,.0f} h at 1500 rpm)")
for m_g in (1.0, 3.0):
    print(f"unbalance {m_g:.0f} g at r=20 mm: {m_g/1000*0.020*(1500*2*math.pi/60)**2:.2f} N at 1500 rpm, "
          f"{m_g/1000*0.020*(900*2*math.pi/60)**2:.2f} N at 900 rpm")

print()
print("=" * 78)
print("4. LOAD MECHANISM - two calibrated compression springs on M5 studs")
print("=" * 78)
k_spring = 5.0                                  # N/mm each (nominal; every spring is calibrated)
housing_weight = 2700 * (96 * 20 * 50 - math.pi * 11 ** 2 * 20) * 1e-9 * 9.81
for F in (20.0, 50.0):
    comp = (F - housing_weight) / (2 * k_spring)
    print(f"target {F:.0f} N: housing weight {housing_weight:.2f} N -> each spring compressed {comp:.2f} mm "
          f"({comp/0.8:.1f} turns of an M5x0.8 nut)")
print("stud-hole clearance tilt allowance: 0.6 mm / 50 mm = "
      f"{math.degrees(0.6/50)*60:.0f} arcmin  (needed: {math.degrees(slope)*60:.1f} arcmin)")

print()
print("=" * 78)
print("5. DATA ACQUISITION - IIS3DWB -> ESP32 -> USB-UART")
print("=" * 78)
odr, fs_cur, frame_s = 26667.0, 5000.0, 0.100
word = 7                                        # FIFO word: 1 tag + 6 data bytes (datasheet)
fifo_words = 3072 // word
print(f"FIFO: {fifo_words} words = {fifo_words/odr*1000:.1f} ms at {odr:.0f} Hz (worst case: 1 sample per word)")
wtm = 256
spi_hz = 8e6
t_read = (wtm * word + 1) * 8 / spi_hz
print(f"watermark {wtm} words = {wtm/odr*1000:.1f} ms; SPI read at {spi_hz/1e6:.0f} MHz = {t_read*1000:.2f} ms; "
      f"service deadline before overrun = {(fifo_words-wtm)/odr*1000:.1f} ms")
print(f"SPI bus load = {odr*word*8/spi_hz*100:.0f} %")
hdr = 4 + 76 + 4                                # magic + RIG3 header + CRC32
per_frame = hdr + odr * frame_s * 2 + fs_cur * frame_s * 2 + 3 * 4
rate = per_frame / frame_s
for baud in (921600, 2000000):
    cap = baud / 10
    print(f"UART {baud:>8d} baud 8N1: capacity {cap/1000:.1f} kB/s, payload {rate/1000:.1f} kB/s "
          f"(frame {per_frame:.0f} B every {frame_s*1000:.0f} ms) -> utilisation {rate/cap*100:.0f} %")
print(f"3-axis at full rate would need {(odr*6 + fs_cur*2)/1000:.1f} kB/s -> exceeds 921,600 baud; single axis selected")
print(f"ESP32 buffering: vib ring 0.5 s = {odr*0.5*2/1024:.1f} KiB, current ring 0.5 s = {fs_cur*0.5*2/1024:.1f} KiB, "
      f"UART TX buffer >= 2 frames = {2*per_frame/1024:.1f} KiB")
