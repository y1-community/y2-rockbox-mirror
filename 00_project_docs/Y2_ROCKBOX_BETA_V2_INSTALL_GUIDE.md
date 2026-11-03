# Y2 Rockbox Beta V2 Installation and Use Guide

Updated: 2026-09-06

Beta V2 is only for the Innioasis Y2 on the official Stock 3.1.7 firmware
lineage. Do not use a Y1 package, another device's scatter/preloader, or a
package for an unknown Y2 hardware revision.

## Before installing

1. Back up internal storage and microSD content.
2. Back up the complete hidden `.rockbox` directory, including themes,
   playlists, settings, and databases.
3. Keep the exact official Stock 3.1.7 recovery package available.
4. Charge the player and use a reliable data cable without a USB hub.
5. Verify the download against `SHA256SUMS.txt`.

## Choose the exact platform asset

- macOS: `Y2-Rockbox-Beta-v0.2.0-UPDATE-ONLY.zip`
- Windows: `Y2-Rockbox-Beta-v0.2.0-Windows-UPDATE-ONLY.zip`

Both files are byte-identical, 361,774,260 bytes, with SHA-256:

`409DDB4D2D18111FB8C3AB619F10F04B916B6B2A3FC04D1D38011324563F326A`

Do not rename either archive to `rom_y2.zip`. Do not use the old
`InnioasisUpdater_Setup_1.1.2.exe`, a withdrawn Beta V2 archive, a Y1 package,
or a generic/full-format updater route.

Install only with an updater explicitly carrying the guarded Y2 Class A route.
That route verifies the exact model, layout, archive identity, and Stock 3.1.7
baseline; performs Download Only; writes only UBOOT, BOOTIMG, RECOVERY, LOGO,
and ANDROID; does not format or clean omitted partitions; performs no automatic
retry; and requires five-range readback verification before reporting success.
If your updater does not describe these protections, stop.

## During installation

1. Select the Innioasis Y2 and Rockbox Beta V2.
2. If browsing manually, select only the exact platform filename above.
3. Keep the Y2 powered off and disconnected until the updater explicitly asks
   for it.
4. Connect directly without a hub and follow the updater's prompts.
5. Do not press Power, Volume, or pinhole unless the guarded updater explicitly
   instructs you.
6. Do not unplug while a read or write is active.
7. Stop on any identity, checksum, partition-plan, timeout, or readback failure.
   Do not improvise a retry.

## Mandatory action after successful verification

1. Wait for the updater to report completed verification.
2. Unplug the Y2 completely.
3. Power it off if necessary.
4. While unplugged, press and release the bottom pinhole once.
5. Start the Y2 normally.

The updater-attached automatic boot can inherit temporary MediaTek loader state,
causing upper-screen artifacts or broken screen sleep. It is not the qualified
first boot. The clean post-pinhole boot should reach the responsive Rbox root in
about 28 seconds without upper artifacts.

## Boot routes

| Input while powering on | Destination |
|---|---|
| No Volume button | Saved normal player; Rockbox by default |
| Volume Up | Opposite player; Stock by default |
| Volume Down | Boot Settings |

In Boot Settings, choose the normal player and select **Save & Restart**.
Volume Up automatically remains the opposite player. A simultaneous
Volume-button chord and fastboot are not Beta V2 features.

## Rockbox controls

- Centre confirms selections and wakes the sleeping display.
- Short Centre on Now Playing toggles play/pause; long Centre opens the standard
  context menu, including Bookmarks.
- Holding Previous/Next seeks within the current track.
- The optional Volume long-press setting makes held Volume buttons skip tracks
  while short presses still change volume.
- Short Back from the database returns to Now Playing. Long Back from Now
  Playing returns to the previous database/browsing context.
- Rockbox wheel-vibration strength includes true-off and remains independent
  from Stock's key-vibration setting.

## Bluetooth and USB

Open **Settings > Bluetooth** from Rockbox to enter Android Bluetooth Settings.
Beta V2 passed pairing, A2DP playback, controls, disconnect, and reconnect.

For USB Storage, wait for the USB screen and enable storage only when needed.
Safely eject every mounted Y2 volume on the computer before turning USB storage
off or unplugging. Rockbox does not automatically resume a paused track after
USB; this is normal.

## Recovery and known limitation

Stop and use the official Stock 3.1.7 recovery path after a failed install,
persistent boot loop, repeated wrong route, missing storage, or persistent
crash dialog. Never substitute recovery files from another device.

The final power-down animation can look imperfect. Shutdown itself passed; the
presentation fix is planned for Beta V3.
