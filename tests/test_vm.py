import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("vm", Path(__file__).resolve().parents[1] / "scripts/test_prototype_vm.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


class DisklessCommand(unittest.TestCase):
    def test_guest_probe_keys_and_shell_syntax(self):
        import subprocess
        probe = vm.guest_probe("0" * 64)
        for character in probe:
            self.assertTrue(vm.keycodes(character))
        self.assertEqual(subprocess.run(["sh", "-n"], input=probe, text=True).returncode, 0)
        self.assertIn("sha256sum -c", probe)
        self.assertIn("/dev/ttyS0", probe)

    def test_uefi_has_only_cd_and_firmware(self):
        args = vm.command(Path("/lab/prototype.iso"), Path("/lab/run"), "uefi", Path("/usr/share/OVMF/code.fd"), "none")
        drives = [args[i + 1] for i, arg in enumerate(args) if arg == "-drive"]
        self.assertEqual(len(drives), 3)
        self.assertIn("readonly=on", drives[0])
        self.assertIn("readonly=on", drives[1])
        self.assertEqual(drives[2], "if=pflash,format=raw,unit=1,file=/lab/run/nvram.fd")
        self.assertIn("q35,accel=kvm", args)
        self.assertIn("virtio-vga", args)
        self.assertEqual(args[args.index("-nic") + 1], "none")
        self.assertFalse(any("qcow2" in arg or "/dev/" in arg for arg in args))

    def test_bios_has_only_readonly_cd(self):
        args = vm.command(Path("/lab/prototype.iso"), Path("/lab/run"), "bios", Path("/unused"), "none")
        drives = [args[i + 1] for i, arg in enumerate(args) if arg == "-drive"]
        self.assertEqual(drives, ["file=/lab/prototype.iso,if=none,id=livecd,format=raw,readonly=on"])


if __name__ == "__main__":
    unittest.main()
