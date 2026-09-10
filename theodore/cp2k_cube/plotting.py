"""Matplotlib rendering helpers for the desktop GUI."""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from .chemistry import element_color, infer_bonds
from .models import BOHR_TO_ANGSTROM, PreviewVolume

try:  # Optional high-quality surfaces.
    from skimage.measure import marching_cubes
except ImportError:  # pragma: no cover - installation dependent
    marching_cubes = None


def _equal_3d_axes(ax, coordinates: np.ndarray, pad: float = 1.0):
    if coordinates.size == 0:
        return
    low = coordinates.min(axis=0)
    high = coordinates.max(axis=0)
    centre = 0.5 * (low + high)
    radius = max(0.5 * float(np.max(high - low)) + pad, 1.0)
    ax.set_xlim(centre[0] - radius, centre[0] + radius)
    ax.set_ylim(centre[1] - radius, centre[1] + radius)
    ax.set_zlim(centre[2] - radius, centre[2] + radius)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:  # older Matplotlib
        pass


def draw_molecule(ax, atoms, fragments=None, selected: Optional[Sequence[int]] = None, labels=True):
    ax.clear()
    if not atoms:
        ax.text2D(0.5, 0.5, "Caricare una geometria", transform=ax.transAxes, ha="center")
        return
    coords = np.asarray([atom.position_angstrom for atom in atoms], dtype=float)
    for i, j in infer_bonds(atoms):
        xyz = coords[[i, j]]
        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#8A8A8A", linewidth=1.6, zorder=1)

    selected = set(selected or [])
    atom_fragment = None
    if fragments is not None:
        try:
            atom_fragment = fragments.atom_to_fragment()
        except Exception:
            atom_fragment = None
    for index, atom in enumerate(atoms):
        if atom_fragment is not None:
            color = fragments.fragments[int(atom_fragment[index])].color
        else:
            color = element_color(atom.atomic_number)
        edge = "#FFD43B" if atom.index in selected else "#1C1C1C"
        linewidth = 2.6 if atom.index in selected else 0.7
        size = 78 if atom.atomic_number == 1 else 145
        ax.scatter(*coords[index], s=size, color=color, edgecolor=edge, linewidth=linewidth, depthshade=True, zorder=3)
        if labels:
            ax.text(*coords[index], " %s%d" % (atom.symbol, atom.index), fontsize=7, color="#202020")

    ax.set_xlabel("x / Å")
    ax.set_ylabel("y / Å")
    ax.set_zlabel("z / Å")
    _equal_3d_axes(ax, coords, pad=1.1)
    ax.grid(False)


def draw_omega(ax, analysis, annotate: bool = True):
    ax.clear()
    image = ax.imshow(analysis.omega, origin="upper", cmap="magma", vmin=0.0, vmax=max(analysis.omega.max(), 1e-12))
    names = analysis.fragment_names
    ax.set_xticks(np.arange(len(names)), labels=names, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(names)), labels=names)
    ax.set_xlabel("Frammento particle / elettrone")
    ax.set_ylabel("Frammento hole")
    ax.set_title("S%d — %s" % (analysis.state_index, analysis.character))
    if annotate and len(names) <= 12:
        cutoff = analysis.omega.max() * 0.55
        for row in range(len(names)):
            for column in range(len(names)):
                value = analysis.omega[row, column]
                ax.text(
                    column,
                    row,
                    "%.3f" % value,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if value >= cutoff else "black",
                )
    return image


def _voxel_coordinates(preview: PreviewVolume, mask: np.ndarray, limit: int = 18000):
    indices = np.argwhere(mask)
    if len(indices) > limit:
        # Deterministic regular sampling gives a stable visual while bounding draw time.
        indices = indices[:: max(1, len(indices) // limit)][:limit]
    return preview.index_to_angstrom(indices)


def _surface_or_points(ax, preview: PreviewVolume, level: float, color: str, alpha: float):
    values = np.asarray(preview.values, dtype=float)
    if marching_cubes is not None and values.min() < level < values.max():
        vertices, faces, _, _ = marching_cubes(values, level=level)
        xyz = preview.index_to_angstrom(vertices)
        if len(faces) > 60000:
            faces = faces[:: int(np.ceil(len(faces) / 60000.0))]
        ax.plot_trisurf(
            xyz[:, 0], xyz[:, 1], xyz[:, 2], triangles=faces, color=color, alpha=alpha,
            linewidth=0.0, antialiased=False, shade=True,
        )
        return xyz

    if level > 0:
        mask = values >= level
    else:
        mask = values <= level
    xyz = _voxel_coordinates(preview, mask)
    if xyz.size:
        ax.scatter(xyz[:, 0], xyz[:, 1], xyz[:, 2], s=3, color=color, alpha=min(0.75, alpha + 0.2), linewidth=0)
    return xyz


def _draw_nto_molecule(ax, atoms):
    coordinates = np.asarray([atom.position_angstrom for atom in atoms], dtype=float)
    if not atoms:
        return np.empty((0, 3))
    for i, j in infer_bonds(atoms):
        xyz = coordinates[[i, j]]
        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#8A8A8A", linewidth=1.1, alpha=0.75)
    for index, atom in enumerate(atoms):
        ax.scatter(
            *coordinates[index],
            s=25 if atom.atomic_number == 1 else 48,
            color=element_color(atom.atomic_number),
            edgecolor="#333333",
            linewidth=0.35,
        )
    return coordinates


def _finish_nto_axes(ax, coordinates, title):
    nonempty = [item for item in coordinates if item.size]
    combined = np.vstack(nonempty) if nonempty else np.empty((0, 3))
    _equal_3d_axes(ax, combined, pad=0.8)
    ax.set_xlabel("x / Å")
    ax.set_ylabel("y / Å")
    ax.set_zlabel("z / Å")
    ax.set_title(title)
    ax.grid(False)
    if marching_cubes is None:
        ax.text2D(
            0.01, 0.01, "Anteprima a punti; installare scikit-image per isosuperfici",
            transform=ax.transAxes, fontsize=8, color="#555555",
        )


def draw_nto(ax, orbital: PreviewVolume, role: str, relative_level: float = 0.12):
    """Draw one signed hole or particle NTO without overlaying its partner."""

    styles = {
        "hole": ("#2F6BFF", "#E53935", "NTO hole / lacuna (blu/rosso)"),
        "particle": ("#FF9F1C", "#22A06B", "NTO particle / elettrone (arancio/verde)"),
    }
    try:
        positive_color, negative_color, title = styles[role]
    except KeyError as exc:
        raise ValueError("Il ruolo NTO deve essere 'hole' o 'particle'.") from exc

    ax.clear()
    coordinates = [_draw_nto_molecule(ax, orbital.atoms)]
    maximum = float(np.max(np.abs(orbital.values)))
    if maximum > 0.0:
        coordinates.append(_surface_or_points(ax, orbital, relative_level * maximum, positive_color, 0.5))
        coordinates.append(_surface_or_points(ax, orbital, -relative_level * maximum, negative_color, 0.5))
    _finish_nto_axes(ax, coordinates, title)


def draw_nto_pair(ax, hole: PreviewVolume, particle: PreviewVolume, relative_level: float = 0.12):
    """Draw positive/negative lobes of a matched hole/particle NTO pair."""

    ax.clear()
    coordinates = [_draw_nto_molecule(ax, hole.atoms)]
    max_hole = float(np.max(np.abs(hole.values)))
    max_particle = float(np.max(np.abs(particle.values)))
    if max_hole > 0.0:
        coordinates.append(_surface_or_points(ax, hole, relative_level * max_hole, "#2F6BFF", 0.42))
        coordinates.append(_surface_or_points(ax, hole, -relative_level * max_hole, "#E53935", 0.42))
    if max_particle > 0.0:
        coordinates.append(_surface_or_points(ax, particle, relative_level * max_particle, "#FF9F1C", 0.42))
        coordinates.append(_surface_or_points(ax, particle, -relative_level * max_particle, "#22A06B", 0.42))
    _finish_nto_axes(ax, coordinates, "NTO hole (blu/rosso) + particle (arancio/verde)")
