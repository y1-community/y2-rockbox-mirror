# Y2 Rockbox Beta v0.1.0 Release

Date: 2026-07-29

## Release decision

Beta v0.1.0 uses the physically tested V88 firmware unchanged. The release
asset is an outer-file rename of the exact tested ZIP, so its bytes and
SHA-256 remain identical:

```text
Release filename:
Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip

Internal engineering build:
V88 route readback repair

Size:
366,781,486 bytes

SHA-256:
40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE
```

V89 is not the release firmware. It is an offline-validated display-surface
hardening experiment which has not been flashed to the physical Y2.

The apparent persistent display-scaling problem reported after the V88 USB
test was resolved by comparison photographs. MacClassic uses an almost
full-screen `468x354` UI viewport. SNAZZ3 deliberately uses a `420` pixel-wide
menu viewport with 30-pixel side margins and a black background, which makes
the interface look inset. V88 continued to render a full `480x360` framebuffer.
The completed USB transfer and automatic Rockbox return therefore count as a
physical pass.

## Physical beta test result

Passed on the Innioasis Y2:

- complete firmware flash through InnioasisUpdater 1.1.2;
- normal no-button boot to Rockbox;
- Volume Up boot to the stock Y2 player;
- Volume Down boot to Boot Settings;
- saving Rockbox and Stock normal-boot choices;
- saving an already-selected choice and automatic restart;
- repeated cold boots using the saved route;
- playback for at least 15 minutes;
- wheel, centre, previous, next, back, play/pause and volume controls;
- sleep and wake;
- theme selection and persistence after restart;
- internal-storage and microSD playback;
- USB storage enable, file transfer, safe eject, disable and Rockbox return;
- normal power off; and
- restoration to official stock firmware.

## Beta limitations

- Bluetooth playback is untested.
- The fixed both-volume fastboot chord is configured but did not open fastboot
  during physical testing. It must not be presented as a working recovery
  route.
- Use InnioasisUpdater with the reset/pinhole detection sequence for recovery.
- Setting the date and time did not persist during Rockbox testing. This may be
  inherited from the stock firmware and has not yet been isolated.
- InnioasisUpdater 1.1.2 performs a full format-download. Flashing erases the
  device, including user data and settings.
- SNAZZ3 intentionally has a visibly inset layout. This is a theme design, not
  display scaling.

These limitations are acceptable only for an explicitly labelled beta.

## Release assets

The assembled folder must contain:

```text
README-FIRST.txt
Y2-Rockbox-Beta-v0.1.0-Guide.pdf
Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip
InnioasisUpdater_Setup_1.1.2.exe
Y2-Rockbox-Beta-v0.1.0-Source.zip
SHA256SUMS.txt
LICENSE.txt
NOTICE.txt
```

The source archive is required because the firmware distributes a modified
Rockbox binary under GPL-2.0-or-later. The checksum manifest is required
because the Windows updater setup is unsigned and the firmware performs a
destructive full-device flash.

The 76 MB updater setup contains `dpinst64.exe`, and the official flashing
tutorial shows its bundled MediaTek USB-driver installation. Do not add an
unverified third-party driver bundle to this release.

## Publishing gate

Before uploading:

1. Confirm the release folder contains only the files listed above.
2. Recompute every SHA-256 from the final folder.
3. Open the PDF from the final folder and visually inspect every page.
4. State clearly in the release title and description that this is a beta.
5. Copy the beta limitations into the public release notes.
6. Keep an official Y2 stock-recovery package available from Innioasis
   support, but do not mix it into the Rockbox firmware ZIP.
7. Publish or attach the complete corresponding source at the same time as
   the firmware binary.

The official support and recovery entry point is:

```text
https://www.innioasis.com/a/docs/y2/reset-your-device
```
