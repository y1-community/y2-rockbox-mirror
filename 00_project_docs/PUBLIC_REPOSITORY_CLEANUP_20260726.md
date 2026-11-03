# Public Repository Cleanup Audit

Date: 2026-07-26 (Australia/Sydney)

## Workspace

The authoritative local workspace is:

```text
<local-workspace>\Y2 RockBox
```

The repository, Rockbox submodule, build intermediates, private evidence, and
local review material now sit beneath this single folder. The following local
directories are deliberately ignored:

```text
build-intermediates/
evidence/
local-review/
.codex/visualizations/
```

The former OneDrive workspace contains zero project files. Its empty directory
shell is held open by the current process and can be removed after the session
restarts.

## Current index cleanup

The release-preparation commit removes 98 previously tracked files from the
public Git index:

- raw physical logcat, dmesg, process, input, property and marker captures;
- one generated Codex HTML visualization;
- generated embedded-script copies and superseded offline scratch reports.

All 98 files remain on local disk under ignored paths. No physical evidence
was deleted. Concise project docs and current V83 validation reports remain
tracked.

The private V81 evidence is retained locally under:

```text
evidence/v81-physical-near-release-settings-save-timeout-20260726/
```

Its SD copy contains 945 files and 133,451,127 bytes with zero SHA-256 copy
mismatches.

## Publication blockers

The working snapshot is suitable for a reviewed public export, but the existing
Git history is not yet suitable for a direct push:

1. Historical commits still contain a 24,014,626-byte raw physical logcat blob.
   Removing it from the current index does not remove it from history.
2. The parent repository has no Git remote.
3. The Rockbox working tree contains unpublished Y2-specific commits and must
   not be referenced as a public submodule. Public binary releases instead
   need a reviewed complete corresponding source archive with the applicable
   upstream license notices.
4. Generated vendor-derived firmware must not be published unless
   redistribution rights are established.
5. V82 failed and is rejected. V83 now requires its physical save/reboot and
   complete regression gate, followed by one confirmed official-stock
   rollback.

## Recommended public export

After the physical gate:

1. Preserve the parent GPL-2.0-or-later license and all third-party notices.
2. Create and push a public Rockbox fork, then update `.gitmodules` to that URL.
3. Build a clean parent history from the reviewed current snapshot, excluding
   vendor firmware, raw captures, generated packages, local tools and private
   evidence.
4. Run secret, personal-path and large-object scans on the clean history.
5. Create the GitHub repository, add its remote, push the clean branch, and
   enable branch protection and CI validation.
6. Publish a user-side patcher, checksums and signed/attested release metadata.
   Require users to supply their own official Y2 3.1.7 firmware.
7. Tag the first public release only after V83 and official rollback pass.

This keeps the project source open and auditable without publishing Innioasis
firmware or private device evidence.
