# USB-PC-Inspector — مختبر فحص الحواسيب

**Current development source: v0.1.6-beta.2 — Arabic GTK physical-right alignment fix; automated Python/GTK PR checks PASS, physical screen retest pending. v0.1.6-beta.1 was field-tested on HP 630, 31/10/2026: P1 health and workload analysis, L1 in 2.165s, and USB JSON/HTML SHA-256 preservation PASS, but Arabic visual right-alignment FAIL. The last fully field-validated release for its claimed scope is v0.1.5-beta.1. UEFI, diskless boot and independent D/G no-internal-write tests are still untested. [0.1.6 evidence and defect](docs/FIELD_VALIDATION_2026-10-31_V016.md).**

**Product plan (31/10/2026):** P0 hardware identity and qualified age are field-validated. P1 health and qualitative office/programming/video/gaming assessments were **field-validated as data/model output** in 0.1.6-beta.1, but visual GTK Arabic RTL failed, so the 0.1.6-beta.2 alignment fix needs a screen retest. No invented benchmarks. Optional buyer profiles (P2) and phone transfer via Wi-Fi/USB/Bluetooth (P3/P4) remain **unimplemented**. See [requirements](docs/PRODUCT_REQUIREMENTS_2026-10-30.md) and [P1 field review](docs/FIELD_VALIDATION_2026-10-31_V016.md).

A portable, Arabic-first, offline diagnostic system designed to boot from USB
even if the target computer has no internal SSD/HDD or a completely empty disk.
The project targets 64-bit Intel/AMD machines first.

## Implemented source code

- Read-only BIOS/UEFI, CPU, RAM, battery, internal disks and SMART inventory.
- **v0.1.6-beta.1 P1 field data PASS, visual RTL FAIL; v0.1.6-beta.2 pending physical retest:** report evidence-based per-component health and documented heuristic workload suitability without real FPS/benchmarks; 0.1.6-beta.2 corrects GTK RTL-mirrored xalign and fixes mixed-script paragraph alignment. JSON remains LTR; HTML has RTL/right alignment. [P1 design](docs/IMPLEMENTATION_P1_2026-10-31.md) and [field review](docs/FIELD_VALIDATION_2026-10-31_V016.md).
- **v0.1.5-beta.1, P0 field-validated on HP 630 (31/10/2026):** read-only PCI GPU, DRM display/EDID (where available), and network adapter inventory; BIOS firmware date and drive power-on hours tracked as **qualified evidence**, not a fictional computer age. Extra GTK tab and offline HTML sections; no health certification from detecting a part. [P0 implementation](docs/IMPLEMENTATION_P0_2026-10-30.md) and [field results](docs/FIELD_VALIDATION_2026-10-31_V015.md).
- Staged JSONL events (`--events`): first CPU/BIOS, then RAM, battery, disks and SMART, with in-process elapsed timings. The GUI auto-starts the scan and previews facts without premature purchase decisions.
- Preliminary evidence-based L1 purchase guidance (do not buy / inspect before payment / undetermined); no health score or price valuation.
- Explicit "not available / not examined" states; no claim that a computer is
  healthy or new solely because no warnings are displayed.
- Native GTK 3 + Pango Arabic RTL dashboard with progressive facts, prominent evidence-based L1 verdict and separate LTR JSON view. The former Tkinter GUI is retained as a legacy fallback, not launched by default.
- Dedicated USB-only report writer for an exFAT/FAT partition labeled
  PCINSPDATA or Ventoy. Validated mount source, independent session directories,
  JSON/HTML read-back, SHA-256 completion manifest and fsync; **save, shutdown, reboot and SHA-256 verification were field-tested on an independent FAT32 PCINSPDATA partition**; writing to the Ventoy boot partition itself is not verified. No intended writing to internal disks.
- Debian Trixie Live ISO recipe with BIOS + UEFI bootloader configuration.
- Automated Python unit-test workflow on pushes and ISO build workflow (source changes to `inspector/` or `bin/` trigger ISO builds). **CI outcomes for this revision must be checked independently before announcing a new ISO.**

**Field evidence:** On 28/10/2026, HP 630 booted via Ventoy/Legacy BIOS, ran the L1 inspection, and saved verified JSON/HTML/complete.json bundles to an independent FAT32 `PCINSPDATA` partition, recoverable after restarting into Ubuntu. On **29/10/2026**, the user explicitly confirmed two L1 scans and two saves **in the same Debian Live session with no reboot between them**. After returning to Ubuntu, four session directories were visible; both new bundles were independently verified (SHA-256 matches for all four JSON/HTML files, valid completion manifests and JSON). The older two directories remained visible; their hashes were not rechecked after the latest test. **B: PASS for the same-session two-scan/two-save persistence behavior on this tested hardware/USB**, with that integrity evidence limit. HP 630 RAM: **8 GB installed (2 × 4 GB DDR3); ~7.56 GiB reported to Linux**. The GTK dashboard's Arabic RTL and LTR JSON were field-observed. UEFI and zero-internal-disk boot remain untested; scan durations exclude USB boot. [29 Oct B field report](docs/FIELD_VALIDATION_2026-10-29_B.md).

**Most recent field verification (29/10/2026):** v0.1.3-beta.1 booted on the real HP 630, scanned in **1.867s** after the collector started (excludes USB boot), displayed the true SMART failure without mislabelling it as a read error, and successfully recovered `report.json` / `report.html` / `complete.json` from `PCINSPDATA` after shutting down Debian Live and returning to Ubuntu. The two report files matched their completion-manifest SHA-256 digests exactly. BIOS date is localized in HTML while JSON preserves its original format. [v0.1.3 field acceptance](docs/FIELD_VALIDATION_2026-10-29_V013.md). **Known reporting UX gaps:** HTML currently lacks an explicit purchase-assessment summary and embeds dense SMART evidence in a single table cell; GTK's RAM card title does not distinguish Linux-visible memory from installed RAM. These issues do not invalidate the tested persistence result.

**Next presentation milestone:** The v0.1.4 source renders the L1 verdict/reasons and key SMART evidence at the top of standalone HTML reports, with long diagnostic output in expandable sections. Both the HTML summary and GTK memory card distinguish installed DMI RAM from Linux-visible `MemTotal`; unknown DMI capacity stays unknown. The JSON v1 and USB save/verification protocol are unchanged. [Presentation design and validation scope](docs/REPORT_PRESENTATION_2026-10-29_V014.md). These improvements are now field-confirmed for the tested HP 630 workflow in [30 October 0.1.4 field report](docs/FIELD_VALIDATION_2026-10-30_V014.md), including an independent SHA-256 check of the recovered JSON and HTML. The older versions remain independently documented.

**Not implemented yet:** full RAM diagnostics, CPU stress testing, BIOS firmware
integrity verification, keyboard/display guided tests, broad hardware compatibility testing,
or any guarantee that a laptop is new.

## Try the scanner from Linux

From the repository root, with Python 3.10+:

    python3 -m inspector.core > report.json
    python3 -m inspector.core --events > inspection-events.jsonl
    python3 -m unittest discover -s tests -v
    python3 -m inspector.gtk_gui

The GTK interface requires `python3-gi` and `gir1.2-gtk-3.0`.
For the old Tk fallback only: `python3 -m inspector.gui`.

The graphical option requires tkinter. Without privileged helpers, SMART and
some DMI information can be unavailable. The complete Live image installs
dedicated allowlisted privileged helpers.

## Building the USB image

On a Debian Trixie Linux build host (Ubuntu 24.04 ships an older live-build that does not support our UEFI options):

    sudo apt-get update
    sudo apt-get install -y live-build debootstrap xorriso squashfs-tools \
      syslinux-utils isolinux grub-pc-bin grub-efi-amd64-bin mtools dosfstools
    sudo ./scripts/build_iso.sh

On Ubuntu 24.04, prefer the GitHub Actions build. Visit **Actions → Build bootable ISO → Run workflow**. The resulting ISO
appears as a downloadable workflow artifact *only if the build passes*.
A successful ISO build still requires testing on physical hardware.

For USB preparation and saved reports, read [docs/USB.md](docs/USB.md).
See also [B/D/G acceptance procedures](docs/ACCEPTANCE_B_D_G_2026-10-28.md) and [v0.1.2 field validation](docs/FIELD_VALIDATION_2026-10-28_V012.md) and [29 Oct B acceptance](docs/FIELD_VALIDATION_2026-10-29_B.md) and [USB save audit and acceptance matrix](docs/USB_SAVE_AUDIT_2026-10-27.md)
and [GTK Arabic UI acceptance](docs/GTK_ARABIC_UI_2026-10-28.md).
For implemented features and planned validation, read
[docs/ROADMAP.md](docs/ROADMAP.md). See [29 October diagnostic-accuracy audit](docs/DIAGNOSTIC_ACCURACY_2026-10-29.md) for the version boundary, SMART semantics and battery field note.

## Approved product direction (planned; not yet implemented)

The default experience is **general, preparation-free, offline-first, rapid inspection**
followed by optional progressively deeper tests. An optional purchase profile can
compare the actual hardware with seller claims, intended workloads, budget and
warranty. Later phases plan secure wireless pairing with a phone, a dedicated
Android companion app, an evidence-grounded optional AI agent, and explicitly
authorized remote desktop control. These features are **not implemented in v0.1**.

- [Approved architecture and product requirements](docs/ARCHITECTURE.md)
- [Milestone roadmap and acceptance criteria](docs/ROADMAP.md)


## Safety policy

No partition creation, formatting, firmware flashing or writing to internal
disks. The default probe only executes observational commands. The external
USB report partition is checked by physical USB transport, label and filesystem.
A missing storage device is a valid inspection outcome, not a fatal exception.
SMART data can be missing, reset or misleading.

Do not change seller-owned firmware settings without permission. Shut down
cleanly before removing the USB.

License and third-party distribution terms will be settled before release.
