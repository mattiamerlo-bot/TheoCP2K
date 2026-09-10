#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
TARGET_DATA_HOME=${XDG_DATA_HOME:-${HOME:?}/.local/share}

install -Dm644 "$SCRIPT_DIR/TheoCP2K.desktop" \
    "$TARGET_DATA_HOME/applications/TheoCP2K.desktop"
install -Dm644 "$PROJECT_ROOT/packaging/appimage/TheoCP2K.svg" \
    "$TARGET_DATA_HOME/icons/hicolor/scalable/apps/TheoCP2K.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$TARGET_DATA_HOME/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$TARGET_DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Desktop entry installata in $TARGET_DATA_HOME/applications/TheoCP2K.desktop"
