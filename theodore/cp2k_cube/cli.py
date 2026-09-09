"""Headless companion CLI for reproducible CP2K cube analyses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .cube import discover_cube
from .errors import CP2KCubeError
from .export import export_json, export_omfrag, export_summary_csv
from .fragments import FragmentSet
from .output_parser import CP2KOutputParser
from .project import CP2KCubeProject


def _parser():
    parser = argparse.ArgumentParser(
        prog="theodore-cp2k",
        description="Analisi TheoDORE-style di NTO cube prodotti da CP2K TDDFPT.",
    )
    parser.add_argument("--version", action="version", version="TheoCP2K %s" % __version__)
    commands = parser.add_subparsers(dest="command", required=True)

    output = commands.add_parser("inspect-output", help="Mostra i dati TDDFPT estratti da un .out")
    output.add_argument("output")

    cube = commands.add_parser("inspect-cube", help="Mostra header e associazione inferita di un cube")
    cube.add_argument("cube")

    analyse = commands.add_parser("analyze", help="Analizza coppie hole/particle per frammenti")
    analyse.add_argument("--out", required=True, help="Output CP2K convergente")
    analyse.add_argument("--cube", action="append", required=True, help="Cube; ripetere l'opzione per ogni file")
    analyse.add_argument("--fragments", help="JSON dei frammenti creato dalla GUI")
    analyse.add_argument("--states", help="Indici separati da virgola; default: tutti gli stati completi")
    analyse.add_argument("--stride", type=int, default=2, help="Stride di integrazione (default: 2; 1 = piena griglia)")
    analyse.add_argument("--csv", default="cp2k_cube_summary.csv")
    analyse.add_argument("--json", default="cp2k_cube_results.json")
    analyse.add_argument("--omfrag", default="OmFrag.txt")

    project = commands.add_parser(
        "analyze-project", help="Ricalcola un progetto salvato dalla GUI (incluse associazioni manuali)"
    )
    project.add_argument("project")
    project.add_argument("--states", help="Indici separati da virgola; default: tutti gli stati completi")
    project.add_argument("--stride", type=int, default=2)
    project.add_argument("--csv", default="cp2k_cube_summary.csv")
    project.add_argument("--json", default="cp2k_cube_results.json")
    project.add_argument("--omfrag", default="OmFrag.txt")
    return parser


def _inspect_output(path):
    run = CP2KOutputParser().parse(path)
    payload = {
        "path": str(run.path),
        "cp2k_version": run.cp2k_version,
        "n_atoms": len(run.atoms),
        "spin": run.spin_label,
        "states": [
            {
                "index": state.index,
                "energy_eV": state.energy_ev,
                "oscillator_strength": state.oscillator_strength,
                "nto_eigenvalues": state.nto_eigenvalues,
                "PRNTO": state.pr_nto,
                "exciton": state.exciton,
            }
            for state in run.states
        ],
        "warnings": run.warnings,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _inspect_cube(path):
    assignment = discover_cube(path)
    header = assignment.header
    payload = {
        "path": str(assignment.path),
        "comments": [header.comment_1, header.comment_2],
        "shape": header.shape,
        "origin_bohr": header.origin_bohr.tolist(),
        "axes_bohr": header.axes_bohr.tolist(),
        "n_atoms": len(header.atoms),
        "voxel_volume_bohr3": header.voxel_volume_bohr3,
        "state_index": assignment.state_index,
        "pair_index": assignment.pair_index,
        "role": assignment.role,
        "note": assignment.detection_note,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _analyse_loaded_project(project, args):
    if args.states:
        states = [int(value.strip()) for value in args.states.split(",") if value.strip()]
    else:
        states = project.available_complete_states()
    if not states:
        raise CP2KCubeError(
            "Nessuno stato ha coppie hole/particle complete. Usare la GUI per correggere associazioni non standard."
        )

    last_percent = {state: -1 for state in states}
    for state_index in states:
        def progress(fraction, message, index=state_index):
            percent = int(fraction * 100)
            if percent // 10 != last_percent[index] // 10:
                print("S%d: %d%% - %s" % (index, percent, message), file=sys.stderr)
                last_percent[index] = percent

        project.analyze_state(state_index, stride=args.stride, progress=progress)

    export_summary_csv(project, args.csv)
    export_json(project, args.json)
    export_omfrag(project, args.omfrag)
    print("Scritti: %s, %s, %s" % (args.csv, args.json, args.omfrag))


def _analyse(args):
    project = CP2KCubeProject()
    project.load_output(args.out)
    project.add_cubes(args.cube)
    if args.fragments:
        project.fragments = FragmentSet.load(args.fragments, expected_n_atoms=len(project.atoms))
    _analyse_loaded_project(project, args)


def _analyse_project(args):
    _analyse_loaded_project(CP2KCubeProject.load(args.project), args)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect-output":
            _inspect_output(args.output)
        elif args.command == "inspect-cube":
            _inspect_cube(args.cube)
        elif args.command == "analyze":
            _analyse(args)
        elif args.command == "analyze-project":
            _analyse_project(args)
        return 0
    except (CP2KCubeError, OSError, ValueError) as exc:
        print("Errore: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
