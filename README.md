# XperiaGriffinA14OTA

A-only OTA infrastructure for **Sony Xperia 5 (J9110 / Griffin)** running Android 14 with `system_b` repurposed as `/product`.

## Why A-only instead of A/B?
- The device boots with `ro.build.ab_update=true` and `ro.boot.slot_suffix=_a`.
- `system_b` (`/dev/block/bootdevice/by-name/system_b`) is permanently mounted as `/product` via DTB fstab (`boot_a`).
- Using stock A/B `update_engine` (`AbFirmwareInstaller`) or `payload.bin` would overwrite `system_b` (`/product`) and break boot.
- Instead, OTA packages use a classic A-only `META-INF/com/google/android/update-binary` script executed inside an unattended TWRP `boot_a` image (`boot_ors.img`), writing only the target `_a` partitions (`system_a`, `vendor_a`, `oem_a`, `boot_a`, `vbmeta_a`) — and writing `system_b` **only** when a `product.img` is explicitly included.

## Repository Layout
- `manifest/updates.json` — Live UEP v4 manifest polled by patched `UpdateCenter` (`https://raw.githubusercontent.com/skniro/XperiaGriffinA14OTA/main/manifest/updates.json`). Note: URL avoids containing the substring `v4` because `Customization.getUrls()` rewrites `v4` -> `v3` when `isUepSpecV3Supported()` is enabled.
- `manifest/updates.example.json` — Example UEP `"fw"` response schema expected by `UpdateManifestParser`.
- `ota_template/META-INF/com/google/android/update-binary` — Non-slot-switching A-only updater shell script.
- `tools/patch_boot_ors.py` — Patches TWRP `boot.img` (removes stale `fileencryption` fstab flags + patches `tw_is_encrypted` ORS skip and `system_readonly` prompt defaults in `system/bin/recovery`, then repacks with `magiskboot`).
- `tools/build_aonly_ota.py` — Builds an A-only OTA `.zip` from partition images and prints `size`, `hash` (SHA-256), and `sha512` for `updates.json`.

## Versioning Convention
- Baseline merged release: `64.2.A.2.272` (`V11_272`).
- Subsequent incremental updates and releases increment the last segment/two digits (`64.2.A.2.273`, `64.2.A.2.274`, etc., scaled by change scope).

## Verified Recovery Bridge
- Tested end-to-end on `QV72077F2Z` (`J9110`, Android 14 `64.2.A.2.265`, unencrypted `ext4` `/data`):
  - `/cache` symlinks to `/data/cache` in both Android and TWRP (`init.rc`).
  - Writing `/cache/recovery/openrecoveryscript` (`install /sdcard/Android/data/com.sonyericsson.updatecenter/files/fota/<pkg>.zip` + `reboot`) and rebooting to `recovery` triggers zero-touch installation and automatic reboot back into Android.
