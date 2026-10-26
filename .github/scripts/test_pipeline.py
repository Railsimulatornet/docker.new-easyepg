import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from build_metadata import main as build_metadata_main, metadata
from check_scan import check
from image_bundle import encode, digest, merge, INDEX, MANIFEST, EXPECTED

BASE = Path(__file__).parent


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(GITHUB_RUN_NUMBER="126", GITHUB_RUN_ATTEMPT="1",
                        GITHUB_REPOSITORY="Railsimulatornet/docker.new-easyepg",
                        GITHUB_REF="refs/heads/master", GITHUB_EVENT_NAME="push")

    def value(self, event="push", files=(), inputs=None, **env):
        return metadata(self.env | {"GITHUB_EVENT_NAME": event} | env, {"inputs": inputs or {}}, files)

    def test_pull_request_never_publishes(self):
        self.assertEqual(self.value("pull_request", ["Dockerfile.amd64"])["publish"], "false")

    def test_workflow_change_only_does_not_publish(self):
        self.assertEqual(self.value(files=[".github/workflows/dockerhub.yml"])["publish"], "false")

    def test_runtime_change_publishes(self):
        for f in ("Dockerfile.arm32v7", "requirements.txt", "root/entrypoint"):
            self.assertEqual(self.value(files=[f])["publish"], "true")

    def test_fork_does_not_publish(self):
        self.assertEqual(self.value("schedule", GITHUB_REPOSITORY="someone/fork")["publish"], "false")

    def test_feature_branch_does_not_publish(self):
        self.assertEqual(self.value("workflow_dispatch", inputs={"publish": "true"}, GITHUB_REF="refs/heads/test")["publish"], "false")

    def test_scheduled_publishes(self):
        self.assertEqual(self.value("schedule")["publish"], "true")

    def test_manual_defaults_to_test_only(self):
        self.assertEqual(self.value("workflow_dispatch")["publish"], "false")

    def test_manual_opt_in(self):
        self.assertEqual(self.value("workflow_dispatch", inputs={"publish": "true"})["publish"], "true")

    def test_pinned_dispatch_publishes_only_exact_commit(self):
        expected = "a" * 40
        inputs = {"publish": "true", "expected_sha": expected}
        self.assertEqual(self.value("workflow_dispatch", inputs=inputs,
                                    GITHUB_SHA=expected)["publish"], "true")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.value("workflow_dispatch", inputs=inputs, GITHUB_SHA="b" * 40)

    def test_invalid_dispatch_commit_rejected(self):
        for invalid in ("bad-sha", "A" * 40, "a" * 39, 123):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Invalid expected"):
                self.value("workflow_dispatch",
                           inputs={"publish": "true", "expected_sha": invalid},
                           GITHUB_SHA="a" * 40)

    def test_post_merge_wiring_keeps_explicit_dispatch_and_pin(self):
        automerge = (BASE.parent / "workflows/dependabot-automerge.yml").read_text()
        build = (BASE.parent / "workflows/dockerhub.yml").read_text()
        self.assertIn("gh workflow run dockerhub.yml", automerge)
        self.assertIn('-f expected_sha="$MERGE_SHA"', automerge)
        self.assertIn("      expected_sha:", build)

    def test_rerun_gets_new_build_tag(self):
        a, b = self.value(), self.value(GITHUB_RUN_ATTEMPT="2")
        self.assertRegex(a["build_tag"], r"^\d{8}-build\.126\.1$")
        self.assertNotEqual(a["build_tag"], b["build_tag"])
        self.assertRegex(a["date_tag"], r"^\d{8}$")

    def test_invalid_run_is_rejected(self):
        with self.assertRaises(ValueError):
            self.value(GITHUB_RUN_NUMBER="../bad")

    def test_main_writes_only_validated_outputs_without_logging(self):
        marker = "sensitive-canary-never-log"
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            output = Path(tmp) / "github-output"
            event.write_text(json.dumps({"inputs": {"publish": "true", "secret": marker}}))
            env = self.env | {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_OUTPUT": str(output),
                "DOCKERHUB_TOKEN": marker,
            }
            with patch.dict(os.environ, env, clear=True):
                with patch("sys.stdout", new_callable=io.StringIO) as logged:
                    build_metadata_main()
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(logged.getvalue(), "")
            self.assertEqual(len(lines), 3)
            self.assertRegex(lines[0], r"^build_tag=[0-9]{8}-build\.126\.1$")
            self.assertRegex(lines[1], r"^date_tag=[0-9]{8}$")
            self.assertEqual(lines[2], "publish=true")
            self.assertNotIn(marker, output.read_text(encoding="utf-8"))

    def test_main_rejects_mismatched_dispatch_commit_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            output = Path(tmp) / "github-output"
            event.write_text(json.dumps({"inputs": {"publish": "true", "expected_sha": "a" * 40}}))
            env = self.env | {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_OUTPUT": str(output),
                "GITHUB_SHA": "b" * 40,
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, "differs"):
                    build_metadata_main()
            self.assertFalse(output.exists())

    def test_main_rejects_untrusted_run_number_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            output = Path(tmp) / "github-output"
            event.write_text(json.dumps({"inputs": {"publish": True}}))
            env = self.env | {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_OUTPUT": str(output),
                "GITHUB_RUN_NUMBER": "126\nDOCKERHUB_TOKEN=secret",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    build_metadata_main()
            self.assertFalse(output.exists())


class ScanReportTests(unittest.TestCase):
    def setUp(self):
        self.report = {"SchemaVersion": 2, "Metadata": {"OS": {"Family": "debian", "Name": "13"}},
                       "Results": [{"Class": "os-pkgs", "Vulnerabilities": []}]}

    def test_clean(self):
        self.assertEqual(check(self.report), (0, 0))

    def test_unfixed_visible_not_blocking(self):
        self.report["Results"][0]["Vulnerabilities"] = [{"Severity": "HIGH", "FixedVersion": ""}]
        self.assertEqual(check(self.report), (1, 0))

    def test_fixed_high_and_critical_block(self):
        self.report["Results"].append({"Class": "lang-pkgs", "Vulnerabilities": [
            {"Severity": "HIGH", "FixedVersion": "2"}, {"Severity": "CRITICAL", "FixedVersion": "3"}]})
        self.assertEqual(check(self.report), (2, 2))

    def test_medium_is_outside_gate(self):
        self.report["Results"][0]["Vulnerabilities"] = [{"Severity": "MEDIUM", "FixedVersion": "2"}]
        self.assertEqual(check(self.report), (0, 0))

    def test_no_report(self):
        with self.assertRaises(ValueError): check({})

    def test_unknown_os(self):
        self.report["Metadata"]["OS"] = {}
        with self.assertRaises(ValueError): check(self.report)

    def test_eol_blocks(self):
        self.report["Metadata"]["OS"]["EOSL"] = True
        with self.assertRaises(ValueError): check(self.report)

    def test_missing_os_results(self):
        self.report["Results"] = [{"Class": "lang-pkgs"}]
        with self.assertRaises(ValueError): check(self.report)

    def test_malformed_vulnerability_blocks(self):
        self.report["Results"][0]["Vulnerabilities"] = ["invalid"]
        with self.assertRaises(ValueError): check(self.report)


def fixture_files(arch, *, attest=True, wrong_config=False, bad_reference=False):
    files = {}
    def blob(obj, media):
        data = encode(obj)
        sha = digest(data)
        files["blobs/sha256/" + sha[7:]] = data
        return {"mediaType": media, "digest": sha, "size": len(data)}
    os_name, cpu, variant = EXPECTED[arch]
    plat = dict(os=os_name, architecture=cpu)
    if variant: plat["variant"] = variant
    config = blob(plat if not wrong_config else {"os": "windows", "architecture": "amd64"}, "application/vnd.oci.image.config.v1+json")
    runtime = blob({"schemaVersion": 2, "mediaType": MANIFEST, "config": config, "layers": []}, MANIFEST)
    runtime["platform"] = plat
    leaves = [runtime]
    if attest:
        ac = blob({}, "application/vnd.oci.image.config.v1+json")
        layer = blob({"subject": arch}, "application/vnd.in-toto+json")
        a = blob({"schemaVersion": 2, "mediaType": MANIFEST, "config": ac, "layers": [layer]}, MANIFEST)
        a["platform"] = {"os": "unknown", "architecture": "unknown"}
        a["annotations"] = {"vnd.docker.reference.digest": "sha256:" + "f" * 64 if bad_reference else runtime["digest"],
                            "vnd.docker.reference.type": "attestation-manifest"}
        leaves.append(a)
    inner = blob({"schemaVersion": 2, "mediaType": INDEX, "manifests": leaves}, INDEX)
    files["index.json"] = encode({"schemaVersion": 2, "manifests": [inner]})
    files["oci-layout"] = encode({"imageLayoutVersion": "1.0.0"})
    return files


def write_tar(path, files):
    with tarfile.open(path, "w") as out:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = {}
        for arch in EXPECTED:
            self.inputs[arch] = self.root / (arch + ".tar")
            write_tar(self.inputs[arch], fixture_files(arch))
        self.output = self.root / "bundle"

    def change(self, arch="amd64", **kw):
        write_tar(self.inputs[arch], fixture_files(arch, **kw))

    def test_all_platforms_and_attestations_preserved(self):
        sha = merge(self.output, self.inputs)
        inner = json.loads((self.output / "blobs/sha256" / sha[7:]).read_text())
        self.assertEqual(len(inner["manifests"]), 6)
        for path in (self.output / "blobs/sha256").iterdir():
            self.assertEqual(digest(path.read_bytes())[7:], path.name)
        self.assertEqual(json.loads((self.output / "index.json").read_text())["manifests"][0]["digest"], sha)

    def test_missing_architecture(self):
        del self.inputs["armv7"]
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_wrong_architecture(self):
        self.inputs["armv7"] = self.inputs["amd64"]
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_wrong_config(self):
        self.change(wrong_config=True)
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_missing_attestation(self):
        self.change(attest=False)
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_unrelated_attestation(self):
        self.change(bad_reference=True)
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_corrupt_blob(self):
        files = fixture_files("amd64")
        name = next(n for n in files if n.startswith("blobs/"))
        files[name] = b"x" * len(files[name])
        write_tar(self.inputs["amd64"], files)
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_unknown_archive_member(self):
        files = fixture_files("amd64") | {"../unexpected": b"x"}
        write_tar(self.inputs["amd64"], files)
        with self.assertRaises(ValueError): merge(self.output, self.inputs)
        self.assertFalse(self.output.exists())

    def test_existing_output_not_replaced(self):
        self.output.mkdir()
        with self.assertRaises(ValueError): merge(self.output, self.inputs)

    def test_repeated_merge_has_same_manifest(self):
        a = merge(self.output, self.inputs)
        b = merge(self.root / "second", self.inputs)
        self.assertEqual(a, b)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = self.root / "calls"
        skopeo = self.root / "skopeo"
        skopeo.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args=sys.argv[1:]
scenario=os.environ.get("CASE", "clean")
if args[0] == "login": sys.stdin.read()
elif args[0] == "manifest-digest": print(Path(args[1]).read_text().strip())
elif args[0] == "copy":
    with open(os.environ["CALLS"], "a") as f: print(args[-1], file=f)
    if scenario == "transfer-fails": sys.exit(1)
elif args[0] == "inspect":
    target=args[-1]
    if target.startswith("oci:"): print("sha256:expected")
    elif Path(os.environ["CALLS"]).exists() and target in Path(os.environ["CALLS"]).read_text():
        print("sha256:corrupt" if scenario == "corrupt" else "sha256:expected")
    elif target.endswith(":27092026") and scenario == "date-exists": print("sha256:old-date")
    elif scenario == "build-conflict": print("sha256:different")
    elif scenario == "registry-error": print("unauthorized", file=sys.stderr); sys.exit(1)
    else: print("manifest unknown", file=sys.stderr); sys.exit(1)
else: sys.exit(2)
''')
        skopeo.chmod(0o755)

    def run_case(self, scenario):
        env = os.environ | {"PATH": str(self.root) + ":" + os.environ["PATH"], "CASE": scenario,
                             "CALLS": str(self.calls), "DOCKERHUB_USERNAME": "fixture", "DOCKERHUB_TOKEN": "fixture"}
        result = subprocess.run(["bash", str(BASE / "publish-image.sh"), str(self.root),
                                 "20260927-build.126.1", "27092026"], env=env, capture_output=True, text=True)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        return result, calls

    def test_latest_is_last(self):
        result, calls = self.run_case("clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c.split(":")[-1] for c in calls], ["20260927-build.126.1", "27092026", "latest"])

    def test_existing_date_is_kept(self):
        result, calls = self.run_case("date-exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(c.endswith(":27092026") for c in calls))

    def test_fixed_build_conflict_blocks_all_writes(self):
        result, calls = self.run_case("build-conflict")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_registry_error_is_not_treated_as_missing(self):
        result, calls = self.run_case("registry-error")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_failed_transfer_blocks_latest(self):
        result, calls = self.run_case("transfer-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.endswith(":latest") for c in calls))

    def test_digest_mismatch_blocks_latest(self):
        result, calls = self.run_case("corrupt")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.endswith(":latest") for c in calls))


if __name__ == "__main__": unittest.main()
