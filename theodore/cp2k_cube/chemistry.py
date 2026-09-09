"""Small dependency-free chemistry helpers for geometry display."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

import numpy as np


SYMBOLS = [
    "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg",
    "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb",
    "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In",
    "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At",
    "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk",
    "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt",
    "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
]


# Covalent radii in angstrom; unknown elements use a conservative fallback.
COVALENT_RADII = {
    1: 0.31, 5: 0.84, 6: 0.76, 7: 0.71, 8: 0.66, 9: 0.57,
    14: 1.11, 15: 1.07, 16: 1.05, 17: 1.02, 26: 1.32, 27: 1.26,
    28: 1.24, 29: 1.32, 30: 1.22, 35: 1.20, 44: 1.46, 46: 1.39,
    47: 1.45, 53: 1.39, 75: 1.51, 77: 1.41, 78: 1.36, 79: 1.36,
}


ELEMENT_COLORS = {
    1: "#F2F2F2", 6: "#4A4A4A", 7: "#3050F8", 8: "#FF0D0D",
    9: "#90E050", 15: "#FF8000", 16: "#FFFF30", 17: "#1FF01F",
    26: "#E06633", 35: "#A62929", 44: "#248F8F", 53: "#940094",
    77: "#175487", 78: "#D0D0E0", 79: "#FFD123",
}


def symbol_for_atomic_number(atomic_number: int) -> str:
    if 0 < atomic_number < len(SYMBOLS):
        return SYMBOLS[atomic_number]
    return "X"


def covalent_radius(atomic_number: int) -> float:
    return COVALENT_RADII.get(int(atomic_number), 1.25)


def element_color(atomic_number: int) -> str:
    return ELEMENT_COLORS.get(int(atomic_number), "#B0B0B0")


def infer_bonds(atoms: Sequence, scale: float = 1.22) -> List[Tuple[int, int]]:
    """Infer bonds from covalent radii; returned indices are zero based."""

    if len(atoms) < 2:
        return []
    coords = np.asarray([a.position_angstrom for a in atoms], dtype=float)
    bonds = []
    for i in range(len(atoms) - 1):
        delta = coords[i + 1 :] - coords[i]
        distances = np.linalg.norm(delta, axis=1)
        for rel, distance in enumerate(distances):
            j = i + rel + 1
            cutoff = scale * (
                covalent_radius(atoms[i].atomic_number)
                + covalent_radius(atoms[j].atomic_number)
            )
            # Avoid coincident atoms and overly generous metal contacts.
            if 0.2 < distance <= cutoff:
                bonds.append((i, j))
    return bonds


def connected_components(n_atoms: int, bonds: Iterable[Tuple[int, int]]) -> List[List[int]]:
    adjacency = [set() for _ in range(n_atoms)]
    for i, j in bonds:
        adjacency[i].add(j)
        adjacency[j].add(i)
    seen = set()
    components = []
    for start in range(n_atoms):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component = []
        while stack:
            current = stack.pop()
            component.append(current + 1)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted(component))
    return components
