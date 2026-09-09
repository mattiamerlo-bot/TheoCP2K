import csv
import json
import tempfile
from pathlib import Path
import unittest

from theodore.cp2k_cube.export import export_json, export_omfrag, export_summary_csv
from theodore.cp2k_cube.cli import main as cli_main
from theodore.cp2k_cube.fragments import FragmentSet
from theodore.cp2k_cube.models import Fragment
from theodore.cp2k_cube.project import CP2KCubeProject

from tests.test_cube_analysis import write_cube


DATA = Path(__file__).parent / "data" / "cp2k_tddfpt_sample.out"


class ProjectExportTest(unittest.TestCase):
    def test_project_analysis_save_reload_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hole = root / "demo-NTO_00101_Hole_State.cube"
            particle = root / "demo-NTO_00101_Particle_State.cube"
            write_cube(hole, "hole", 1, [1.0] * 8 + [0.0] * 8)
            write_cube(particle, "particle", 1, [0.0] * 8 + [1.0] * 8)

            project = CP2KCubeProject()
            project.load_output(DATA)
            project.add_cubes([hole, particle])
            project.fragments = FragmentSet(2, [Fragment("D", [1]), Fragment("A", [2])])
            result = project.analyze_state(1, stride=1)
            self.assertGreater(result.descriptors["CT"], 0.99)

            project_path = root / "sample.theodore-cp2k.json"
            project.save(project_path)
            loaded = CP2KCubeProject.load(project_path)
            self.assertEqual(loaded.fragments.names, ["D", "A"])
            self.assertEqual(loaded.available_complete_states(), [1])

            csv_path = root / "summary.csv"
            json_path = root / "results.json"
            om_path = root / "OmFrag.txt"
            export_summary_csv(project, csv_path)
            export_json(project, json_path)
            export_omfrag(project, om_path)

            with csv_path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["state"], "S1")
            self.assertAlmostEqual(float(rows[0]["CT"]), 1.0)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["states"][0]["cube_analysis"]["fragment_names"], ["D", "A"])
            om_values = om_path.read_text(encoding="utf-8").splitlines()[1].split()
            self.assertAlmostEqual(float(om_values[1]), 0.9)
            self.assertAlmostEqual(sum(map(float, om_values[2:])), 0.9)

            cli_csv = root / "cli.csv"
            cli_json = root / "cli.json"
            cli_om = root / "cli-OmFrag.txt"
            code = cli_main(
                [
                    "analyze-project", str(project_path), "--stride", "1",
                    "--csv", str(cli_csv), "--json", str(cli_json), "--omfrag", str(cli_om),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(cli_csv.exists() and cli_json.exists() and cli_om.exists())


if __name__ == "__main__":
    unittest.main()
