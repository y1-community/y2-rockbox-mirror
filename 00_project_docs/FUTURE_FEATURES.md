# Y2 Rockbox Future Features

Updated: 2026-09-06

Beta V2 is the current physically accepted public beta. This page records the
next public priorities without treating an idea as a promised release date.

## Beta V3 priorities

1. **Power-down presentation polish**
   - Remove the remaining imperfect final shutdown animation.
   - Keep the already-proven shutdown, cold-boot routing and recovery behavior
     unchanged.

2. **Lyrics and 480x360 theme diagnostics**
   - Qualify synchronized and plain-text lyrics on Now Playing.
   - Document supported embedded and sidecar formats.
   - Make the native 480x360 resolution prominent and diagnose incomplete,
     wrong-resolution or malformed theme packages.

3. **Playback resilience**
   - Stress high-resolution FLAC and malformed media.
   - Reproduce and harden equalizer reset/recovery behavior.
   - Prevent damaged saved DSP state from making ordinary playback unusable.

4. **DAC and wired-audio qualification**
   - Test representative USB DACs, wired headphones and route changes.
   - Prove reconnect and Bluetooth-to-wired fallback without playback or UI
     instability.

5. **Settings and restart audit**
   - Review Restart Rockbox and every Y2-specific setting for save, reset,
     restart and cold-boot behavior.
   - Keep Stock and Rockbox settings isolated where the two interfaces expose
     independent controls.

6. **Library and playlist presentation**
   - Improve database and playlist track-line options.
   - Qualify disc/track ordering, M3U order and persistent browsing context on
     larger internal and microSD libraries.

7. **PictureFlow polish**
   - Improve adjacent-cover loading.
   - Add a branded, deterministic missing-art slide.
   - Expand oversized/malformed artwork diagnostics without regressing the
     cache-recovery and carousel behavior accepted in Beta V2.

8. **Safer public updating**
   - Retain Beta V2's release-locked Class A route, five-target write boundary,
     readback verification, no-retry rule, and mandatory post-flash reset.
   - Continue toward a user-supplied-stock patching path that preserves user
     data and generates a validated package.
   - Keep complete recovery, checksum and corresponding-source requirements for
     every binary release.

## Community and upstream work

- Curate and document tested native 480x360 themes.
- Separate portable Android/Rockbox fixes from Y2-only firmware and routing
  policy, then prepare focused upstream contributions where maintainers consider
  them in scope.
- Improve backup/restore guidance so users know exactly which internal, microSD,
  settings, theme, playlist and database data can be affected.
- Keep Bluetooth, USB, storage, routing and media-format compatibility reports
  open for community retesting against the latest beta.

## Deferred or externally gated

- FM remains blocked until an Innioasis Y2 vendor firmware baseline with a
  demonstrably working tuner is available for comparison.
- Wi-Fi integration and a Rockbox hold/lock gesture remain exploratory.
- Fastboot and a simultaneous-volume chord are not advertised beta features.

Please search existing issues before opening a new report:
<https://github.com/SPYCEMAGIC/Y2-Rockbox/issues>
