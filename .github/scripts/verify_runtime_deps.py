#!/usr/bin/env python3
"""Reject unapproved Python package versions or unexpected runtime packages."""

from importlib import metadata
from pathlib import Path
import re
import sys


PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9._+!-]*)")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(content):
    pinned = {}
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError(f"Line {number}: only exact name==version pins are permitted")
        name, version = normalize(match.group(1)), match.group(2)
        if name in pinned:
            raise ValueError(f"Line {number}: duplicate package {name}")
        pinned[name] = version
    if not pinned:
        raise ValueError("Empty dependency lock")
    return pinned


def check_versions(pinned, installed):
    missing = sorted(set(pinned) - set(installed))
    unapproved = sorted(set(installed) - set(pinned))
    wrong = sorted(
        f"{name}: expected {pinned[name]}, installed {installed[name]}"
        for name in set(pinned) & set(installed) if pinned[name] != installed[name]
    )
    problems = []
    if missing:
        problems.append("missing: " + ", ".join(missing))
    if unapproved:
        problems.append("not in requirements.txt: " + ", ".join(unapproved))
    if wrong:
        problems.append("wrong version: " + "; ".join(wrong))
    if problems:
        raise ValueError("; ".join(problems))


def runtime_packages():
    found = {}
    for dist in metadata.distributions():
        raw_name = dist.metadata.get("Name")
        if not raw_name:
            raise ValueError("Installed distribution without name")
        name = normalize(raw_name)
        if name in found:
            raise ValueError(f"Duplicate installed distribution: {name}")
        found[name] = dist.version
    return found


def main():
    try:
        locked = parse_lock(Path(sys.argv[1]).read_text(encoding="utf-8"))
        check_versions(locked, runtime_packages())
    except (OSError, ValueError, IndexError) as error:
        print(f"Python package lock FAILED: {error}", file=sys.stderr)
        return 1
    print(f"Python package lock OK: {len(locked)} exact runtime versions verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
