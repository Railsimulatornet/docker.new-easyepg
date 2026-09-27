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
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/cache"
# Trivy reads an OCI layout directory, not the Buildx OCI tar transport.
# Preserve all digests; the original archive remains the publication artifact.
skopeo copy --all --preserve-digests "oci-archive:$archive" "oci:$work/layout:verified"
[[ -s "$work/layout/index.json" ]]
docker pull ghcr.io/aquasecurity/trivy:latest
scanner="$(docker image inspect ghcr.io/aquasecurity/trivy:latest --format '{{.Id}}')"
[[ "$scanner" =~ ^sha256:[a-f0-9]{64}$ ]]
run_trivy() {
  docker run --rm --user "$(id -u):$(id -g)" --env HOME=/tmp \
    --mount "type=bind,src=$work/layout,dst=/image,readonly" \
    --mount "type=bind,src=$output,dst=/out" \
    --mount "type=bind,src=$work/cache,dst=/cache" \
    "$scanner" --cache-dir /cache "$@"
}
# Retain ALL severities and unfixed findings. Scanner errors stop the script.
run_trivy image --input /image --platform "$platform" --scanners vuln \
  --pkg-types os,library --format json --output /out/full.json --exit-code 0
[[ -s "$output/full.json" ]]
run_trivy convert --format table --severity HIGH,CRITICAL /out/full.json > "$output/high-critical.txt"
cat "$output/high-critical.txt"
python3 "$(dirname "$0")/check_scan.py" "$output/full.json"
