# G15Forge OS

Reproducible Gentoo-based OS engineering project for Dell G15 5511 (i7-11800H, Intel UHD, NVIDIA RTX 3060 Laptop, 32 GiB RAM).

## Current milestone: ISO prototype, not a finished custom Gentoo install

The build script remasters an **already verified** Gentoo amd64 Minimal ISO, retaining its boot configuration, and embeds the G15Forge profile and (optionally) an authenticated systemd Stage3. It does **not** silently claim the live kernel, initramfs, drivers or installed root filesystem have been optimized. The original Gentoo Live OS is retained.

For full hardware-specific kernel and NVIDIA driver integration, follow docs/ROADMAP.md. Hardware validation must occur on the real Dell using non-destructive live boot before installing anything.

## Prerequisites

Linux host with xorriso, sha256sum, bash, coreutils, sufficient free storage. Official Gentoo live ISO independently authenticated using Gentoo's signing keys.

## Build a prototype

    bash tests/smoke.sh
    bash scripts/build-prototype-iso.sh --help

Then set paths explicitly and build:

    bash scripts/build-prototype-iso.sh \
      --iso "$HOME/G15Forge-VM/iso/install-amd64-minimal-20261018T124555Z.iso" \
      --iso-sha256 "INSERT_VERIFIED_ISO_SHA256" \
      --stage3 "$HOME/Downloads/G15Forge-Gentoo-Stage3-v0.4/artifacts/stage3/stage3-amd64-systemd-20261018T124555Z.tar.xz" \
      --stage3-sha256 "01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217" \
      --out "$HOME/G15Forge-VM/iso/g15forge-prototype-v0.1.iso"

The ISO SHA-256 MUST come from a trustworthy previously verified record; the script refuses missing or malformed hashes. This repository intentionally does not embed an unverified ISO digest.

Build and ISO inspection are separate from boot testing: use a fresh QEMU overlay and validate UEFI boot, payload access and both ISO boot paths. The build does not attach NVMe or other host block devices.

## Safety

Never run destructive installation commands on host disks. Do not remove Codex Security Guard protections. No auto-apply for LLM-proposed kernel/bootloader changes. Prototype ISO generation writes a new ordinary file only; refuses overwriting outputs.

See docs/HARDWARE.md and docs/ROADMAP.md.
