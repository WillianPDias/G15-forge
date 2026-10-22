"""P4 unit tests. Every external ISO tool is mocked; no host/VM writes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts/p4_live_iso.py"
spec = importlib.util.spec_from_file_location("p4", SOURCE)
p4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p4)


class P4LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "gentoo"
        for item in ("etc", "usr/lib/systemd", "lib/modules/6.18-test", "boot"):
            (self.root / item).mkdir(parents=True, exist_ok=True)
        (self.root / "etc/gentoo-release").write_text("Gentoo Base System\n")
        (self.root / "usr/lib/systemd/systemd").write_bytes(b"\x7fELF")
        (self.root / "lib/modules/6.18-test/modules.dep").write_text("ok\n")
        (self.root / "etc/fstab").write_text("# independent Live root\n")
        self.kernel = self.root / "boot/vmlinuz-6.18-test"
        self.kernel.write_bytes(b"K" * 65536)
        self.initramfs = self.root / "boot/initramfs-6.18-test-live.img"
        self.initramfs.write_bytes(b"I" * 1024)
        self.out = self.base / "candidate.iso"

    def preflight(self):
        with patch.object(p4, "mounts_within", return_value=[]), \
             patch.object(p4.shutil, "which", return_value="/fake/tool"), \
             patch.object(p4, "command", return_value="systemd dmsquash-live\n"):
            return p4.preflight(self.root, self.kernel, self.initramfs,
                                "6.18-test", self.out)

    def test_valid_preflight(self):
        self.assertEqual(self.preflight()["volume_id"], "G15FORGE_LIVE")

    def test_fixed_root_partition_rejected(self):
        (self.root / "etc/fstab").write_text("UUID=bad / ext4 defaults 0 1\n")
        with self.assertRaisesRegex(p4.Rejected, "fstab"):
            self.preflight()

    def test_disk_specific_p2_verifier_rejected(self):
        wants = self.root / "etc/systemd/system/multi-user.target.wants"
        wants.mkdir(parents=True)
        (wants / "g15forge-p2-verify.service").symlink_to("/missing/unit")
        with self.assertRaisesRegex(p4.Rejected, "P2"):
            self.preflight()

    def test_nonempty_machine_id_rejected(self):
        (self.root / "etc/machine-id").write_text("host-machine-id\n")
        with self.assertRaisesRegex(p4.Rejected, "machine-id"):
            self.preflight()

    def test_ssh_host_private_key_rejected(self):
        keys = self.root / "etc/ssh"
        keys.mkdir()
        (keys / "ssh_host_ed25519_key").write_text("PRIVATE")
        with self.assertRaisesRegex(p4.Rejected, "SSH"):
            self.preflight()

    def test_wrong_kernel_rejected(self):
        other = self.base / "wrong"
        other.write_bytes(b"Z" * 65536)
        with patch.object(p4, "mounts_within", return_value=[]):
            with self.assertRaisesRegex(p4.Rejected, "differs"):
                p4.preflight(self.root, other, self.initramfs,
                             "6.18-test", self.out)

    def test_active_bind_mount_rejected(self):
        with patch.object(p4, "mounts_within", return_value=["/root/sys"]):
            with self.assertRaisesRegex(p4.Rejected, "active mounts"):
                p4.preflight(self.root, self.kernel, self.initramfs,
                             "6.18-test", self.out)

    def test_existing_output_is_untouched(self):
        self.out.write_bytes(b"untouched")
        with self.assertRaisesRegex(p4.Rejected, "overwrite"):
            self.preflight()
        self.assertEqual(self.out.read_bytes(), b"untouched")

    def test_missing_live_dracut_rejected(self):
        with patch.object(p4, "mounts_within", return_value=[]), \
             patch.object(p4.shutil, "which", return_value="/fake/tool"), \
             patch.object(p4, "command", return_value="systemd base\n"):
            with self.assertRaisesRegex(p4.Rejected, "dmsquash-live"):
                p4.preflight(self.root, self.kernel, self.initramfs,
                             "6.18-test", self.out)

    def test_grub_uses_own_live_root(self):
        cfg = p4.grub_config()
        self.assertIn("root=live:CDLABEL=G15FORGE_LIVE", cfg)
        self.assertIn("rd.live.overlay.overlayfs=1", cfg)
        self.assertNotIn("/dev/nvme", cfg)

    def test_bios_without_uefi_rejected(self):
        with patch.object(p4, "command",
                          return_value="El Torito boot img : BIOS"):
            with self.assertRaisesRegex(p4.Rejected, "both BIOS and UEFI"):
                p4.inspect_iso(self.out)

    def test_exclusive_publish_no_overwrite(self):
        original = self.base / "original"
        original.write_bytes(b"new")
        self.out.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            p4.exclusive_publish(original, self.out)
        self.assertEqual(self.out.read_bytes(), b"old")

    def test_mock_candidate_build(self):
        def fake(argv):
            if argv[0] == "lsinitrd":
                return "dmsquash-live\n"
            if argv[0] == "mksquashfs":
                Path(argv[2]).write_bytes(b"SQUASHFS")
                return ""
            if argv[0] == "grub-mkrescue":
                Path(argv[argv.index("-o") + 1]).write_bytes(b"MOCK ISO")
                return ""
            if "-report_el_torito" in argv:
                return "El Torito boot img : BIOS\nEl Torito boot img : UEFI\n"
            if "-pvd_info" in argv:
                return "Volume Id : G15FORGE_LIVE\n"
            if "-find" in argv:
                return "\n".join(("/boot/vmlinuz", "/boot/initramfs.img",
                                   "/boot/grub/grub.cfg",
                                   "/LiveOS/squashfs.img", "/G15FORGE/build.json"))
            raise AssertionError(argv)
        with patch.object(p4, "mounts_within", return_value=[]), \
             patch.object(p4.shutil, "which", return_value="/fake/tool"), \
             patch.object(p4, "command", side_effect=fake):
            proof = p4.build(self.root, self.kernel, self.initramfs,
                             "6.18-test", self.out)
        self.assertEqual(self.out.read_bytes(), b"MOCK ISO")
        self.assertEqual(proof["iso_sha256"], p4.sha(self.out))
        sidecar = json.loads(Path(str(self.out) + ".provenance.json").read_text())
        self.assertEqual(sidecar["volume_id"], "G15FORGE_LIVE")


if __name__ == "__main__":
    unittest.main()
