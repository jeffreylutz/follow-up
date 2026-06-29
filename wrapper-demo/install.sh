#!/usr/bin/env sh
# Single-line, zero-dependency installer for the xwrap CLI from Nexus.
#
#   curl -fsSL https://nexus.example.com/repository/raw-hosted/xwrap/install.sh | sh
#
# Needs only `curl` and `sh` — no Python, pip, uv, or cargo. Downloads the
# prebuilt static binary for this OS/arch from a Nexus raw (hosted) repo,
# verifies its checksum, and installs it to ~/.local/bin.
set -eu

# Base URL of the xwrap folder in the Nexus raw repo. Override for your instance.
BASE_URL="${XWRAP_BASE_URL:-https://nexus.example.com/repository/raw-hosted/xwrap}"
INSTALL_DIR="${XWRAP_INSTALL_DIR:-$HOME/.local/bin}"

os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Linux) os="linux" ;;
  Darwin) os="macos" ;;
  *) echo "error: unsupported OS '$os'" >&2; exit 1 ;;
esac
case "$arch" in
  x86_64|amd64) arch="x86_64" ;;
  arm64|aarch64) arch="aarch64" ;;
  *) echo "error: unsupported arch '$arch'" >&2; exit 1 ;;
esac
asset="xwrap-${os}-${arch}"

version="$(curl -fsSL "${BASE_URL}/latest/VERSION")"
version="$(printf '%s' "$version" | tr -d '[:space:]')"
url="${BASE_URL}/${version}/${asset}"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo ">> Downloading ${asset} ${version}"
curl -fsSL "$url" -o "$tmp/xwrap"

if curl -fsSL "${url}.sha256" -o "$tmp/xwrap.sha256" 2>/dev/null; then
  echo ">> Verifying checksum"
  expected="$(cut -d' ' -f1 "$tmp/xwrap.sha256")"
  if command -v shasum >/dev/null; then
    actual="$(shasum -a 256 "$tmp/xwrap" | cut -d' ' -f1)"
  else
    actual="$(sha256sum "$tmp/xwrap" | cut -d' ' -f1)"
  fi
  [ "$expected" = "$actual" ] || { echo "error: checksum mismatch" >&2; exit 1; }
fi

mkdir -p "$INSTALL_DIR"
chmod +x "$tmp/xwrap"
mv "$tmp/xwrap" "$INSTALL_DIR/xwrap"
echo ">> Installed: $INSTALL_DIR/xwrap ($version)"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "   note: add $INSTALL_DIR to your PATH" ;; esac
echo ">> Try: xwrap list"
