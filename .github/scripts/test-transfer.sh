#!/usr/bin/env bash
set -Eeuo pipefail
layout="$(realpath "${1:?OCI layout required}")"
work="$(mktemp -d)"
name="easyepg-registry-${RANDOM}-$$"
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
docker run -d --name "$name" -p 127.0.0.1::5000 registry:3 >/dev/null
port="$(docker port "$name" 5000/tcp | sed 's/.*://')"
[[ "$port" =~ ^[0-9]+$ ]]
for _ in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:$port/v2/" >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent "http://127.0.0.1:$port/v2/" >/dev/null
source="oci:$layout:verified"
remote="docker://127.0.0.1:$port/easyepg:verified"
skopeo copy --dest-tls-verify=false --all --preserve-digests "$source" "$remote"
skopeo copy --src-tls-verify=false --all --preserve-digests "$remote" "oci:$work/roundtrip:verified"
skopeo inspect --raw "$source" > "$work/source.json"
skopeo inspect --raw "oci:$work/roundtrip:verified" > "$work/returned.json"
cmp "$work/source.json" "$work/returned.json"
# Compare every source blob: runtime layers AND build attestations.
for blob in "$layout"/blobs/sha256/*; do
  cmp "$blob" "$work/roundtrip/blobs/sha256/$(basename "$blob")"
done
echo "All three platforms and build attestations survived the registry round trip unchanged."
