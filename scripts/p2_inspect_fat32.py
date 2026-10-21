#!/usr/bin/env python3
"""Inspect an existing partitioned P2 QCOW2 without booting or writing it.

Only evidence files and an independent raw ESP copy are created. Source image
access uses qemu-io -r and qemu-img read-only=on; fsck.fat always uses -n.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid
import zlib

import p2_vm as p2

SOURCE = "https://github.com/dosfstools/dosfstools/blob/v4.2/src/mkfs.fat.c#L730-L736"
REVIEW_SHA = "63ffb251c9c13e8d571506e72656ee6bb5b107f2209872af59b16c3c8ffc88fc"
ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
ROOT_TYPE = "0fc63daf-8483-4772-8e79-3d69d8477de4"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def virtual_read(disk, offset, count):
    result = subprocess.run(["qemu-io", "-r", "-f", "qcow2", "-c",
                             f"read -v {offset} {count}", str(disk)],
                            check=True, capture_output=True, text=True)
    data = b"".join(bytes.fromhex(" ".join(line.split(":", 1)[1].split()[:16]))
                    for line in result.stdout.splitlines()
                    if re.match(r"^[0-9a-f]+:", line))
    require(len(data) == count, "short virtual read")
    return data


def esp_readonly_options(disk, first_sector, size_bytes):
    """Use a bounded raw view; avoid qemu-img dd's count/skip interaction."""
    require(first_sector >= 0 and size_bytes > 0, "invalid export window")
    require(not any(c in str(disk) for c in (",", "\n", "\r")), "unsafe image option path")
    return (f"driver=raw,offset={first_sector * 512},size={size_bytes},read-only=on,"
            f"file.driver=qcow2,file.read-only=on,file.file.driver=file,file.file.filename={disk}")


def gpt_header(data, current, backup, disk_sectors):
    require(len(data) == 512 and data[:8] == b"EFI PART", "invalid GPT signature")
    length = u32(data, 12)
    require(u32(data, 8) == 0x10000 and 92 <= length <= 512 and u32(data, 20) == 0,
            "invalid GPT revision/header length/reserved field")
    check = bytearray(data[:length])
    check[16:20] = b"\0" * 4
    require(zlib.crc32(check) == u32(data, 16), "GPT header CRC mismatch")
    here, other, first, last = struct.unpack_from("<QQQQ", data, 24)
    require(here == current and other == backup and 2 < first <= last < disk_sectors - 1,
            "GPT header bounds mismatch")
    lba, count, size, crc = struct.unpack_from("<QIII", data, 72)
    require(count == 128 and size == 128, "unexpected P2 GPT entry dimensions")
    return {"current_lba": here, "backup_lba": other, "first_usable": first,
            "last_usable": last, "disk_guid": str(uuid.UUID(bytes_le=bytes(data[56:72]))),
            "entries_lba": lba, "entry_count": count, "entry_size": size, "entries_crc": crc}


def inspect_gpt(read, disk_bytes):
    sectors = disk_bytes // 512
    mbr = read(0, 512)
    require(mbr[510:512] == b"\x55\xaa" and mbr[450] == 0xEE,
            "protective MBR missing")
    require(u32(mbr, 454) == 1 and u32(mbr, 458) == sectors - 1,
            "protective MBR bounds mismatch")
    require(mbr[462:510] == b"\0" * 48, "hybrid MBR forbidden")
    primary = gpt_header(read(512, 512), 1, sectors - 1, sectors)
    backup = gpt_header(read((sectors - 1) * 512, 512), sectors - 1, 1, sectors)
    for key in ("first_usable", "last_usable", "disk_guid", "entry_count", "entry_size", "entries_crc"):
        require(primary[key] == backup[key], "GPT mirror mismatch: " + key)
    require(primary["entries_lba"] == 2 and primary["first_usable"] == 34 and
            backup["entries_lba"] == sectors - 33 and primary["last_usable"] == sectors - 34,
            "GPT metadata geometry mismatch")
    length = primary["entry_count"] * primary["entry_size"]
    entries = read(primary["entries_lba"] * 512, length)
    require(zlib.crc32(entries) == primary["entries_crc"], "GPT entry CRC mismatch")
    require(entries == read(backup["entries_lba"] * 512, length), "backup GPT entries differ")
    parts = []
    for i in range(primary["entry_count"]):
        entry = entries[i * 128:(i + 1) * 128]
        if entry[:16] == b"\0" * 16:
            require(entry == b"\0" * 128, "nonempty unused GPT entry")
            continue
        start, end = struct.unpack_from("<QQ", entry, 32)
        require(primary["first_usable"] <= start <= end <= primary["last_usable"],
                "partition outside usable GPT bounds")
        parts.append({"number": i + 1, "first_sector": start, "last_sector": end,
                      "sectors": end - start + 1, "bytes": (end - start + 1) * 512,
                      "type_guid": str(uuid.UUID(bytes_le=entry[:16])),
                      "partuuid": str(uuid.UUID(bytes_le=entry[16:32])),
                      "name": entry[56:128].decode("utf-16le").rstrip("\0")})
    require(len(parts) == 2 and [v["number"] for v in parts] == [1, 2], "unexpected partition count")
    esp, root = parts
    require(esp["first_sector"] == 2048 and esp["bytes"] == 1024**3 and esp["type_guid"] == ESP_TYPE,
            "ESP layout differs from review")
    require(root["type_guid"] == ROOT_TYPE and root["first_sector"] == esp["last_sector"] + 1 and
            root["last_sector"] == primary["last_usable"], "root layout differs from review")
    require(esp["partuuid"] != root["partuuid"], "duplicate partition GUID")
    return {"primary": primary, "backup": backup, "partitions": parts,
            "header_crcs": "PASS", "entry_crcs_and_mirrors": "PASS", "protective_mbr": "PASS"}


def fat_geometry(boot, partition_bytes, first_sector):
    require(len(boot) == 512 and boot[510:512] == b"\x55\xaa" and boot[82:90] == b"FAT32   ",
            "invalid FAT32 boot sector")
    bps, spc, reserved = u16(boot, 11), boot[13], u16(boot, 14)
    fats, total, track = boot[16], u32(boot, 32), u16(boot, 24)
    require(bps == 512 and spc in (1, 2, 4, 8, 16, 32, 64, 128), "unsupported FAT sector/cluster size")
    require(partition_bytes % bps == 0 and 1 <= track <= 63, "invalid FAT track geometry")
    require(u16(boot, 17) == 0 and u16(boot, 19) == 0 and u16(boot, 22) == 0 and
            u16(boot, 40) == 0 and u16(boot, 42) == 0, "invalid FAT32 BPB fields")
    require(u32(boot, 28) == first_sector, "FAT hidden-sector offset mismatch")
    partition_sectors = partition_bytes // bps
    rounded = partition_sectors // track * track
    # Accept exact size or ONLY the precise dosfstools track-rounding formula.
    # Merely being smaller than the partition is deliberately insufficient.
    require(total > 0 and total <= partition_sectors and total in (partition_sectors, rounded),
            "unexplained FAT32 size discrepancy")
    fat_sectors = u32(boot, 36)
    require(reserved >= 8 and fats == 2 and fat_sectors > 0, "invalid reserved/FAT geometry")
    overhead = reserved + fats * fat_sectors
    require(overhead < total, "FAT structures exceed volume")
    clusters = (total - overhead) // spc
    require(65525 <= clusters < 0x0FFFFFF5 and fat_sectors * bps // 4 >= clusters + 2,
            "FAT32 cluster count/table capacity invalid")
    require(2 <= u32(boot, 44) < clusters + 2, "invalid root cluster")
    fsinfo, backup = u16(boot, 48), u16(boot, 50)
    require(0 < fsinfo < reserved and 0 < backup < reserved and fsinfo != backup and
            backup + fsinfo < reserved, "invalid FSInfo/backup locations")
    return {"bytes_per_sector": bps, "sectors_per_cluster": spc, "reserved_sectors": reserved,
            "fats": fats, "fat_sectors": fat_sectors, "sectors_per_track": track,
            "heads": u16(boot, 26), "hidden_sectors": u32(boot, 28),
            "partition_sectors": partition_sectors, "partition_bytes": partition_bytes,
            "fat32_sectors": total, "fat32_bytes": total * bps,
            "difference_sectors": partition_sectors - total,
            "difference_bytes": partition_bytes - total * bps,
            "track_rounding_expected_sectors": rounded, "cluster_count": clusters,
            "root_cluster": u32(boot, 44), "fsinfo_sector": fsinfo, "backup_sector": backup,
            "old_equality_result": bps * total == partition_bytes,
            "size_explanation": "exact" if total == partition_sectors else "dosfstools-4.2-track-rounding"}


def inspect_fat(raw, geometry):
    bps = geometry["bytes_per_sector"]
    with raw.open("rb") as stream:
        def read_sector(sector, count=1):
            stream.seek(sector * bps)
            data = stream.read(count * bps)
            require(len(data) == count * bps, "short ESP read")
            return data
        boot = read_sector(0)
        require(boot == read_sector(geometry["backup_sector"]), "backup boot sector differs")
        info = read_sector(geometry["fsinfo_sector"])
        require(info == read_sector(geometry["backup_sector"] + geometry["fsinfo_sector"]),
                "backup FSInfo differs")
        require(u32(info, 0) == 0x41615252 and u32(info, 484) == 0x61417272 and
                u32(info, 508) == 0xAA550000, "FSInfo signature mismatch")
        require(u32(info, 488) in (0xFFFFFFFF, geometry["cluster_count"] - 1),
                "unexpected fresh-ESP FSInfo free cluster count")
        require(u32(info, 492) == 0xFFFFFFFF or 2 <= u32(info, 492) < geometry["cluster_count"] + 2,
                "FSInfo next cluster outside volume")
        fat = read_sector(geometry["reserved_sectors"], geometry["fat_sectors"])
        second = read_sector(geometry["reserved_sectors"] + geometry["fat_sectors"], geometry["fat_sectors"])
        require(fat == second, "FAT copies differ")
        require(u32(fat, 0) & 0x0FFFFFFF == 0x0FFFFF00 | boot[21], "invalid FAT media entry")
        require(u32(fat, 4) & 0x0FFFFFFF >= 0x0FFFFFF8, "FAT dirty/error bits or reserved entry invalid")
        require(u32(fat, geometry["root_cluster"] * 4) & 0x0FFFFFFF >= 0x0FFFFFF8,
                "root cluster is not an end-of-chain")
        tail = read_sector(geometry["fat32_sectors"], geometry["difference_sectors"])
        require(not any(tail), "unexpected nonzero bytes in track-rounding tail")
    return {"boot_and_backup_identical": True, "fsinfo_and_backup_identical": True,
            "fat_copies_identical": True, "fat_sha256": hashlib.sha256(fat).hexdigest(),
            "free_clusters": u32(info, 488), "next_cluster": u32(info, 492), "unused_tail_zero": True}


def inspect(lab):
    lab, state = p2.load(lab)
    disk = lab / "disk.qcow2"
    receipt = json.loads((lab / "partition.json").read_text())
    before = p2.regular(disk)
    require(before == receipt["disk_after"], "QCOW2 differs from partition receipt")
    require(state["lab_id"] == "7a1233dcc99f44c9a31bbd37457c8719" and
            state["serial"] == "G15P27a1233dcc99f", "unauthorized lab identity")
    require(p2.sha(lab / "review.json") == REVIEW_SHA, "review hash mismatch")
    p2.validate(state, pristine=False)
    evidence = lab / "fat32-inspection-ro"
    evidence.mkdir(mode=0o700, exist_ok=False)
    report = {"status": "POST_PARTITION=BLOCKED", "lab_id": state["lab_id"],
              "serial": state["serial"], "disk_before": before, "source": SOURCE,
              "method": "host-only read-only image access; independent raw ESP; no VM, mount or physical devices",
              "previous_error_origin": "ad hoc Python command in previous session, not a persisted repository script",
              "previous_comparison": "BPB_BytsPerSec * BPB_TotSec32 == (GPT_LastLBA - GPT_FirstLBA + 1) * 512"}
    try:
        info = p2.image_info(disk)
        gpt = inspect_gpt(lambda offset, count: virtual_read(disk, offset, count), info["virtual-size"])
        report["gpt"] = gpt
        esp, root = gpt["partitions"]
        boot = virtual_read(disk, esp["first_sector"] * 512, 512)
        geometry = fat_geometry(boot, esp["bytes"], esp["first_sector"])
        report["fat_geometry"] = geometry
        raw = evidence / "esp.raw"
        options = esp_readonly_options(disk, esp["first_sector"], esp["bytes"])
        command = ["qemu-img", "convert", "--image-opts", "-O", "raw", options, str(raw)]
        exported = subprocess.run(command, capture_output=True, text=True, check=True)
        (evidence / "export.log").write_text(exported.stdout + exported.stderr)
        report["export_command"] = command
        require(raw.stat().st_size == esp["bytes"], "ESP export size mismatch")
        raw.chmod(0o400)
        raw_before = p2.sha(raw)
        with raw.open("rb") as stream:
            require(stream.read(512) == boot, "exported boot sector mismatch")
        report["fat_integrity"] = inspect_fat(raw, geometry)
        command = [shutil.which("fsck.fat") or "fsck.fat", "-n", "-v", str(raw)]
        checked = subprocess.run(command, capture_output=True, text=True)
        (evidence / "fsck-fat-n.log").write_text(checked.stdout + checked.stderr)
        report["fsck_fat"] = {"command": command, "exit_code": checked.returncode,
                              "raw_sha256_before": raw_before, "raw_sha256_after": p2.sha(raw)}
        require(raw_before == report["fsck_fat"]["raw_sha256_after"], "fsck changed ESP evidence")
        require(checked.returncode == 0, "fsck.fat -n reported errors")
        checked = subprocess.run(["qemu-img", "check", "-f", "qcow2", str(disk)], capture_output=True, text=True)
        (evidence / "qcow2-check.log").write_text(checked.stdout + checked.stderr)
        require(checked.returncode == 0, "QCOW2 check failed")
        ext = virtual_read(disk, root["first_sector"] * 512 + 1024, 1024)
        require(ext[56:58] == b"\x53\xef", "ext superblock signature invalid")
        ext_block_size = 1024 << u32(ext, 24)
        ext_blocks = u32(ext, 4)
        if u32(ext, 96) & 0x80:
            ext_blocks += u32(ext, 336) << 32
        require(ext_blocks * ext_block_size <= root["bytes"], "ext filesystem exceeds root partition")
        require(root["bytes"] - ext_blocks * ext_block_size < ext_block_size, "unexplained ext root tail")
        report["root_alignment"] = {"start_aligned_2048_sectors": root["first_sector"] % 2048 == 0,
                                    "exclusive_end_remainder_2048": (root["last_sector"] + 1) % 2048,
                                    "sectors_to_next_boundary": (-(root["last_sector"] + 1)) % 2048,
                                    "reason": "--new=2:0:0 uses last usable LBA; backup GPT occupies final 33 sectors",
                                    "ext_block_bytes": ext_block_size, "ext_blocks": ext_blocks,
                                    "ext_bytes": ext_block_size * ext_blocks,
                                    "partition_tail_bytes": root["bytes"] - ext_block_size * ext_blocks,
                                    "impact": "no overlap or start misalignment; end alignment caution for some encryption tools; no encryption configured"}
        report["status"] = "POST_PARTITION=PASS"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["disk_after"] = p2.regular(disk)
        report["qcow2_unchanged"] = before == report["disk_after"]
        report["scripts_unchanged"] = p2.guest_hashes() == state["scripts"]
        report["checkpoints_unchanged"] = (p2.regular(lab / "checkpoint-blank.qcow2") == state["checkpoint"] and
                                            p2.regular(lab / "checkpoint-nvram.fd") == state["checkpoint_nvram"])
        report["review_unchanged"] = p2.sha(lab / "review.json") == REVIEW_SHA
        if not all(report[k] for k in ("qcow2_unchanged", "scripts_unchanged", "checkpoints_unchanged", "review_unchanged")):
            report["status"] = "POST_PARTITION=BLOCKED"
        p2.write_new(evidence / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", required=True, type=Path)
    args = parser.parse_args()
    lab, _ = p2.load(args.lab)
    with p2.exclusive(lab):
        report = inspect(lab)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["status"] == "POST_PARTITION=PASS" else 1)


if __name__ == "__main__":
    main()
