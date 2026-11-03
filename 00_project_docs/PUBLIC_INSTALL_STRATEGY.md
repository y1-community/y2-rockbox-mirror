# Public Install Strategy

Updated: 2026-09-06

## Current Beta V2 distribution

Beta V2 publishes two byte-identical, platform-qualified Class A update files:

- macOS: `Y2-Rockbox-Beta-v0.2.0-UPDATE-ONLY.zip`
- Windows: `Y2-Rockbox-Beta-v0.2.0-Windows-UPDATE-ONLY.zip`

Both are 361,774,260 bytes with SHA-256
`409DDB4D2D18111FB8C3AB619F10F04B916B6B2A3FC04D1D38011324563F326A`.
They target only the Innioasis Y2 on the official Stock 3.1.7 lineage.

The archive and updater are fail-closed around a five-target Download Only
plan: UBOOT, BOOTIMG, RECOVERY, LOGO, and ANDROID. PRELOADER, partition tables,
SEC_RO, CACHE, USRDATA, formatting, whole-device erase, omitted-partition
cleanup, protected writes, and automatic retry are forbidden.

`rom_y2.zip`, the withdrawn Beta V2 packages, and
`InnioasisUpdater_Setup_1.1.2.exe` are not supported. See
[Y2_BETA_V2_UPDATER_FORMATS.md](Y2_BETA_V2_UPDATER_FORMATS.md) for the complete
contract and failure history.

## Required user safeguards

Before installation, users must:

1. back up internal storage, microSD content, and the hidden `.rockbox` tree;
2. preserve settings, themes, playlists, and databases;
3. retain the official Y2 Stock 3.1.7 recovery package;
4. verify the selected asset against `SHA256SUMS.txt`;
5. use a charged player, reliable data cable, and no USB hub; and
6. stop on any identity, validation, timeout, write, or readback failure.

After verified completion, users must fully unplug the Y2 and perform one
unplugged pinhole reset before the qualified first boot.

## Public source and history model

The public repository contains reviewed source, documentation, builders, and
validators. Generated firmware, vendor images, device dumps, and private
device-unique evidence remain outside Git history. Every binary release carries
complete corresponding source and applicable license notices.

## Publication requirements

Every public firmware release must include:

- exact device and official-baseline compatibility;
- immutable filenames, sizes, checksums, and machine-readable manifest;
- complete backup, install, post-flash reset, and recovery instructions;
- complete corresponding source and license notices;
- an explicit permitted partition/write plan;
- separate physical qualification of each public updater route;
- server-side re-download and checksum verification; and
- clear accepted behavior, known limitations, and stop conditions.

No experimental, offline-only, generically routed, or merely booting build may
be described as physically accepted.
