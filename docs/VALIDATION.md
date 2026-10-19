# Prototype validation

`bash tests/smoke.sh` runs shell syntax checks and Python regression tests. Build safety tests use a **fake xorriso** and synthetic files. A separate integration test uses real xorriso with dummy boot images to validate hybrid layout and reject GPT corruption; it is skipped when xorriso is absent. CI installs xorriso. These tests do not prove a real Gentoo ISO boots. Run `shellcheck scripts/*.sh tests/smoke.sh` separately.

## Authenticate before building

Verify the detached ISO signature and compare the complete primary fingerprint with an independent official Gentoo publication. A locally calculated SHA-256 alone cannot establish authenticity. See the [Gentoo Handbook verification instructions](https://wiki.gentoo.org/wiki/Handbook:Parts/Full/Installation).

The 2026-10-19 local verification returned GOODSIG and VALIDSIG for both source artifacts:

| Input | SHA-256 |
| --- | --- |
| `install-amd64-minimal-20261018T124555Z.iso` | `a0422d9d74c99174417ba2538642e687c838667bbd1ca01293987405116c4c4c` |
| `stage3-amd64-systemd-20261018T124555Z.tar.xz` | `01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217` |

Primary key: `13EBBDBEDE7A12775DFDB1BABB572E0E2D182910`.
Signing subkey: `534E4209AB49EEE1C19D96162C44695DB9F6043D`.
Both match the official Handbook. Verification used the pre-existing public `verified-release-key.gpg` with an independent temporary GnuPG home, leaving the user's default keyring alone. Local logs are in `out/first-build-20261019/{iso-signature,stage3-signature}.log`; these ignored logs are not published to Git.

## Inspect the output

After a successful build, use an existing parent directory and a new evidence subdirectory:

```bash
python3 scripts/verify_prototype_iso.py \
  --iso /home/williandias/G15Forge-VM/iso/g15forge-prototype-v0.1.iso \
  --source-iso /home/williandias/G15Forge-VM/iso/install-amd64-minimal-20261018T124555Z.iso \
  --stage3-sha256 01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217 \
  --out-dir /home/williandias/G15Forge-VM/inspection-v0.1
```

This verifies size, ISO SHA-256 sidecar, El Torito platform preservation, both GPT header/table CRCs, partition bounds and absence of overlap, identical EFI partition bytes, payload checksums and the embedded Stage3 against the independently supplied hash. It saves El Torito/system area reports for **manual examination** of boot image paths, load parameters and MBR. Its static PASS does not establish successful firmware/kernel boot. This inspector targets the authenticated GPT-based Gentoo source used by this prototype.

## Diskless KVM observation

```bash
python3 scripts/test_prototype_vm.py \
  --iso /home/williandias/G15Forge-VM/iso/g15forge-prototype-v0.1.iso \
  --out-dir /home/williandias/G15Forge-VM/uefi-v0.1 \
  --firmware uefi --duration 240 --probe-after 90 \
  --stage3-sha256 01ed7040d5768b5a056d3c0f7d38b0db23e8c1c4e28a57736d92ea9e30342217
```

Use a different new output directory and `--firmware bios` for legacy boot. KVM is required; there is no TCG fallback. UEFI uses a new copy of OVMF VARS. The command contains a read-only CD and firmware only, no installation disk, no existing QCOW2, and no network. Paths containing commas/newlines are rejected. QEMU is terminated and reaped at the deadline or on an exception. Evidence includes the exact argument list, serial output, QEMU log, periodic PPM screenshots and a result JSON. Serial output can be empty when the live boot config uses VGA.

The default video device is `virtio-vga`. The VGA alternative (`--video VGA`) produced an unreadable UEFI framebuffer with the stock live runtime, although serial guest checks passed. For human interaction on a graphical host, add `--display gtk`; this requires GUI permission in restricted runtimes.

With `--probe-after`, the runner types a fixed read-only guest probe via QMP, checks firmware mode, executes the embedded verifier, and independently checks Stage3 against the supplied digest. Output and full dmesg are captured through the guest serial port. PASS requires all guest markers, not process launch or screenshot alone. If the guest has not reached its shell, no PASS is produced. Inspect the recorded dmesg and screenshots separately for boot/video problems. Without this option, the runner only records observation and never claims PASS. The runner owns the QMP connection during execution.

Inside the booted live guest:

```sh
findmnt -t iso9660
# Use the live CD mount reported above; the usual path is /mnt/cdrom.
sh /mnt/cdrom/G15FORGE/verify-live-payload.sh /mnt/cdrom/G15FORGE
uname -a
dmesg | grep -Ei 'panic|oops|failed|error|initramfs'
```

Record the visible live shell, firmware mode, `G15FORGE_GUEST=PASS`, checksum results and relevant kernel diagnostics. Review errors in context; a successful process launch, screenshot or grep alone is insufficient. Inspect UEFI with `/sys/firmware/efi` in the guest; it should be absent in legacy BIOS mode. Firmware mode must be recorded from the guest, not inferred only from the launcher.

## Execution record (2026-10-19)

The repository was cloned at `c6bd150` on `feat/iso-prototype-dell-g15-5511`, initially clean. The original smoke suite passed. Git 2.43.0, Bash 5.2.21, GnuPG 2.4.4, coreutils 9.4, Python 3.12.3, QEMU/qemu-img 8.2.2 and OVMF 4M files were available.

Initially `xorriso`, ShellCheck and sandbox KVM access were unavailable. The operator subsequently installed the missing tools; approved execution outside the sandbox provided access to host KVM and the output directory. No security hook was modified or bypassed.

The first real build failed with a GPT overlap because xorriso's emulated TOC placed the session at LBA 32. The corrected build uses `-compliance no_emul_toc` and starts at LBA 0. The failed build remains preserved. The first ISO was then built and passed static inspection plus BIOS and UEFI guest payload probes. See [FIRST_ISO.md](FIRST_ISO.md) for exact identity and evidence. Future builds also recognize the whitespace in the real HFS+ report when preserving HFS+ blessings; Apple firmware boot is outside this validation.
