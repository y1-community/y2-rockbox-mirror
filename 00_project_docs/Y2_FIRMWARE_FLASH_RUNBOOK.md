# Y2 Firmware Package Flash Runbook

Date: 2026-07-29

> [!CAUTION]
> This file is a historical development runbook. Its V84/V88 candidates and
> InnioasisUpdater 1.1.2 procedures are not Beta V2 installation instructions.
> For the current public release, use
> `Y2_ROCKBOX_BETA_V2_INSTALL_GUIDE.md` and only the exact guarded Class A
> platform asset documented there.

## Purpose

Use the Y1-style install method on the Y2, but with a Y2-specific package based on the official Y2 3.1.7 firmware.

The active qualified firmware base is V88. Its saved-route readback repair has
passed physically: saved Stock and saved Rockbox no-button boots recorded
`route_map_source=saved-settings`, and both save transactions were verified,
acknowledged, and followed by automatic reboot. Full regressions, the
remaining route checks, and official-stock rollback are still required before
public release.

```text
ACTIVE CANDIDATE:
build-intermediates/y2-v88-route-readback-repair-innioasis-full.zip
366,781,486 bytes
SHA-256: 40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE
Offline validation: 24/24 passed; package rebuilt byte-for-byte
Physical status: saved-route readback passed; regressions/rollback remain
```

The definitive instructions are in
`Y2_V88_ROUTE_READBACK_REPAIR_BUILD_AND_TEST.md`.

The V84 required three-partition update is rejected for InnioasisUpdater
1.1.2. That frontend was proven to invoke SP Flash Tool `format-download`,
which erased the full eMMC before writing the three selected images.
The authoritative recovery state is in
`Y2_V84R1_FLASH_FAILURE_RECOVERY_AND_BUILD.md` and
`V84R1_RECOVERY_AND_PHYSICAL_GATE_CHECKLIST.md`. The older version notes below
are development history, not recommendations to flash them.

All earlier prototypes and V14-V83 packages are superseded for the active
physical gate. V83 physically produced a mixed V83-system/V81-boot installation
and is rejected. The selective V84 package is also rejected for this updater.

```text
REJECTED: build-intermediates/y2-v84-required-three-partition-update.zip
OFFLINE CANDIDATE: build-intermediates/y2-v84r1-innioasis-updater-full.zip
```

The immediate device action, after explicit approval, is official-stock
recovery. Do not retry the selective package. The V84R1 package is not a
substitute for first proving that stock recovery and normal boot still work.

## Historical V84 Recovery Candidate

Rejected selective ZIP:

```text
build-intermediates/y2-v84-required-three-partition-update.zip
```

V84R1 offline candidate:

```text
build-intermediates/y2-v84r1-innioasis-updater-full.zip
366,783,952 bytes
SHA-256 5E503D03E4615F14AE4EE307DBED14172A2240379CBD1AD89418F35DFE78A263
```

Validation report:

```text
Progress logs/v84r1-offline-validation/validation-summary.txt
```

Validation result:

```text
Dedicated packaging validation: 12/12 PASS
Valid Y2 package shape: true
Full official selection: 12 partitions including PRELOADER, MBR/EBRs,
LK, BOOTIMG, RECOVERY, SEC_RO, LOGO, ANDROID, CACHE, and USRDATA
Official-stock exact: preloader, MBR/EBRs, secro, cache, userdata
Firmware payload: exact reproduced V84 images
```

Expected V81 physical markers:

```text
y2_rockbox_v84_coherent_boot_settings_marker.txt
y2_rockbox_v84_coherent_boot_settings_snapshot.txt
```

Physical V9 result:

```text
Stock UI booted.
Device scanned files and showed the language selection flow.
Probe UI auto-launched as "Y2 V9 Input Capture Probe".
Hardware keys and wheel updated the key logger.
F:\y2_probe_v9_input_marker.txt confirmed app-level dispatchKeyEvent logging.
The lock/power button did not update the app key logger.
```

Dedicated result note:

```text
00_project_docs/Y2_PROBE_SYSTEM_PROTOTYPE_V9_PHYSICAL_RESULT.md
```

Confirmed app-level key codes:

```text
4  BACK
19 DPAD_UP/wheel-up
20 DPAD_DOWN/wheel-down
21 DPAD_LEFT/previous
22 DPAD_RIGHT/next
24 VOLUME_UP
25 VOLUME_DOWN
66 ENTER/center
85 MEDIA_PLAY_PAUSE
```

V9 verification hashes:

```text
Dumped V9 Y2Probe.apk: 81403A8BFFCC7F3C2FEAA475512F6B2F4238CCE9CE426C20A4D21A76B10AE4C9
Dumped MyLauncher.apk: AD39091E24CB0542FFEBF0D2E922860B3A51EA13B5A2F95233FED159F62CB1BD
Stock MyLauncher.apk:  AD39091E24CB0542FFEBF0D2E922860B3A51EA13B5A2F95233FED159F62CB1BD
```

## V7 Finding

V7 physically flashed after stock restore readiness, booted into the normal stock UI, exposed USB mass storage, and wrote `F:\y2_probe_v7_boot_marker.txt`. The marker confirmed `org.y2rockbox.probe` received `BOOT_COMPLETED` and wrote entries at boot start, 15 seconds, and 60 seconds with shared storage mounted.

## V8 Finding

V8 physically flashed after V7 success, booted into the normal stock UI, exposed USB mass storage, wrote `F:\y2_probe_v8_launch_marker.txt`, and auto-launched the visible probe UI. The marker confirmed `BOOT_COMPLETED:start`, `BOOT_COMPLETED:15s`, `BOOT_COMPLETED:60s`, `BootLogService:launchActivity`, and `MainActivity:onCreate` with `externalState=mounted`.

The visible probe screen confirmed `/storage/sdcard0` exists, is readable, and reports writable. Hardware key capture was not confirmed: button presses and wheel movement did not visibly update the probe key log, and the probe screen could not be scrolled by controls or touch.

## V9 Finding

V9 physically passed. It kept the V8 boot auto-launch behavior and added broader input logging. The marker confirmed foreground app-level `dispatchKeyEvent` delivery for wheel up/down, previous/next, center, play/pause, back, and volume up/down. Long presses generated repeated down events. The lock/power button did not appear in the app key logger and should be treated as a system power path unless later lower-level work proves otherwise.

## V10 Finding

V10 physically proved the Rockbox-owned boot receiver, delayed launch service, and activity launch path. The device booted normally to stock UI, showed the stock file-scan/language selection flow, then Rockbox auto-launched and crashed with Android reporting `Unfortunately, Rockbox has stopped`. V10 did not include marker instrumentation, so V11 was built to locate the crash stage.

## V11 Finding

V11 physically confirmed the launch path and found the concrete failure. `F:\y2_rockbox_v11_launch_marker.txt` showed `Y2BootReceiver`, `Y2BootLaunchService`, `RockboxActivity`, and `RockboxService` all ran. The service reached `RockboxService:System.loadLibrary rockbox begin`, then the Rockbox thread threw `UnsatisfiedLinkError` because Android searched `nativeLibraryDirectories=[/vendor/lib, /system/lib]` and did not find `librockbox.so`.

The V11 APK contains `lib/armeabi/librockbox.so`, but the current `/system/app/Rockbox.apk` installation path does not make that library visible to the Android 4.4 loader on this firmware. Preserve the V11 marker instrumentation and build V12 with Rockbox native libraries copied into `/system/lib`.

## V12 Finding

V12 was physically flashed and passed its immediate diagnostic goal. The marker reached `RockboxService:System.loadLibrary rockbox success`, then `extract complete`, `native main begin`, and `framebuffer attached before native main display`. The visible screen was a repeated striped/grid display rather than readable Rockbox UI.

Interpretation: the native-library blocker is fixed. The next blocker is display integration, likely native framebuffer dimensions/orientation versus Android surface dimensions.

## V13 Finding

V13 was physically flashed and failed. It launched Rockbox, but forced the device UI sideways and Android reported `Unfortunately, Rockbox has stopped`. The marker reached `native main begin`, created a framebuffer, and logged `displayMetrics=360x480` and `surface=360x480 native=320x480 dst=20,0-340,480`, but did not capture a first framebuffer update before process death.

Interpretation: the forced portrait setting caused the sideways stock UI state, and the 320-pixel-wide native framebuffer conflicted with the existing default `ui viewport: 6,3,468,354` config.

## V14 Finding

V14 is built and validated offline as the next physical test candidate. It uses `y2_rockbox_v14_landscape_marker.txt`, restores landscape orientation, rebuilds Rockbox as 480x360, keeps the scale/center framebuffer bridge, and starts only after external storage is mounted/readable/writable.

The immediate physical success criterion is that the stock UI is not left sideways after Rockbox launch/crash. If Rockbox still crashes, preserve the marker and inspect `RockboxFramebuffer:firstUpdate` and `UNCAUGHT_EXCEPTION` lines.

## V6 Finding

V6 physically flashed but did not reach the normal UI. The device showed the Innioasis logo, then stayed on the logo after pinhole reset. ADB was not available from either local `adb.exe` copy while in that state. Treat V6 as failed and superseded.

## V5 Finding

V5 physically flashed and booted, but `E-book` still opened the stock e-book UI. Offline follow-up found the build script used the sparse compatibility tool with the wrong argument order:

```text
python3 y2_sparse_compat.py --rewrite-no-fill system.fill.img system.img
```

The tool expects the input image as the positional argument and the output after `--rewrite-no-fill`:

```text
python3 y2_sparse_compat.py system.fill.img --rewrite-no-fill system.img
```

Because the output directory had copied a base `system.img` before the rewrite step, V5 inspected the stale sparse image rather than replacing it. The modified raw image and dumped APK checks were real, but the flash zip's `system.img` stayed at SHA-256 `CEC46EF34288C11339E19DB98A7EBEB28612DCF4B8C9C12AE433E2C45F009A9F`. V6 force-removes stale sparse outputs before conversion and has a distinct `system.img` hash.

## Failed V2 Finding

Do not flash these superseded packages:

```text
12_build_outputs/y2-probe-system-prototype-rom.zip
12_build_outputs/y2-probe-system-prototype-rom-v2.zip
12_build_outputs/y2-probe-system-prototype-rom-v3-nofill.zip
12_build_outputs/y2-probe-system-prototype-rom-v4-nofill-0644.zip
12_build_outputs/y2-probe-system-prototype-rom-v5-ebook-probe.zip
12_build_outputs/y2-probe-system-prototype-rom-v6-ebook-activity-probe.zip
```

The v2 flash failed after `FormatAll` and early image download with:

```text
S_DA_SDMMC_WRITE_FAILED (3154)
```

Offline comparison showed all stock restore files matched except `system.img`. The likely package-format issue was sparse chunk compatibility:

```text
stock system.img: RAW + DONT_CARE chunks, no FILL chunks
v2 system.img:    RAW + FILL chunks
v4 system.img:    RAW + DONT_CARE chunks, no FILL chunks; probe APK mode 0644
```

See:

```text
00_project_docs/Y2_FAILED_PROTOTYPE_FLASH_ANALYSIS.md
```

## Safety Rules

Do not use any Y1 package, scatter, preloader, or updater output.

Flash only an explicitly approved, hash-verified candidate under its documented
physical test contract.

Do not continue if validation reports any changed critical file:

```text
preloader_eastaeon82_wet_kk.bin
MBR
EBR1
EBR2
lk.bin
boot.img
recovery.img
secro.img
```

Keep the official stock package ready before starting:

```text
Y2/y2_v3.1.7-20260601/y2_v3.1.7-20260601
```

## Pre-Flight

Run these from the repo root before plugging in the Y2:

```powershell
python 00_tools\y2_firmware_validator.py "Y2\y2_v3.1.7-20260601\y2_v3.1.7-20260601" --official-root "Y2\y2_v3.1.7-20260601\y2_v3.1.7-20260601" --fail-on-critical-diff
python 00_tools\y2_firmware_validator.py "12_build_outputs\y2-probe-system-prototype-rom-v9-input.zip" --official-root "Y2\y2_v3.1.7-20260601\y2_v3.1.7-20260601" --out-md "00_project_docs\Y2_PROBE_SYSTEM_PROTOTYPE_V9_INPUT_VALIDATION.md" --out-json "12_build_outputs\y2-probe-system-prototype-v9-input-fullraw\validation.json" --fail-on-critical-diff
python 00_tools\y2_sparse_compat.py "12_build_outputs\y2-probe-system-prototype-v9-input-fullraw\system.img"
Get-FileHash "12_build_outputs\y2-probe-system-prototype-rom-v9-input.zip" -Algorithm SHA256
```

Expected hash:

```text
F9EDE166419A557DD8CDECCA4A108A7A811FC3247AAEB3E51356B3C9D5E58F0A
```

## Physical Session Outline

Only plug in the Y2 when ready to do the physical flash session.

1. Charge the Y2 sufficiently.
2. Confirm the official stock restore package and prototype zip are both present.
3. Open Innioasis Updater.
4. Use the same supported package-selection path from the Innioasis Y2 recovery PDF.
5. Select:

```text
12_build_outputs/y2-probe-system-prototype-rom-v9-input.zip
```

6. Start flashing only after verifying the selected filename is the probe prototype zip.
7. Fully power off the Y2.
8. Connect USB when the updater asks for it.
9. If the flasher does not detect the Y2, press the pinhole reset while the cable remains connected. This was the recovery sequence that made stock restore detection work.
10. Let the updater complete to 100%.
11. Do not interrupt the cable or app during flashing.

## Expected First Boot

After flashing, boot normally into stock UI.

Expected outcome:

- Stock UI still boots.
- Probe app is installed as a system app.
- Main menu entries remain visually the same.
- `E-book` remains the stock e-book UI.
- After boot/media scan, USB mass storage may expose `y2_probe_v9_input_marker.txt` at the root of shared storage.
- The probe UI should show `Y2 V9 Input Capture Probe`.

If V9 boots:

- Do not immediately flash Rockbox.
- Record whether the normal stock UI appears.
- Press each hardware button and rotate the wheel while the V9 probe UI is focused.
- Connect USB mass storage and check for `y2_probe_v9_input_marker.txt`.
- If the marker exists, copy or report its contents.
- If the marker does not exist, record whether USB storage still works and whether stock e-book/file-manager behavior is normal.

## Recovery If The Prototype Fails

Use the official Innioasis Y2 recovery PDF and official stock package:

```text
Y2/y2_v3.1.7-20260601/y2_v3.1.7-20260601
```

The stock restore package validation report is:

```text
00_project_docs/Y2_FIRMWARE_PACKAGE_VALIDATION.md
```

## Stop Conditions

Stop immediately if:

- Innioasis Updater selects the wrong package.
- The package name mentions Y1.
- The package validation fails.
- Windows repeatedly disconnects/reconnects outside the expected MediaTek flashing flow.
- The updater reports a scatter/preloader mismatch.
- The updater reports any format/download error.

Do not attempt a Rockbox package until a V9-style input probe proves how the Y2 buttons and wheel can be captured outside the stock launcher.
