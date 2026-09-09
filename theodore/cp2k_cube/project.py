"""High-level project model used by the CP2K cube GUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

from .analysis import CubeStateAnalyzer
from .cube import assert_compatible, discover_cube
from .errors import CP2KCubeError, CubeCompatibilityError
from .fragments import FragmentSet
from .models import Atom, CP2KRun, CubeAssignment, StateAnalysis
from .output_parser import CP2KOutputParser


class CP2KCubeProject:
    schema_version = 1

    def __init__(self):
        self.output: Optional[CP2KRun] = None
        self.assignments: List[CubeAssignment] = []
        self.fragments: Optional[FragmentSet] = None
        self.analyses: Dict[int, StateAnalysis] = {}
        self.project_path: Optional[Path] = None

    @property
    def atoms(self) -> List[Atom]:
        if self.output is not None and self.output.atoms:
            return self.output.atoms
        if self.assignments:
            return self.assignments[0].header.atoms
        return []

    @property
    def state_indices(self) -> List[int]:
        return [state.index for state in self.output.states] if self.output else []

    def load_output(self, path):
        run = CP2KOutputParser().parse(path)
        if run.atoms:
            if self.assignments:
                self._check_output_cube_geometry(run.atoms, self.assignments[0])
        self.output = run
        if run.atoms:
            self.fragments = FragmentSet.from_connected_components(run.atoms)
        elif self.assignments:
            self.fragments = FragmentSet.from_connected_components(self.assignments[0].header.atoms)
        self.analyses.clear()
        return run

    def add_cubes(self, paths: Iterable) -> List[CubeAssignment]:
        existing = {assignment.path.resolve() for assignment in self.assignments}
        added = []
        for path in paths:
            assignment = discover_cube(path)
            if assignment.path.resolve() in existing:
                continue
            reference = self.assignments[0].header if self.assignments else (added[0].header if added else None)
            if reference is not None:
                assert_compatible(reference, assignment.header)
            if self.output is not None and self.output.atoms:
                self._check_output_cube_geometry(self.output.atoms, assignment)
            existing.add(assignment.path.resolve())
            added.append(assignment)
        self.assignments.extend(added)
        if self.fragments is None and self.assignments:
            self.fragments = FragmentSet.from_connected_components(self.assignments[0].header.atoms)
        self.analyses.clear()
        return added

    @staticmethod
    def _check_output_cube_geometry(output_atoms, assignment: CubeAssignment):
        cube_atoms = assignment.header.atoms
        if len(output_atoms) != len(cube_atoms):
            raise CubeCompatibilityError(
                "La geometria CP2K contiene %d atomi, il cube %s ne contiene %d."
                % (len(output_atoms), assignment.path.name, len(cube_atoms))
            )
        for output_atom, cube_atom in zip(output_atoms, cube_atoms):
            if output_atom.atomic_number != cube_atom.atomic_number or not np.allclose(
                output_atom.position_bohr, cube_atom.position_bohr, atol=3.0e-5, rtol=0.0
            ):
                raise CubeCompatibilityError(
                    "La geometria di %s non coincide con quella dell'output CP2K (atomo %d)."
                    % (assignment.path.name, output_atom.index)
                )

    def remove_assignment(self, path):
        target = Path(path).resolve()
        self.assignments = [item for item in self.assignments if item.path.resolve() != target]
        self.analyses.clear()

    def update_assignment(self, path, state_index: int, pair_index: int, role: str):
        target = Path(path).resolve()
        if role not in ("hole", "particle"):
            raise CP2KCubeError("Il ruolo deve essere 'hole' o 'particle'.")
        if int(state_index) < 1 or int(pair_index) < 1:
            raise CP2KCubeError("Stato e coppia NTO devono essere interi positivi.")
        for assignment in self.assignments:
            if assignment.path.resolve() == target:
                assignment.state_index = int(state_index)
                assignment.pair_index = int(pair_index)
                assignment.role = role
                assignment.detection_note = "associazione modificata dall'utente"
                self.analyses.clear()
                return assignment
        raise KeyError(path)

    def assignment_issues(self) -> Dict[Path, str]:
        issues: Dict[Path, str] = {}
        seen = {}
        valid_states = set(self.state_indices)
        for assignment in self.assignments:
            if assignment.role not in ("hole", "particle"):
                issues[assignment.path] = "ruolo non definito"
                continue
            if assignment.state_index is None:
                issues[assignment.path] = "stato elettronico non definito"
                continue
            if valid_states and assignment.state_index not in valid_states:
                issues[assignment.path] = "stato %d assente nell'output" % assignment.state_index
                continue
            if assignment.pair_index is None:
                issues[assignment.path] = "coppia NTO non definita"
                continue
            if assignment.key in seen:
                issues[assignment.path] = "duplicato di %s" % seen[assignment.key].name
                issues[seen[assignment.key]] = "duplicato di %s" % assignment.path.name
            else:
                seen[assignment.key] = assignment.path
        return issues

    def pairs_for_state(self, state_index: int) -> Dict[int, Dict[str, CubeAssignment]]:
        pairs: Dict[int, Dict[str, CubeAssignment]] = {}
        issues = self.assignment_issues()
        for assignment in self.assignments:
            if assignment.path in issues or assignment.state_index != state_index:
                continue
            pairs.setdefault(int(assignment.pair_index), {})[assignment.role] = assignment
        return pairs

    def available_complete_states(self) -> List[int]:
        output = []
        for state_index in self.state_indices:
            pairs = self.pairs_for_state(state_index)
            if pairs and all("hole" in roles and "particle" in roles for roles in pairs.values()):
                output.append(state_index)
        return output

    def analyze_state(self, state_index: int, stride=2, progress=None, cancel_event=None):
        if self.output is None:
            raise CP2KCubeError("Caricare prima il file .out di CP2K.")
        if self.fragments is None:
            raise CP2KCubeError("Definire i frammenti molecolari.")
        state = self.output.state(int(state_index))
        result = CubeStateAnalyzer().analyze(
            state,
            self.pairs_for_state(state.index),
            self.fragments,
            stride=stride,
            progress=progress,
            cancel_event=cancel_event,
        )
        self.analyses[state.index] = result
        return result

    def invalidate_analyses(self):
        self.analyses.clear()

    def to_dict(self, base_dir: Optional[Path] = None) -> dict:
        output_path = None
        if self.output is not None:
            output_path = self.output.path
            if base_dir is not None:
                try:
                    output_path = output_path.resolve().relative_to(base_dir.resolve())
                except ValueError:
                    pass
        return {
            "schema_version": self.schema_version,
            "cp2k_output": str(output_path) if output_path is not None else None,
            "cube_files": [assignment.to_dict(base_dir=base_dir) for assignment in self.assignments],
            "fragments": self.fragments.to_dict() if self.fragments is not None else None,
        }

    def save(self, path):
        destination = Path(path).expanduser().resolve()
        destination.write_text(
            json.dumps(self.to_dict(base_dir=destination.parent), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.project_path = destination

    @classmethod
    def load(cls, path):
        source = Path(path).expanduser().resolve()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CP2KCubeError("Progetto non valido: %s" % exc) from exc
        if int(data.get("schema_version", 0)) != cls.schema_version:
            raise CP2KCubeError("Versione del progetto non supportata.")
        result = cls()
        output_path = data.get("cp2k_output")
        if output_path:
            resolved = Path(output_path)
            if not resolved.is_absolute():
                resolved = source.parent / resolved
            result.load_output(resolved)
        cube_paths = []
        for item in data.get("cube_files", []):
            cube_path = Path(item["path"])
            if not cube_path.is_absolute():
                cube_path = source.parent / cube_path
            cube_paths.append(cube_path)
        if cube_paths:
            result.add_cubes(cube_paths)
            by_path = {assignment.path.resolve(): assignment for assignment in result.assignments}
            for item, cube_path in zip(data.get("cube_files", []), cube_paths):
                assignment = by_path[cube_path.resolve()]
                assignment.role = item.get("role", assignment.role)
                assignment.state_index = item.get("state_index", assignment.state_index)
                assignment.pair_index = item.get("pair_index", assignment.pair_index)
        if data.get("fragments") is not None:
            result.fragments = FragmentSet.from_dict(
                data["fragments"], expected_n_atoms=len(result.atoms) or None
            )
        result.project_path = source
        return result
