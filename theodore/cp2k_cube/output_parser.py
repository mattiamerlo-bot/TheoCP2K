"""Parser for converged CP2K TDDFPT output.

Only final property tables are consumed.  In particular, the repeated Davidson
iteration tables are deliberately ignored because those energies are not the
reported converged excitation energies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from .chemistry import symbol_for_atomic_number
from .errors import CP2KOutputError
from .models import Atom, BOHR_TO_ANGSTROM, CP2KRun, ExcitedState, OrbitalTransition


_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"


def _as_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


class CP2KOutputParser:
    """Read geometry and excited-state properties from a CP2K output file."""

    _state_row = re.compile(
        rf"^\s*TDDFPT\|\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$"
    )
    _nto_state = re.compile(rf"^\s*STATE\s+NR\.\s*(\d+)\s+({_FLOAT})\s+eV", re.I)
    _nto_pair = re.compile(
        rf"Particle-Hole\s+state:\s*(\d+).*?Eigenvalue:\s*({_FLOAT}).*?Sum\s+Eigv:\s*({_FLOAT})",
        re.I,
    )
    _transition_state = re.compile(rf"^\s*(\d+)\s+({_FLOAT})\s+eV\s*$", re.I)
    _transition_row = re.compile(rf"^\s*(\d+)\s+(\d+)\s+({_FLOAT})\s*$")
    _geometry_row = re.compile(
        rf"^\s*(\d+)\s+(\d+)\s+([A-Za-z]{{1,3}})\s+(\d+)\s+"
        rf"({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})(?:\s+.*)?$"
    )

    def parse(self, path) -> CP2KRun:
        source = Path(path).expanduser().resolve()
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise CP2KOutputError("Impossibile leggere l'output CP2K: %s" % exc) from exc

        cp2k_version = self._parse_version(lines)
        atoms = self._parse_geometry(lines)
        rows = self._parse_final_state_table(lines)
        if not rows:
            raise CP2KOutputError(
                "Nessuna tabella TDDFPT finale con energia e oscillator strength trovata. "
                "Verificare che il calcolo sia convergente e che la tabella finale sia presente."
            )

        multiplicity, spin_label = self._parse_spin(lines)
        states = [
            ExcitedState(
                index=index,
                energy_ev=energy,
                transition_dipole_au=(mux, muy, muz),
                oscillator_strength=oscillator,
                multiplicity=multiplicity,
            )
            for index, energy, mux, muy, muz, oscillator in rows
        ]
        by_index = {state.index: state for state in states}

        for state_index, values in self._parse_nto_eigenvalues(lines).items():
            if state_index in by_index:
                by_index[state_index].nto_eigenvalues = values

        for state_index, transitions in self._parse_transitions(lines).items():
            if state_index in by_index:
                by_index[state_index].transitions = transitions

        for state_index, descriptors in self._parse_exciton_descriptors(lines).items():
            if state_index in by_index:
                by_index[state_index].exciton = descriptors

        electron_centres, hole_centres = self._parse_relative_centres(lines)
        for state_index, centre in electron_centres.items():
            if state_index in by_index:
                by_index[state_index].electron_centroid_angstrom = centre
        for state_index, centre in hole_centres.items():
            if state_index in by_index:
                by_index[state_index].hole_centroid_angstrom = centre

        warnings = []
        if not atoms:
            warnings.append("Geometria non trovata nell'output; verrà usata quella dei cube.")
        if not any(state.nto_eigenvalues for state in states):
            warnings.append("Autovalori NTO non trovati; per ogni stato è utilizzabile una sola coppia con peso 1.")
        if not any("TDDFPT run converged" in line for line in lines):
            warnings.append("Il marcatore 'TDDFPT run converged' non è presente.")

        return CP2KRun(
            path=source,
            states=states,
            atoms=atoms,
            cp2k_version=cp2k_version,
            spin_label=spin_label,
            warnings=warnings,
        )

    @staticmethod
    def _parse_version(lines: Iterable[str]) -> Optional[str]:
        pattern = re.compile(r"CP2K\s+version\s+([\w.+-]+)", re.I)
        value = None
        for line in lines:
            if "version string" not in line:
                continue
            match = pattern.search(line)
            if match:
                value = match.group(1)
        return value

    def _parse_final_state_table(self, lines: List[str]) -> List[Tuple[int, float, float, float, float, float]]:
        """Return the last final TDDFPT property table in the file."""

        tables = []
        for index, line in enumerate(lines):
            if not ("State" in line and "Excitation" in line and "Oscillator" in line):
                continue
            rows = []
            started = False
            for candidate in lines[index + 1 :]:
                match = self._state_row.match(candidate)
                if match:
                    started = True
                    rows.append(
                        (
                            int(match.group(1)),
                            _as_float(match.group(2)),
                            _as_float(match.group(3)),
                            _as_float(match.group(4)),
                            _as_float(match.group(5)),
                            _as_float(match.group(6)),
                        )
                    )
                    continue
                if started:
                    break
            if rows:
                tables.append(rows)
        return tables[-1] if tables else []

    @staticmethod
    def _parse_spin(lines: Iterable[str]) -> Tuple[Optional[int], Optional[str]]:
        multiplicity = None
        label = None
        mult_re = re.compile(r"R?-?TDDFPT\s+states\s+of\s+multiplicity\s+(\d+)", re.I)
        label_re = re.compile(r"Spin symmetry of excitations\s+(.+?)\s*$", re.I)
        for line in lines:
            match = mult_re.search(line)
            if match:
                multiplicity = int(match.group(1))
            match = label_re.search(line)
            if match:
                label = match.group(1).strip()
        return multiplicity, label

    def _parse_geometry(self, lines: List[str]) -> List[Atom]:
        geometries = []
        for start, line in enumerate(lines):
            if "MODULE QUICKSTEP: ATOMIC COORDINATES IN ANGSTROM" not in line:
                continue
            atoms = []
            data_started = False
            for candidate in lines[start + 1 :]:
                match = self._geometry_row.match(candidate)
                if match:
                    data_started = True
                    atomic_number = int(match.group(4))
                    symbol = match.group(3).capitalize() or symbol_for_atomic_number(atomic_number)
                    position_angstrom = np.asarray(
                        [_as_float(match.group(i)) for i in (5, 6, 7)], dtype=float
                    )
                    atoms.append(
                        Atom(
                            index=int(match.group(1)),
                            atomic_number=atomic_number,
                            symbol=symbol,
                            position_bohr=position_angstrom / BOHR_TO_ANGSTROM,
                        )
                    )
                elif data_started:
                    break
            if atoms:
                geometries.append(atoms)
        return geometries[-1] if geometries else []

    def _parse_nto_eigenvalues(self, lines: List[str]) -> Dict[int, List[float]]:
        values: Dict[int, List[float]] = {}
        in_section = False
        current = None
        for line in lines:
            if "Natural Orbital analysis" in line:
                in_section = True
                current = None
                continue
            if not in_section:
                continue
            match = self._nto_state.match(line)
            if match:
                current = int(match.group(1))
                values[current] = []
                continue
            match = self._nto_pair.search(line)
            if match and current is not None:
                pair_index = int(match.group(1))
                while len(values[current]) < pair_index:
                    values[current].append(0.0)
                values[current][pair_index - 1] = _as_float(match.group(2))
                continue
            if current is not None and "Exciton descriptors" in line:
                break
        return values

    def _parse_transitions(self, lines: List[str]) -> Dict[int, List[OrbitalTransition]]:
        transitions: Dict[int, List[OrbitalTransition]] = {}
        in_section = False
        current = None
        for line in lines:
            if "Excitation analysis" in line:
                in_section = True
                continue
            if not in_section:
                continue
            if "Natural Orbital analysis" in line:
                break
            match = self._transition_state.match(line)
            if match:
                current = int(match.group(1))
                transitions[current] = []
                continue
            match = self._transition_row.match(line)
            if match and current is not None:
                transitions[current].append(
                    OrbitalTransition(
                        occupied=int(match.group(1)),
                        virtual=int(match.group(2)),
                        amplitude=_as_float(match.group(3)),
                    )
                )
        return transitions

    @staticmethod
    def _parse_exciton_descriptors(lines: List[str]) -> Dict[int, Dict[str, float]]:
        output: Dict[int, Dict[str, float]] = {}
        header_index = None
        for index, line in enumerate(lines):
            if "d_eh" in line and "d_exc" in line and "R_eh" in line and "c_n" in line:
                header_index = index
        if header_index is None:
            return output
        started = False
        for line in lines[header_index + 1 :]:
            words = line.split()
            if len(words) == 7:
                try:
                    state_index = int(words[0])
                    numbers = [_as_float(value) for value in words[1:]]
                except ValueError:
                    if started:
                        break
                    continue
                started = True
                output[state_index] = dict(
                    zip(("norm", "d_eh", "sigma_e", "sigma_h", "d_exc", "R_eh"), numbers)
                )
            elif started:
                break
        return output

    @staticmethod
    def _parse_relative_centres(lines: List[str]):
        electron: Dict[int, np.ndarray] = {}
        hole: Dict[int, np.ndarray] = {}
        target = None
        row_re = re.compile(rf"^\s*(\d+)\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$")
        for line in lines:
            if "Excitation n" in line and "x_e" in line:
                target = electron
                continue
            if "Excitation n" in line and "x_h" in line:
                target = hole
                continue
            if target is None:
                continue
            match = row_re.match(line)
            if match:
                target[int(match.group(1))] = np.asarray(
                    [_as_float(match.group(i)) for i in (2, 3, 4)], dtype=float
                )
            elif target and line.strip() and not set(line.strip()) <= {"-"}:
                # A non-row after at least one parsed row closes this block.
                target = None
        return electron, hole
