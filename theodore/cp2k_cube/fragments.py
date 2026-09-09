"""Editable fragment definitions shared by the GUI and analyser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np

from .chemistry import connected_components, infer_bonds
from .errors import FragmentError
from .models import Fragment


FRAGMENT_COLORS = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2",
    "#FF9DA6", "#9D755D", "#BAB0AC", "#8C6D31", "#17BECF", "#9467BD",
]


class FragmentSet:
    """A complete, non-overlapping assignment of atoms to fragments."""

    schema_version = 1

    def __init__(self, n_atoms: int, fragments: Optional[Sequence[Fragment]] = None):
        self.n_atoms = int(n_atoms)
        self.fragments: List[Fragment] = list(fragments or [])

    @classmethod
    def one_fragment(cls, atoms, name: str = "Molecola"):
        return cls(
            len(atoms),
            [Fragment(name=name, atom_indices=list(range(1, len(atoms) + 1)), color=FRAGMENT_COLORS[0])],
        )

    @classmethod
    def from_connected_components(cls, atoms):
        bonds = infer_bonds(atoms)
        components = connected_components(len(atoms), bonds)
        fragments = [
            Fragment(
                name=("Molecola" if len(components) == 1 else "Frammento %d" % (index + 1)),
                atom_indices=component,
                color=FRAGMENT_COLORS[index % len(FRAGMENT_COLORS)],
            )
            for index, component in enumerate(components)
        ]
        return cls(len(atoms), fragments)

    @property
    def names(self) -> List[str]:
        return [fragment.name for fragment in self.fragments]

    def copy(self):
        return FragmentSet(
            self.n_atoms,
            [Fragment(f.name, list(f.atom_indices), f.color) for f in self.fragments],
        )

    def validate(self, require_complete: bool = True):
        if not self.fragments:
            raise FragmentError("Definire almeno un frammento.")
        names = [fragment.name.strip() for fragment in self.fragments]
        if any(not name for name in names):
            raise FragmentError("I nomi dei frammenti non possono essere vuoti.")
        if len(names) != len(set(names)):
            raise FragmentError("I nomi dei frammenti devono essere univoci.")

        seen = {}
        for fragment_index, fragment in enumerate(self.fragments):
            if not fragment.atom_indices:
                raise FragmentError("Il frammento '%s' non contiene atomi." % fragment.name)
            for atom_index in fragment.atom_indices:
                if atom_index < 1 or atom_index > self.n_atoms:
                    raise FragmentError(
                        "Indice atomico %d fuori dall'intervallo 1-%d." % (atom_index, self.n_atoms)
                    )
                if atom_index in seen:
                    raise FragmentError(
                        "L'atomo %d appartiene sia a '%s' sia a '%s'."
                        % (atom_index, self.fragments[seen[atom_index]].name, fragment.name)
                    )
                seen[atom_index] = fragment_index
        if require_complete:
            missing = sorted(set(range(1, self.n_atoms + 1)) - set(seen))
            if missing:
                raise FragmentError("Atomi non assegnati: %s." % ", ".join(map(str, missing)))
        return True

    def atom_to_fragment(self) -> np.ndarray:
        self.validate(require_complete=True)
        output = np.full(self.n_atoms, -1, dtype=np.int32)
        for fragment_index, fragment in enumerate(self.fragments):
            output[np.asarray(fragment.atom_indices, dtype=int) - 1] = fragment_index
        return output

    def fragment_for_atom(self, atom_index: int) -> Optional[int]:
        for fragment_index, fragment in enumerate(self.fragments):
            if atom_index in fragment.atom_indices:
                return fragment_index
        return None

    def add(self, name: str, atom_indices: Iterable[int], color: Optional[str] = None) -> int:
        clean_name = name.strip()
        if not clean_name:
            raise FragmentError("Il nome del frammento non può essere vuoto.")
        if clean_name in self.names:
            raise FragmentError("Esiste già un frammento chiamato '%s'." % clean_name)
        atoms = sorted(set(int(value) for value in atom_indices))
        if not atoms:
            raise FragmentError("Selezionare almeno un atomo.")
        # Assignment is exclusive: selected atoms are moved from their old fragments.
        for fragment in self.fragments:
            fragment.atom_indices = [index for index in fragment.atom_indices if index not in atoms]
        self.fragments = [fragment for fragment in self.fragments if fragment.atom_indices]
        fragment = Fragment(
            clean_name,
            atoms,
            color or FRAGMENT_COLORS[len(self.fragments) % len(FRAGMENT_COLORS)],
        )
        self.fragments.append(fragment)
        return len(self.fragments) - 1

    def assign(self, atom_indices: Iterable[int], target_fragment: int):
        if target_fragment < 0 or target_fragment >= len(self.fragments):
            raise FragmentError("Frammento di destinazione non valido.")
        target = self.fragments[target_fragment]
        atoms = sorted(set(int(value) for value in atom_indices))
        if not atoms:
            raise FragmentError("Selezionare almeno un atomo.")
        for atom_index in atoms:
            if atom_index < 1 or atom_index > self.n_atoms:
                raise FragmentError("Indice atomico %d non valido." % atom_index)
        for index, fragment in enumerate(self.fragments):
            if index != target_fragment:
                fragment.atom_indices = [atom for atom in fragment.atom_indices if atom not in atoms]
        target.atom_indices = sorted(set(target.atom_indices).union(atoms))
        self.fragments = [fragment for fragment in self.fragments if fragment.atom_indices]

    def rename(self, fragment_index: int, name: str):
        clean_name = name.strip()
        if not clean_name:
            raise FragmentError("Il nome del frammento non può essere vuoto.")
        if clean_name in self.names and self.fragments[fragment_index].name != clean_name:
            raise FragmentError("Esiste già un frammento chiamato '%s'." % clean_name)
        self.fragments[fragment_index].name = clean_name

    def merge_into(self, source_fragment: int, target_fragment: int):
        if source_fragment == target_fragment:
            return
        source = self.fragments[source_fragment]
        target = self.fragments[target_fragment]
        target.atom_indices = sorted(set(target.atom_indices).union(source.atom_indices))
        del self.fragments[source_fragment]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "n_atoms": self.n_atoms,
            "fragments": [fragment.to_dict() for fragment in self.fragments],
        }

    def save(self, path):
        destination = Path(path)
        destination.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict, expected_n_atoms: Optional[int] = None):
        if int(data.get("schema_version", 1)) != 1:
            raise FragmentError("Versione del file frammenti non supportata.")
        n_atoms = int(data["n_atoms"])
        if expected_n_atoms is not None and n_atoms != int(expected_n_atoms):
            raise FragmentError(
                "Il file frammenti contiene %d atomi, ma la geometria ne contiene %d."
                % (n_atoms, expected_n_atoms)
            )
        fragments = [
            Fragment(
                name=item["name"],
                atom_indices=[int(value) for value in item["atom_indices"]],
                color=item.get("color", FRAGMENT_COLORS[index % len(FRAGMENT_COLORS)]),
            )
            for index, item in enumerate(data["fragments"])
        ]
        result = cls(n_atoms, fragments)
        result.validate()
        return result

    @classmethod
    def load(cls, path, expected_n_atoms: Optional[int] = None):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            raise FragmentError("File frammenti non valido: %s" % exc) from exc
        return cls.from_dict(data, expected_n_atoms=expected_n_atoms)
