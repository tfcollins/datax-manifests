#!/usr/bin/env bash
# Install an upstream analogdevicesinc/cim release binary into ~/.local/bin and
# expose it to later workflow steps. Works on hosted and self-hosted runners
# (no sudo needed).
set -euo pipefail

version="${1:?usage: install-cim.sh <vX.Y.Z>}"
arch="$(uname -m)"
case "$arch" in
    x86_64)  target="x86_64-unknown-linux-gnu" ;;
    aarch64) target="aarch64-unknown-linux-gnu" ;;
    *) echo "unsupported arch: $arch" >&2; exit 1 ;;
esac

suite="cim-suite-${version}-${target}"
url="https://github.com/analogdevicesinc/cim/releases/download/${version}/${suite}.tar.gz"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -sSL "$url" | tar xz -C "$tmp"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$tmp/$suite/cim" "$HOME/.local/bin/cim"

if [ -n "${GITHUB_PATH:-}" ]; then
    echo "$HOME/.local/bin" >> "$GITHUB_PATH"
fi
"$HOME/.local/bin/cim" --version
