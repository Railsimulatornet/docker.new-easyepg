"""Offline regression tests for staged EasyEPG application updates."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "root/easyepg.safe_update.py"
spec = importlib.util.spec_from_file_location("easyepg_safe_update", SCRIPT)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def create_db(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE channels (channel_id TEXT, channel_name TEXT, provider_name TEXT, provider_id TEXT, country TEXT, config TEXT)")
        db.execute("INSERT INTO channels (channel_id) VALUES (?)", (value,))


def read_db(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT channel_id FROM channels").fetchone()[0]


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root / "live"
        self.root.mkdir()
        self.source = root / "candidate"
        self.source.mkdir()
        self.make_source()

    def make_source(self):
        for rel, content in {
            "main.py": 'print("new")\n',
            "requirements.txt": "bottle\n",
            "resources/lib/db.py": "x = 42\n",
            "resources/data/json/providers.json": '{"provider":"test"}',
        }.items():
            path = self.source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        create_db(self.source / updater.DATABASE, "upstream")

    def populate_old(self):
        (self.root / "main.py").write_text('print("old")\n')
        (self.root / "settings.json").write_text('{"secret":"leave alone"}')
        (self.root / "cache").mkdir()
        (self.root / "cache/cache.json").write_text('{"cached":true}')
        (self.root / "xml").mkdir()
        (self.root / "xml/epg.xml").write_text("<tv/>\n")
        create_db(self.root / updater.DATABASE, "user-local")

    def data_unchanged(self):
        self.assertEqual(read_db(self.root / updater.DATABASE), "user-local")
        self.assertEqual((self.root / "settings.json").read_text(),
                         '{"secret":"leave alone"}')
        self.assertEqual((self.root / "cache/cache.json").read_text(),
                         '{"cached":true}')
        self.assertEqual((self.root / "xml/epg.xml").read_text(), "<tv/>\n")

    def test_update_preserves_database_settings_cache_and_xml(self):
        self.populate_old()
        u = updater.Updater(self.root)
        self.assertTrue(u.apply(self.source, "revision-a", runtime=False))
        self.assertEqual((self.root / "main.py").read_text(), 'print("new")\n')
        self.data_unchanged()
        self.assertTrue((u.state / "previous/journal.json").is_file())
        self.assertFalse((u.state / "transaction").exists())

    def test_single_rollback_restores_old_source_without_data_loss(self):
        self.populate_old()
        u = updater.Updater(self.root)
        u.apply(self.source, "revision-a", runtime=False)
        self.assertTrue(u.rollback_recent())
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        self.assertFalse((self.root / "resources/lib/db.py").exists())
        self.data_unchanged()
        self.assertFalse((u.state / "previous").exists())
        self.assertFalse(u.apply(self.source, "revision-a", runtime=False))
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')

    def test_fresh_install_seeds_new_database(self):
        u = updater.Updater(self.root)
        self.assertTrue(u.apply(self.source, "revision-a", runtime=False))
        self.assertEqual(read_db(self.root / updater.DATABASE), "upstream")
        self.assertTrue((self.root / "main.py").is_file())

    def test_invalid_source_never_changes_live_files(self):
        self.populate_old()
        (self.source / "main.py").write_text("def broken(:\n")
        u = updater.Updater(self.root)
        with self.assertRaises(updater.UpdateError):
            u.apply(self.source, "revision-a", runtime=False)
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        self.data_unchanged()

    def test_mid_copy_failure_restores_every_original_file(self):
        self.populate_old()
        u = updater.Updater(self.root)
        original = u.install
        fail_once = {"count": 0}

        def flaky(source, destination):
            original(source, destination)
            fail_once["count"] += 1
            if fail_once["count"] == 2:
                raise OSError("Simulated interruption")

        with patch.object(u, "install", side_effect=flaky):
            with self.assertRaises(OSError):
                u.apply(self.source, "revision-a", runtime=False)
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        self.data_unchanged()
        self.assertFalse((u.state / "transaction").exists())


    def test_rejects_incompatible_local_database_schema(self):
        self.populate_old()
        db = self.root / updater.DATABASE
        db.unlink()
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE channels (id TEXT)")
            con.execute("INSERT INTO channels VALUES ('untouched')")
        u = updater.Updater(self.root)
        with self.assertRaisesRegex(updater.UpdateError, "schema needs review"):
            u.apply(self.source, "revision-a", runtime=False)
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        with sqlite3.connect(db) as con:
            self.assertEqual(con.execute("SELECT id FROM channels").fetchone()[0],
                             "untouched")
        self.assertFalse((u.state / "transaction").exists())

    def test_rejects_corrupt_local_database_before_updating(self):
        self.populate_old()
        db = self.root / updater.DATABASE
        db.write_bytes(b"damaged sqlite database")
        u = updater.Updater(self.root)
        with self.assertRaisesRegex(updater.UpdateError, "database is invalid"):
            u.apply(self.source, "revision-a", runtime=False)
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        self.assertEqual(db.read_bytes(), b"damaged sqlite database")

    def test_recover_after_abrupt_interruption(self):
        # Simulate SIGKILL: BaseException bypasses the ordinary failure handler,
        # leaving the journal for the next container start to recover.
        self.populate_old()
        u = updater.Updater(self.root)
        original = u.install
        count = {"n": 0}

        def interrupted(source, destination):
            original(source, destination)
            count["n"] += 1
            if count["n"] == 2:
                raise KeyboardInterrupt("Simulated process kill")

        with patch.object(u, "install", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                u.apply(self.source, "revision-a", runtime=False)

        self.assertTrue((u.state / "transaction").is_dir())
        u.recover()
        self.assertEqual((self.root / "main.py").read_text(), 'print("old")\n')
        self.data_unchanged()
        self.assertFalse((u.state / "transaction").exists())

    def test_rejects_unreviewed_upstream_paths(self):
        (self.source / "unsafe.sh").write_text("echo unexpected")
        with self.assertRaises(updater.UpdateError):
            updater.manifest_for(self.source)

    def test_symlink_is_refused(self):
        outside = Path(self.tmp.name) / "outside"
        outside.write_text("safe")
        (self.root / "main.py").symlink_to(outside)
        u = updater.Updater(self.root)
        with self.assertRaises(updater.UpdateError):
            u.apply(self.source, "revision-a", runtime=False)
        self.assertEqual(outside.read_text(), "safe")

    def test_requirements_changes_fail_closed(self):
        (self.source / "requirements.txt").write_text("unknown-package\n")
        with patch.object(updater.importlib.metadata, "version", return_value="1.0"):
            with self.assertRaises(updater.UpdateError):
                updater.validate_requirements(self.source)

    def test_no_multiple_rollback_copies_or_perpetual_rewrite(self):
        self.populate_old()
        u = updater.Updater(self.root)
        self.assertTrue(u.apply(self.source, "revision-a", runtime=False))
        self.assertFalse(u.apply(self.source, "revision-a", runtime=False))
        (self.source / "main.py").write_text('print("newer")\n')
        self.assertTrue(u.apply(self.source, "revision-b", runtime=False))
        self.assertEqual((self.root / "main.py").read_text(), 'print("newer")\n')
        self.assertEqual(len(list(u.state.glob("previous"))), 1)
        self.assertEqual(len(list(u.state.glob(".retired-*"))), 0)

    def test_rollback_expires_after_startup_window(self):
        self.populate_old()
        u = updater.Updater(self.root)
        u.apply(self.source, "revision-a", runtime=False)
        current = u.info()
        current["updated_at"] = int(time.time()) - 500
        u.write_json(u.state / "current.json", current)
        self.assertFalse(u.rollback_recent())
        self.assertEqual((self.root / "main.py").read_text(), 'print("new")\n')


if __name__ == "__main__":
    unittest.main()
