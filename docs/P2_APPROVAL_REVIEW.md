# Specific P2 partition review — awaiting human confirmation

This is a local technical review of the proposed operation, not native authorization and not a claim that P2 is installed. **Partitioning, formatting, installation and independent systemd boot are NOT EXECUTED.** P1 was not rebuilt or recertified.

## Exact selected target

| Field | Value |
| --- | --- |
| Lab | `/home/williandias/G15Forge-VM/source/G15-forge/out/p2-9054f0ad37de` |
| Lab ID | `6b3c5c0610bf4514a61de1346def54e5` |
| Target | `disk.qcow2` in that lab, a newly created standalone QCOW2 |
| File identity | device `66309`, inode `4624851`, owner UID/GID `1000/1000`, mode `0600`, one link |
| Capacity | `68719476736` bytes / 64 GiB virtual; `197632` bytes current file length |
| Virtio serial | `G15P26b3c5c0610bf` |
| Guest target | `/dev/vda`, accepted only after matching that serial, capacity, UEFI/live context and single-disk inventory |
| Independent checkpoint | `checkpoint-blank.qcow2`, inode `4624853`, mode `0400`, same length, one link |
| Target/checkpoint SHA-256 | `19eb403b49ebb8007177a5f8cc49713c69a517d81c30fb31673336e5dd298cc3` |
| Independent NVRAM checkpoint | `checkpoint-nvram.fd`, inode `4624854`, `540672` bytes, mode `0400` |
| NVRAM SHA-256 | `5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e` |
| Machine review | `review.json` in the lab; binds target/checkpoints, scripts, diagnosis and intended QEMU command |
| Review SHA-256 | `893a63a17ec2a084c81a2bf92196e0b334d071c17cd79354bacafdea8c20f9af` |

## Evidence and technical assessment

- `qemu-img check`: no errors. The QCOW2 has no backing image or external data file. `qemu-img map` reports the entire 64 GiB as zero/unallocated. The blank checkpoint is an independent full-file copy with distinct inode and identical hash. The NVRAM checkpoint also compares byte-for-byte with the installed OVMF VARS template.
- Real read-only KVM/OVMF diagnosis: PASS. The actual QMP block graph included only this QCOW2 in read-only mode, firmware/new NVRAM, the existing installer ISO and the new read-only seed. Network was disabled. Guest sysfs reported the exact serial above, a single 64 GiB disk and no target partitions/filesystem. All required formatting/installation utilities in the diagnostic checklist were present.
- The VM shut down normally with exit code zero, and the controller reaped QEMU. Target inode, length and hash remained equal to the prepared record/checkpoint. The successful run is `r/d-b2aeb358/`; its serial log SHA-256 is `3e609030db3b312ee8e5bf91a4d0d546779aedef06af31a73aa893c995d098e4`.
- Before a partition run, the controller requires unchanged image/checkpoint identities, pristine content, current script hashes, exact approval/review binding and no prior completion. It then audits the actual QMP graph before executing guest commands. The writable target is a fixed lab-relative file, not an arbitrary `--disk` argument. The guest repeats its own identity and mount/swap guards.
- Layout: GPT; 1 GiB FAT32 ESP; ext4 root using the remaining space. No installation disk is attached from history. No physical block device or network is included in the partition run. The guard code and formatting operations are in `guest/p2-installer.sh`, using `guest/p2-identity.sh` for the serial comparison.
- Automated validation: 34 tests PASS, including 16 P2 tests for approval refusal, checkpoint tampering, controller exclusion, receipt preservation, graph mismatches, aliases, real QCOW2 independence/backing rejection and the observed offline serial case. ShellCheck passed. Tests are not evidence of an installed systemd boot.

The previous diagnostic labs `out/p2-f7ff54109fe2/` and `out/p2-7de8b8f59d44/` remain preserved. They rejected an empty lsblk serial even though the kernel sysfs serial was correct. Both had read-only targets, unchanged hashes and normal guest shutdown. The successful lab uses the corrected canonical identity check and a new target, without altering the failed variants.

## Concrete operation, only after confirmation

From the repository root:

```bash
python3 scripts/p2_vm.py partition \
  --lab /home/williandias/G15Forge-VM/source/G15-forge/out/p2-9054f0ad37de \
  --approval /home/williandias/G15Forge-VM/source/G15-forge/out/p2-9054f0ad37de/approval.json
```

No real-lab approval file has been created. After the user explicitly confirms this exact target/operation, its documentary JSON must bind the lab ID, serial and review hash above, as specified in [P2.md](P2.md). Runtime KVM permission is still required independently.

The guarded guest operation is:

```bash
sgdisk --clear --new=1:2048:+1G --typecode=1:ef00 --change-name=1:G15P2_EFI \
  --new=2:0:0 --typecode=2:8300 --change-name=2:G15P2_ROOT /dev/vda
blockdev --rereadpt /dev/vda
udevadm settle
mkfs.fat -F 32 -n G15P2EFI /dev/vda1
mkfs.ext4 -L G15P2ROOT /dev/vda2
```

These commands run only inside the identity-checked VM. A failure is preserved; there is no automatic rollback or restoration. Signed package availability, actual installation, kernel/initramfs generation and independent PID 1 systemd boot remain to be validated after the required confirmation.
