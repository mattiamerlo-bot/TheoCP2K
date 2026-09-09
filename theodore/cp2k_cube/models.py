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

    @classmethod
    def from_dict(cls, data: dict):
        """Restore and validate an analysis stored in a project snapshot."""

        try:
            state_index = int(data["state_index"])
            fragment_names = [str(value) for value in data["fragment_names"]]
            omega = np.asarray(data["omega"], dtype=float)
            omega_raw_sum = float(data["omega_raw_sum"])
            hole_population = np.asarray(data["hole_population"], dtype=float)
            electron_population = np.asarray(data["electron_population"], dtype=float)
            descriptors = {
                str(name): float(value) for name, value in data["descriptors"].items()
            }
            character = str(data["character"])
            dominant_channel = str(data["dominant_channel"])
            pair_weights_used = [float(value) for value in data["pair_weights_used"]]
            grid_stride = tuple(int(value) for value in data["grid_stride"])
            approximate = bool(data.get("approximate", True))
            warnings = [str(value) for value in data.get("warnings", [])]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Campi dell'analisi mancanti o non validi: %s" % exc) from exc

        n_fragments = len(fragment_names)
        if state_index < 1:
            raise ValueError("L'indice dello stato deve essere positivo.")
        if n_fragments < 1:
            raise ValueError("L'analisi non contiene frammenti.")
        if omega.shape != (n_fragments, n_fragments):
            raise ValueError(
                "La matrice Omega ha forma %s, attesa (%d, %d)."
                % (omega.shape, n_fragments, n_fragments)
            )
        if hole_population.shape != (n_fragments,) or electron_population.shape != (n_fragments,):
            raise ValueError("Le popolazioni hole/particle non corrispondono ai frammenti.")
        if not np.all(np.isfinite(omega)) or np.any(omega < -1.0e-12):
            raise ValueError("La matrice Omega contiene valori non validi.")
        if not np.isclose(float(omega.sum()), 1.0, atol=1.0e-8, rtol=1.0e-8):
            raise ValueError("La matrice Omega salvata non è normalizzata.")
        if not np.allclose(hole_population, omega.sum(axis=1), atol=1.0e-8, rtol=1.0e-8):
            raise ValueError("La popolazione hole non coincide con la matrice Omega.")
        if not np.allclose(electron_population, omega.sum(axis=0), atol=1.0e-8, rtol=1.0e-8):
            raise ValueError("La popolazione particle non coincide con la matrice Omega.")
        if not np.isfinite(omega_raw_sum) or omega_raw_sum <= 0.0:
            raise ValueError("La somma Omega non normalizzata non è valida.")
        if len(grid_stride) != 3 or any(value < 1 for value in grid_stride):
            raise ValueError("Lo stride salvato deve contenere tre interi positivi.")
        if (
            not pair_weights_used
            or not np.all(np.isfinite(pair_weights_used))
            or any(value <= 0.0 for value in pair_weights_used)
        ):
            raise ValueError("I pesi NTO salvati non sono validi.")
        if not all(np.isfinite(value) for value in descriptors.values()):
            raise ValueError("I descrittori salvati contengono valori non validi.")
        if not character or not dominant_channel:
            raise ValueError("Carattere o canale dominante mancanti nell'analisi salvata.")

        return cls(
            state_index=state_index,
            omega=omega,
            omega_raw_sum=omega_raw_sum,
            fragment_names=fragment_names,
            hole_population=hole_population,
            electron_population=electron_population,
            descriptors=descriptors,
            character=character,
            dominant_channel=dominant_channel,
            pair_weights_used=pair_weights_used,
            grid_stride=grid_stride,
            approximate=approximate,
            warnings=warnings,
        )


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
