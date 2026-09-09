"""Data models used by the CP2K cube parser, analyser, and GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


BOHR_TO_ANGSTROM = 0.529177210903


@dataclass
class Atom:
    """One atom, stored internally in bohr."""

    index: int
    atomic_number: int
    symbol: str
    position_bohr: np.ndarray
    charge: float = 0.0

    @property
    def position_angstrom(self) -> np.ndarray:
        return np.asarray(self.position_bohr, dtype=float) * BOHR_TO_ANGSTROM

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "atomic_number": self.atomic_number,
            "symbol": self.symbol,
            "position_bohr": np.asarray(self.position_bohr).tolist(),
            "charge": self.charge,
        }


@dataclass
class CubeHeader:
    """Header and grid description of a Gaussian/CP2K cube file."""

    path: Path
    comment_1: str
    comment_2: str
    origin_bohr: np.ndarray
    shape: Tuple[int, int, int]
    axes_bohr: np.ndarray
    atoms: List[Atom]
    data_offset: int
    dataset_ids: List[int] = field(default_factory=list)
    original_units: str = "bohr"

    @property
    def n_values(self) -> int:
        return int(np.prod(self.shape, dtype=np.int64))

    @property
    def voxel_volume_bohr3(self) -> float:
        return float(abs(np.linalg.det(np.asarray(self.axes_bohr, dtype=float))))

    @property
    def cell_vectors_bohr(self) -> np.ndarray:
        return np.asarray(self.axes_bohr) * np.asarray(self.shape)[:, None]

    def grid_signature(self) -> tuple:
        return (
            tuple(self.shape),
            tuple(np.round(self.origin_bohr, 10)),
            tuple(np.round(self.axes_bohr.ravel(), 10)),
            tuple((a.atomic_number, *np.round(a.position_bohr, 8)) for a in self.atoms),
        )


@dataclass
class OrbitalTransition:
    occupied: int
    virtual: int
    amplitude: float


@dataclass
class ExcitedState:
    """Excited-state properties parsed from the converged CP2K table."""

    index: int
    energy_ev: float
    oscillator_strength: float
    transition_dipole_au: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    multiplicity: Optional[int] = None
    nto_eigenvalues: List[float] = field(default_factory=list)
    transitions: List[OrbitalTransition] = field(default_factory=list)
    exciton: Dict[str, float] = field(default_factory=dict)
    electron_centroid_angstrom: Optional[np.ndarray] = None
    hole_centroid_angstrom: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "S%d" % self.index

    @property
    def nto_sum(self) -> float:
        return float(sum(self.nto_eigenvalues))

    @property
    def pr_nto(self) -> Optional[float]:
        values = np.asarray(self.nto_eigenvalues, dtype=float)
        if values.size == 0 or np.dot(values, values) <= 0.0:
            return None
        return float(values.sum() ** 2 / np.dot(values, values))

    @property
    def nto_entropy(self) -> Optional[float]:
        values = np.asarray(self.nto_eigenvalues, dtype=float)
        if values.size == 0 or values.sum() <= 0.0:
            return None
        # Match TheoDORE's definition. Missing values below CP2K's print
        # threshold simply make this a lower-bound estimate.
        positive = values[values > 0.0]
        return float(-np.sum(positive * np.log2(positive)))


@dataclass
class CP2KRun:
    path: Path
    states: List[ExcitedState]
    atoms: List[Atom]
    cp2k_version: Optional[str] = None
    spin_label: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def state(self, index: int) -> ExcitedState:
        for item in self.states:
            if item.index == index:
                return item
        raise KeyError(index)


@dataclass
class CubeAssignment:
    """A cube file associated with an electronic state and an NTO pair."""

    path: Path
    role: str
    state_index: Optional[int]
    pair_index: Optional[int]
    header: CubeHeader
    detection_note: str = ""

    @property
    def key(self) -> Tuple[Optional[int], Optional[int], str]:
        return self.state_index, self.pair_index, self.role

    def to_dict(self, base_dir: Optional[Path] = None) -> dict:
        path = self.path
        if base_dir is not None:
            try:
                path = path.resolve().relative_to(base_dir.resolve())
            except ValueError:
                pass
        return {
            "path": str(path),
            "role": self.role,
            "state_index": self.state_index,
            "pair_index": self.pair_index,
        }


@dataclass
class Fragment:
    name: str
    atom_indices: List[int]
    color: str = "#4C78A8"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "atom_indices": list(self.atom_indices),
            "color": self.color,
        }


@dataclass
class OrbitalPopulation:
    fragment_population: np.ndarray
    norm: float
    centroid_angstrom: np.ndarray
    mean_r2_angstrom2: float


@dataclass
class StateAnalysis:
    state_index: int
    omega: np.ndarray
    omega_raw_sum: float
    fragment_names: List[str]
    hole_population: np.ndarray
    electron_population: np.ndarray
    descriptors: Dict[str, float]
    character: str
    dominant_channel: str
    pair_weights_used: List[float]
    grid_stride: Tuple[int, int, int]
    approximate: bool = True
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "state_index": self.state_index,
            "fragment_names": self.fragment_names,
            "omega": self.omega.tolist(),
            "omega_raw_sum": self.omega_raw_sum,
            "hole_population": self.hole_population.tolist(),
            "electron_population": self.electron_population.tolist(),
            "descriptors": self.descriptors,
            "character": self.character,
            "dominant_channel": self.dominant_channel,
            "pair_weights_used": self.pair_weights_used,
            "grid_stride": list(self.grid_stride),
            "approximate": self.approximate,
            "warnings": self.warnings,
        }


@dataclass
class PreviewVolume:
    values: np.ndarray
    origin_bohr: np.ndarray
    axes_bohr: np.ndarray
    sampling_stride: Tuple[int, int, int]
    atoms: Sequence[Atom]

    def index_to_angstrom(self, vertices: np.ndarray) -> np.ndarray:
        effective_axes = np.asarray(self.axes_bohr) * np.asarray(self.sampling_stride)[:, None]
        coords_bohr = np.asarray(self.origin_bohr) + np.asarray(vertices) @ effective_axes
        return coords_bohr * BOHR_TO_ANGSTROM
