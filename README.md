# USB-PC-Inspector — مختبر فحص الحواسيب

**v0.1 development prototype — real USB boot and ISO build NOT YET VERIFIED.**

A portable, Arabic-first, offline diagnostic system designed to boot from USB
even if the target computer has no internal SSD/HDD or a completely empty disk.
The project targets 64-bit Intel/AMD machines first.

## Implemented source code

- Read-only BIOS/UEFI, CPU, RAM, battery, internal disks and SMART inventory.
- Staged JSONL events (`--events`): first CPU/BIOS, then RAM, battery, disks and SMART, with in-process elapsed timings. The GUI auto-starts the scan and previews facts without premature purchase decisions.
- Preliminary evidence-based L1 purchase guidance (do not buy / inspect before payment / undetermined); no health score or price valuation.
- Explicit "not available / not examined" states; no claim that a computer is
  healthy or new solely because no warnings are displayed.
- Arabic Tkinter GUI; JSON scan result and escaped HTML report.
- Dedicated USB-only report writer for an exFAT/FAT partition labeled
  PCINSPDATA or Ventoy. **No writing to internal disks.**
- Debian Trixie Live ISO recipe with BIOS + UEFI bootloader configuration.
- Automated Python unit-test workflow on pushes and ISO build workflow (source changes to `inspector/` or `bin/` trigger ISO builds). **Successful CI execution and artifact availability require independent verification.**

**Implementation is not field validation:** progressive events, assessments and SMART parsing have source and unit-test coverage, but an ISO boot on physical hardware, results of current CI runs, and the 10–30 second L1 target have not been verified. Process scan durations do not include boot time.

**Not implemented yet:** full RAM diagnostics, CPU stress testing, BIOS firmware
integrity verification, keyboard/display guided tests, confirmed hardware boot,
or any guarantee that a laptop is new.

## Try the scanner from Linux

From the repository root, with Python 3.10+:

    python3 -m inspector.core > report.json
    python3 -m inspector.core --events > inspection-events.jsonl
    python3 -m unittest discover -s tests -v
    python3 -m inspector.gui

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
For implemented features and planned validation, read
[docs/ROADMAP.md](docs/ROADMAP.md).

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
