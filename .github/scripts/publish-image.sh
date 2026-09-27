#!/usr/bin/env bash
set -Eeuo pipefail
layout="$(realpath "${1:?Verified OCI layout required}")"
build="${2:?Build tag required}"
dated="${3:?Legacy date tag required}"
[[ "$build" =~ ^[0-9]{8}-build\.[1-9][0-9]*\.[1-9][0-9]*$ ]]
[[ "$dated" =~ ^[0-9]{8}$ ]]
: "${DOCKERHUB_USERNAME:?Docker Hub user missing}"
: "${DOCKERHUB_TOKEN:?Docker Hub token missing}"
repo="docker.io/railsimulatornet/new-easyepg"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077
auth="$work/auth.json"
printf '%s' "$DOCKERHUB_TOKEN" | skopeo login --authfile "$auth" \
  --username "$DOCKERHUB_USERNAME" --password-stdin docker.io
source="oci:$layout:verified"
skopeo inspect --raw "$source" > "$work/expected.json"
expected="$(skopeo manifest-digest "$work/expected.json")"
exists() {
  if skopeo inspect --authfile "$auth" --raw "docker://$repo:$1" > "$work/existing.json" 2> "$work/error"; then
    return 0
  fi
  if grep -Eqi 'manifest unknown|MANIFEST_UNKNOWN' "$work/error"; then
    return 1
  fi
  cat "$work/error" >&2
  exit 2
}
# Preflight both immutable names before the first registry write.
if exists "$build"; then
  [[ "$(skopeo manifest-digest "$work/existing.json")" == "$expected" ]] || {
    echo "Refusing to replace existing build: $build" >&2; exit 1;
  }
fi
write_date=true
if exists "$dated"; then
  write_date=false
  echo "Keeping existing date tag $dated unchanged."
fi
copy_tag() {
  skopeo copy --authfile "$auth" --all --preserve-digests "$source" "docker://$repo:$1"
  skopeo inspect --authfile "$auth" --raw "docker://$repo:$1" > "$work/published.json"
  [[ "$(skopeo manifest-digest "$work/published.json")" == "$expected" ]]
  echo "$repo:$1 -> $expected"
}
copy_tag "$build"
if [[ "$write_date" == true ]]; then copy_tag "$dated"; fi
# latest changes only after immutable publication and digest verification succeed.
copy_tag latest
