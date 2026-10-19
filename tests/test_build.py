"""Regression tests with a fake xorriso; these do NOT validate an ISO or boot."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class BuildSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="g15forge-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.iso = self.root / "source.iso"
        self.stage = self.root / "stage.tar.xz"
        self.out = self.root / "prototype.iso"
        self.iso.write_bytes(b"synthetic iso fixture")
        self.stage.write_bytes(b"synthetic stage fixture")
        tool = self.root / "xorriso"
        tool.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
if args == ['-version']:
    print('FAKE xorriso for regression tests only')
    sys.exit(0)
if '-report_el_torito' in args:
    print('APM partition type:   2  Apple_HFS')
    sys.exit(0)
if os.environ.get('FAKE_FAIL'):
    sys.exit(7)
assert args[-3:] == ['-boot_image', 'any', 'replay'] or args[-4:] == ['-boot_image', 'any', 'replay', '-commit']
assert args[:4] == ['-compliance', 'no_emul_toc', '-hfsplus', 'on']
if os.environ.get('FAKE_RACE'):
    pathlib.Path(os.environ['FAKE_RACE']).write_bytes(b'competing writer')
pathlib.Path(args[args.index('-outdev') + 1]).write_bytes(b'FAKE IMAGE, NOT BOOTABLE')
''')
        tool.chmod(0o700)

    def run_build(self, extra_env=None, iso_sha=None):
        env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}")
        env.update(extra_env or {})
        return subprocess.run([
            "bash", str(REPO / "scripts/build-prototype-iso.sh"),
            "--iso", str(self.iso), "--iso-sha256", iso_sha or hashlib.sha256(self.iso.read_bytes()).hexdigest(),
            "--stage3", str(self.stage), "--stage3-sha256", hashlib.sha256(self.stage.read_bytes()).hexdigest(),
            "--out", str(self.out),
        ], env=env, text=True, capture_output=True)

    def test_payload_and_provenance(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = next(self.root.glob('.g15forge-build-*/G15FORGE'))
        checked = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=payload, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual((payload / "stage3-amd64-systemd.tar.xz").read_bytes(), self.stage.read_bytes())
        self.assertIn("BOOT_STATUS=NOT_TESTED", Path(str(self.out) + ".provenance.txt").read_text())
        self.assertEqual(subprocess.run(["sha256sum", "-c", str(self.out) + ".sha256"], capture_output=True).returncode, 0)

    def test_existing_iso_preserved(self):
        self.out.write_bytes(b"preserved")
        self.assertNotEqual(self.run_build().returncode, 0)
        self.assertEqual(self.out.read_bytes(), b"preserved")

    def test_existing_sidecars_preserved(self):
        for suffix in (".sha256", ".provenance.txt"):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(self.out) + suffix)
                sidecar.write_bytes(b"preserved")
                self.assertNotEqual(self.run_build().returncode, 0)
                self.assertEqual(sidecar.read_bytes(), b"preserved")
                self.assertFalse(self.out.exists())
                sidecar.unlink()

    def test_dangling_sidecar_symlink_preserved(self):
        sidecar = Path(str(self.out) + ".sha256")
        sidecar.symlink_to(self.root / "absent")
        self.assertNotEqual(self.run_build().returncode, 0)
        self.assertTrue(sidecar.is_symlink())
        self.assertFalse(self.out.exists())

    def test_bad_hash_no_output(self):
        self.assertNotEqual(self.run_build(iso_sha="0" * 64).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_tool_failure_no_output(self):
        self.assertNotEqual(self.run_build({"FAKE_FAIL": "1"}).returncode, 0)
        self.assertFalse(self.out.exists())

    def test_competing_iso_writer_preserved(self):
        self.assertNotEqual(self.run_build({"FAKE_RACE": str(self.out)}).returncode, 0)
        self.assertEqual(self.out.read_bytes(), b"competing writer")

    def test_competing_manifest_writer_preserved(self):
        sidecar = Path(str(self.out) + ".sha256")
        self.assertNotEqual(self.run_build({"FAKE_RACE": str(sidecar)}).returncode, 0)
        self.assertEqual(sidecar.read_bytes(), b"competing writer")

    def test_guest_verifier_rejects_missing_payload(self):
        result = subprocess.run(["sh", str(REPO / "scripts/verify-live-payload.sh"), str(self.root / "absent")], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
