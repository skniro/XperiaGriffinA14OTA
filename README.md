# XperiaGriffinA14OTA

A-only OTA infrastructure for **Sony Xperia 5 (J9110 / Griffin)** running Android 14 with `system_b` repurposed as `/product`.

## Why A-only instead of A/B?
- The device boots with `ro.build.ab_update=true` and `ro.boot.slot_suffix=_a`.
- `system_b` (`/dev/block/bootdevice/by-name/system_b`) is permanently mounted as `/product` via DTB fstab (`boot_a`).
- Using stock A/B `update_engine` (`AbFirmwareInstaller`) or `payload.bin` would overwrite `system_b` (`/product`) and break boot.
- Instead, OTA packages use a classic A-only `META-INF/com/google/android/update-binary` script executed inside an unattended TWRP `boot_a` image (`boot_ors.img`), writing only the target `_a` partitions (`system_a`, `vendor_a`, `oem_a`, `boot_a`, `vbmeta_a`) — and writing `system_b` **only** when a `product.img` is explicitly included.

## Repository Layout
- `manifest/updates.json` — Live UEP v4 manifest polled by patched `UpdateCenter` (`https://raw.githubusercontent.com/skniro/XperiaGriffinA14OTA/main/manifest/updates.json`). Note: URL avoids containing the substring `v4` because `Customization.getUrls()` rewrites `v4` -> `v3` when `isUepSpecV3Supported()` is enabled.
- `manifest/release_notes.xml` & `manifest/release_notes_en.xml` — Bilingual (Chinese / English) release notes. `UpdateCenter` automatically selects `releaseNotesUrlEn` (`release_notes_en.xml`) on English/non-Chinese system locales and `releaseNotesUrl` (`release_notes.xml`) on Chinese locales, while each XML also embeds a secondary `<operator-feature-list>` in the other language.
- `manifest/updates.example.json` — Example UEP `"fw"` response schema expected by `UpdateManifestParser`.
- `ota_template/META-INF/com/google/android/update-binary` — Non-slot-switching A-only updater shell script supporting full raw `.img`, gzipped `.img.gz` (with `/data/ota_work` staging or streaming fallback), `ota.meta` (`BASE_VERSION` / `TARGET_VERSION`) check against `/system/build.prop`, and 4K-extent incremental deltas (`<part>.delta.meta` + `.extents` + `.delta.gz` with `BASE_SHA256` and `TARGET_SHA256` verification).
- `tools/patch_boot_ors.py` — Patches TWRP `boot.img` (removes stale `fileencryption` fstab flags + patches `tw_is_encrypted` ORS skip and `system_readonly` prompt defaults in `system/bin/recovery`, then repacks with `magiskboot`).
- `tools/build_aonly_ota.py` — Builds an A-only OTA `.zip` from partition images (full `--format gzip|raw`, or Sony-style compact incremental deltas via `--base-<part>` and `--base-version` / `--target-version`) and prints `size`, `hash` (SHA-256), and `sha512` for `updates.json`.

## Anti-Skip BaseVersion Chain Protection
To prevent older builds from skipping intermediate updates and directly downloading or flashing a delta built against a newer base:
1. **Client-side (`UpdateManifestParser.filterFirmwareArray`)**: Scans all entries in `"fw"`, requiring `"version" != Build.ID` and (when `"baseVersion"` is present) `"baseVersion" == Build.ID`. Devices step through the `"fw"` upgrade chain (`64.2.A.2.272 -> 64.2.A.3.62 -> ...`) one release at a time.
2. **Recovery-side (`update-binary` + `ota.meta` + `<part>.delta.meta`)**: Before modifying any block device, `update-binary` checks `ro.build.id` in `system_a`'s `/system/build.prop` against `BASE_VERSION` in `ota.meta` and verifies the full-partition cryptographic `BASE_SHA256` of every delta target.

## Versioning Convention
- Baseline merged release: `64.2.A.2.272` (`V11_272`).
- Subsequent incremental updates and releases increment the last segment/two digits (`64.2.A.2.273`, `64.2.A.2.274`, etc., scaled by change scope).

## Verified Recovery Bridge
- Tested end-to-end on `QV72077F2Z` (`J9110`, Android 14 `64.2.A.2.265`, unencrypted `ext4` `/data`):
  - `/cache` symlinks to `/data/cache` in both Android and TWRP (`init.rc`).
  - Writing `/cache/recovery/openrecoveryscript` (`install /sdcard/Android/data/com.sonyericsson.updatecenter/files/fota/<pkg>.zip` + `reboot`) and rebooting to `recovery` triggers zero-touch installation and automatic reboot back into Android.
