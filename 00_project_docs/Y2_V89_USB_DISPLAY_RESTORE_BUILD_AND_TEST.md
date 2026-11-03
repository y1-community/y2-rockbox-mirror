# Y2 V89 USB Display Restore — Build and Physical Test

## Candidate

```text
File: build-intermediates/y2-v89-usb-display-restore-innioasis-full.zip
Size: 366,781,990 bytes
SHA-256: 58C7D205DFFD211F265515B840EC71A4283D126960D7E86D2632AA0A5361075B
Dedicated offline validation: 21/21 passed
Generic Y2 package shape: valid
Reproducibility: APK, system image, and full ZIP rebuilt byte-for-byte
Physical status: USB display-return test required
Release status: not included in Beta v0.1.0
```

V89 is a complete 12-partition InnioasisUpdater package. The installed updater
uses SP Flash Tool `format-download`, so back up both storage volumes and the
complete `.rockbox` tree before flashing.

V89 was built before comparison photographs established that the apparently
persistent inset presentation was the selected SNAZZ3 theme. V89 has never
been flashed to the physical Y2. The physically tested V88 package was
therefore selected for Beta v0.1.0 and V89 remains a separate hardening
experiment.

## V88 physical finding

USB storage transfer worked and Rockbox returned. The visible Rockbox
presentation was initially reported as incorrectly scaled/inset afterward. The
expanded SD evidence preserves 1,531 files and 169,230,606 bytes with zero hash
mismatch.

The Android and framebuffer geometry remained full-screen:

```text
native=480x360 surface=480x360 bitmap=480x360 dst=0,0-480,360
```

The return did record a lifecycle ordering worth hardening:

```text
RockboxFramebuffer:firstUpdate ...
RockboxFramebuffer:surface cleared reason=surfaceChanged ...
RockboxFramebuffer:surfaceChanged ... surface=480x360 ...
```

The complete Rockbox frame arrived 58 ms before `surfaceChanged`. V88 then
discarded the populated bitmap, created a blank bitmap, and cleared the new
surface. No later framebuffer update was captured in that marker.

Later physical photographs resolved the persistent visual report: SNAZZ3 uses
`%Vi(menuViewport,30,103,420,195,4)` and matching 30-pixel margins, while
MacClassic uses `ui viewport: 6,3,468,354,...`. Switching themes, not USB,
explains the different apparent size. The logged event order remains a valid
defensive-hardening opportunity, but it is not evidence that V88 changed to a
smaller framebuffer.

Evidence summary:
`Progress logs/v88-persistent-display-scaling-20260729/evidence-summary.md`

## V89 repair

`RockboxFramebuffer` now:

- retains the fixed 480x360 RGB565 bitmap across valid surface recreation;
- marks a frame cached only after a complete native framebuffer copy;
- shares cached-frame state safely across the native and Android UI threads;
- redraws the cached bitmap into the current full destination rectangle after
  `surfaceChanged`;
- clears only a genuinely new surface that has no cached Rockbox frame; and
- records whether cached restore succeeded, was skipped without a canvas, or
  threw an exception.

The change is limited to the Rockbox Android application. Relative to the
physically accepted V88 route build, only `system.img` changes. V88 `boot.img`,
`recovery.img`, route scripts, saved-map behavior, and the physically proven
V87 save broker remain byte-for-byte unchanged.

OneBitMono remains the patched full-width resource:

```text
%Vi(menu,0,48,480,268,-)
```

## Build and validation

```powershell
wsl bash 00_tools/build_rockbox_y2_v89_usb_display_restore_wsl.sh
wsl bash 00_tools/build_y2_rockbox_v89_system.sh
python 00_tools/build_y2_v89_innioasis_updater_full.py
python 00_tools/validate_y2_v89_usb_display_restore.py
```

Validation binds the source repair to the physical V88 event order, checks the
compiled APK tokens and full-width theme resource, verifies the exact APK and
resource payload inside `system.img`, requires a clean filesystem, confirms
the complete 12-partition package, proves that only `system.img` differs from
V88, and verifies exact V88 boot and recovery hashes.

## Short physical test

1. Back up both storage volumes and verify the V89 ZIP SHA-256 exactly.
2. Insert the diagnostic microSD while the Y2 is powered off.
3. Flash the complete V89 ZIP using the already-proven InnioasisUpdater
   workflow. Require `S_DONE(0)` and `Download Succeeded`.
4. Cold boot normally into Rockbox. Stop if the display is already visibly
   incorrect before USB.
5. Select OneBitMono, open the main menu, and open the playback screen. Take
   one clear pre-USB photograph of each so menu layout is not confused with
   framebuffer scaling.
6. Play audio, connect USB, enable USB storage, and copy/read one small test
   file.
7. Safely eject every exposed volume, disable USB storage, then unplug.
8. Require automatic Rockbox return. Compare the same menu and playback
   screens with the pre-USB photographs. Both must retain their prior size and
   edge alignment.
9. Sleep and wake once, change menus, and confirm controls and playback still
   work.
10. Repeat the USB enable/eject/disable/unplug sequence once.
11. Power off before removing the diagnostic SD, then return the complete V89
    debug directory and root marker/snapshot.

Expected V89 evidence includes:

```text
y2_rockbox_v89_usb_display_restore_marker.txt
RockboxFramebuffer:cached frame restored reason=surfaceChanged
surface=480x360
dst=0,0-480,360
```

Stop and photograph the screen if either pre-USB or post-USB presentation is
wrong. Do not adjust a theme viewport to compensate for an Android surface
failure.
