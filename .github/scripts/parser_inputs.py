"""Build parser-test inputs from immutable repository revisions, without duplicate pins."""
import json
from pathlib import Path
import re
import subprocess
import sys

DOCKERFILE = """ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --no-deps -r /tmp/requirements.txt \\
    && python -m pip check
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
"""


def prepare(revision, destination, repository="."):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Parser comparison requires an immutable full commit SHA")

    def read(path):
        return subprocess.check_output(
            ["git", "-C", str(repository), "show", f"{revision}:{path}"], text=True)

    dockerfile = read("Dockerfile.amd64")
    images = re.findall(r"^FROM\s+(\S+)\s*$", dockerfile, re.MULTILINE)
    if len(images) != 1 or not re.fullmatch(
            r"python:[A-Za-z0-9_.-]+(?:@sha256:[0-9a-f]{64})?", images[0]):
        raise ValueError("Expected one explicitly versioned official Python base image")
    requirements = read("requirements.txt")
    pins = {}
    for raw in requirements.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9.!+_-]*)", line)
        if not match:
            raise ValueError(f"Parser test requires exact dependency pins: {line!r}")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in pins:
            raise ValueError(f"Duplicate dependency pin: {name}")
        pins[name] = match[2]
    for name in ("requests", "xmltodict", "simplejson"):
        if name not in pins:
            raise ValueError(f"Missing parser dependency: {name}")

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    metadata = {"revision": revision, "python_image": images[0], "dependencies": pins}
    (destination / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (destination / "requirements.txt").write_text(requirements, encoding="utf-8")
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: parser_inputs.py COMMIT_SHA OUTPUT_DIRECTORY")
    print(prepare(sys.argv[1], sys.argv[2])["python_image"])
