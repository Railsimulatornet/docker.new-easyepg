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
    now = dt.datetime.now(ZoneInfo("Europe/Berlin"))
    trusted = (env.get("GITHUB_REPOSITORY") == REPOSITORY
               and env.get("GITHUB_REF") == "refs/heads/master")
    name = env.get("GITHUB_EVENT_NAME")
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
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in values.items():
            print(f"{key}={value}", file=out)
            print(f"{key}={value}")


if __name__ == "__main__":
    main()
