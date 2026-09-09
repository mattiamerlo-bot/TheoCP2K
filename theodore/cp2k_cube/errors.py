"""Errors raised by the CP2K cube extension."""


class CP2KCubeError(Exception):
    """Base class for user-facing CP2K/cube errors."""


class CP2KOutputError(CP2KCubeError):
    """The CP2K output is missing or contains inconsistent data."""


class CubeFormatError(CP2KCubeError):
    """A cube file is malformed or unsupported."""


class CubeCompatibilityError(CP2KCubeError):
    """Hole and particle cube files do not share the same grid/geometry."""


class FragmentError(CP2KCubeError):
    """A fragment definition is incomplete or invalid."""


class AnalysisCancelled(CP2KCubeError):
    """The user cancelled an analysis in progress."""
