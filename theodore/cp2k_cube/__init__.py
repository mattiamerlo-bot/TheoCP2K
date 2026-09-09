"""CP2K TDDFPT/NTO cube support for TheoDORE.

The extension intentionally keeps cube-based descriptors separate from the
AO-transition-density path in :mod:`theodore.lib_tden`: cube files do not carry
the AO overlap matrix and therefore cannot reproduce Mulliken/Lowdin charge
transfer numbers verbatim.
"""

from .analysis import CubeStateAnalyzer, classify_state, omega_descriptors
from .cube import CubeValueStream, discover_cube, read_cube_header, read_preview_volume
from .errors import (
    AnalysisCancelled,
    CP2KCubeError,
    CP2KOutputError,
    CubeCompatibilityError,
    CubeFormatError,
    FragmentError,
)
from .fragments import FragmentSet
from .models import (
    Atom,
    BOHR_TO_ANGSTROM,
    CP2KRun,
    CubeAssignment,
    CubeHeader,
    ExcitedState,
    Fragment,
    PreviewVolume,
    StateAnalysis,
)
from .output_parser import CP2KOutputParser
from .project import CP2KCubeProject

__all__ = [
    "AnalysisCancelled",
    "Atom",
    "BOHR_TO_ANGSTROM",
    "CP2KCubeError",
    "CP2KCubeProject",
    "CP2KOutputError",
    "CP2KOutputParser",
    "CP2KRun",
    "CubeAssignment",
    "CubeCompatibilityError",
    "CubeFormatError",
    "CubeHeader",
    "CubeStateAnalyzer",
    "CubeValueStream",
    "ExcitedState",
    "Fragment",
    "FragmentError",
    "FragmentSet",
    "PreviewVolume",
    "StateAnalysis",
    "classify_state",
    "discover_cube",
    "omega_descriptors",
    "read_cube_header",
    "read_preview_volume",
]
