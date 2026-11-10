# Demo recordings (Paderborn University bearing data)

This folder holds only the three held-out recordings replayed by the dashboard's professor demo:

| File | Bearing | Condition |
|---|---|---|
| `KI18/N15_M07_F10_KI18_1.mat` | KI18 | inner-race damage (real, accelerated lifetime test) |
| `KA22/N15_M07_F10_KA22_1.mat` | KA22 | outer-race damage (real, accelerated lifetime test) |
| `K004/N15_M07_F10_K004_1.mat` | K004 | healthy |

None of these bearings was used to train `models/demo_models.pkl`. The files are unmodified.

**Source and licence.** Paderborn University, Chair of Design and Drive Technology (KAt),
KAt-DataCenter: https://mb.uni-paderborn.de/kat/forschung/kat-datacenter/bearing-datacenter.
Licensed under Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0):
https://creativecommons.org/licenses/by-nc/4.0/ . Non-commercial academic use only.

Please cite: C. Lessmeier, J. K. Kimotho, D. Zimmer, W. Sextro, "Condition Monitoring of Bearing Damage
in Electromechanical Drive Systems by Using Motor Current Signals of Electric Motors: A Benchmark Data Set
for Data-Driven Classification", European Conference of the PHM Society, Bilbao, 2016.

The full dataset (download with `scripts/windows/pu_download.bat`) is not part of this repository.

## Gearbox demo recordings (MCC5-THU v2)

Deployments without `data/mcc5` (Streamlit Cloud) replay three held-out recordings of the 1000 rpm / 10 Nm
operating profile, listed with their SHA-256 in `models/gearbox_demo_manifest.json`. They are unchanged
(gzip-compressed) copies of the publisher's CSV files. Source: Shijin Chen, Zeyi Liu, Xiao He, Dongliang Zou
and Donghua Zhou (2024), MCC5-THU v2, Mendeley Data, DOI 10.17632/p92gj2732w.2, licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). The dashboard accepts a file only if its checksum matches.
`models/gearbox_demo_1000rpm_10Nm.pkl` is the pilot model for that profile, fitted by
`scripts/export_gearbox_demo.py` on the other three profiles exactly as the dashboard fits it.
