# Linux AppImage packaging

The GitHub Actions workflow in `.github/workflows/appimage.yml` builds the
standalone `TheoCP2K-x86_64.AppImage` on Ubuntu 22.04. The bundle contains
Python, Tk, NumPy, Matplotlib, SciPy, scikit-image, and the CP2K cube GUI; users
do not need to install Python or those modules.

## Automatic builds

- every push to `main`, every pull request, and a manual `workflow_dispatch`
  run tests and upload a 30-day workflow artifact;
- a pushed `v*` tag additionally creates a GitHub Release and attaches the
  AppImage plus `SHA256SUMS.txt`.

Example release:

```bash
git tag -a v0.1.0 -m "TheoCP2K v0.1.0"
git push origin v0.1.0
```

## Local x86_64 build

On Debian/Ubuntu, install Tk and a virtual environment, then run:

```bash
sudo apt-get install desktop-file-utils python3-tk python3-venv xauth xvfb
python3 -m venv .venv-appimage
.venv-appimage/bin/python -m pip install -r packaging/appimage/requirements.txt
PYTHON_BIN=.venv-appimage/bin/python packaging/appimage/build-appimage.sh
```

The direct Python build dependencies are pinned for repeatable builds. The
build script downloads the pinned `appimagetool` 1.9.1 x86_64 release and
verifies its SHA-256 digest before execution. Set `APPIMAGETOOL_BIN` to an
already downloaded executable to build offline.

Test the finished GUI without FUSE:

```bash
xvfb-run -a env APPIMAGE_EXTRACT_AND_RUN=1 \
  dist/TheoCP2K-x86_64.AppImage --smoke-test
```
