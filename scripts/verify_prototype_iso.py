#!/usr/bin/env python3
"""Inspect a built ISO and verify extracted payload; does not claim VM boot."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_manifest(directory, name):
    entries = (directory / name).read_text().splitlines()
    if not entries:
        raise ValueError(f"empty manifest: {name}")
    checked = set()
    for line in entries:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"invalid manifest entry: {name}")
        expected, relative = match.groups()
        path = directory / relative
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError(f"unsafe manifest path: {relative}")
        if digest(path) != expected:
            raise ValueError(f"checksum mismatch: {relative}")
        checked.add(relative)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--source-iso", type=Path, required=True)
    parser.add_argument("--stage3-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.stage3_sha256):
        parser.error("invalid Stage3 SHA-256")
    if not shutil.which("xorriso"):
        parser.error("BLOCKED: xorriso missing")
    for path in (args.iso, args.source_iso):
        if path.is_symlink() or not path.is_file():
            parser.error("inputs must be regular non-symlink files")
    output = args.out_dir.resolve()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {"iso": str(args.iso.resolve()), "static_validation": "FAIL", "boot": "NOT_TESTED"}

    def run(label, command):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (output / f"{label}.txt").write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f"{label} failed, exit {result.returncode}")
        return result.stdout

    try:
        report["size_bytes"] = args.iso.stat().st_size
        if report["size_bytes"] <= args.source_iso.stat().st_size:
            raise ValueError("output is not larger than source ISO with added Stage3")
        report["sha256"] = digest(args.iso)
        sidecar = Path(str(args.iso) + ".sha256").read_text()
        if sidecar != f"{report['sha256']}  {args.iso.resolve()}\n":
            raise ValueError("output SHA-256 sidecar mismatch")
        platforms = []
        for label, iso in (("source", args.source_iso), ("prototype", args.iso)):
            text = run(label + "-boot", ["xorriso", "-indev", str(iso.resolve()),
                       "-report_el_torito", "plain", "-report_system_area", "plain"])
            found = set(re.findall(r"El Torito boot img\s*:\s*\d+\s+(BIOS|UEFI)\b", text))
            if not found:
                raise ValueError(f"no recognized boot platforms in {label} report")
            platforms.append(found)
        if platforms[0] != platforms[1] or "UEFI" not in platforms[1]:
            raise ValueError("boot platform mismatch or UEFI missing")
        report["boot_platforms"] = sorted(platforms[1])
        run("extract", ["xorriso", "-osirrox", "on", "-indev", str(args.iso.resolve()),
                        "-extract", "/G15FORGE", str(output / "payload")])
        payload = output / "payload"
        checked = check_manifest(payload, "SHA256SUMS")
        required = {"README.txt", "profiles/make.conf", "verify-live-payload.sh", "PROVENANCE.txt",
                    "stage3-amd64-systemd.tar.xz", "STAGE3.SHA256"}
        if not required.issubset(checked):
            raise ValueError("required payload files missing from manifest")
        check_manifest(payload, "STAGE3.SHA256")
        if digest(payload / "stage3-amd64-systemd.tar.xz") != args.stage3_sha256:
            raise ValueError("embedded Stage3 does not match independently supplied digest")
        report["static_validation"] = "PASS"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
