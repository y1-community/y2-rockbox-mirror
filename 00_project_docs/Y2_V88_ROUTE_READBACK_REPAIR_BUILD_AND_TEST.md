# Y2 V88 Route Readback Repair — Build and Physical Test

## Candidate

```text
File: build-intermediates/y2-v88-route-readback-repair-innioasis-full.zip
Size: 366,781,486 bytes
SHA-256: 40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE
Offline validation: 24/24 passed
Reproducibility: identical SHA-256 across two package builds
Physical status: selected as the Beta v0.1.0 firmware base
```

Additional payload hashes:

```text
APK:
7E10CA5A1CC5984CD4D895AB542C64EB11D8E74EDEE9415953851D50F7227063
system.img:
0F6169BD174C359439BB330CD7383D94B7B938A60855E855E2EA87734215E160
```

This is a complete 12-partition package. InnioasisUpdater 1.1.2 invokes SP
Flash Tool in `format-download` mode, so back up every internal file before
flashing.

## Physical evidence and exact repair

V87's Boot Settings save passed. Request `33249` selected Stock and the root
broker recorded received, verified, acknowledged, synced, and reboot events.
The immediate next boot nevertheless recorded:

```text
physical_route=stock
route=rockbox
route_map_key=no_button
route_map_source=built-in-defaults
```

V86 had already physically proved that this Y2 vendor shell reports
`printf: not found`. V87 removed `printf` from the save broker, but the
separate route, route-guard, and USB-guard `read_kv()` functions embedded in
boot and recovery still used it. The early reader therefore emitted an empty
map version and deliberately selected the built-in Rockbox default.

V88 makes one compatibility repair in those three readers:

```sh
# rejected on this device
printf '%s\n' "${READ_KV_LINE#*=}"

# V88
echo "${READ_KV_LINE#*=}"
```

The `/data/system/y2_boot_routes.conf` format, its root-only permissions,
atomic save, exact reread, default Rockbox map, and button semantics remain
unchanged. V88 reuses the exact V87 echo-only save broker that physically
passed.

## Physical result

The returned 2026-07-29 microSD evidence passes the defect-specific V88 gate.
It contains seven V88 route sessions, all with successful dispatch:

| Map key | Effective route | Map source | Physical result |
| --- | --- | --- | --- |
| `no_button` | Rockbox | `built-in-defaults` | Expected first-post-flash default passed |
| `volume_down` | Settings | `built-in-defaults` | Initial Boot Settings route passed |
| `no_button` | Stock | `saved-settings` | Automatic post-save boot passed |
| `no_button` | Stock | `saved-settings` | Repeated cold boot passed |
| `volume_up` | Rockbox | `saved-settings` | Opposite-player route under saved Stock passed |
| `volume_down` | Settings | `saved-settings` | Boot Settings remained reachable |
| `no_button` | Rockbox | `saved-settings` | Automatic post-save boot passed |

Stock request `31296` and Rockbox request `29938` each reached `received`,
`verified`, `acknowledged status=ok`, and `reboot`. The saved maps were:

```text
no_button=stock volume_up=rockbox volume_down=settings
no_button=rockbox volume_up=stock volume_down=settings
```

All seven route dispatch records report `Status: ok` and
`dispatch=success`. The V88 application marker contains both corresponding
`BootSettings:saved` events and no uncaught exception, rapid Rockbox failure,
relaunch block, save timeout, or save failure. Both captured Rockbox snapshots
reached `RockboxService:healthy-20s`.

One first-post-flash Rockbox session used the designed single bounded retry
after a readiness timeout and then dispatched successfully. The settings
provider also emitted transient not-ready polling messages during startup
before reaching `provider-query-ok`; both saves then completed normally.

Tracked evidence summary:
`Progress logs/v88-physical-route-readback-pass/evidence-summary.md`

The subsequent beta regression also passed:

- saving the already-selected Rockbox choice and automatic restart;
- no-button Rockbox and Volume-Up Stock boots;
- 15-minute audio playback and hardware controls;
- sleep and wake;
- theme selection and persistence;
- internal-storage and microSD playback;
- USB storage enable, transfer, safe eject, disable and automatic Rockbox
  return;
- normal power off; and
- official-stock rollback.

The initially reported post-USB display scaling was resolved by physical
comparison photographs. SNAZZ3 deliberately defines a 420-pixel-wide menu
viewport starting 30 pixels from the left edge, while MacClassic uses an
almost full-screen 468x354 viewport. V88 continued to report and draw a full
480x360 framebuffer. The visual difference follows the selected theme and is
not a USB display failure.

## Build

From PowerShell in the repository root:

```powershell
wsl bash 00_tools/build_rockbox_y2_v88_route_readback_repair_wsl.sh
wsl bash 00_tools/build_y2_rockbox_v88_system.sh
python 00_tools/build_y2_v88_innioasis_updater_full.py
python 00_tools/validate_y2_v88_route_readback_repair.py
```

The validator inspects the actual boot and recovery ramdisks. It requires the
exact V88 route scripts, rejects `printf` in all three handoff readers, runs
their shell syntax checks, executes the exact saved-map reader against a Stock
map, verifies the complete 12-partition scatter, and binds every packaged image
to the manifest hash.

## Button map

| Power-on input | Result |
| --- | --- |
| No volume button | Selected normal-boot player; Rockbox by default |
| Volume Up | The other player |
| Volume Down | Boot Settings |
| Volume Up + Volume Down | Fixed fastboot safety route |

Boot Settings changes only the normal-boot player. It does not ask the user to
configure the other routes.

## Short physical gate

The saved Stock and saved Rockbox readback portions below have passed. Items
not represented by the returned evidence remain open for release
qualification.

1. Back up the Y2 and verify the candidate SHA-256 exactly.
2. Insert the diagnostic microSD into the powered-off Y2.
3. Flash the complete V88 ZIP. Require `S_DONE(0)` and
   `Download Succeeded`.
4. Cold boot with Volume Down. Confirm the V88 marker and minimal Boot Settings
   screen.
5. Choose **Y2 Stock** and select **Save & Restart**.
6. Require `Saving...`, `Saved - restarting...`, and an automatic normal boot
   into Y2 Stock.
7. Power off and cold boot with no buttons. Require Y2 Stock.
8. Power off and cold boot with Volume Up. Require Rockbox.
9. Cold boot with Volume Down, choose **Rockbox**, and save. Require the
   automatic normal boot into Rockbox.
10. Cold boot normally and require Rockbox; cold boot with Volume Up and
    require Y2 Stock.
11. Save the already-selected Rockbox choice. It must still verify,
    acknowledge, and restart successfully.
12. Confirm Volume Down still opens Boot Settings and both volume buttons still
    enter the fixed fastboot route.
13. Power off, remove the microSD, insert it into the PC, and preserve the
    complete diagnostic tree before further work.

Stop on any flash error, save error, wrong route, missing marker, or unexpected
formatting behavior. Do not retry by changing SP Flash Tool modes.

## Beta v0.1.0 decision

V88 is the physically tested base for Beta v0.1.0. The public asset is an
outer-file rename of the byte-identical ZIP:

```text
Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip
SHA-256:
40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE
```

The remaining limitations are disclosed rather than treated as stable-release
passes:

- Bluetooth is untested.
- The both-volume fastboot chord did not open fastboot.
- Date/time persistence remains unresolved.
- InnioasisUpdater performs a destructive full-device format-download.

See `00_project_docs/Y2_ROCKBOX_BETA_V0.1.0_RELEASE.md`.
