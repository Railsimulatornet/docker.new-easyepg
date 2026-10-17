#!/usr/bin/env python3
"""Staged EasyEPG application updater. Never replaces persistent EPG data."""
import argparse
import ast
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

STATE_NAME = ".easyepg-updater"
ROOT_FILES = {
    "LICENSE", "README.md", "addon.py", "addon.xml", "fanart.jpg",
    "icon.png", "main.py", "requirements.txt",
}
SOURCE_AREAS = ("resources/lib/", "resources/data/css/", "resources/data/html/",
                "resources/data/img/", "resources/data/js/", "resources/data/json/")
DATABASE = "resources/data/db/channels.db"
KNOWN_PACKAGES = {
    "bottle", "beautifulsoup4", "cheroot", "curl-cffi", "pytz",
    "requests", "xmltodict",
}
MAX_FILES = 500
MAX_BYTES = 100_000_000
MAX_RECENT_SECONDS = 180


class UpdateError(Exception):
    pass


def log(message):
    print("EasyEPG update: " + str(message), flush=True)


def check_name(value, label):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value)
            or value.startswith(".") or ".." in value):
        raise UpdateError("Invalid " + label)
    return value


def check_branch(value):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value)
            or ".." in value or "//" in value
            or value.endswith(("/", "."))):
        raise UpdateError("Invalid branch name")
    return value


def managed_file(path):
    if path in ROOT_FILES:
        return True
    if re.fullmatch(r"screenshot-[0-9]+\.jpg", path):
        return True
    if path.startswith("resources/lib/"):
        return path.endswith(".py")
    return any(path.startswith(prefix) for prefix in SOURCE_AREAS[1:])


def manifest_for(source):
    """Only allow known program paths; treat the included database as user data."""
    files = []
    total = 0
    for directory, dirs, entries in os.walk(source, followlinks=False):
        base = Path(directory)
        if ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + entries:
            path = base / name
            if path.is_symlink():
                raise UpdateError("Symlink in upstream checkout: " + str(path))
        for name in entries:
            path = base / name
            rel = path.relative_to(source).as_posix()
            if rel == DATABASE:
                continue
            if not path.is_file() or not managed_file(rel):
                raise UpdateError("Unreviewed upstream file: " + rel)
            total += path.stat().st_size
            files.append(rel)
    if not 2 <= len(files) <= MAX_FILES or total > MAX_BYTES:
        raise UpdateError("Unexpected upstream size or file count")
    if "main.py" not in files or "requirements.txt" not in files:
        raise UpdateError("Upstream does not provide the required entrypoint")
    if not (source / DATABASE).is_file():
        raise UpdateError("Upstream channel database missing")
    return sorted(files)


def validate_requirements(source):
    requirements = (source / "requirements.txt").read_text(encoding="utf-8")
    found = set()
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", line):
            raise UpdateError("Upstream requirements changed; image review required")
        name = line.lower().replace("_", "-").replace(".", "-")
        if name not in KNOWN_PACKAGES:
            raise UpdateError("New upstream dependency needs an image update: " + name)
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise UpdateError("Missing container dependency: " + name) from error
        found.add(name)
    if not found:
        raise UpdateError("Upstream requirements are empty")


def validate_source(source, files, runtime=True):
    for rel in files:
        if rel.endswith(".py"):
            path = source / rel
            try:
                ast.parse(path.read_bytes(), filename=str(path))
            except (SyntaxError, ValueError) as error:
                raise UpdateError("Invalid Python code: " + rel) from error
        if rel.startswith("resources/data/json/"):
            try:
                json.loads((source / rel).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeError) as error:
                raise UpdateError("Invalid provider JSON: " + rel) from error

    try:
        with sqlite3.connect("file:" + str(source / DATABASE) +
                             "?mode=ro&immutable=1", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise UpdateError("Bundled channel database failed integrity check")
    except sqlite3.DatabaseError as error:
        raise UpdateError("Bundled channel database is invalid") from error

    if runtime:
        validate_requirements(source)
        check = (
            "import importlib, sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "from resources.lib import db, epg, web; "
            "[importlib.import_module('resources.lib.providers.' + x) "
            "for x in ('canal','cpsol','tkmde','tvmat','tvspf','zttch')]; "
            "print('EasyEPG staged imports OK')"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", check, str(source)],
            cwd=source, text=True, capture_output=True, timeout=45,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            raise UpdateError("New EasyEPG code failed runtime imports: " +
                              result.stderr.strip()[-650:])


def validate_local_channel_db(path):
    """Refuse incompatible or damaged local SQLite databases before changing code."""
    if not path.is_file() or path.is_symlink():
        raise UpdateError("Local channel database is not a regular file")
    required = {
        "channel_id", "channel_name", "provider_name",
        "provider_id", "country", "config",
    }
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise UpdateError("Existing channel database failed integrity check")
            columns = {column[1] for column in db.execute("PRAGMA table_info(channels)")}
            if not required.issubset(columns):
                raise UpdateError("Existing channel database schema needs review")
    except sqlite3.DatabaseError as error:
        raise UpdateError("Existing channel database is invalid") from error



class Updater:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise UpdateError("Invalid /easyepg mount")
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = self.root / STATE_NAME
        if self.state.is_symlink() or (self.state.exists() and not self.state.is_dir()):
            raise UpdateError("Invalid updater state")
        self.state.mkdir(exist_ok=True)

    def target(self, rel):
        if (not rel or rel.startswith("/") or
                any(x in ("", ".", "..") for x in rel.split("/"))):
            raise UpdateError("Unsafe relative path")
        target = self.root
        for part in rel.split("/"):
            target = target / part
            if target.is_symlink():
                raise UpdateError("Symlink in installed source: " + rel)
        return target

    def info(self):
        path = self.state / "current.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write_json(self, path, obj):
        tmp = path.with_name(".tmp-" + uuid4().hex)
        try:
            with tmp.open("w", encoding="utf-8") as file:
                json.dump(obj, file, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def install(self, source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        self.target(target.relative_to(self.root).as_posix())
        temp = target.with_name(".easyepg-temp-" + uuid4().hex)
        try:
            shutil.copy2(source, temp, follow_symlinks=False)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def restore(self, directory):
        journal = json.loads((directory / "journal.json").read_text(encoding="utf-8"))
        existing = set(journal["existing"])
        for rel in journal["touched"]:
            path = self.target(rel)
            if rel in existing:
                backup = directory / "backup" / rel
                if not backup.is_file() or backup.is_symlink():
                    raise UpdateError("Rollback backup incomplete: " + rel)
                self.install(backup, path)
            elif path.is_file():
                path.unlink()
        current = self.state / "current.json"
        if journal["previous_current"] is None:
            current.unlink(missing_ok=True)
        else:
            self.write_json(current, journal["previous_current"])
        for rel in sorted(journal["touched"], key=lambda s: s.count("/"), reverse=True):
            p = self.target(rel).parent
            while p != self.root and p != self.state:
                try:
                    p.rmdir()
                except OSError:
                    break
                p = p.parent

    def recover(self):
        pending = self.state / "transaction"
        if pending.is_symlink():
            raise UpdateError("Invalid transaction path")
        if pending.is_dir():
            log("Interrupted source update found; restoring previous code")
            self.restore(pending)
            shutil.rmtree(pending)
        for candidate in self.state.iterdir():
            if candidate.name.startswith((".preparing-", ".retired-")):
                if candidate.is_symlink():
                    raise UpdateError("Unexpected state symlink")
                if candidate.is_dir():
                    shutil.rmtree(candidate)

    def apply(self, source, revision, runtime=True):
        files = manifest_for(source)
        validate_source(source, files, runtime=runtime)
        current = self.info()
        if current and current.get("revision") == revision and (self.root / "main.py").is_file():
            log("Application already at " + revision[:12])
            return False
        rejected = self.state / "rejected.json"
        if rejected.is_file() and json.loads(rejected.read_text()).get("revision") == revision:
            log("Previously failed code " + revision[:12] + " will not be installed again")
            return False

        old_managed = set(current.get("files", [])) if current else set()
        removed = {f for f in old_managed - set(files) if managed_file(f)}
        db_path = self.target(DATABASE)
        db_is_new = not db_path.exists()
        if not db_is_new:
            validate_local_channel_db(db_path)
        touched = sorted(set(files) | removed | ({DATABASE} if db_is_new else set()))
        for rel in touched:
            self.target(rel)

        preparing = self.state / (".preparing-" + uuid4().hex)
        preparing.mkdir()
        existing = []
        try:
            for rel in touched:
                path = self.target(rel)
                if path.exists():
                    if not path.is_file():
                        raise UpdateError("Not a regular source file: " + rel)
                    backup = preparing / "backup" / rel
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, backup)
                    existing.append(rel)
            journal = {
                "touched": touched,
                "existing": existing,
                "previous_current": current,
                "revision": revision,
                "prior_main": (self.root / "main.py").is_file(),
            }
            self.write_json(preparing / "journal.json", journal)
            txn = self.state / "transaction"
            if txn.exists():
                raise UpdateError("Unresolved transaction present")
            os.replace(preparing, txn)
            try:
                for rel in files:
                    self.install(source / rel, self.target(rel))
                for rel in sorted(removed):
                    path = self.target(rel)
                    if path.is_file():
                        path.unlink()
                if db_is_new:
                    self.install(source / DATABASE, self.target(DATABASE))
                self.write_json(self.state / "current.json",
                                {"revision": revision, "files": files,
                                 "updated_at": int(time.time())})
                previous = self.state / "previous"
                if previous.is_dir():
                    old = self.state / (".retired-" + uuid4().hex)
                    os.replace(previous, old)
                    shutil.rmtree(old)
                os.replace(txn, previous)
            except Exception:
                self.recover()
                raise
            rejected.unlink(missing_ok=True)
            log("Installed validated source " + revision[:12] +
                " (settings, XML and existing channels.db preserved)")
            return True
        finally:
            if preparing.is_dir():
                shutil.rmtree(preparing)

    def rollback_recent(self):
        previous = self.state / "previous"
        current = self.info()
        if not current or not previous.is_dir():
            return False
        if time.time() - current.get("updated_at", 0) > MAX_RECENT_SECONDS:
            return False
        journal = json.loads((previous / "journal.json").read_text(encoding="utf-8"))
        if not journal.get("prior_main"):
            return False
        self.restore(previous)
        self.write_json(self.state / "rejected.json",
                        {"revision": current["revision"], "failed_at": int(time.time())})
        shutil.rmtree(previous)
        log("Restored previous source after failed startup; data left unchanged")
        return True


def fetch_source(directory, repo, branch):
    repo = check_name(repo, "repository")
    branch = check_branch(branch)
    url = "https://github.com/sunsettrack4/" + repo + ".git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--single-branch",
                        "--branch", branch, url, str(directory)],
                       check=True, capture_output=True, text=True, timeout=120, env=env)
        rev = subprocess.check_output(["git", "-C", str(directory),
                                       "rev-parse", "HEAD"], text=True).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise UpdateError("Could not download EasyEPG source") from error
    return rev


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("recover", "update", "rollback-recent"))
    parser.add_argument("--root", default="/easyepg")
    args = parser.parse_args(argv)
    try:
        updater = Updater(args.root)
        with (updater.state / ".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            updater.recover()
            if args.action == "recover":
                return 0
            if args.action == "rollback-recent":
                return 0 if updater.rollback_recent() else 1
            with tempfile.TemporaryDirectory(prefix="easyepg-upstream-") as tmp:
                stage = Path(tmp) / "source"
                try:
                    revision = fetch_source(
                        stage, os.getenv("REPO", "script.service.easyepg-lite"),
                        os.getenv("BRANCH", "main"))
                    updater.apply(stage, revision)
                except (UpdateError, OSError, subprocess.SubprocessError) as error:
                    if (updater.root / "main.py").is_file():
                        log("WARNING: " + str(error) + "; keeping existing application")
                        return 0
                    raise
        return 0
    except (UpdateError, OSError, subprocess.SubprocessError) as error:
        log("ERROR: " + str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
