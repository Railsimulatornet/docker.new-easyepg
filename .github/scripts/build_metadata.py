"""Keep registry publication out of PRs and workflow-only maintenance pushes."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

REPOSITORY = "Railsimulatornet/docker.new-easyepg"
PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64", "armv7": "linux/arm/v7"}


def metadata(env, event, changed=()):
    run = env["GITHUB_RUN_NUMBER"]
    attempt = env["GITHUB_RUN_ATTEMPT"]
    if not all(re.fullmatch(r"[1-9][0-9]*", v) for v in (run, attempt)):
        raise ValueError("Invalid workflow run number/attempt")
    # Convert validated GitHub counters to integers so arbitrary environment
    # strings cannot appear in generated tags or workflow outputs.
    run, attempt = int(run), int(attempt)
    now = dt.datetime.now(ZoneInfo("Europe/Berlin"))
    trusted = (env.get("GITHUB_REPOSITORY") == REPOSITORY
               and env.get("GITHUB_REF") == "refs/heads/master")
    name = env.get("GITHUB_EVENT_NAME")
    if name == "workflow_dispatch":
        expected_sha = event.get("inputs", {}).get("expected_sha", "")
        if expected_sha not in ("", None):
            if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
                raise ValueError("Invalid expected post-merge commit SHA")
            if env.get("GITHUB_SHA") != expected_sha:
                raise ValueError("Dispatch SHA differs from verified merge commit")
    runtime_change = any(p in {"Dockerfile.amd64", "Dockerfile.arm64v8", "Dockerfile.arm32v7", "requirements.txt"}
                         or p.startswith("root/") for p in changed)
    requested = event.get("inputs", {}).get("publish", False) in (True, "true")
    publish = trusted and (name == "schedule" or name == "push" and runtime_change
                           or name == "workflow_dispatch" and requested)
    return {"build_tag": f"{now:%Y%m%d}-build.{run}.{attempt}",
            "date_tag": now.strftime("%d%m%Y"), "publish": str(publish).lower()}


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    changed = []
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        before, after = event.get("before", ""), os.environ.get("GITHUB_SHA", "")
        if not all(re.fullmatch(r"[a-f0-9]{40}", v) for v in (before, after)):
            raise ValueError("Missing push revision")
        if before != "0" * 40:
            changed = subprocess.check_output(["git", "diff", "--name-only", before, after], text=True).splitlines()
    values = metadata(os.environ, event, changed)
    # GitHub Actions consumes these three non-secret values through GITHUB_OUTPUT.
    # Never duplicate environment-derived metadata in the public runner log.
    build_tag = values["build_tag"]
    date_tag = values["date_tag"]
    publish = values["publish"]
    if (not re.fullmatch(r"[0-9]{8}-build\.[1-9][0-9]*\.[1-9][0-9]*", build_tag)
            or not re.fullmatch(r"[0-9]{8}", date_tag)
            or publish not in ("true", "false")):
        raise ValueError("Invalid publication metadata")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"build_tag={build_tag}\ndate_tag={date_tag}\npublish={publish}\n")


if __name__ == "__main__":
    main()
