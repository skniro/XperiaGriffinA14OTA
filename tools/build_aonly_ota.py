#!/usr/bin/env python3
"""
Build an A-only OTA ZIP package for Xperia 5 (J9110) and output manifest hashes.

Example:
  python tools/build_aonly_ota.py --out j9110_a14_v12_ota.zip --system system_v22.img --product product_v39.img
"""

import argparse
import hashlib
import json
import os
import zipfile


ALLOWED_IMAGES = {
    "system": "system.img",
    "product": "product.img",
    "vendor": "vendor.img",
    "oem": "oem.img",
    "boot": "boot.img",
    "dtbo": "dtbo.img",
    "vbmeta": "vbmeta.img",
}


def sha_and_size(path: str) -> tuple[int, str, str]:
    h256 = hashlib.sha256()
    h512 = hashlib.sha512()
    size = 0
    with open(path, "rb") as f:
        while True:
            buf = f.read(4 * 1024 * 1024)
            if not buf:
                break
            size += len(buf)
            h256.update(buf)
            h512.update(buf)
    return size, h256.hexdigest(), h512.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output OTA zip path")
    ap.add_argument(
        "--updater",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ota_template",
            "META-INF",
            "com",
            "google",
            "android",
            "update-binary",
        ),
        help="Path to update-binary script",
    )
    for key in ALLOWED_IMAGES:
        ap.add_argument(f"--{key}", default=None, help=f"Optional {key}.img path")
    args = ap.parse_args()

    selected = []
    for key, arcname in ALLOWED_IMAGES.items():
        val = getattr(args, key)
        if val:
            if not os.path.isfile(val):
                raise FileNotFoundError(val)
            selected.append((val, arcname))

    if not selected:
        raise SystemExit("At least one partition image must be specified")

    updater_bytes = open(args.updater, "rb").read().replace(b"\r\n", b"\n")
    zi = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
    zi.external_attr = 0o100755 << 16

    with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr(zi, updater_bytes)
        for src, arcname in selected:
            print(f"Adding {src} as {arcname} ...")
            zf.write(src, arcname=arcname)

    size, h256, h512 = sha_and_size(args.out)
    print(
        json.dumps(
            {
                "file": os.path.abspath(args.out),
                "size": size,
                "hash": h256,
                "sha512": h512,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
