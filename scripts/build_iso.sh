#!/usr/bin/env bash
# Build an amd64 Debian Live ISO with BIOS and UEFI bootloaders.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$ROOT/live"
DEST="$LIVE/config/includes.chroot"
if [[ "$(id -u)" != "0" ]]; then
  echo "Run: sudo ./scripts/build_iso.sh" >&2
  exit 1
fi
command -v lb >/dev/null || { echo "Install live-build first" >&2; exit 1; }
mkdir -p "$DEST/opt/pc-inspector/inspector" "$DEST/usr/local/bin"
install -m 0644 "$ROOT"/inspector/*.py "$DEST/opt/pc-inspector/inspector/"
install -m 0755 "$ROOT/bin/pc-inspector-collect" "$DEST/usr/local/bin/pc-inspector-collect"
install -m 0755 "$ROOT/bin/pc-inspector-save" "$DEST/usr/local/bin/pc-inspector-save"
cd "$LIVE"
# Remove ONLY generated configuration. Keep tracked package lists and includes.
rm -rf config/binary config/bootstrap config/chroot config/common config/source
lb config \
  --distribution trixie \
  --architecture amd64 \
  --binary-image iso-hybrid \
  --bootloaders "syslinux,grub-efi" \
  --uefi-secure-boot auto \
  --debian-installer none \
  --archive-areas "main contrib non-free-firmware" \
  --bootappend-live "boot=live components username=user" \
  --apt-recommends false
lb build
echo "ISO build finished. Verify SHA-256 before writing any USB device."
