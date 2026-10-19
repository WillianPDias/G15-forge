# Prototype validation

`bash tests/smoke.sh` runs shell syntax checks and Python regression tests. The build tests use a **fake xorriso** and synthetic files: their PASS does not prove ISO validity or boot. Run `shellcheck scripts/*.sh tests/smoke.sh` separately when installed.

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

This verifies size, ISO SHA-256 sidecar, El Torito platform preservation, payload checksums and the embedded Stage3 against the independently supplied hash. It saves El Torito/system area reports for **manual examination** of boot image paths, load parameters, MBR/GPT and appended EFI partitions; matching platform names alone cannot prove full hybrid boot structure preservation. Its static PASS does not establish successful firmware/kernel boot.

## Diskless KVM observation

```bash
python3 scripts/test_prototype_vm.py \
  --iso /home/williandias/G15Forge-VM/iso/g15forge-prototype-v0.1.iso \
  --out-dir /home/williandias/G15Forge-VM/uefi-v0.1 \
  --firmware uefi --duration 180
```

Use a different new output directory and `--firmware bios` for legacy boot. KVM is required; there is no TCG fallback. UEFI uses a new copy of OVMF VARS. The command contains a read-only CD and firmware only, no installation disk, no existing QCOW2, and no network. Paths containing commas/newlines are rejected. QEMU is terminated and reaped at the deadline or on an exception. Evidence includes the exact argument list, serial output, QEMU log, periodic PPM screenshots and a result JSON. Serial output can be empty when the live boot config uses VGA.

For human interaction on a graphical host, add `--display gtk` and allow the default live entry to boot. This requires GUI permission in restricted runtimes. Headless operation records screenshots and exposes the per-run QMP socket for an operator; it does not automatically type shell commands or claim boot PASS.

Inside the booted live guest:

```sh
findmnt -t iso9660
# Use the live CD mount reported above; the usual path is /mnt/cdrom.
sh /mnt/cdrom/G15FORGE/verify-live-payload.sh /mnt/cdrom/G15FORGE
uname -a
dmesg | grep -Ei 'panic|oops|failed|error|initramfs'
```

Record the visible live shell, firmware mode, `G15FORGE_GUEST=PASS`, checksum results and relevant kernel diagnostics. Review errors in context; a successful process launch, screenshot or grep alone is insufficient. Inspect UEFI with `/sys/firmware/efi` in the guest; it should be absent in legacy BIOS mode. Firmware mode must be recorded from the guest, not inferred only from the launcher.

## Current execution limits (2026-10-19)

The repository was cloned at `c6bd150` on `feat/iso-prototype-dell-g15-5511`, initially clean. The original smoke suite passed. Git 2.43.0, Bash 5.2.21, GnuPG 2.4.4, coreutils 9.4, Python 3.12.3, QEMU/qemu-img 8.2.2 and OVMF 4M files were available.

`xorriso` and ShellCheck were absent. `apt-get -s install xorriso shellcheck` proposed five new packages (including libburn4t64, libisoburn1t64 and libisofs6t64), zero upgrades and zero removals. Security Guard denied the administrative installation command before execution. No alternative installation was attempted. `/dev/kvm` was also absent; the VM launcher refused execution at preflight. The requested ISO directory is outside this session's writable roots, so an actual build there also requires runtime write approval.

**Actual ISO build: NOT EXECUTED. ISO inspection: NOT EXECUTED. UEFI/BIOS live boot: NOT TESTED.** The updated scripts require real xorriso and VM execution before these gates can be promoted.
