# P2 post-partition FAT32 inspection

The inspection of lab `out/p2-03a53f8e000c` concluded `POST_PARTITION=PASS`.
This is a filesystem/partition inspection, not Gentoo installation or boot
acceptance. No VM was started, and no physical device or mount was used.

## Exact failure and root cause

`FAT32 size mismatch` came from an ad hoc Python command in the previous
session, not a persisted repository script or any of the six lab-bound files.
The original comparison was:

```python
require(struct.unpack_from('<H', fat, 11)[0] * struct.unpack_from('<I', fat, 32)[0] == parts[0]['bytes'], 'FAT32 size mismatch')
```

`require` raised `RuntimeError` when its first argument was false. The two
little-endian BPB fields were read at offsets 11 (`BPB_BytsPerSec`) and 32
(`BPB_TotSec32`). `parts[0]['bytes']` was `(last_lba - first_lba + 1) * 512`.
The old comparison evaluated `512 * 2097144 == 1073741824`, which is false.
Its formula is also recorded in the preserved `post-partition-verification.json`.

| Value | Sectors (512 bytes) | Bytes |
| --- | ---: | ---: |
| GPT ESP, inclusive LBA 2048–2099199 | 2097152 | 1073741824 |
| FAT32 volume | 2097144 | 1073737728 |
| Unused tail inside ESP | 8 | 4096 |

The BPB reports 63 sectors per track and 16 heads. dosfstools 4.2 intentionally
rounds the filesystem size down to complete tracks when structure alignment
is enabled: `num_sectors / secs_track * secs_track` using integer arithmetic.
Here `floor(2097152 / 63) * 63 = 2097144`. See the
[upstream implementation](https://github.com/dosfstools/dosfstools/blob/v4.2/src/mkfs.fat.c#L730-L736).
The difference is an explained unused tail, not evidence of corruption.

## Read-only procedure and evidence

`scripts/p2_inspect_fat32.py` is independent of the six bound scripts. It
requires the existing partition receipt and exact disk identity/hash. It uses
`p2_vm.validate(pristine=False)` for sources/checkpoints/script binding; it does
not invoke a controller phase or require a blank disk.

It reads virtual sectors through `qemu-io -r`, checks both GPT headers and entry
arrays including CRCs, protective MBR, usable bounds, partition types and
non-overlap. It exports only the ESP using a bounded raw view:
`driver=raw,offset=1048576,size=1073741824,read-only=on`, wrapping the QCOW2
driver with `file.read-only=on`. The original image is never the export target.
It checks the raw copy's exact size and boot sector, sets its permissions to
`0400`, verifies FAT structures, runs `fsck.fat -n -v`, and checks the raw copy's
hash before/after fsck. It also runs `qemu-img check` without repair flags.

The completed evidence is under `fat32-inspection-ro/` in the existing lab:

- `report.json`: numeric fields, commands, hashes, integrity checks and result.
- `esp.raw`: independent, complete, read-only ESP copy (1 GiB logical size).
- `fsck-fat-n.log`: fsck.fat 4.2, exit 0, no repairs; 1/261627 clusters used.
- `qcow2-check.log`: no errors found.
- `tests.log`: complete regression-suite result.

Boot sector and backup at sector 6 match exactly. FSInfo at sector 1 and its
backup at sector 7 match, including signatures and free-cluster count. Both
1 MiB FATs match; root cluster and reserved entries are consistent. The 8-sector
tail is zero. Full directory/allocation consistency is checked by fsck.fat.

An initial export attempt was retained under `fat32-inspection/`. Its
`qemu-img dd count=1024 skip=1 bs=1048576` produced a raw file 1 MiB short,
which the inspector rejected before fsck. QEMU 8.2.2 applies `count` to the
input endpoint before subtracting `skip`; the bounded raw view avoids that
interaction. The initial report and copy have not been replaced or removed.

The inspector uses exclusive evidence creation and stops if its output folder
already exists. Do not remove prior evidence to rerun it. This completed
inspection does not require another execution.

## Root partition end-alignment caution

Root starts at LBA 2099200, aligned to 2048 sectors, and ends inclusively at
LBA 134217694, the last usable GPT sector. Backup GPT entries occupy LBAs
134217695–134217726 and its header is at 134217727. There is no overlap.
`--new=2:0:0` selected the maximum usable end, rather than rounding it down.

The exclusive root end is 134217695: remainder 2015 modulo 2048, or 33 sectors
short of the next boundary. This explains the guest warning about some disk
encryption tools; it does not indicate start misalignment or GPT corruption.
No encryption is configured. No physical-device performance conclusion is
drawn. The ext superblock declares 16514811 blocks of 4096 bytes, fitting inside
the partition with 3584 bytes (7 sectors) unused, less than one filesystem
block. No resizing or reformatting was performed.

## Preservation and regression boundary

QCOW2 SHA-256 before and after:
`e377a564486e50a22b2b4223c114b895a03c057cf105990be5a513246f42f53d`.
Device/inode, six scripts, checkpoints and review remain unchanged. Original
partition logs, approval and failed post-verification evidence are preserved.

The new tests reproduce the original false positive and accept only exact
size or the precise declared-track rounding. Arbitrary truncation, oversize,
invalid BPB fields, GPT header CRC corruption, FAT/FSInfo/boot backup mismatch
and nonzero unused tail remain failures. A parser-level size explanation alone
does not produce the final verdict: GPT, FAT structures, fsck, QCOW2 and
preservation checks must also pass.

Gentoo installation requires separate human authorization.
