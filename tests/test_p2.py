"""P2 guard/graph tests. Never run partition or installation commands."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
SPEC = importlib.util.spec_from_file_location("p2", REPO / "scripts/p2_vm.py")
p2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p2)


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="g15forge-p2-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = {"lab": str(self.root), "lab_id": "a" * 32, "serial": "G15P2" + "a" * 12,
                      "live_iso": {"path": "/lab/live.iso"}, "scripts": {"guest.sh": "x"},
                      "disk": {"path": str(self.root / "disk.qcow2")}, "checkpoint": {"sha256": "0" * 64}, "checkpoint_nvram": {"sha256": "1" * 64}}

    def test_diagnostic_disk_readonly_and_no_network(self):
        args = p2.qemu_command(self.state, "diagnose", self.root, self.root / "seed.iso")
        disks = [args[i + 1] for i, arg in enumerate(args) if arg == "-drive"]
        self.assertEqual(len(disks), 5)
        self.assertIn("readonly=on", disks[0])
        self.assertEqual(args[args.index("-nic") + 1], "none")
        self.assertIn("serial=" + self.state["serial"], args[args.index("-device", args.index("-drive")) + 1])

    def test_independent_boot_has_no_iso(self):
        args = p2.qemu_command(self.state, "verify", self.root)
        self.assertNotIn("/lab/live.iso", " ".join(args))
        self.assertNotIn("ide-cd", " ".join(args))
        self.assertEqual(args[args.index("-nic") + 1], "none")
        self.assertEqual(sum(arg == "-drive" for arg in args), 3)

    def test_only_install_has_nat(self):
        args = p2.qemu_command(self.state, "install", self.root, self.root / "seed.iso")
        self.assertEqual(args[args.index("-nic") + 1], "user,model=virtio-net-pci,ipv6=off")
        self.assertNotIn("hostfwd", " ".join(args))
        args = p2.qemu_command(self.state, "partition", self.root, self.root / "seed.iso")
        self.assertEqual(args[args.index("-nic") + 1], "none")

    def test_unknown_phase_rejected(self):
        with self.assertRaises(ValueError):
            p2.qemu_command(self.state, "unreviewed", self.root)

    def test_missing_seed_rejected(self):
        with self.assertRaises(ValueError):
            p2.qemu_command(self.state, "partition", self.root)

    def test_unapproved_partition_never_starts_qemu(self):
        with patch.object(p2.os, "access", return_value=True), patch.object(p2, "validate"), patch.object(p2.subprocess, "Popen") as process:
            with self.assertRaisesRegex(ValueError, "specific human approval"):
                p2.execute(self.root, self.state, "partition")
            process.assert_not_called()
        self.assertFalse((self.root / "r").exists())

    def test_completed_partition_never_replayed(self):
        (self.root / "partition.json").write_text('{}')
        with patch.object(p2.os, "access", return_value=True), patch.object(p2.subprocess, "Popen") as process:
            with self.assertRaisesRegex(ValueError, "already completed"):
                p2.execute(self.root, self.state, "partition")
            process.assert_not_called()

    def test_regular_rejects_aliases(self):
        original = self.root / "original"
        original.write_bytes(b"test")
        link = self.root / "link"
        link.symlink_to(original)
        with self.assertRaises(ValueError):
            p2.regular(link)
        os.link(original, self.root / "hardlink")
        with self.assertRaises(ValueError):
            p2.regular(original)

    def test_approval_bound_to_review(self):
        p2.write_new(self.root / "review.json", {k: self.state[k] for k in ("scripts", "disk", "checkpoint", "checkpoint_nvram", "lab_id", "serial")})
        approval = {"approved": True, "operation": "partition-and-format", "lab_id": self.state["lab_id"],
                    "serial": self.state["serial"], "review_sha256": p2.sha(self.root / "review.json")}
        path = self.root / "approval.json"
        path.write_text(json.dumps(approval))
        self.assertEqual(p2.check_approval(self.root, self.state, path), approval)
        for key, value in (("approved", False), ("approved", 1), ("serial", "wrong"), ("review_sha256", "0" * 64), ("extra", True)):
            with self.subTest(key=key, value=value):
                wrong = dict(approval); wrong[key] = value
                path.write_text(json.dumps(wrong))
                with self.assertRaises(ValueError):
                    p2.check_approval(self.root, self.state, path)

    def test_qmp_block_graph(self):
        expected = {"/lab/disk.qcow2": False, "/lab/code.fd": True}
        blocks = [{"inserted": {"image": {"filename": name}, "ro": ro}} for name, ro in expected.items()]
        p2.audit_blocks(blocks, expected)
        for changed in (blocks[:1], blocks + blocks[:1], blocks + [{"inserted": {"image": {"filename": "/unapproved.raw"}, "ro": False}}], [{}]):
            with self.assertRaises(ValueError):
                p2.audit_blocks(changed, expected)
        blocks[0]["inserted"]["ro"] = True
        with self.assertRaises(ValueError):
            p2.audit_blocks(blocks, expected)

    def test_checkpoint_and_target_tampering_rejected(self):
        disk = self.root / "disk.qcow2"
        checkpoint = self.root / "checkpoint-blank.qcow2"
        nvram = self.root / "checkpoint-nvram.fd"
        disk.write_bytes(b"blank disk fixture")
        shutil.copyfile(disk, checkpoint)
        nvram.write_bytes(b"NVRAM fixture")
        self.state.update(disk=p2.regular(disk), checkpoint=p2.regular(checkpoint), checkpoint_nvram=p2.regular(nvram),
                          stage3={"path": "/lab/stage3"})
        with patch.object(p2, "image_info"), patch.object(p2, "guest_hashes", return_value=self.state["scripts"]), patch.object(p2, "source"):
            p2.validate(self.state, pristine=True)
            disk.write_bytes(b"unexpected write")
            with self.assertRaisesRegex(ValueError, "blank checkpoint"):
                p2.validate(self.state, pristine=True)
            shutil.copyfile(checkpoint, disk)
            checkpoint.write_bytes(b"changed checkpoint")
            with self.assertRaisesRegex(ValueError, "checkpoint identity"):
                p2.validate(self.state, pristine=True)

    def test_controller_lock_excludes_other_writer(self):
        with p2.exclusive(self.root):
            with self.assertRaises(BlockingIOError):
                with p2.exclusive(self.root):
                    self.fail("second controller acquired lock")

    def test_phase_record_cannot_be_overwritten(self):
        record = self.root / "receipt.json"
        p2.write_new(record, {"result": "FAIL"})
        with self.assertRaises(FileExistsError):
            p2.write_new(record, {"result": "PASS"})
        self.assertEqual(json.loads(record.read_text())["result"], "FAIL")

    def test_kernel_serial_when_offline_lsblk_serial_empty(self):
        # Reproduce the live guest: lsblk SERIAL is empty but sysfs holds the
        # exact virtio ID, without a trailing newline. Never run the installer.
        kernel_serial = self.root / "serial"
        serial = self.state["serial"]
        helper = REPO / "guest/p2-identity.sh"
        command = ["bash", "-c", 'source "$1"; p2_check_serial "$2" "$3"', "identity-test", str(helper), serial, str(kernel_serial)]
        kernel_serial.write_text(serial)
        self.assertEqual(subprocess.run(command).returncode, 0)
        for observed in ("", serial[:-1], "G15P2bbbbbbbbbbbb"):
            kernel_serial.write_text(observed)
            self.assertNotEqual(subprocess.run(command).returncode, 0)

    @unittest.skipUnless(shutil.which("qemu-img"), "qemu-img missing")
    def test_real_standalone_checkpoint_and_backing_rejection(self):
        disk = self.root / "disk.qcow2"
        subprocess.run(["qemu-img", "create", "-f", "qcow2", str(disk), str(p2.SIZE)], check=True, capture_output=True)
        checkpoint = self.root / "checkpoint.qcow2"
        shutil.copyfile(disk, checkpoint)
        self.assertEqual(p2.sha(disk), p2.sha(checkpoint))
        self.assertNotEqual(p2.regular(disk)["inode"], p2.regular(checkpoint)["inode"])
        self.assertEqual(p2.image_info(disk)["virtual-size"], p2.SIZE)
        overlay = self.root / "synthetic-overlay.qcow2"
        subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(disk), str(overlay)], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            p2.image_info(overlay)

    def test_guest_syntax_only(self):
        for path in (REPO / "guest").glob("p2-*.sh"):
            with self.subTest(path=path.name):
                subprocess.run(["bash", "-n", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()
