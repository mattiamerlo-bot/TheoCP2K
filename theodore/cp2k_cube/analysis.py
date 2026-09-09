"""Fragment analysis of CP2K NTO cube files.

The cube-only route evaluates a real-space Voronoi population for every NTO
orbital and constructs the positive NTO-diagonal approximation

    Omega_AB = sum_k lambda_k P_h(k,A) P_e(k,B).

For one NTO pair this is the separable electron-hole probability exactly on the
chosen real-space partition.  For multiple pairs it omits inter-pair
interference because independent CP2K cube files do not preserve enough phase
information to reconstruct those terms safely.  The GUI and exported files
carry this distinction explicitly.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, Optional, Tuple

import numpy as np

from .cube import CubeValueStream, assert_compatible
from .errors import AnalysisCancelled, CP2KCubeError, FragmentError
from .fragments import FragmentSet
from .models import BOHR_TO_ANGSTROM, CubeAssignment, ExcitedState, OrbitalPopulation, StateAnalysis

try:  # SciPy is optional; the NumPy fallback is deliberately memory bounded.
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover - depends on the local installation
    cKDTree = None


ProgressCallback = Callable[[float, str], None]


def _normalise_stride(stride) -> Tuple[int, int, int]:
    if isinstance(stride, int):
        values = (stride, stride, stride)
    else:
        values = tuple(int(value) for value in stride)
    if len(values) != 3 or any(value < 1 for value in values):
        raise ValueError("Lo stride deve contenere tre interi positivi.")
    return values


def _nearest_atoms_numpy(points: np.ndarray, atom_positions: np.ndarray) -> np.ndarray:
    output = np.empty(points.shape[0], dtype=np.int32)
    # Bound the temporary (points x atoms x xyz) array to roughly tens of MiB.
    block = max(1024, min(32768, int(2_000_000 / max(1, len(atom_positions)))))
    for start in range(0, len(points), block):
        stop = min(start + block, len(points))
        delta = points[start:stop, None, :] - atom_positions[None, :, :]
        distance2 = np.einsum("ijk,ijk->ij", delta, delta, optimize=True)
        output[start:stop] = np.argmin(distance2, axis=1)
    return output


def _integrate_orbital(
    assignment: CubeAssignment,
    fragments: FragmentSet,
    stride: Tuple[int, int, int],
    progress: Optional[ProgressCallback] = None,
    cancel_event=None,
) -> OrbitalPopulation:
    header = assignment.header
    if len(header.atoms) != fragments.n_atoms:
        raise FragmentError(
            "%s contiene %d atomi, mentre i frammenti ne descrivono %d."
            % (header.path.name, len(header.atoms), fragments.n_atoms)
        )

    atom_to_fragment = fragments.atom_to_fragment()
    atom_positions = np.asarray([atom.position_bohr for atom in header.atoms], dtype=float)
    tree = cKDTree(atom_positions) if cKDTree is not None else None
    fragment_integrals = np.zeros(len(fragments.fragments), dtype=float)
    density_sum = 0.0
    first_moment = np.zeros(3, dtype=float)
    second_moment = 0.0
    nx, ny, nz = header.shape
    flat_start = 0

    with CubeValueStream(header) as stream:
        for values in stream.iter_blocks():
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisCancelled("Analisi annullata.")
            flat = np.arange(flat_start, flat_start + values.size, dtype=np.int64)
            ix = flat // (ny * nz)
            remainder = flat % (ny * nz)
            iy = remainder // nz
            iz = remainder % nz
            sample = (
                (ix % stride[0] == 0)
                & (iy % stride[1] == 0)
                & (iz % stride[2] == 0)
            )
            if np.any(sample):
                sampled_values = values[sample]
                density = sampled_values * sampled_values
                sample_ix = ix[sample]
                sample_iy = iy[sample]
                sample_iz = iz[sample]
                coordinates = (
                    header.origin_bohr
                    + sample_ix[:, None] * header.axes_bohr[0]
                    + sample_iy[:, None] * header.axes_bohr[1]
                    + sample_iz[:, None] * header.axes_bohr[2]
                )
                if tree is not None:
                    nearest = tree.query(coordinates, k=1, workers=1)[1]
                else:
                    nearest = _nearest_atoms_numpy(coordinates, atom_positions)
                fragment_index = atom_to_fragment[np.asarray(nearest, dtype=int)]
                fragment_integrals += np.bincount(
                    fragment_index, weights=density, minlength=len(fragment_integrals)
                )
                density_sum += float(density.sum())
                first_moment += np.sum(density[:, None] * coordinates, axis=0)
                second_moment += float(np.dot(density, np.einsum("ij,ij->i", coordinates, coordinates)))

            flat_start += values.size
            if progress is not None:
                progress(flat_start / header.n_values, "Integrazione %s" % header.path.name)

    if density_sum <= np.finfo(float).tiny:
        raise CP2KCubeError("L'orbitale in %s ha norma numerica nulla." % header.path.name)

    quadrature = header.voxel_volume_bohr3 * int(np.prod(stride))
    norm = density_sum * quadrature
    centroid_bohr = first_moment / density_sum
    mean_r2_bohr2 = second_moment / density_sum
    return OrbitalPopulation(
        fragment_population=fragment_integrals / density_sum,
        norm=float(norm),
        centroid_angstrom=centroid_bohr * BOHR_TO_ANGSTROM,
        mean_r2_angstrom2=float(mean_r2_bohr2 * BOHR_TO_ANGSTROM**2),
    )


def omega_descriptors(omega: np.ndarray) -> Dict[str, float]:
    """Compute the standard TheoDORE-style descriptors from a normalised Omega."""

    matrix = np.asarray(omega, dtype=float)
    total = float(matrix.sum())
    if total <= 0.0:
        raise CP2KCubeError("La matrice Omega ha somma nulla.")
    matrix = matrix / total
    hole = matrix.sum(axis=1)
    electron = matrix.sum(axis=0)
    pri = 1.0 / float(np.dot(hole, hole))
    prf = 1.0 / float(np.dot(electron, electron))
    pr = 0.5 * (pri + prf)
    prh = 2.0 / (1.0 / pri + 1.0 / prf)
    squared_sum = float(np.sum(matrix * matrix))
    indices = np.arange(1, matrix.shape[0] + 1, dtype=float)
    posi = float(np.dot(indices, hole))
    posf = float(np.dot(indices, electron))
    ct = float(matrix.sum() - np.trace(matrix))
    descriptors = {
        "CT": ct,
        "LE": float(np.trace(matrix)),
        "PRi": pri,
        "PRf": prf,
        "PR": pr,
        "PRh": prh,
        "POSi": posi,
        "POSf": posf,
        "POS": 0.5 * (posi + posf),
        "CTnt": posf - posi,
        "COH": (1.0 / squared_sum / pr) if squared_sum > 0.0 else float("nan"),
        "COHh": (1.0 / squared_sum / prh) if squared_sum > 0.0 else float("nan"),
    }
    return descriptors


def classify_state(
    omega: np.ndarray,
    fragment_names: Iterable[str],
    le_threshold: float = 0.35,
    ct_threshold: float = 0.65,
):
    """Return a readable LE/CT assignment and its dominant channel."""

    matrix = np.asarray(omega, dtype=float)
    names = list(fragment_names)
    if matrix.shape == (1, 1):
        return "LE (frammento unico)", "%s → %s" % (names[0], names[0])

    ct = float(matrix.sum() - np.trace(matrix)) / float(matrix.sum())
    diagonal = np.diag(matrix)
    diag_index = int(np.argmax(diagonal))
    off_diagonal = matrix.copy()
    np.fill_diagonal(off_diagonal, -np.inf)
    hole_index, electron_index = np.unravel_index(np.argmax(off_diagonal), matrix.shape)
    dominant_ct = "%s → %s" % (names[hole_index], names[electron_index])
    dominant_le = "%s → %s" % (names[diag_index], names[diag_index])

    if ct <= le_threshold:
        label = "LE su %s" % names[diag_index]
        if diagonal[diag_index] / matrix.sum() < 0.50:
            label = "LE delocalizzata"
        return label, dominant_le
    if ct >= ct_threshold:
        label = "CT %s" % dominant_ct
        if off_diagonal[hole_index, electron_index] / matrix.sum() < 0.50:
            label = "CT delocalizzato (%s)" % dominant_ct
        return label, dominant_ct
    return "Misto LE/CT (%s)" % dominant_ct, dominant_ct


class CubeStateAnalyzer:
    """Analyse all available NTO pairs for one converged CP2K state."""

    def analyze(
        self,
        state: ExcitedState,
        pairs: Dict[int, Dict[str, CubeAssignment]],
        fragments: FragmentSet,
        stride=2,
        progress: Optional[ProgressCallback] = None,
        cancel_event=None,
    ) -> StateAnalysis:
        stride3 = _normalise_stride(stride)
        fragments.validate()
        if not pairs:
            raise CP2KCubeError("Nessuna coppia NTO assegnata allo stato %d." % state.index)

        pair_indices = sorted(pairs)
        for pair_index in pair_indices:
            roles = pairs[pair_index]
            if "hole" not in roles or "particle" not in roles:
                missing = "hole" if "hole" not in roles else "particle"
                raise CP2KCubeError(
                    "Stato %d, coppia NTO %d: manca il cube %s."
                    % (state.index, pair_index, missing)
                )

        reference = pairs[pair_indices[0]]["hole"].header
        for pair_index in pair_indices:
            for role in ("hole", "particle"):
                assert_compatible(reference, pairs[pair_index][role].header)

        warnings = [
            "Omega cube usa una partizione Voronoi nello spazio reale; non è la popolazione Lowdin/Mulliken AO."
        ]
        if state.nto_eigenvalues:
            pair_weights = []
            for pair_index in pair_indices:
                try:
                    value = float(state.nto_eigenvalues[pair_index - 1])
                except IndexError as exc:
                    raise CP2KCubeError(
                        "Nessun autovalore CP2K per lo stato %d, coppia NTO %d."
                        % (state.index, pair_index)
                    ) from exc
                if value <= 0.0:
                    raise CP2KCubeError(
                        "Autovalore NTO non positivo per lo stato %d, coppia %d."
                        % (state.index, pair_index)
                    )
                pair_weights.append(value)
        elif len(pair_indices) == 1:
            pair_weights = [1.0]
            warnings.append("Autovalore NTO assente: alla singola coppia è stato assegnato peso 1.")
        else:
            raise CP2KCubeError(
                "Più coppie NTO richiedono gli autovalori presenti nell'output CP2K."
            )

        if len(pair_indices) > 1:
            warnings.append(
                "Con più coppie, Omega è l'approssimazione NTO-diagonale: i termini d'interferenza non sono ricostruibili in modo affidabile dai soli cube."
            )

        raw_omega = np.zeros((len(fragments.fragments), len(fragments.fragments)), dtype=float)
        hole_centroids = []
        electron_centroids = []
        hole_r2 = []
        electron_r2 = []
        total_files = 2 * len(pair_indices)
        file_number = 0

        for pair_index, weight in zip(pair_indices, pair_weights):
            populations = {}
            for role in ("hole", "particle"):
                assignment = pairs[pair_index][role]

                def local_progress(fraction, message, offset=file_number):
                    if progress is not None:
                        progress((offset + fraction) / total_files, message)

                populations[role] = _integrate_orbital(
                    assignment,
                    fragments,
                    stride3,
                    progress=local_progress,
                    cancel_event=cancel_event,
                )
                file_number += 1

            hole = populations["hole"]
            electron = populations["particle"]
            raw_omega += weight * np.outer(hole.fragment_population, electron.fragment_population)
            hole_centroids.append(hole.centroid_angstrom)
            electron_centroids.append(electron.centroid_angstrom)
            hole_r2.append(hole.mean_r2_angstrom2)
            electron_r2.append(electron.mean_r2_angstrom2)
            if abs(hole.norm - 1.0) > 0.05:
                warnings.append(
                    "%s: norma integrata %.4f (atteso circa 1)." % (pairs[pair_index]["hole"].path.name, hole.norm)
                )
            if abs(electron.norm - 1.0) > 0.05:
                warnings.append(
                    "%s: norma integrata %.4f (atteso circa 1)."
                    % (pairs[pair_index]["particle"].path.name, electron.norm)
                )

        omega_sum = float(raw_omega.sum())
        if omega_sum <= 0.0:
            raise CP2KCubeError("La matrice Omega risultante ha somma nulla.")
        omega = raw_omega / omega_sum
        descriptors = omega_descriptors(omega)
        normalised_weights = np.asarray(pair_weights, dtype=float) / sum(pair_weights)
        mean_h = np.sum(normalised_weights[:, None] * np.asarray(hole_centroids), axis=0)
        mean_e = np.sum(normalised_weights[:, None] * np.asarray(electron_centroids), axis=0)
        descriptors["d_centroid_cube"] = float(np.linalg.norm(mean_e - mean_h))
        mean_square_separation = 0.0
        for probability, centre_h, centre_e, r2_h, r2_e in zip(
            normalised_weights, hole_centroids, electron_centroids, hole_r2, electron_r2
        ):
            mean_square_separation += probability * (
                r2_h + r2_e - 2.0 * float(np.dot(centre_h, centre_e))
            )
        descriptors["d_exc_cube_diag"] = math.sqrt(max(0.0, mean_square_separation))
        descriptors["PRNTO"] = state.pr_nto if state.pr_nto is not None else 1.0
        entropy = state.nto_entropy
        if entropy is not None:
            descriptors["S_HE"] = entropy
            descriptors["Z_HE"] = 2.0**entropy
        descriptors["captured_NTO_weight"] = float(sum(pair_weights))
        printed_weight = state.nto_sum if state.nto_eigenvalues else float(sum(pair_weights))
        descriptors["loaded_NTO_fraction"] = (
            float(sum(pair_weights)) / printed_weight if printed_weight > 0.0 else 1.0
        )
        if descriptors["loaded_NTO_fraction"] < 0.90:
            warnings.append(
                "I cube caricati coprono solo %.1f%% del peso NTO stampato da CP2K; la classificazione può non rappresentare l'intero stato."
                % (100.0 * descriptors["loaded_NTO_fraction"])
            )
        character, dominant = classify_state(omega, fragments.names)

        return StateAnalysis(
            state_index=state.index,
            omega=omega,
            omega_raw_sum=omega_sum,
            fragment_names=fragments.names,
            hole_population=omega.sum(axis=1),
            electron_population=omega.sum(axis=0),
            descriptors=descriptors,
            character=character,
            dominant_channel=dominant,
            pair_weights_used=pair_weights,
            grid_stride=stride3,
            approximate=True,
            warnings=warnings,
        )
