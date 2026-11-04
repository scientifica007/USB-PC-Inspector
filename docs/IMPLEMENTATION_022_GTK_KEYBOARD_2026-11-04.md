# 0.2.2-beta.1 — GTK scroll, RGB pixel diagnostics, and keyboard layouts

**Status: development candidate, not field validated on HP 630.**
Reference: 04/11/2026 field report 09, preserving L1/SMART failure and previous working L2/L3/phone features.

## Field issues and fixes

1. After L2, Health grows, and long pages are cut short: the main Gtk.Stack now uses vhomogeneous=False, and all Gtk.ScrolledWindows keep natural height propagation disabled, with explicit vertical expansion. A GTK/Xvfb test checks bottom-of-page scroll after switching through Health, Hardware and Workloads. No diagnostics or disk behavior was changed.
2. Colors remained gray after repeated Cairo drawing attempts. Both regular and fullscreen tests now paint an actual RGB GdkPixbuf into Gtk.Image, with exact red, green, blue, white, black bytes verified in GTK tests. Real LCD behavior must be visually confirmed; an Xvfb PASS does not prove hardware PASS.
3. Keyboard test accepts selection between US QWERTY (XKB us), French AZERTY (XKB fr), and **Arabic (Algeria)** (XKB dz(ar), not the plain Berber dz layout). It shows physical-row references, last key name, and scancode when available. F keys may still be intercepted by the window manager; missing events do not independently prove hardware failure.
4. Selecting a reference keyboard does **not** change the live keyboard. A separate user-initiated button changes the current X11 session using setxkbmap, snapshots the original XKB layout/model/variant/options, and tries to restore it when closing the test window. This temporary session-wide change can affect other programs. No disk or system keyboard config is written. Unsupported Wayland/Xwayland does not silently claim success. The restoring operation is best-effort if X11 disappears.

## Required hardware acceptance steps

- Open each right-sidebar page, run L2, return to Hardware/Health/Workloads/JSON; verify the vertical scrollbar reaches the actual last line. No need to repeat a 15-minute L3 to validate scrolling.
- Open the display test. For each of the five colors, check the regular panel and fullscreen image: real pixels should change, with no persistent gray rectangle. Escape must exit fullscreen.
- Change keyboard reference among QWERTY, AZERTY, Arabic Algeria. Check it changes the displayed reference but not the OS layout. Then apply each explicitly, type and observe the resulting symbols, close, and confirm the original layout is restored. Report intercepted F2/F3/F12/Print Screen honestly as inconclusive until independently checked.
- Save on Ventoy writable partition as previously, and verify report JSON, HTML, complete.json. L1 SMART must remain do_not_buy for the HP 630.
- No field PASS should be announced from only CI, an ISO build, or pixel-buffer memory tests.

## Tests
- Python unit: XKB snapshot validation, whitelist, exact Algerian variant, Wayland fail-closed, restoration.
- GTK/Xvfb: fullscreen image widget initialization and 5 distinct pixel RGB colors, scroll-to-end after L2, read-only reference selector, reversible apply and close.
- ISO: x11-xkb-utils (setxkbmap) is now explicitly included in the Debian Live package list.

**Security scope:** no intentional writes to internal disks, no new privileged commands, no changes to USB persistence.
