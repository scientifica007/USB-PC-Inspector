# Field validation — USB-PC-Inspector 0.1.7-beta.1 — 02/11/2026

**Scope:** HP 630 / Ventoy / Legacy BIOS; first real-device exercise of optional P2 buyer profiles. This is **partial field acceptance**, not certification of all devices or every workflow. **No automatic destructive operation, benchmark, or internal disk write was authorized.**

## Evidence reviewed

- User Drive folder: https://drive.google.com/drive/folders/1K_O2zP1z3rw1T1KF7AtoeDOeywFoxFdR
- 50 photographs from 02/11/2026 showing boot selection, live UI, generic L1, RTL tabs, optional buyer form, partial personal verdict, file chooser, USB profile save, and report-save confirmation.
- Independent subsequent Ubuntu screenshots show `PCINSPDATA/PC-Inspector-Profiles/` containing one profile and `PCINSPDATA/PC-Inspector-Reports/` containing the new 02 Nov report alongside prior sessions.
- The specific newly recovered files: `profile-821732684d6e47ba89ed4c9491908712.json` (300 bytes), `report.json` (53,269 bytes), `report.html` (53,464 bytes), `complete.json` (252 bytes). Neither raw reports nor photographs are committed to this public repository.

## Independently checked artifact integrity

| File | Size (bytes) | SHA-256 | Matches complete.json? |
| --- | ---: | --- | --- |
| report.json | 53269 | a9309dd4bc933b4d285b7d11c4df09f79189eb526912cc61b4de3fcb2813573b | PASS |
| report.html | 53464 | d189c439fee3f87dab7b1bb33ebb0e2809b3469c28f3fccdb1912d772958cce9 | PASS |
| profile-821732684d6e47ba89ed4c9491908712.json | 300 | 3efad79650b7f47ab8bdafeaad5998c16bc6185323cff837dda10fb92197d806 | Separate profile (not a complete.json report entry) |

`complete.json` contains `complete=true`, byte counts and matching SHA-256 for both report files. The persisted profile's parsed JSON object equals `report.json.buyer_profile`.

Report: `tool_version=0.1.7-beta.1`, `created_utc=2026-11-02T06:42:38.783251+00:00`, `scan_timing.total_seconds=1.553` (scan duration, not boot time).

## P2 personalized evaluation (observed)

- Personal profile name: «متطلباتي  001»; office workload; minimum installed RAM 8 GB; minimum disk capacity 500 GB; personal budget ceiling 70,000 DZD; claimed minimum warranty 2 months; seller model `hp630`, RAM 8 GB.
- Offer supplied by user: 20,000 DZD and 2 months' claimed warranty; **not independently verified seller claims**.
- Hardware requirements PASS for installed RAM and nominal disk capacity; office suitability CONDITIONAL without performance measurement; budget and supplied warranty thresholds PASS.
- Critical SMART problem still yields generic `purchase_assessment.verdict=do_not_buy`, overall health `critical`, personalized `buyer_profile_assessment.personal_verdict=reject`. **PASS: profile, low price, warranty do not override drive failure.**
- HTML contains the original L1 verdict and independently labeled personal verdict with the five assessment axes.
- `seller_model` check was marked `fail` although the DMI model is `HP 630 Notebook PC` and buyer profile has `hp630`. This is a **real field false mismatch** due to abbreviated/spaceless spelling. The source fix must mark such compact-prefix matches `needs_verification`, not `pass` or `fail`; `HP 650` remains `fail`.
- Photo of a rejected nonnumeric `min_logical_processors` entry: appropriate input validation, not evidence of a crashed scan.

## Acceptance decisions

| Capability | Status on HP 630 |
| --- | --- |
| Legacy BIOS / Ventoy boot and app launch | PASS (photographed) |
| General no-profile path and original L1 SMART rejection | PASS (photographed + report) |
| Optional GTK Arabic profile editor and personalized comparison | PASS within visible tested scenarios |
| RTL physical-right presentation of Arabic tabs/personal view | PASS visually in submitted photos; mixed English/Arabic alignment can still be refined |
| Profile export to USB separate from preserved older reports | PASS (screenshot + recovered profile) |
| Saved custom report JSON/HTML and SHA-256 manifest | PASS (independent recovery/check) |
| Matching saved profile to embedded evaluated profile | PASS |
| `hp630` vs `HP 630 Notebook PC` seller-model normalization | FAIL (fixed in follow-on source branch; not field retested) |
| End-to-end re-import from USB by the app / arbitrary file chooser | Not conclusively proven by recovered artifacts; some chooser screenshots show empty directories |
| UEFI / diskless / independent D/G no-write test / P3 phone transfer | Not tested / not implemented |

## Retest strategy

Do **not** repeat the prior P0/P1/RTL/USB save exercises. After new fixed image becomes available, retest the model claim `hp630` against `HP 630 Notebook PC` expecting `needs_verification`, still `reject` for failing SMART. If practical, do one explicit `list → load → compare` profile round-trip in the app. No destructive tests.
