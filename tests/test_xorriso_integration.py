"""Real xorriso hybrid-layout regression; dummy boot images cannot boot a VM."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("xorriso"), "real xorriso not installed")
class HybridLayout(unittest.TestCase):
    def test_remaster_efi_gpt_hfs_at_lba_zero(self):
        with tempfile.TemporaryDirectory(prefix="g15forge-real-layout-") as name:
            root = Path(name)
            tree = root / "tree"
            tree.mkdir()
            (tree / "efi.img").write_bytes(bytes(2949120))
            (tree / "bios.img").write_bytes(bytes(4096))
            stage = root / "stage.tar.xz"
            stage.write_bytes(b"synthetic Stage3 fixture, not a tar archive")
            source = root / "source.iso"
            output = root / "prototype.iso"
            made = subprocess.run([
                "xorriso", "-compliance", "no_emul_toc", "-outdev", str(source),
                "-map", str(tree), "/", "-hfsplus", "on",
                "-boot_image", "any", "apm_block_size=2048",
                "-boot_image", "any", "efi_boot_part=--efi-boot-image",
                "-boot_image", "any", "bin_path=/bios.img",
                "-boot_image", "any", "next", "-boot_image", "any", "efi_path=/efi.img", "-commit",
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            stage_sha = hashlib.sha256(stage.read_bytes()).hexdigest()
            built = subprocess.run([
                "bash", str(REPO / "scripts/build-prototype-iso.sh"),
                "--iso", str(source), "--iso-sha256", hashlib.sha256(source.read_bytes()).hexdigest(),
                "--stage3", str(stage), "--stage3-sha256", stage_sha, "--out", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertIn("at LBA 0", built.stdout)
            inspected = subprocess.run([
                "python3", str(REPO / "scripts/verify_prototype_iso.py"),
                "--iso", str(output), "--source-iso", str(source),
                "--stage3-sha256", stage_sha, "--out-dir", str(root / "inspection"),
            ], capture_output=True, text=True)
            self.assertEqual(inspected.returncode, 0, inspected.stdout + inspected.stderr)
            report = (root / "inspection/prototype-boot.txt").read_text()
            self.assertIn("GPT", report)
            self.assertIn("Apple_HFS", report)
            with output.open("rb") as stream:
                stream.seek(512)
                self.assertEqual(stream.read(8), b"EFI PART")
