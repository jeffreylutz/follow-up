#!/usr/bin/env bash
# Publish a built xwrap binary to a Nexus raw (hosted) repository.
#
# Usage:
#   NEXUS_USER=svc-ci NEXUS_PASS=*** \
#   NEXUS_URL=https://nexus.example.com/repository/raw-hosted/xwrap \
#   ./publish-to-nexus.sh <binary> [os] [arch]
#
# Uploads, using the layout install.sh + the self-updater expect:
#   {NEXUS_URL}/{version}/xwrap-{os}-{arch}
#   {NEXUS_URL}/{version}/xwrap-{os}-{arch}.sha256
#   {NEXUS_URL}/latest/VERSION
set -euo pipefail

BIN="${1:?usage: publish-to-nexus.sh <binary> [os] [arch]}"
OS="${2:-$(uname -s | tr '[:upper:]' '[:lower:]' | sed 's/darwin/macos/')}"
ARCH="${3:-$(uname -m | sed 's/arm64/aarch64/;s/amd64/x86_64/')}"
: "${NEXUS_URL:?set NEXUS_URL to the raw-repo xwrap folder}"
: "${NEXUS_USER:?set NEXUS_USER}"
: "${NEXUS_PASS:?set NEXUS_PASS}"

# Version comes from Cargo.toml so it matches env!("CARGO_PKG_VERSION") in the binary.
VERSION="$(awk -F\" '/^version *=/{print $2; exit}' Cargo.toml)"
asset="xwrap-${OS}-${ARCH}"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
( cd "$(dirname "$BIN")" && shasum -a 256 "$(basename "$BIN")" | awk -v a="$asset" '{print $1"  "a}' ) > "$tmp/$asset.sha256"
printf '%s\n' "$VERSION" > "$tmp/VERSION"

put() { curl -fsS -u "$NEXUS_USER:$NEXUS_PASS" --upload-file "$1" "$2" && echo "  -> $2"; }

echo ">> Publishing $asset $VERSION to $NEXUS_URL"
put "$BIN"               "${NEXUS_URL}/${VERSION}/${asset}"
put "$tmp/$asset.sha256" "${NEXUS_URL}/${VERSION}/${asset}.sha256"
put "$tmp/VERSION"       "${NEXUS_URL}/latest/VERSION"
echo ">> Done."
