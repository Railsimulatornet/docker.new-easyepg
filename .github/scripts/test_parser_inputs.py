import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from parser_inputs import prepare


class ParserInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repository = self.root / "source"
        self.repository.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Offline test")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.repository), *arguments], text=True).strip()

    def commit(self, image="python:3.12-slim", json_version="4.2.0", extra=""):
        (self.repository / "Dockerfile.amd64").write_text(f"FROM {image}\n")
        (self.repository / "requirements.txt").write_text(
            f"# Complete fixture lock\nrequests==2.34.2\nxmltodict==1.0.4\nsimplejson=={json_version}\n" + extra)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_baseline_and_candidate_use_their_actual_python_and_pins(self):
        baseline = self.commit()
        candidate = self.commit("python:3.15-slim", "4.3.0", "urllib3==2.8.0\n")
        old = prepare(baseline, self.root / "baseline", self.repository)
        new = prepare(candidate, self.root / "candidate", self.repository)
        self.assertEqual(old["python_image"], "python:3.12-slim")
        self.assertEqual(new["python_image"], "python:3.15-slim")
        self.assertEqual(old["dependencies"]["simplejson"], "4.2.0")
        self.assertEqual(new["dependencies"]["simplejson"], "4.3.0")
        self.assertEqual(new["dependencies"]["urllib3"], "2.8.0")
        self.assertEqual((self.root / "candidate/requirements.txt").read_text(),
                         self.git("show", f"{candidate}:requirements.txt") + "\n")
        self.assertEqual(json.loads((self.root / "candidate/metadata.json").read_text())["revision"], candidate)

    def test_mutable_ref_is_rejected(self):
        self.commit()
        for revision in ("HEAD", "master", "a" * 39, "a" * 40 + "\n"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                prepare(revision, self.root / "output", self.repository)

    def test_unpinned_requirement_is_rejected(self):
        sha = self.commit(extra="urllib3>=2\n")
        with self.assertRaisesRegex(ValueError, "exact dependency pins"):
            prepare(sha, self.root / "output", self.repository)

    def test_duplicate_normalized_name_is_rejected(self):
        sha = self.commit(extra="SimpleJSON==4.3.0\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            prepare(sha, self.root / "output", self.repository)

    def test_unexpected_base_image_is_rejected(self):
        sha = self.commit("untrusted.example/python:latest")
        with self.assertRaisesRegex(ValueError, "official Python"):
            prepare(sha, self.root / "output", self.repository)


if __name__ == "__main__":
    unittest.main()
