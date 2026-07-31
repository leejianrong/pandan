#!/usr/bin/env bash
#
# Build-provenance gate for the MCP image (KAN-452).
#
# WHY: `ghcr.io/<owner>/pandan-mcp:latest` is as unidentifiable as the old `kan`
# binary was — pull it and you cannot tell which commit you are running. The CLI
# answers that with `pandan --version` printing `pandan 0.5.0 (5da9ace)`, and
# `.github/workflows/release-cli.yml` FAILS the release if the built asset's
# `--version` doesn't carry the release commit. A container's native answer is
# not a `--version` string but OCI labels + the digest, so this script is the
# mirror of that smoke test: `docker/metadata-action` EMITS the labels, and this
# asserts they actually landed on the built image and name THIS commit. Without
# the assertion the labels are merely present, not non-regressible.
#
# The CI gate runs this BEFORE the push (the image is built with `load: true`
# first), so an image that can't identify itself is never published.
#
# Usage:
#   mcp/scripts/assert-image-provenance.sh <image-ref> <expected-revision> [expected-version]
#
#   <image-ref>          an image in the LOCAL docker daemon (CI builds with
#                        `load: true`; a human can `docker pull` it first)
#   <expected-revision>  the full git SHA the image must claim it was built from
#   <expected-version>   optional; the release version the image must claim
#
# Exit: 0 all assertions pass · 1 an assertion failed · 2 bad usage.

set -euo pipefail

REV_LABEL="org.opencontainers.image.revision"
VER_LABEL="org.opencontainers.image.version"
CREATED_LABEL="org.opencontainers.image.created"

usage() {
  sed -n '/^# Usage:/,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//' >&2
}

ref="${1:-}"
expected_revision="${2:-}"
expected_version="${3:-}"

if [ -z "$ref" ] || [ -z "$expected_revision" ]; then
  echo "error: need an image ref and an expected revision" >&2
  usage
  exit 2
fi

echo "== build-provenance gate =="
echo "image:              $ref"
echo "expected revision:  $expected_revision"
echo "expected version:   ${expected_version:-<not checked>}"

if ! labels=$(docker image inspect "$ref" --format '{{json .Config.Labels}}' 2>/dev/null); then
  echo "::error::image '$ref' is not in the local docker daemon — build it with 'load: true' (CI) or 'docker pull' it first"
  exit 1
fi
# A label-less image inspects as JSON null; normalise so jq below still works
# and the missing-label branch produces the real diagnostic.
if [ "$labels" = "null" ] || [ -z "$labels" ]; then
  labels='{}'
fi

echo "OCI labels carried by the image:"
printf '%s' "$labels" | jq -S . || true

label_of() {
  printf '%s' "$labels" | jq -r --arg k "$1" '.[$k] // ""'
}

failed=0

revision=$(label_of "$REV_LABEL")
if [ -z "$revision" ]; then
  echo "::error::$ref carries no $REV_LABEL label — the image cannot say which commit built it. Is 'labels: \${{ steps.meta.outputs.labels }}' still wired into the build step?"
  failed=1
elif [ "$revision" != "$expected_revision" ]; then
  echo "::error::$REV_LABEL is '$revision' but this build is '$expected_revision' — the image does not carry the release commit"
  failed=1
else
  echo "OK   $REV_LABEL = $revision"
fi

if [ -n "$expected_version" ]; then
  # Independent of metadata-action: derived from the git tag by the caller, so
  # this catches a mis-wired tag/label mapping and not just a missing label.
  # (Assumes the repo's `vX.Y.Z` tag convention — a deliberately non-semver tag
  # would trip this, which is the intended "stop and look" outcome.)
  version=$(label_of "$VER_LABEL")
  if [ -z "$version" ]; then
    echo "::error::$ref carries no $VER_LABEL label — the image cannot say which release it is"
    failed=1
  elif [ "$version" != "$expected_version" ]; then
    echo "::error::$VER_LABEL is '$version' but this release is '$expected_version' — the image does not carry the release version"
    failed=1
  else
    echo "OK   $VER_LABEL = $version"
  fi
fi

created=$(label_of "$CREATED_LABEL")
if [ -z "$created" ]; then
  echo "::error::$ref carries no $CREATED_LABEL label — the image cannot say when it was built"
  failed=1
else
  echo "OK   $CREATED_LABEL = $created"
fi

if [ "$failed" -ne 0 ]; then
  echo "::error::build-provenance gate FAILED for $ref — refusing to publish an image that cannot identify itself (KAN-452)"
  exit 1
fi

echo "build provenance OK — $ref identifies itself as $expected_revision"
