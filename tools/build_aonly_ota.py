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


def build_block_delta(
    base_path: str,
    target_path: str,
    delta_gz_path: str,
    extents_path: str,
    meta_path: str,
    level: int = 6,
    block_size: int = 4096,
) -> tuple[bool, int, int]:
    """Build 4K contiguous-extent delta from base_path -> target_path.
    Returns (changed, changed_blocks, num_extents).
    """
    base_size, base_sha, _ = sha_and_size(base_path)
    target_size, target_sha, _ = sha_and_size(target_path)
    if base_size % block_size != 0 or target_size % block_size != 0:
        raise ValueError(f"Sizes must be multiples of {block_size}: base={base_size}, target={target_size}")
    if base_size == target_size and base_sha == target_sha:
        return False, 0, 0

    extents: list[tuple[int, int, int]] = []
    src_blk = 0
    changed_blocks = 0
    cur_dst = None
    cur_src = 0
    cur_len = 0

    with open(base_path, "rb") as fb, open(target_path, "rb") as ft, gzip.open(
        delta_gz_path, "wb", compresslevel=level
    ) as gz:
        dst_blk = 0
        while True:
            bb = fb.read(block_size)
            bt = ft.read(block_size)
            if not bt:
                break
            if bb != bt:
                gz.write(bt)
                changed_blocks += 1
                if cur_dst is None:
                    cur_dst = dst_blk
                    cur_src = src_blk
                    cur_len = 1
                else:
                    cur_len += 1
                src_blk += 1
            else:
                if cur_dst is not None:
                    extents.append((cur_src, cur_dst, cur_len))
                    cur_dst = None
                    cur_len = 0
            dst_blk += 1
        if cur_dst is not None:
            extents.append((cur_src, cur_dst, cur_len))

    with open(extents_path, "w", encoding="utf-8", newline="\n") as ef:
        for s_blk, d_blk, cnt in extents:
            ef.write(f"{s_blk} {d_blk} {cnt}\n")

    with open(meta_path, "w", encoding="utf-8", newline="\n") as mf:
        mf.write(f"BASE_SHA256={base_sha}\n")
        mf.write(f"BASE_SIZE={base_size}\n")
        mf.write(f"TARGET_SHA256={target_sha}\n")
        mf.write(f"TARGET_SIZE={target_size}\n")

    return True, changed_blocks, len(extents)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output OTA zip path")
    ap.add_argument(
        "--format",
        choices=("gzip", "raw"),
        default="gzip",
        help="Store each full partition as <part>.img.gz (default, avoids 4GiB ZIP64) or raw <part>.img",
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
        ap.add_argument(f"--base-{key}", dest=f"base_{key}", default=None, help=f"Optional base {key}.img for 4K-extent delta OTA")
    args = ap.parse_args()

    selected = []
    for key in ALLOWED_IMAGES:
        val = getattr(args, key)
        base_val = getattr(args, f"base_{key}")
        if val:
            if not os.path.isfile(val):
                raise FileNotFoundError(val)
            if base_val and not os.path.isfile(base_val):
                raise FileNotFoundError(base_val)
            selected.append((key, val, base_val))

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
            for key, src, base_src in selected:
                if base_src:
                    d_gz = os.path.join(tmpdir, f"{key}.delta.gz")
                    d_ext = os.path.join(tmpdir, f"{key}.extents")
                    d_meta = os.path.join(tmpdir, f"{key}.delta.meta")
                    print(f"Computing 4K-extent delta {base_src} -> {src} ...")
                    changed, chg_blks, n_ext = build_block_delta(
                        base_src, src, d_gz, d_ext, d_meta, level=args.gzip_level
                    )
                    if not changed:
                        print(f"Skipping {key} (unchanged, 0 bytes)")
                        continue
                    gz_sz = os.path.getsize(d_gz)
                    print(
                        f"Adding {key} delta ({chg_blks} blocks across {n_ext} extents, {gz_sz} B gz) ..."
                    )
                    zf.write(d_meta, arcname=f"{key}.delta.meta", compress_type=zipfile.ZIP_DEFLATED)
                    zf.write(d_ext, arcname=f"{key}.extents", compress_type=zipfile.ZIP_DEFLATED)
                    zf.write(d_gz, arcname=f"{key}.delta.gz", compress_type=zipfile.ZIP_STORED)
                elif args.format == "gzip":
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
