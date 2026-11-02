"""Static and negative tests for the fail-closed runtime dependency lock."""

from pathlib import Path
import unittest

from verify_runtime_deps import check_versions, normalize, parse_lock


ROOT = Path(__file__).resolve().parents[2]
DIRECT = {
    "bottle", "requests", "urllib3", "certifi", "idna", "xmltodict",
    "beautifulsoup4", "simplejson", "cffi", "cheroot", "curl-cffi", "pytz",
}


class LockTests(unittest.TestCase):
    def test_repo_requirements_are_fully_pinned(self):
        locked = parse_lock((ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertTrue(DIRECT.issubset(locked))
        self.assertGreaterEqual(len(locked), len(DIRECT))

    def test_rejects_ranges_and_unpinned_versions(self):
        for content in ("requests>=2.34.2,<3", "requests~=2.34.2", "requests",
                        "-r other-file.txt", "requests==2.34.2; python_version>'3'"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_lock(content)

    def test_rejects_empty_or_duplicate_lock(self):
        for content in ("# comment only", "curl-cffi==0.16.3\ncurl_cffi==0.16.3"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_lock(content)

    def test_different_spellings_are_canonical(self):
        self.assertEqual(normalize("Charset_Normalizer"), "charset-normalizer")
        self.assertEqual(parse_lock("jaraco.functools==4.6.0")["jaraco-functools"], "4.6.0")

    def test_approved_snapshot_passes(self):
        check_versions({"a": "1.0", "b": "2.0"}, {"a": "1.0", "b": "2.0"})

    def test_missing_dependency_fails(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            check_versions({"a": "1.0", "b": "2.0"}, {"a": "1.0"})

    def test_unapproved_transitive_fails(self):
        with self.assertRaisesRegex(ValueError, "not in requirements"):
            check_versions({"a": "1.0"}, {"a": "1.0", "new-dependency": "2.0"})

    def test_version_drift_fails(self):
        with self.assertRaisesRegex(ValueError, "wrong version"):
            check_versions({"a": "1.0"}, {"a": "1.1"})


if __name__ == "__main__":
    unittest.main()
