#!/usr/bin/env python3
"""
Build an A-only OTA ZIP package for Xperia 5 (J9110) and output manifest hashes.

Example:
  python tools/build_aonly_ota.py --out j9110_a14_v12_ota.zip --system system_v22.img --product product_v39.img
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import zipfile


ALLOWED_IMAGES = (
    "system",
    "product",
    "vendor",
    "oem",
    "boot",
    "dtbo",
    "vbmeta",
)


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


def gzip_copy(src: str, dst: str, level: int = 6) -> None:
    with open(src, "rb") as fin, gzip.open(dst, "wb", compresslevel=level) as fout:
        shutil.copyfileobj(fin, fout, length=4 * 1024 * 1024)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output OTA zip path")
    ap.add_argument(
        "--format",
        choices=("gzip", "raw"),
        default="gzip",
        help="Store each partition as <part>.img.gz (default, avoids 4GiB ZIP64) or raw <part>.img",
    )
    ap.add_argument(
        "--gzip-level",
        type=int,
        default=6,
        help="Gzip compression level 1-9 when --format gzip (default: 6)",
    )
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
        ap.add_argument(f"--{key}", default=None, help=f"Optional {key}.img or {key}.img.gz path")
    args = ap.parse_args()

    selected = []
    for key in ALLOWED_IMAGES:
        val = getattr(args, key)
        if val:
            if not os.path.isfile(val):
                raise FileNotFoundError(val)
            selected.append((key, val))

    if not selected:
        raise SystemExit("At least one partition image must be specified")

    updater_bytes = open(args.updater, "rb").read().replace(b"\r\n", b"\n")
    zi = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
    zi.external_attr = 0o100755 << 16

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    with tempfile.TemporaryDirectory(prefix=".aonly_ota_", dir=out_dir) as tmpdir:
        with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            zf.writestr(zi, updater_bytes, compress_type=zipfile.ZIP_DEFLATED)
            for key, src in selected:
                if args.format == "gzip":
                    arcname = f"{key}.img.gz"
                    if src.endswith(".gz"):
                        gz_path = src
                    else:
                        gz_path = os.path.join(tmpdir, arcname)
                        print(f"Compressing {src} -> {arcname} (level {args.gzip_level}) ...")
                        gzip_copy(src, gz_path, level=args.gzip_level)
                    print(f"Adding {arcname} (stored, {os.path.getsize(gz_path)} bytes) ...")
                    zf.write(gz_path, arcname=arcname, compress_type=zipfile.ZIP_STORED)
                else:
                    arcname = f"{key}.img"
                    print(f"Adding {src} as {arcname} ...")
                    zf.write(src, arcname=arcname, compress_type=zipfile.ZIP_DEFLATED)

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
