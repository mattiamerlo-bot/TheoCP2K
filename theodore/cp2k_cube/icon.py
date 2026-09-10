"""Embedded application icon used by Tk windows and Linux dock entries."""

from __future__ import annotations


# Tk derives the X11 resource class by applying Tcl's title-case conversion to
# the application name. Use that exact value in StartupWMClass as well.
TK_WINDOW_CLASS = "Theocp2k"


# 128x128 PNG rendered from packaging/appimage/TheoCP2K.svg. Keeping the
# runtime icon inside the Python package makes it available from source,
# editable installs, and the PyInstaller/AppImage bundle without path probing.
ICON_PNG_BASE64 = (
    "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"
)


def apply_window_icon(root, strict=False):
    """Apply the TheoCP2K icon at several sizes and keep Tk references alive."""

    import tkinter as tk

    try:
        large = tk.PhotoImage(master=root, data=ICON_PNG_BASE64, format="png")
        medium = large.subsample(2, 2)
        small = large.subsample(4, 4)
        root.iconphoto(True, large, medium, small)
    except tk.TclError:
        if strict:
            raise
        return ()
    icons = (large, medium, small)
    root._theocp2k_icons = icons
    return icons


__all__ = ["ICON_PNG_BASE64", "TK_WINDOW_CLASS", "apply_window_icon"]
