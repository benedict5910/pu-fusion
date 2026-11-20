"""Rig mechanical drawing, rev A (Design B). Generates docs/drawings/rig_revA.pdf (+ PNG previews).

All dimensions in mm. Coordinates: x along the shaft from the motor-plate front face, y across, z up from the
base top face. Values marked (V) must be verified on the purchased motor before machining the motor plate.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, Polygon, Rectangle

OUT = Path(__file__).resolve().parents[2] / "docs" / "drawings"
OUT.mkdir(parents=True, exist_ok=True)

ZC = 40.0                         # shaft centre height above base top
# x positions (centre lines)
X = dict(coup=(2, 27), supA=47, disc=107, supB=167, test=197, shaft=(17, 212))
LW = 0.8


def rect(ax, x0, y0, w, h, fc="none", ec="k", lw=LW, ls="-", hatch=None, z=2):
    ax.add_patch(Rectangle((x0, y0), w, h, fc=fc, ec=ec, lw=lw, ls=ls, hatch=hatch, zorder=z))


def dim(ax, p1, p2, off, text, horiz=True, fs=6.5):
    (x1, y1), (x2, y2) = p1, p2
    if horiz:
        y = off
        ax.plot([x1, x1], [y1, y], "k-", lw=0.3)
        ax.plot([x2, x2], [y2, y], "k-", lw=0.3)
        ax.annotate("", (x1, y), (x2, y), arrowprops=dict(arrowstyle="<->", lw=0.5))
        ax.text((x1 + x2) / 2, y + 1.2, text, ha="center", va="bottom", fontsize=fs)
    else:
        x = off
        ax.plot([x1, x], [y1, y1], "k-", lw=0.3)
        ax.plot([x2, x], [y2, y2], "k-", lw=0.3)
        ax.annotate("", (x, y1), (x, y2), arrowprops=dict(arrowstyle="<->", lw=0.5))
        ax.text(x + 1.2, (y1 + y2) / 2, text, ha="left", va="center", fontsize=fs, rotation=90)


def note(ax, x, y, s, fs=6.5, **kw):
    ax.text(x, y, s, fontsize=fs, **kw)


def leader(ax, xy, xytext, s, fs=6.5):
    ax.annotate(s, xy=xy, xytext=xytext, fontsize=fs, arrowprops=dict(arrowstyle="-", lw=0.4))


def title_block(fig, sheet, title):
    fig.text(0.70, 0.035, f"IVHM bearing rig - Design B - {title}\nRev A, 22 Oct 2026 - sheet {sheet}/2 - all dims mm"
             "\nGeneral tol. ISO 2768-m; (V) = verify on purchased part before machining", fontsize=7,
             va="bottom", bbox=dict(fc="w", ec="k", lw=0.6))


def side_view(ax):
    ax.set_title("VIEW A - side elevation (x-z), guard shown dashed", fontsize=8, loc="left")
    # base plate
    rect(ax, -95, -12, 330, 12, fc="0.85", hatch="///")
    # motor + plate
    rect(ax, -10, 0, 10, 82, fc="0.9")                              # motor plate, 10 thick
    rect(ax, -76, ZC - 22.25, 66, 44.5, fc="0.95")                  # 775 body (V)
    rect(ax, -90, ZC - 2.5, 14, 5, fc="0.7")                        # rear shaft
    rect(ax, -94, ZC - 9, 20, 18, fc="none", ls="--")               # rear-shaft cap
    note(ax, -93, ZC + 11, "rear-shaft\ncap", fs=5.5)
    note(ax, -70, ZC - 3, "775 motor 12 V (V)", fs=6)
    rect(ax, 0, ZC - 2.5, 12, 5, fc="0.6")                          # motor shaft 5 (V)
    # coupling
    rect(ax, X["coup"][0], ZC - 10, 25, 20, fc="0.8")
    note(ax, 3, ZC + 12, "jaw coupling\n5x8, D20 L25", fs=5.5)
    # shaft
    rect(ax, X["shaft"][0], ZC - 4, X["shaft"][1] - X["shaft"][0], 8, fc="0.75", z=1)
    # supports
    for xc, lab in ((X["supA"], "SUPPORT A\n(locating)"), (X["supB"], "SUPPORT B\n(floating)")):
        rect(ax, xc - 10, 0, 20, 60, fc="0.92")
        rect(ax, xc - 3.5, ZC - 11, 7, 22, fc="0.6")                # 608 outer ring section
        note(ax, xc - 9, 62, lab, fs=5.5)
    # collars at A (both sides) and inboard/outboard of test bearing
    for x0 in (X["supA"] - 3.5 - 8, X["supA"] + 3.5, X["test"] - 3.5 - 8, X["test"] + 3.5):
        rect(ax, x0, ZC - 9, 8, 18, fc="0.55")
    # disc
    rect(ax, X["disc"] - 5, ZC - 30, 10, 60, fc="0.88")
    note(ax, X["disc"] - 14, ZC + 32, "unbalance disc\nD60x10, 6xM3 @R20", fs=5.5)
    # test housing (floating)
    rect(ax, X["test"] - 10, 15, 20, 50, fc="0.97", ec="b", lw=1.0)
    rect(ax, X["test"] - 3.5, ZC - 11, 7, 22, fc="0.6")
    rect(ax, X["test"] - 10, 13.5, 20, 1.5, fc="0.5")                # hard stop gap shown
    rect(ax, X["test"] - 9, 0, 18, 14, fc="0.8")                     # stop block
    note(ax, X["test"] + 11, 5, "hard stop\n1.0 gap", fs=5.5)
    rect(ax, X["test"] - 6, 65, 12, 12, fc="0.7", z=3)               # sensor cube
    note(ax, X["test"] - 48, 76, "IIS3DWB on Al cube\n(axis X = vertical)", fs=5.5)
    # load stud + spring (front stud drawn)
    rect(ax, X["test"] - 2.5, 0, 5, 104, ls="--", z=0)                # studs at y=+/-38 (hidden behind housing)
    ax.plot([X["test"] - 5, X["test"] + 5] * 6, [65 + i * 2.5 for i in range(12)], "k-", lw=0.4)
    rect(ax, X["test"] - 7, 95, 14, 2, fc="0.3")
    rect(ax, X["test"] - 4, 97, 8, 7.5, fc="0.2")
    note(ax, X["test"] + 12, 92, "2x M5 stud (y=+/-38),\nspring, washer, nut +\nlock-nut (captive)", fs=5.5)
    # guard
    rect(ax, 0, 0, 232, 112, ls="--", ec="r", lw=0.7, z=0)
    note(ax, 150, 106, "polycarbonate guard 3 mm (lift-off lid, cable grommet)", fs=5.5, color="r")
    # centre line
    ax.plot([-95, 220], [ZC, ZC], "k-.", lw=0.4)
    # dims
    dim(ax, (X["supA"], 0), (X["supB"], 0), -24, "L = 120")
    dim(ax, (X["supB"], 0), (X["test"], 0), -24, "a = 30")
    dim(ax, (X["supA"], 0), (X["disc"], 0), -34, "60")
    dim(ax, (0, 0), (X["supA"], 0), -34, "47")
    dim(ax, (X["shaft"][0], 0), (X["shaft"][1], 0), -44, "shaft D8 h6 x 195 (x = 17 ... 212)")
    dim(ax, (225, 0), (225, ZC), 226, "40.00 +/-0.02", horiz=False)
    ax.set_xlim(-100, 245)
    ax.set_ylim(-50, 118)
    ax.set_aspect("equal")
    ax.axis("off")


def end_view(ax):
    ax.set_title("VIEW B - test housing and captive load (y-z), looking from shaft end", fontsize=8, loc="left")
    rect(ax, -70, -12, 140, 12, fc="0.85", hatch="///")
    rect(ax, -48, 15, 96, 50, fc="0.97", ec="b", lw=1.0)           # housing
    ax.add_patch(Circle((0, ZC), 11, fc="0.6", ec="k", lw=LW))      # bearing OD 22
    ax.add_patch(Circle((0, ZC), 4, fc="0.75", ec="k", lw=LW))      # shaft
    rect(ax, -9, 0, 18, 14, fc="0.8")                               # stop block
    for ys in (-38, 38):
        rect(ax, ys - 2.8, 15, 5.6, 50, fc="w", ls=":")             # clearance hole 5.6
        rect(ax, ys - 2.5, 0, 5, 100, fc="0.4")                     # M5 stud
        ax.plot([ys - 5, ys + 5] * 6, [65 + i * 2.5 for i in range(12)], "k-", lw=0.4)  # spring
        rect(ax, ys - 7, 95, 14, 2, fc="0.3")                       # washer
        rect(ax, ys - 4, 97, 8, 4, fc="0.2")                        # nut
        rect(ax, ys - 4, 101.5, 8, 3, fc="0.2")                     # lock nut
        rect(ax, ys - 4, 65, 8, 1.2, fc="0.5")                      # PTFE washer
    rect(ax, -6, 65, 12, 12, fc="0.7")
    leader(ax, (0, 77), (-30, 118), "sensor cube 12x12x12 on M3 (top face);\nIIS3DWB adapter bonded to cube side, X axis vertical", fs=6)
    leader(ax, (43, 82), (52, 106), "spring k~5 N/mm (calibrated)\nF = 2 k s + housing weight", fs=6)
    leader(ax, (9, 10), (60, 4), "hard stop block, 1.0 mm gap\n(captures housing if bearing fails)", fs=6)
    leader(ax, (0, ZC + 11), (-44, 72), "load zone = top of bearing\n(springs pull housing DOWN)", fs=6)
    dim(ax, (-38, 104), (38, 104), 109, "stud pitch 76", fs=6)
    dim(ax, (-48, 15), (48, 15), 3, "96")
    dim(ax, (55, 15), (55, 65), 57, "50", horiz=False)
    dim(ax, (-60, 0), (-60, ZC), -62, "40.00", horiz=False)
    note(ax, -68, -24, "Load set by measuring washer height above housing top (vernier) on both studs; equal within 0.1 mm.\n"
                        "Studs M5 in tapped base holes + lock-nut below; holes in housing D5.6 (allows vertical travel and 41' tilt).", fs=5.8)
    ax.set_xlim(-72, 105)
    ax.set_ylim(-30, 125)
    ax.set_aspect("equal")
    ax.axis("off")


def top_view(ax):
    ax.set_title("VIEW C - base plate (x-y), 330 x 160 x 12 Al 6061, holes", fontsize=8, loc="left")
    rect(ax, -95, -80, 330, 160, fc="0.95", z=1)
    pts = [((-5, -25), "M5 (motor plate)"), ((-5, 25), "")]
    for xc in (X["supA"], X["supB"]):
        pts += [((xc, -20), "M5 thru, c'bore below"), ((xc, 20), "")]
    pts += [((X["test"], -38), "M5 tapped (stud)"), ((X["test"], 38), ""), ((X["test"], 0), "M4 (stop block)")]
    for (x, y), s in pts:
        ax.add_patch(Circle((x, y), 2.5, fc="w", ec="k", lw=LW, zorder=3))
        if s:
            note(ax, x + 3, y + 3, s, fs=5.5)
    for (x, y) in ((-85, -70), (-85, 70), (225, -70), (225, 70)):
        ax.add_patch(Circle((x, y), 3, fc="0.6", ec="k", lw=LW, zorder=3))
    note(ax, -84, -64, "4x rubber feet / bench clamps", fs=5.5)
    for (x, y) in ((-2, -62), (-2, 62), (229, -62), (229, 62)):
        ax.add_patch(Circle((x, y), 1.6, fc="w", ec="r", lw=LW, zorder=3))
    note(ax, 100, -76, "4x M3 guard angles (red)", fs=5.5, color="r")
    ax.plot([-95, 235], [0, 0], "k-.", lw=0.4)
    dim(ax, (X["supA"], -20), (X["supB"], -20), -45, "120")
    dim(ax, (X["supB"], -38), (X["test"], -38), -55, "30")
    dim(ax, (-95, 80), (235, 80), 88, "330")
    ax.set_xlim(-100, 250)
    ax.set_ylim(-90, 100)
    ax.set_aspect("equal")
    ax.axis("off")


def parts_sheet(fig):
    ax = fig.add_axes([0.03, 0.12, 0.94, 0.83])
    ax.axis("off")
    ax.set_xlim(0, 420)
    ax.set_ylim(0, 260)
    # Support housing (x2, identical) and test housing - line-bored together
    ax.text(5, 250, "P1  SUPPORT HOUSING x2  (Al 6061-T6, 60 x 20 x 60)", fontsize=8, weight="bold")
    rect(ax, 10, 175, 60, 60, fc="0.95")
    ax.add_patch(Circle((40, 175 + 40), 11, fc="w", ec="k", zorder=3))
    ax.text(30, 213, "D22 H7", fontsize=6, zorder=4)
    for xs in (20, 60):
        ax.plot([xs, xs], [175, 183], "k--", lw=0.5)
    dim(ax, (10, 175), (70, 175), 168, "60")
    dim(ax, (75, 175), (75, 215), 77, "40.00 +/-0.02", horiz=False)
    dim(ax, (75, 175), (75, 235), 92, "60", horiz=False)
    ax.text(105, 230, "Bore D22 H7 (+0.021/0) through, Ra 0.8\n"
                      "Bore axis to base face: 40.00 +/-0.02 (all three housings line-bored in ONE setup, clamped together)\n"
                      "Base face flat 0.01; bore perpendicular to faces 0.02\n"
                      "2x M5 tapped 10 deep in base face at y = +/-20\n"
                      "4x M3 tapped 6 deep each face on PCD 30 for cover plates (P4)\n"
                      "Support A: covers both faces (locating). Support B: cover on one face only (axial float)", fontsize=6.5, va="top")
    ax.text(5, 155, "P2  TEST HOUSING x1  (Al 6061-T6, 96 x 20 x 50, floating)", fontsize=8, weight="bold")
    rect(ax, 10, 85, 96, 50, fc="0.97", ec="b")
    ax.add_patch(Circle((58, 85 + 25), 11, fc="w", ec="k", zorder=3))
    ax.text(48, 108, "D22 H7", fontsize=6, zorder=4)
    ax.add_patch(Rectangle((52, 135), 12, 3, fc="0.7", ec="k", zorder=3))
    for xs in (20, 96):
        ax.plot([xs, xs], [85, 135], "k:", lw=0.6)
    dim(ax, (10, 85), (106, 85), 78, "96")
    dim(ax, (20, 135), (96, 135), 140, "76 (stud pitch)")
    ax.text(115, 135, "Bore D22 H7 through, centred (25.00 from bottom face), line-bored with P1 (shim 15.00 under it)\n"
                      "2x D5.6 through (vertical) at y = +/-38 for M5 studs; PTFE washer under each spring\n"
                      "M3 x 6 deep tapped at top-face centre (sensor cube); top face flat 0.02\n"
                      "4x M3 for cover plates each face (cartridge: housing + 608 + 2 covers)\n"
                      "Mass ~ 0.24 kg (adds 2.3 N to the spring load)", fontsize=6.5, va="top")
    ax.text(5, 70, "P3  UNBALANCE DISC (Al, D60 x 10)", fontsize=8, weight="bold")
    ax.add_patch(Circle((40, 35), 30, fc="0.95", ec="k"))
    ax.add_patch(Circle((40, 35), 4, fc="w", ec="k"))
    import math
    for k in range(6):
        t = math.radians(60 * k)
        ax.add_patch(Circle((40 + 20 * math.cos(t), 35 + 20 * math.sin(t)), 1.5, fc="w", ec="k"))
    ax.add_patch(Circle((40, 35 - 25), 2.5, fc="0.5", ec="k"))
    ax.text(75, 62, "Bore D8 H7; 2x M4 set screws at 90 deg (cup point, thread-locked)\n"
                    "6x M3 tapped through on R20 at 60 deg (unbalance screws M3x6, ~0.5 g; M3 nut adds ~0.3 g)\n"
                    "Magnet pocket D5 x 2 deep at R25 (tach); balance check: run with no masses, record 1x level\n"
                    "Faces parallel 0.02; run-out after mounting <= 0.03 TIR (dial indicator)", fontsize=6.5, va="top")
    ax.text(215, 155, "P4  COVER PLATES x6 (Al 2 mm, D34)", fontsize=8, weight="bold")
    ax.text(215, 148, "Centre hole D20 (clears collars D18); 4x D3.4 on PCD 30\nClamp outer ring axially; no contact with inner ring",
            fontsize=6.5, va="top")
    ax.text(215, 128, "P5  MOTOR PLATE (Al 10 thick, 80 x 70, + gusset)", fontsize=8, weight="bold")
    ax.text(215, 121, "Pilot bore for 775 front boss: D (V) H8, centre 40.00 +/-0.02 above base face\n"
                      "2x motor screw clearance holes on the 775 face pattern (V) (typ. M4 on 29 mm)\n"
                      "2x M5 tapped into bottom edge + 1 gusset; plate face perpendicular to base 0.05\n"
                      "Shim pack 0.05/0.1 under plate for final centre-height match", fontsize=6.5, va="top")
    ax.text(215, 90, "P6  STOP BLOCK (Al 18 x 20 x 14), P7 SENSOR CUBE (Al 12 x 12 x 12, M3 clearance)", fontsize=8, weight="bold")
    ax.text(215, 82, "Stop block top 14.00 -> 1.0 mm gap to housing (15.00); cube faces square 0.05", fontsize=6.5, va="top")
    ax.text(215, 70, "BOUGHT-OUT / ASSEMBLY NOTES", fontsize=8, weight="bold")
    ax.text(215, 63, "Shaft: D8 h6 induction-hardened linear rod, cut 195, ends chamfered 0.5x45; micrometer check 7.991-8.000\n"
                     "Bearings: SKF 608-2Z, one batch; mark serials; press only on the ring being fitted (sleeve tools)\n"
                     "Shaft collars D8 clamp type x4 (A both sides, test inboard + outboard); torque recorded\n"
                     "Coupling jaw 5x8 D20 L25; set screws on motor flat / shaft, thread-locked\n"
                     "Alignment: dial indicator across coupling hubs, parallel <= 0.05, angular <= 0.1 deg\n"
                     "Springs: 2 identical (wire ~1.2, OD ~10, free ~30); rate calibrated with 2 kg and 5 kg masses\n"
                     "Studs M5 x 110 (8.8), base lock-nut; nut + lock-nut above washer; never run with nuts removed\n"
                     "Guard closed + supply OFF/E-stop pressed for every adjustment (isolation rule)", fontsize=6.5, va="top")


def main():
    with PdfPages(OUT / "rig_revA.pdf") as pdf:
        fig = plt.figure(figsize=(16.54, 11.69))       # A3 landscape
        side_view(fig.add_axes([0.02, 0.45, 0.62, 0.52]))
        end_view(fig.add_axes([0.64, 0.45, 0.35, 0.52]))
        top_view(fig.add_axes([0.02, 0.05, 0.55, 0.38]))
        title_block(fig, 1, "assembly")
        pdf.savefig(fig)
        fig.savefig(OUT / "rig_revA_sheet1.png", dpi=110)
        plt.close(fig)
        fig = plt.figure(figsize=(16.54, 11.69))
        parts_sheet(fig)
        title_block(fig, 2, "machined parts")
        pdf.savefig(fig)
        fig.savefig(OUT / "rig_revA_sheet2.png", dpi=110)
        plt.close(fig)
    print("wrote", OUT / "rig_revA.pdf")


if __name__ == "__main__":
    main()
