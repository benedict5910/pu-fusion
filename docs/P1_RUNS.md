# P1 on the starter subset: completed runs, skipped folds, statistical power

Data: 12 bearings (healthy K001-K004; real outer-race KA04, KA15, KA16, KA22; real inner-race
KI04, KI14, KI16, KI18). P1 is defined on the full dataset (5 repeats x 3 bearing-disjoint folds
over 6 healthy, 5 real OR and 6 real IR bearings, with artificial-damage bearings used only for
training). `run_experiments.py` keeps only bearings present in the feature file and drops any fold
whose test set lacks a class. That rule was in the code before any result existed; it was not
chosen after seeing results.

| Fold | Status | Test bearings (starter) | Training bearings | Reason |
|---|---|---|---|---|
| P1_r0_f0 | run | K003, K004, KA15, KI16 | 8 | |
| P1_r0_f1 | **skipped** | KA04, KA16, KI04 | 9 | no healthy bearing in test (designed K005/K006 not in starter) |
| P1_r0_f2 | run | K001, K002, KA22, KI14, KI18 | 7 | |
| P1_r1_f0 | **skipped** | KA04, KA22, KI16, KI18 | 8 | no healthy bearing in test |
| P1_r1_f1 | **skipped** | K002, K003, KA15 | 9 | no inner-race bearing in test (designed KI17/KI21 not in starter) |
| P1_r1_f2 | run | K001, K004, KA16, KI04, KI14 | 7 | |
| P1_r2_f0 | run | K003, K004, KA22, KI04 | 8 | |
| P1_r2_f1 | run | K002, KA04, KA15, KI14, KI18 | 7 | |
| P1_r2_f2 | run | K001, KA16, KI16 | 9 | |
| P1_r3_f0 | run | K002, K003, KA04, KA16, KI18 | 7 | |
| P1_r3_f1 | run | K001, KA22, KI14, KI16 | 8 | |
| P1_r3_f2 | run | K004, KA15, KI04 | 9 | |
| P1_r4_f0 | run | K004, KA04, KA16, KI14 | 8 | |
| P1_r4_f1 | run | K001, K002, KA15, KA22, KI04 | 7 | |
| P1_r4_f2 | **skipped** | K003, KI16, KI18 | 9 | no outer-race bearing in test (designed KA30 not in starter) |

## Implications

1. **Fewer, smaller runs.** 11 of 15 folds ran. Each test fold holds only 3-5 bearings (1-2 per
   class), and each model was trained on only 7-9 bearings. The full design trains on about 20,
   including 12 artificial-damage bearings. The results are therefore a lower-data preliminary
   estimate, not the final P1 result.
2. **Runs are not independent.** The 11 runs reuse the same 12 bearings across repeats, so the
   effective sample size is closer to 12 bearings than 11 independent runs. The paired Wilcoxon
   p-values treat runs as independent and so **overstate** the evidence. They are reported for
   completeness, not as confirmation.
3. **Power is low.** With 11 pairs the smallest possible two-sided Wilcoxon p is about 0.001, and
   Holm correction over the 24 comparisons in `SUMMARY.txt` needs p < 0.002 for the first test.
   Only a difference that holds in essentially every run could reach significance. No comparison
   involving the gated model did (smallest Holm-adjusted p = 0.117, vs stacked fusion).
4. **Large between-run spread.** Clean macro-F1 standard deviation is 0.16-0.18 across runs. That
   is larger than any between-model difference, so which bearings end up in the test fold drives
   the result more than the choice of model.
5. **How to state the result.** On the starter subset, the gated model scores higher than early
   fusion (+0.049) and average fusion (+0.057) under withheld sensor faults. It scores lower than
   vibration-only (-0.015) under withheld faults and lower than all three on clean data. None of
   these differences is statistically significant after Holm correction. This is preliminary
   evidence only.
6. **What would firm this up (after 28 Oct).** The full download enables all 15 P1 folds with the
   designed training sets and P2. A bearing-level analysis (one score per test bearing) would
   avoid the dependence between overlapping runs.
