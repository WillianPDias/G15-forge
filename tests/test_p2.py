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


class Recipe(unittest.TestCase):
    """Static regression locks for the reviewed installation recipe.

    Lab-bound scripts cannot change after preparation, so these tests pin the
    package policy that the real upstream binhost forced: binary-only
    installation wherever signed binaries exist, and a source build only for
    the two packages the binhost cannot redistribute (gentoo-kernel,
    intel-microcode). They also lock the independent-boot essentials so a
    future edit cannot silently weaken them.
    """

    def chroot(self):
        return (REPO / "guest/p2-chroot.sh").read_text()

    def test_binary_only_line_excludes_source_only_packages(self):
        line = next(l for l in self.chroot().splitlines() if l.startswith("emerge --getbinpkgonly "))
        for package in ("sys-fs/dosfstools", "sys-fs/e2fsprogs", "sys-kernel/dracut", "sys-boot/grub"):
            self.assertIn(package, line)
        for absent in ("gentoo-kernel", "intel-microcode"):
            self.assertNotIn(absent, line)

    def test_kernel_and_microcode_built_from_signed_sources(self):
        line = next(l for l in self.chroot().splitlines() if l.startswith("emerge --getbinpkg "))
        self.assertIn("sys-kernel/gentoo-kernel", line)
        self.assertIn("sys-firmware/intel-microcode", line)

    def test_signature_verification_stays_mandatory(self):
        text = (REPO / "guest/p2-installer.sh").read_text()
        self.assertIn('FEATURES="${FEATURES} binpkg-request-signature"', text)
        self.assertIn("sync-webrsync-verify-signature = true", text)
        self.assertIn("verify-signature = true", text)
        self.assertNotIn("verify-signature = false", text)
        self.assertNotIn("sync-webrsync-verify-signature = false", text)

    def test_dracut_generic_with_virtio_and_early_microcode(self):
        text = self.chroot()
        self.assertIn('hostonly="no"', text)
        self.assertIn('early_microcode="yes"', text)
        self.assertIn('add_drivers+=" virtio_pci virtio_blk virtio_net "', text)

    def test_grub_removable_fallback_without_nvram(self):
        line = next(l for l in self.chroot().splitlines() if l.startswith("grub-install"))
        self.assertIn("--target=x86_64-efi", line)
        self.assertIn("--removable", line)
        self.assertIn("--no-nvram", line)

    def test_installed_verification_service_enabled(self):
        line = next(l for l in self.chroot().splitlines() if l.startswith("systemctl enable"))
        for unit in ("systemd-networkd.service", "systemd-resolved.service", "g15forge-p2-verify.service"):
            self.assertIn(unit, line)

    def test_installed_boot_requires_pid1_systemd_and_no_live_media(self):
        text = (REPO / "guest/p2-installed-verify.sh").read_text()
        self.assertIn("[[ $(cat /proc/1/comm) == systemd ]]", text)
        self.assertIn("iso9660", text)
        self.assertIn("P2_SYSTEMD_PASS", text)
        self.assertIn("systemctl poweroff", text)

    def test_documented_stage3_hash_matches_controller(self):
        self.assertIn(p2.STAGE_SHA, (REPO / "docs/P2.md").read_text())


class Report(unittest.TestCase):
    """The read-only evidence summarizer must report drift, never write."""

    def fixture(self, scripts=None):
        import p2_report
        (REPO / "out").mkdir(exist_ok=True)
        lab = Path(tempfile.mkdtemp(prefix="p2-report-test-", dir=REPO / "out"))
        self.addCleanup(shutil.rmtree, lab, ignore_errors=True)
        disk = lab / "disk.qcow2"
        disk.write_bytes(b"blank")
        (lab / "checkpoint-blank.qcow2").write_bytes(b"blank")
        (lab / "checkpoint-nvram.fd").write_bytes(b"nvram")
        state = {"lab_id": "b" * 32, "serial": "G15P2" + "b" * 12,
                 "disk": {"path": str(disk), "inode": disk.stat().st_ino, "bytes": disk.stat().st_size,
                          "mode": oct(disk.stat().st_mode & 0o777), "sha256": p2.sha(disk)},
                 "checkpoint": {"sha256": p2.sha(lab / "checkpoint-blank.qcow2")},
                 "checkpoint_nvram": {"sha256": p2.sha(lab / "checkpoint-nvram.fd")},
                 "scripts": scripts if scripts is not None else {"guest/p2-identity.sh": p2.sha(REPO / "guest/p2-identity.sh")}}
        p2.write_new(lab / "state.json", state)
        return p2_report, lab, state

    def test_summarize_reports_evidence_without_writing(self):
        report, lab, state = self.fixture()
        before = sorted(path.name for path in lab.iterdir())
        text = report.summarize(lab)
        self.assertIn("lab_id=" + state["lab_id"], text)
        self.assertIn("serial=" + state["serial"], text)
        self.assertIn("disk inode=" + str(state["disk"]["inode"]), text)
        self.assertIn("checkpoint match=YES", text)
        self.assertIn("bound scripts unchanged=YES", text)
        self.assertIn("phase diagnose: not executed", text)
        self.assertIn("review: absent", text)
        self.assertEqual(before, sorted(path.name for path in lab.iterdir()))

    def test_summarize_exposes_checkpoint_and_script_drift(self):
        report, lab, state = self.fixture(scripts={"guest/p2-identity.sh": "0" * 64})
        state["checkpoint"]["sha256"] = "1" * 64
        (lab / "state.json").unlink()
        p2.write_new(lab / "state.json", state)
        text = report.summarize(lab)
        self.assertIn("checkpoint match=NO", text)
        self.assertIn("bound scripts unchanged=NO guest/p2-identity.sh", text)

    def test_summarize_rejects_labs_outside_out(self):
        import p2_report
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(ValueError, "direct child"):
                p2_report.summarize(outside)


if __name__ == "__main__":
    unittest.main()
