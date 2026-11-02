# 0.2.0-beta.1 — three-level diagnostics and local phone bridge

**Status:** Implementation candidate, not hardware-accepted. The existing L1, P1, P2 and trusted USB save protocol remain independent. This is a significant functional batch, but **NOT yet a comprehensive hardware certification or a finished Android application**.

## Implemented in this candidate

- L1 remains automatic and unchanged at collector/SMART level; opt-in separate GTK "فحص L2 / L3" tab.
- L2: bounded CPU SHA-256 integrity workload; a 16 MiB test buffer with reversible byte patterns; kernel thermal readings; inventory of webcam, sound, inputs, USB devices, network interfaces. Collection is non-privileged and creates no writes to internal drives.
- L3: explicit desktop confirmation before a 25-second bounded CPU workload and 64 MiB test buffer; thermal stop threshold 85°C for available sysfs thermal zones; cancellation between work chunks; records each step, duration, limitations and pending guided tests.
- Interactive test checklist *instructions* for display, keyboard, touchpad, audio, camera, ports, Wi-Fi and Bluetooth. These are **not automated functional tests** and always retain \`not_tested\` until new dedicated tests exist.
- Separate \`diagnostic_sessions\` field appended only to derived saved/exported report snapshot. Never modifies raw L1 or its purchase verdict, SMART or schema v1 mandatory fields.
- The user explicitly starts/stops the local phone bridge from GTK. Requires an active private IPv4 LAN or phone hotspot/USB tethering. Phone connects to \`https://<local-IP>:<ephemeral-port>/?token=<random>\` and can read report JSON and safe test status; no cloud dependency. Ephemeral RSA certificate with SHA-256 fingerprint displayed on the desktop; browser will flag a locally signed certificate. **User must verify matching certificate fingerprint**, otherwise do not proceed. Server binds one private interface, uses a one-session random bearer token, responds \`403\` for missing/incorrect token, and stops on window close. No remote shell, no automatic service, no public interfaces intentionally bound.
- \`openssl\` and \`iproute2\` included in Live ISO package list.
- Tests for L2/L3 cancellation, evidence semantics, thermal stop, phone access denial, TLS integration and shutdown.

## Limitations / acceptance blockers

1. No QR code in this first batch; user enters/copies URL. No first-party Android APK yet.
2. No remote run/stop from phone; dashboard+JSON only (read-only).
3. No actual touchscreen, panel pixel, speaker/mic, webcam, network throughput, Bluetooth pairing or USB loopback **functional tests** yet. Listing their presence is not a health test.
4. Not an exhaustive DIMM test or GPU/VRAM stress tool; 16/64 MiB allocation does not replace Memtest86+. CPU result is a bounded integrity/workload check, not a certification. Some hardware thermal zones do not expose CPU temperature, and 85°C is a conservative simple default that may not match every chip-specific thermal rating.
5. HTTPS uses a temporary self-signed certificate. Successful HTTPS alone does **not** provide trusted device authentication without verifying the certificate fingerprint. It can be cumbersome on phones; improve pairing before wider distribution.
6. Tests beyond L1 are optional. No intentional writes to inspected internal disks, no auto SMART self-test, no \`badblocks\`, no \`stress-ng\` launched. But running CPU/RAM tests still entails some thermal/runtime risk on marginal hardware.
7. Tests must pass unit tests, GTK smoke tests, bootable ISO build and then real device/phone acceptance; support UEFI, diskless boot and external USB no-write guarantee remain separate physical acceptance gates.

## Minimal real-device acceptance plan (one field session, not incremental patch churn)

- Boot candidate through Ventoy; L1 result must appear as before, without needing phone/hotspot or preparation.
- Start L2, review CPU/RAM, sensors and \`not_tested\` guided components; stop mid-L3 with confirmation and verify cancellation in report.
- Connect Android phone via user hotspot or USB tethering. Start HTTPS bridge locally, validate fingerprint, open URL and download JSON (should match L1 evidence), then close and confirm access no longer works.
- Save report to verified USB; compare \`report.json\` and \`report.html\` hashes against \`complete.json\`. No destructive tests.
- Do not claim PASS until these device tests actually happened.

This candidate intentionally creates a foundation for the fuller L2/L3 test plugins and secure mobile control. The next major implementation batch should add *real* interactive hardware exercises and mobile pairing improvements; do not ask user to field-test tiny intermediate fixes.
