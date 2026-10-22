"""Real GRUB/xorriso/squashfs layout integration; fixture files are NOT bootable."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/p4_live_iso.py"
spec = importlib.util.spec_from_file_location("p4_layout", SOURCE)
p4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p4)

TOOLCHAIN = all(shutil.which(x) for x in
                ("grub-mkrescue", "xorriso", "mksquashfs"))


@unittest.skipUnless(TOOLCHAIN, "real ISO authoring tools unavailable")
class RealISOLayoutTests(unittest.TestCase):
    def test_real_hybrid_grub_iso_with_liveos_tree(self):
        with tempfile.TemporaryDirectory(prefix="p4-iso-layout-") as dirname:
            base = Path(dirname)
            root = base / "synthetic-root"
            (root / "etc").mkdir(parents=True)
            (root / "etc/gentoo-release").write_text("SYNTHETIC NON-BOOTABLE\n")
            tree = base / "tree"
            for name in ("boot/grub", "LiveOS", "G15FORGE"):
                (tree / name).mkdir(parents=True)
            (tree / "boot/vmlinuz").write_bytes(b"NOT A KERNEL")
            (tree / "boot/initramfs.img").write_bytes(b"NOT AN INITRAMFS")
            (tree / "boot/grub/grub.cfg").write_text(p4.grub_config())
            (tree / "G15FORGE/build.json").write_text('{"fixture":true}\n')
            p4.command(["mksquashfs", str(root),
                        str(tree / "LiveOS/squashfs.img"),
                        "-noappend", "-comp", "xz", "-processors", "2",
                        "-no-progress"])
            iso = base / "layout-only.iso"
            p4.command(["grub-mkrescue", "-o", str(iso), "-volid",
                        p4.LABEL, str(tree)])
            self.assertTrue(iso.stat().st_size > 0)
            p4.inspect_iso(iso)


if __name__ == "__main__":
    unittest.main()
