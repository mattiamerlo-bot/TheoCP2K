"""Export CP2K cube analyses to interoperable text formats."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .errors import CP2KCubeError


def _analysed_states(project):
    if project.output is None:
        raise CP2KCubeError("Nessun output CP2K caricato.")
    return [state for state in project.output.states if state.index in project.analyses]


def export_summary_csv(project, path):
    states = _analysed_states(project)
    if not states:
        raise CP2KCubeError("Nessuno stato analizzato da esportare.")
    destination = Path(path)
    fragment_names = []
    for state in states:
        for name in project.analyses[state.index].fragment_names:
            if name not in fragment_names:
                fragment_names.append(name)
    fields = [
        "state", "energy_eV", "oscillator_strength", "character", "dominant_channel",
        "CT", "LE", "PR", "PRi", "PRf", "PRNTO", "S_HE", "Z_HE",
        "d_eh_CP2K_A", "d_exc_CP2K_A", "R_eh_CP2K", "d_centroid_cube_A",
        "d_exc_cube_diag_A", "captured_NTO_weight", "loaded_NTO_fraction", "grid_stride", "method",
    ]
    fields.extend("hole_localization[%s]" % name for name in fragment_names)
    fields.extend("electron_localization[%s]" % name for name in fragment_names)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for state in states:
            analysis = project.analyses[state.index]
            descriptor = analysis.descriptors
            row = {
                "state": state.name,
                "energy_eV": state.energy_ev,
                "oscillator_strength": state.oscillator_strength,
                "character": analysis.character,
                "dominant_channel": analysis.dominant_channel,
                "CT": descriptor.get("CT"),
                "LE": descriptor.get("LE"),
                "PR": descriptor.get("PR"),
                "PRi": descriptor.get("PRi"),
                "PRf": descriptor.get("PRf"),
                "PRNTO": descriptor.get("PRNTO"),
                "S_HE": descriptor.get("S_HE"),
                "Z_HE": descriptor.get("Z_HE"),
                "d_eh_CP2K_A": state.exciton.get("d_eh"),
                "d_exc_CP2K_A": state.exciton.get("d_exc"),
                "R_eh_CP2K": state.exciton.get("R_eh"),
                "d_centroid_cube_A": descriptor.get("d_centroid_cube"),
                "d_exc_cube_diag_A": descriptor.get("d_exc_cube_diag"),
                "captured_NTO_weight": descriptor.get("captured_NTO_weight"),
                "loaded_NTO_fraction": descriptor.get("loaded_NTO_fraction"),
                "grid_stride": "x".join(map(str, analysis.grid_stride)),
                "method": "real-space Voronoi; NTO-diagonal cube approximation",
            }
            for name, value in zip(analysis.fragment_names, analysis.hole_population):
                row["hole_localization[%s]" % name] = float(value)
            for name, value in zip(analysis.fragment_names, analysis.electron_population):
                row["electron_localization[%s]" % name] = float(value)
            writer.writerow(row)


def export_json(project, path):
    states = _analysed_states(project)
    destination = Path(path)
    payload = {
        "schema_version": 1,
        "method": {
            "name": "TheoDORE CP2K cube extension",
            "partition": "nearest-atom Voronoi in real space",
            "omega": "NTO-diagonal approximation",
            "rows": "hole fragment",
            "columns": "particle/electron fragment",
        },
        "cp2k_output": str(project.output.path),
        "cp2k_version": project.output.cp2k_version,
        "fragments": project.fragments.to_dict() if project.fragments else None,
        "states": [],
    }
    for state in states:
        payload["states"].append(
            {
                "state": state.name,
                "index": state.index,
                "energy_eV": state.energy_ev,
                "oscillator_strength": state.oscillator_strength,
                "transition_dipole_au": list(state.transition_dipole_au),
                "nto_eigenvalues": state.nto_eigenvalues,
                "exciton_CP2K": state.exciton,
                "cube_analysis": project.analyses[state.index].to_dict(),
            }
        )
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export_omfrag(project, path):
    """Write the legacy TheoDORE ``OmFrag.txt`` matrix layout."""

    states = _analysed_states(project)
    if not states:
        raise CP2KCubeError("Nessuno stato analizzato da esportare.")
    destination = Path(path)
    with destination.open("w", encoding="utf-8") as handle:
        handle.write("%d\n" % len(project.fragments.fragments))
        for state in states:
            analysis = project.analyses[state.index]
            handle.write("%10s %8.5f" % (state.name, analysis.omega_raw_sum))
            for value in (analysis.omega * analysis.omega_raw_sum).ravel(order="C"):
                handle.write(" %8.5f" % value)
            handle.write("\n")
