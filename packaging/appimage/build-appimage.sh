#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD_DIR="$ROOT_DIR/build/appimage"
APP_DIR="$BUILD_DIR/TheoCP2K.AppDir"
OUTPUT_DIR=${1:-"$ROOT_DIR/dist"}
PYTHON_BIN=${PYTHON_BIN:-python3}
APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage"
APPIMAGETOOL_BIN=${APPIMAGETOOL_BIN:-"$BUILD_DIR/appimagetool-x86_64.AppImage"}

case "$(uname -m)" in
    x86_64|amd64) ;;
    *)
        echo "Errore: questo script produce l'AppImage x86_64 e deve essere eseguito su x86_64." >&2
        exit 2
        ;;
esac

command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Errore: interprete Python non trovato: $PYTHON_BIN" >&2
    exit 2
}

"$PYTHON_BIN" -c "import numpy, matplotlib, scipy, skimage, PyInstaller, tkinter"

rm -rf -- "$BUILD_DIR"
mkdir -p "$BUILD_DIR/pyinstaller-dist" "$BUILD_DIR/pyinstaller-work" "$APP_DIR/usr/bin" "$APP_DIR/usr/lib" "$OUTPUT_DIR"

"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name TheoCP2K \
    --paths "$ROOT_DIR" \
    --distpath "$BUILD_DIR/pyinstaller-dist" \
    --workpath "$BUILD_DIR/pyinstaller-work" \
    --specpath "$BUILD_DIR" \
    --hidden-import matplotlib.backends.backend_tkagg \
    --hidden-import scipy.spatial._ckdtree \
    --hidden-import skimage.measure._marching_cubes_lewiner_cy \
    "$ROOT_DIR/packaging/appimage/launcher.py"

cp -a "$BUILD_DIR/pyinstaller-dist/TheoCP2K" "$APP_DIR/usr/lib/TheoCP2K"
install -Dm755 "$ROOT_DIR/packaging/appimage/theocp2k-wrapper" "$APP_DIR/usr/bin/TheoCP2K"
install -Dm755 "$ROOT_DIR/packaging/appimage/AppRun" "$APP_DIR/AppRun"
install -Dm644 "$ROOT_DIR/packaging/appimage/TheoCP2K.desktop" "$APP_DIR/TheoCP2K.desktop"
install -Dm644 "$ROOT_DIR/packaging/appimage/TheoCP2K.svg" "$APP_DIR/TheoCP2K.svg"
install -Dm644 "$ROOT_DIR/packaging/appimage/TheoCP2K.desktop" \
    "$APP_DIR/usr/share/applications/TheoCP2K.desktop"
install -Dm644 "$ROOT_DIR/packaging/appimage/TheoCP2K.svg" \
    "$APP_DIR/usr/share/icons/hicolor/scalable/apps/TheoCP2K.svg"
ln -s TheoCP2K.svg "$APP_DIR/.DirIcon"

if [[ ! -x "$APPIMAGETOOL_BIN" ]]; then
    command -v curl >/dev/null 2>&1 || {
        echo "Errore: curl è necessario per scaricare appimagetool." >&2
        exit 2
    }
    curl --fail --location --retry 3 --output "$APPIMAGETOOL_BIN" "$APPIMAGETOOL_URL"
    echo "$APPIMAGETOOL_SHA256  $APPIMAGETOOL_BIN" | sha256sum --check --status || {
        echo "Errore: checksum appimagetool non valido." >&2
        exit 2
    }
    chmod 755 "$APPIMAGETOOL_BIN"
fi

OUTPUT_FILE="$OUTPUT_DIR/TheoCP2K-x86_64.AppImage"
rm -f -- "$OUTPUT_FILE"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL_BIN" "$APP_DIR" "$OUTPUT_FILE"
chmod 755 "$OUTPUT_FILE"
(
    cd "$OUTPUT_DIR"
    sha256sum "$(basename -- "$OUTPUT_FILE")" > SHA256SUMS.txt
)

echo "Creato: $OUTPUT_FILE"
