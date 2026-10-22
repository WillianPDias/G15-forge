#!/usr/bin/env python3
"""Offline assembly of a G15Forge Live ISO candidate from a separate Gentoo root.

Never mounts disks, edits inputs, downloads packages, or claims boot validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

LABEL = "G15FORGE_LIVE"
KVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{1,100}$")
REPO = Path(__file__).resolve().parents[1]
TOOLS = ("mksquashfs", "grub-mkrescue", "xorriso", "lsinitrd")


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command(argv):
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=False)
    if proc.returncode:
        raise Rejected(f"{argv[0]} failed ({proc.returncode}): {proc.stdout[-1500:]}")
    return proc.stdout


def mounts_within(rootfs):
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 5:
            mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\t")
            if os.path.commonpath((str(rootfs), mountpoint)) == str(rootfs):
                mounts.append(mountpoint)
    return mounts


def preflight(rootfs, kernel, initramfs, release, output):
    require(bool(KVER.fullmatch(release)), "invalid kernel release")
    require(rootfs.is_dir() and not rootfs.is_symlink(), "rootfs absent or symlink")
    rootfs = rootfs.resolve()
    require(rootfs != Path("/") and rootfs != REPO and rootfs not in REPO.parents,
            "host or repository filesystem is not a Live root")
    require(not mounts_within(rootfs), "rootfs contains active mounts")
    gentoo = rootfs / "etc/gentoo-release"
    require(gentoo.is_file() and "Gentoo" in gentoo.read_text(errors="replace"),
            "Gentoo release marker missing")
    require(any((rootfs / p).is_file() for p in
                ("usr/lib/systemd/systemd", "lib/systemd/systemd")),
            "systemd binary missing")
    require((rootfs / "lib/modules" / release / "modules.dep").is_file(),
            "kernel modules.dep missing")
    expected_kernel = rootfs / "boot" / ("vmlinuz-" + release)
    require(expected_kernel.is_file(), "rootfs kernel image missing")
    for item, minimum in ((kernel, 65536), (initramfs, 1024)):
        require(item.is_file() and not item.is_symlink(), "boot input missing or symlink")
        require(item.stat().st_size >= minimum, "boot input too small")
    require(sha(expected_kernel) == sha(kernel), "kernel differs from rootfs")
    fstab = rootfs / "etc/fstab"
    require(fstab.is_file(), "Live fstab missing")
    for line in fstab.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        require(len(fields) >= 2 and fields[1] not in ("/", "/boot/efi"),
                "fixed installed-disk entry in Live fstab")
    require(not (rootfs / "etc/systemd/system/multi-user.target.wants/"
                 "g15forge-p2-verify.service").is_symlink(),
            "P2 disk-specific verifier remains enabled")
    mid = rootfs / "etc/machine-id"
    require(not mid.exists() or not mid.read_text().strip(),
            "nonempty machine-id must not be distributed")
    require(not (rootfs / "root/.ssh").exists(), "root SSH secrets present")
    require(not list((rootfs / "etc/ssh").glob("ssh_host_*_key")),
            "SSH host private key present")
    home = rootfs / "home"
    require(not home.is_dir() or not any(home.glob("*/.ssh")),
            "user SSH secrets present")
    require(output.suffix == ".iso", "expected .iso output")
    require(output.parent.is_dir() and not output.parent.is_symlink(),
            "output parent missing or symlink")
    require(os.path.commonpath((str(rootfs), str(output.parent.resolve())))
            != str(rootfs), "output cannot be inside rootfs")
    for destination in (output, Path(str(output) + ".sha256"),
                        Path(str(output) + ".provenance.json")):
        require(not destination.exists() and not destination.is_symlink(),
                f"refusing to overwrite {destination}")
    for tool in TOOLS:
        require(shutil.which(tool) is not None, f"missing tool: {tool}")
    require(re.search(r"(?<!\w)dmsquash-live(?!\w)",
                      command(["lsinitrd", "-m", str(initramfs)])) is not None,
            "initramfs does not include dracut dmsquash-live")
    return {"kernel_release": release, "volume_id": LABEL,
            "kernel_sha256": sha(kernel), "initramfs_sha256": sha(initramfs),
            "dracut_dmsquash_live": True}


def grub_config():
    return (
        "set default=0\nset timeout=5\n"
        "menuentry 'G15Forge Gentoo Live' {\n"
        f"  search --no-floppy --label {LABEL} --set=root\n"
        f"  linux /boot/vmlinuz root=live:CDLABEL={LABEL} "
        "rd.live.dir=/LiveOS rd.live.squashimg=squashfs.img "
        "rd.live.overlay.overlayfs=1 console=tty0 console=ttyS0,115200n8\n"
        "  initrd /boot/initramfs.img\n}\n"
    )


def inspect_iso(candidate):
    eltorito = command(["xorriso", "-indev", str(candidate),
                        "-report_el_torito", "plain"])
    require(re.search(r"\bBIOS\b", eltorito) is not None and
            re.search(r"\bUEFI\b", eltorito) is not None,
            "both BIOS and UEFI El Torito entries required")
    pvd = command(["xorriso", "-indev", str(candidate), "-pvd_info"])
    require(LABEL in pvd, "wrong ISO volume ID")
    inventory = command(["xorriso", "-indev", str(candidate), "-find", "/",
                         "-type", "f", "-print"])
    for expected in ("/boot/vmlinuz", "/boot/initramfs.img",
                     "/boot/grub/grub.cfg", "/LiveOS/squashfs.img",
                     "/G15FORGE/build.json"):
        require(expected in inventory, f"ISO missing {expected}")


def exclusive_publish(source, dest):
    os.link(source, dest)
    dest.chmod(0o444)


def build(rootfs, kernel, initramfs, release, output):
    rootfs, kernel, initramfs = (p.absolute() for p in
                                 (rootfs, kernel, initramfs))
    output = output.absolute()
    record = preflight(rootfs, kernel, initramfs, release, output)
    workspace = Path(tempfile.mkdtemp(prefix=".g15forge-live-", dir=output.parent))
    try:
        tree = workspace / "iso"
        for name in ("boot/grub", "LiveOS", "G15FORGE"):
            (tree / name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(kernel, tree / "boot/vmlinuz")
        shutil.copyfile(initramfs, tree / "boot/initramfs.img")
        (tree / "boot/grub/grub.cfg").write_text(grub_config())
        squash = tree / "LiveOS/squashfs.img"
        command(["mksquashfs", str(rootfs), str(squash), "-noappend",
                 "-comp", "xz", "-processors", "4", "-no-progress"])
        require(squash.is_file() and squash.stat().st_size > 0, "SquashFS absent")
        record["squashfs_sha256"] = sha(squash)
        record["layout"] = "dracut direct SquashFS / OverlayFS"
        (tree / "G15FORGE/build.json").write_text(
            json.dumps(record, sort_keys=True, indent=2) + "\n")
        iso = workspace / "candidate.iso"
        command(["grub-mkrescue", "-o", str(iso), "-volid", LABEL, str(tree)])
        require(iso.is_file() and iso.stat().st_size > 0, "ISO absent")
        inspect_iso(iso)
        record["iso_sha256"] = sha(iso)
        provenance = workspace / "provenance.json"
        provenance.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        digest = workspace / "sha256"
        digest.write_text(f"{record['iso_sha256']}  {output.name}\n")
        # ISO published last, never overwrite any existing name.
        exclusive_publish(provenance, Path(str(output) + ".provenance.json"))
        exclusive_publish(digest, Path(str(output) + ".sha256"))
        exclusive_publish(iso, output)
        return record
    except Exception:
        print(f"P4_RETAINED_WORKSPACE={workspace}", flush=True)
        raise
    finally:
        if output.is_file():
            shutil.rmtree(workspace)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rootfs", type=Path, required=True)
    ap.add_argument("--kernel", type=Path, required=True)
    ap.add_argument("--initramfs", type=Path, required=True)
    ap.add_argument("--kernel-release", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = build(args.rootfs, args.kernel, args.initramfs,
                   args.kernel_release, args.out)
    print(json.dumps({"result": "CANDIDATE_NOT_BOOT_VALIDATED", **result},
                     sort_keys=True))


if __name__ == "__main__":
    main()
