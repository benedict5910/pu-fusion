"""One command for the whole benchmark study (run on your own machine).

  python scripts/run_all.py                 # starter subset (~1.9 GB), quick
  python scripts/run_all.py --subset all    # full dataset (~5.1 GB), final results

Steps (each is skipped if its output already exists, so re-running resumes):
  download -> features -> P1 (bearing-disjoint) -> P2 (artificial->real)
  -> P3 (bearing+condition-disjoint) -> leaky reference -> summaries -> demo model
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def step(name, cmd, out=None, force=False):
    if out and Path(out).exists() and not force:
        print(f"[skip] {name}: {out} exists"); return
    print(f"\n=== {name} ===\n$ {' '.join(map(str, cmd))}")
    subprocess.run([PY, *map(str, cmd)], check=True, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", choices=["starter", "all"], default="starter")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--skip-download", action="store_true", help="archives already extracted under data/raw")
    a = ap.parse_args()
    feats = f"data/features_{a.subset}.npz"
    res = Path(f"results/{a.subset}")
    if not a.skip_download:
        step("download", ["scripts/download_pu.py", "--subset", a.subset])
    step("features", ["scripts/build_features.py", "--raw", "data/raw", "--out", feats, "--jobs", a.jobs], feats)
    runs = {"p1": ["--protocol", "p1", "--repeats", a.repeats, "--models", "all"],
            "p2": ["--protocol", "p2", "--models", "main"],
            "p3": ["--protocol", "p1", "--repeats", 1, "--condition-holdout", "--models", "main"],
            "leaky": ["--protocol", "leaky", "--models", "main"]}
    if a.subset == "starter":
        runs.pop("p2")   # P2 needs artificially damaged bearings, which the starter subset omits
        print("[note] P2 (artificial -> real) needs --subset all")
    for name, args in runs.items():
        out = res / f"{name}.csv"
        step(f"experiment {name}", ["scripts/run_experiments.py", "--features", feats, *args, "--out", out], out)
    q = res / "quality.json"
    step("sensor-quality validation", ["scripts/eval_quality.py", "--features", feats, "--repeats", a.repeats,
                                       "--out", q], q)
    with open(res / "SUMMARY.txt", "w") as f:
        for name in runs:
            f.write(f"\n##### {name}\n")
            f.flush()
            subprocess.run([PY, "scripts/summarize.py", str(res / f"{name}.csv")], cwd=ROOT, stdout=f, check=True)
        f.write("\n##### sensor-quality detector\n"); f.flush()
        subprocess.run([PY, "scripts/eval_quality.py", "--features", feats, "--repeats", str(a.repeats),
                        "--out", str(q)], cwd=ROOT, stdout=f, check=True)
    print((res / "SUMMARY.txt").read_text())
    step("demo model", ["scripts/train_demo_model.py", "--features", feats, "--out", "models/demo_models.pkl"],
         "models/demo_models.pkl")
    print("\nDone. Send results/%s/ back for review; start the dashboard with:\n"
          "  streamlit run app/dashboard.py" % a.subset)


if __name__ == "__main__":
    main()
