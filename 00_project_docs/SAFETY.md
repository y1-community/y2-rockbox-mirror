# Y2 Rockbox Safety Rules

Updated: 2026-09-06

Firmware installation can erase data or leave the player temporarily
unbootable. Rockbox Y2 packages are device- and baseline-specific.

## Never do this

- Never flash a Y1 package or another device's preloader/scatter.
- Never use a package for an unknown Y2 hardware or firmware revision.
- Never rename a Beta V2 archive to `rom_y2.zip`.
- Never use the withdrawn Beta V2 packages or
  `InnioasisUpdater_Setup_1.1.2.exe`.
- Never use Format All, Firmware Upgrade, whole-device erase, automatic retry,
  or a write plan outside the five approved Beta V2 partitions.
- Never disconnect or reset while a read or write is active.
- Never publish device-unique protected data or raw private evidence.

## Before installation

- Back up internal storage, microSD, and the complete hidden `.rockbox` tree.
- Keep the exact official Y2 Stock 3.1.7 recovery package available.
- Verify the platform asset against `SHA256SUMS.txt`.
- Charge the player, use a reliable data cable, and avoid hubs.
- Close software that may claim MediaTek or Android USB devices.

## Beta V2 accepted boundary

The only accepted assets are:

- `Y2-Rockbox-Beta-v0.2.0-UPDATE-ONLY.zip`
- `Y2-Rockbox-Beta-v0.2.0-Windows-UPDATE-ONLY.zip`

Both are 361,774,260 bytes with SHA-256
`409DDB4D2D18111FB8C3AB619F10F04B916B6B2A3FC04D1D38011324563F326A`.

The guarded updater may write only UBOOT, BOOTIMG, RECOVERY, LOGO, and ANDROID.
It must verify the device and archive, preserve omitted/protected partitions,
perform no automatic retry, and complete five-range readback verification.

## After flashing

After the updater reports verified completion, unplug the Y2 completely, power
it off if required, and press/release the pinhole once while unplugged. Only the
next clean cold boot is qualified. Temporary artifacts or broken screen sleep
on an updater-attached automatic boot do not replace this reset requirement.

## Stop and recover

Stop on an identity mismatch, checksum failure, unexpected partition, timeout,
write/readback failure, persistent boot loop, repeated wrong route, missing
storage, or persistent crash. Do not improvise a retry. Restore only with the
official complete Y2 Stock 3.1.7 recovery package.

## Release evidence

A release requires deterministic packaging, offline validation, guarded
physical installation on every public route, complete readback, functional and
USB regression, saved-route tests, power/sleep tests, Stock rollback, and
server-side download verification. Public summaries omit device identifiers
and protected partition hashes.
