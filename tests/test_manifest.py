import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("verify", Path(__file__).resolve().parents[1] / "scripts/verify_prototype_iso.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class ManifestValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="g15forge-manifest-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "payload").write_bytes(b"verified")
        self.sha = hashlib.sha256(b"verified").hexdigest()

    def manifest(self, content):
        (self.root / "SHA256SUMS").write_text(content)
        return verify.check_manifest(self.root, "SHA256SUMS")

    def test_valid(self):
        self.assertEqual(self.manifest(f"{self.sha}  payload\n"), {"payload"})

    def test_tampered(self):
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.manifest(f"{'0' * 64}  payload\n")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "empty manifest"):
            self.manifest("")

    def test_traversal(self):
        with self.assertRaisesRegex(ValueError, "unsafe manifest path"):
            self.manifest(f"{self.sha}  ../outside\n")

    def test_symlink(self):
        (self.root / "link").symlink_to(self.root / "payload")
        with self.assertRaisesRegex(ValueError, "unsafe manifest path"):
            self.manifest(f"{self.sha}  link\n")


if __name__ == "__main__":
    unittest.main()
