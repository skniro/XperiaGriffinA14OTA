#!/usr/bin/env python3
"""
Patch J9110 TWRP boot.img for unattended OpenRecoveryScript A-only OTA updates.

Uses `magiskboot` on a connected rooted ADB device (TWRP or Android) to:
  1. Strip stale `fileencryption`/`wrappedkey`/`inlinecrypt` flags from
     `system/etc/recovery.fstab` and `system/etc/twrp.flags` (/data is unencrypted ext4).
  2. Patch 3 AArch64 instructions in `system/bin/recovery` (TWRP 3.7.1_12-067c00cb):
     - 0x0d7f9c: tbnz w8, #0, #0xd8020 -> nop (run ORS even if tw_is_encrypted=1)
     - 0x0e8cd0: mov w8, #0x3202 -> mov w8, #0x3102 (tw_mount_system_ro = "1")
     - 0x0e8d48: mov w8, #0x3002 -> mov w8, #0x3102 (tw_never_show_system_ro_page = "1")
  3. Repack with `magiskboot` preserving DTB, kernel, and AVB header/footer structure.

Usage:
  python tools/patch_boot_ors.py <src_boot.img> <out_boot_ors.img> [--serial SERIAL]
"""

import argparse
import gzip
import os
import struct
import subprocess
import tempfile


PATCHES_RECOVERY = {
    0x0D7F9C: (0x37000428, 0xD503201F),  # tbnz w8, #0, #0xd8020 -> nop
    0x0E8CD0: (0x52864048, 0x52862048),  # mov w8, #0x3202 -> mov w8, #0x3102
    0x0E8D48: (0x52860048, 0x52862048),  # mov w8, #0x3002 -> mov w8, #0x3102
}


def extract_from_boot_ramdisk(boot_path: str, workdir: str) -> tuple[str, str, str, str]:
    raw = open(boot_path, "rb").read()
    magic, ksize, _, rsize, _, _, _, _, psize, hdrver = struct.unpack("<8s9I", raw[:44])
    if magic != b"ANDROID!" or hdrver != 2:
        raise ValueError(f"Unexpected boot image header: magic={magic!r}, hdrver={hdrver}")
    r_off = (1 + (ksize + psize - 1) // psize) * psize
    ramdisk = gzip.decompress(raw[r_off : r_off + rsize])

    targets = {
        "system/etc/recovery.fstab": None,
        "system/etc/twrp.flags": None,
        "system/bin/recovery": None,
        "system/bin/magiskboot": None,
    }
    pos = 0
    while pos < len(ramdisk):
        if ramdisk[pos : pos + 6] != b"070701":
            raise ValueError(f"Bad cpio magic at {pos}")
        hdr = ramdisk[pos : pos + 110]
        fsz = int(hdr[54:62], 16)
        nsz = int(hdr[94:102], 16)
        name = ramdisk[pos + 110 : pos + 110 + nsz - 1].decode("utf-8", "replace")
        fs = (pos + 110 + nsz + 3) & ~3
        fd = ramdisk[fs : fs + fsz]
        pos = (fs + fsz + 3) & ~3
        if name == "TRAILER!!!":
            break
        if name in targets:
            targets[name] = fd

    for k, v in targets.items():
        if v is None:
            raise FileNotFoundError(f"{k} not found in ramdisk")

    fstab_txt = (
        targets["system/etc/recovery.fstab"]
        .decode("utf-8")
        .replace(",inlinecrypt", "")
        .replace(
            "wrappedkey,fileencryption=ice:aes-256-cts,keydirectory=/metadata/vold/metadata_encryption,",
            "",
        )
        .replace(",wrappedkey", "")
    )
    flags_txt = (
        targets["system/etc/twrp.flags"]
        .decode("utf-8")
        .replace("flags=fileencryption=ice:aes-256-cts", "")
    )

    rec = bytearray(targets["system/bin/recovery"])
    for off, (expected, patched) in PATCHES_RECOVERY.items():
        actual = struct.unpack_from("<I", rec, off)[0]
        if actual != expected:
            raise ValueError(
                f"Recovery binary mismatch at {hex(off)}: expected {hex(expected)}, got {hex(actual)}"
            )
        struct.pack_into("<I", rec, off, patched)

    p_fstab = os.path.join(workdir, "p_recovery.fstab")
    p_flags = os.path.join(workdir, "p_twrp.flags")
    p_rec = os.path.join(workdir, "p_recovery")
    p_mb = os.path.join(workdir, "magiskboot")

    open(p_fstab, "wb").write(fstab_txt.encode("utf-8"))
    open(p_flags, "wb").write(flags_txt.encode("utf-8"))
    open(p_rec, "wb").write(rec)
    open(p_mb, "wb").write(targets["system/bin/magiskboot"])
    return p_fstab, p_flags, p_rec, p_mb


def run_adb(serial: str | None, args: list[str]) -> None:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src_boot")
    ap.add_argument("out_boot")
    ap.add_argument("--serial", default=None)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        p_fstab, p_flags, p_rec, p_mb = extract_from_boot_ramdisk(args.src_boot, tmp)
        dev_dir = "/data/local/tmp/mb_patch"
        run_adb(args.serial, ["root"])
        run_adb(args.serial, ["shell", f"rm -rf {dev_dir} && mkdir -p {dev_dir}"])
        run_adb(args.serial, ["push", args.src_boot, f"{dev_dir}/boot.img"])
        run_adb(args.serial, ["push", p_mb, f"{dev_dir}/magiskboot"])
        run_adb(args.serial, ["push", p_fstab, f"{dev_dir}/p_recovery.fstab"])
        run_adb(args.serial, ["push", p_flags, f"{dev_dir}/p_twrp.flags"])
        run_adb(args.serial, ["push", p_rec, f"{dev_dir}/p_recovery"])
        run_adb(
            args.serial,
            [
                "shell",
                f"cd {dev_dir} && chmod 755 magiskboot && ./magiskboot unpack -h boot.img && "
                "./magiskboot cpio ramdisk.cpio "
                "'add 0644 system/etc/recovery.fstab p_recovery.fstab' "
                "'add 0644 system/etc/twrp.flags p_twrp.flags' "
                "'add 0755 system/bin/recovery p_recovery' && "
                "./magiskboot repack boot.img new-boot.img",
            ],
        )
        run_adb(args.serial, ["pull", f"{dev_dir}/new-boot.img", args.out_boot])
        run_adb(args.serial, ["shell", f"rm -rf {dev_dir}"])
        print(f"Created {args.out_boot}")


if __name__ == "__main__":
    main()
