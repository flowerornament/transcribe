#!/usr/bin/env bash
# Ship transcribe to nix-config scripts (symlink for live dev)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.nix-config/scripts/transcribe"

ln -sf "$SCRIPT_DIR/transcribe.py" "$TARGET"
echo "Linked: $TARGET → $SCRIPT_DIR/transcribe.py"
