#!/usr/bin/env bash
set -Eeuo pipefail
archive="$(realpath "${1:?OCI archive required}")"
platform="${2:?Platform required}"
output="${3:?Report directory required}"
case "$platform" in linux/amd64|linux/arm64|linux/arm/v7) ;; *) exit 2 ;; esac
[[ -s "$archive" ]]
mkdir -p "$output"
output="$(realpath "$output")"
# A new directory prevents an old successful report from satisfying this run.
[[ ! -e "$output/full.json" ]]
cache="$(mktemp -d)"
trap 'rm -rf "$cache"' EXIT
docker pull ghcr.io/aquasecurity/trivy:latest
scanner="$(docker image inspect ghcr.io/aquasecurity/trivy:latest --format '{{.Id}}')"
[[ "$scanner" =~ ^sha256:[a-f0-9]{64}$ ]]
run_trivy() {
  docker run --rm --mount "type=bind,src=$archive,dst=/image.tar,readonly" \
    --mount "type=bind,src=$output,dst=/out" \
    --mount "type=bind,src=$cache,dst=/root/.cache/trivy" "$scanner" "$@"
}
# Retain ALL severities and unfixed findings. Scanner errors stop the script.
run_trivy image --input /image.tar --platform "$platform" --scanners vuln \
  --pkg-types os,library --format json --output /out/full.json --exit-code 0
[[ -s "$output/full.json" ]]
run_trivy convert --format table --severity HIGH,CRITICAL /out/full.json > "$output/high-critical.txt"
cat "$output/high-critical.txt"
python3 "$(dirname "$0")/check_scan.py" "$output/full.json"
