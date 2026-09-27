"""Merge verified OCI archives locally, preserving image and attestation blobs."""
import contextlib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
EXPECTED = {"amd64": ("linux", "amd64", ""), "arm64": ("linux", "arm64", ""),
            "armv7": ("linux", "arm", "v7")}


def encode(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def platform(value):
    os_name, arch, variant = value.get("os"), value.get("architecture"), value.get("variant", "")
    if arch == "arm64" and variant == "v8":
        variant = ""
    return os_name, arch, variant


class Archive:
    def __init__(self, archive):
        self.tar = archive
        self.files = {}
        for member in archive.getmembers():
            if member.isdir():
                continue
            name = member.name.removeprefix("./")
            if not member.isfile() or name in self.files:
                raise ValueError("Non-regular or duplicate archive member")
            if name not in {"oci-layout", "index.json"} and not re.fullmatch(r"blobs/sha256/[a-f0-9]{64}", name):
                raise ValueError(f"Unexpected OCI archive member: {name}")
            self.files[name] = member
        if self.json_file("oci-layout").get("imageLayoutVersion") != "1.0.0":
            raise ValueError("Unsupported OCI layout")
        self.verified = set()
        self.required = set()

    def stream(self, name):
        return self.tar.extractfile(self.files[name])

    def json_file(self, name):
        if self.files[name].size > 16 * 1024 * 1024:
            raise ValueError("Oversized JSON document")
        with self.stream(name) as src:
            return json.load(src)

    def verify(self, desc):
        sha = desc.get("digest", "")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", sha):
            raise ValueError("Invalid blob digest")
        name = "blobs/sha256/" + sha[7:]
        if self.files[name].size != desc.get("size"):
            raise ValueError("Blob size mismatch")
        if name not in self.verified:
            h = hashlib.sha256()
            with self.stream(name) as src:
                while chunk := src.read(1024 * 1024):
                    h.update(chunk)
            if h.hexdigest() != sha[7:]:
                raise ValueError("Blob digest mismatch")
            self.verified.add(name)
        return name

    def flatten(self, descriptors, depth=0):
        if depth > 8 or not isinstance(descriptors, list) or not descriptors:
            raise ValueError("Invalid OCI manifest tree")
        leaves = []
        for desc in descriptors:
            name = self.verify(desc)
            obj = self.json_file(name)
            if obj.get("schemaVersion") != 2:
                raise ValueError("Invalid OCI manifest schema")
            media = desc.get("mediaType")
            if media == INDEX:
                leaves.extend(self.flatten(obj["manifests"], depth + 1))
            elif media == MANIFEST:
                self.required.add(name)
                self.required.add(self.verify(obj["config"]))
                for layer in obj["layers"]:
                    self.required.add(self.verify(layer))
                leaves.append((desc, obj))
            else:
                raise ValueError(f"Unsupported manifest type: {media}")
        return leaves


def merge(output, inputs):
    output = Path(output)
    if output.exists() or set(inputs) != set(EXPECTED):
        raise ValueError("New output directory and exactly three architectures required")
    with contextlib.ExitStack() as stack:
        archives, combined = [], []
        for arch, expected in EXPECTED.items():
            src = Archive(stack.enter_context(tarfile.open(inputs[arch], "r:*")))
            root = src.json_file("index.json")
            leaves = src.flatten(root["manifests"])
            runtime = [(d, m) for d, m in leaves if platform(d.get("platform", {})) == expected]
            if len(runtime) != 1:
                raise ValueError(f"Missing/duplicate runtime platform: {arch}")
            runnable, manifest = runtime[0]
            config = src.json_file(src.verify(manifest["config"]))
            if platform(config) != expected:
                raise ValueError("Image configuration disagrees with platform descriptor")
            attestations = [(d, m) for d, m in leaves if d != runnable]
            if not attestations:
                raise ValueError("Build attestations are missing")
            for desc, att in attestations:
                reference = desc.get("annotations", {}).get("vnd.docker.reference.digest")
                reference = reference or att.get("subject", {}).get("digest")
                if reference != runnable["digest"] or platform(desc.get("platform", {})) != ("unknown", "unknown", ""):
                    raise ValueError("Unexpected platform or unrelated attestation")
            combined.extend(d for d, _ in leaves)
            archives.append(src)
        if len({d["digest"] for d in combined}) != len(combined):
            raise ValueError("Duplicate platform/attestation descriptors")
        blobs = output / "blobs" / "sha256"
        blobs.mkdir(parents=True)
        for src in archives:
            for name in sorted(src.required):
                target = output / name
                if not target.exists():
                    with src.stream(name) as reader, target.open("xb") as writer:
                        shutil.copyfileobj(reader, writer, 1024 * 1024)
        content = encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": combined})
        sha = digest(content)
        (blobs / sha[7:]).write_bytes(content)
        (output / "oci-layout").write_bytes(encode({"imageLayoutVersion": "1.0.0"}))
        (output / "index.json").write_bytes(encode({"schemaVersion": 2, "manifests": [
            {"mediaType": INDEX, "digest": sha, "size": len(content),
             "annotations": {"org.opencontainers.image.ref.name": "verified"}}]}))
        print(f"Verified bundle: {sha}; runtime platforms: {len(EXPECTED)}; descriptors: {len(combined)}")
        return sha


if __name__ == "__main__":
    try:
        merge(sys.argv[1], dict(v.split("=", 1) for v in sys.argv[2:]))
    except (OSError, ValueError, KeyError, TypeError, IndexError, tarfile.TarError) as exc:
        print(f"Image bundle refused: {exc}", file=sys.stderr)
        sys.exit(1)
