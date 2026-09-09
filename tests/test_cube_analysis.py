import tempfile
from pathlib import Path
import unittest

import numpy as np

from theodore.cp2k_cube.analysis import CubeStateAnalyzer
from theodore.cp2k_cube.cube import CubeValueStream, discover_cube, read_preview_volume
from theodore.cp2k_cube.fragments import FragmentSet
from theodore.cp2k_cube.models import ExcitedState, Fragment


def write_cube(path: Path, role: str, pair: int, values):
    lines = [
        "-Quickstep-",
        " Natural Transition Orbital %s State %d" % (role.capitalize(), pair),
        "    2    0.000000    0.000000    0.000000",
        "    4    1.000000    0.000000    0.000000",
        "    2    0.000000    1.000000    0.000000",
        "    2    0.000000    0.000000    1.000000",
        "    1    0.000000    0.000000    0.000000    0.000000",
        "    1    0.000000    3.000000    0.000000    0.000000",
    ]
    numbers = ["% .7E" % value for value in values]
    for start in range(0, len(numbers), 6):
        lines.append(" ".join(numbers[start : start + 6]))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


class CubeAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hole_path = self.root / "demo-NTO_00101_Hole_State.cube"
        self.particle_path = self.root / "demo-NTO_00101_Particle_State.cube"
        # Cube order: z fastest, then y, then x. Hole lives on x=0/1;
        # particle lives on x=2/3, matching the two atomic Voronoi cells.
        write_cube(self.hole_path, "hole", 1, [1.0] * 8 + [0.0] * 8)
        write_cube(self.particle_path, "particle", 1, [0.0] * 8 + [1.0] * 8)

    def tearDown(self):
        self.temp.cleanup()

    def test_cp2k_filename_and_title_are_discovered(self):
        assignment = discover_cube(self.hole_path)
        self.assertEqual(assignment.state_index, 1)
        self.assertEqual(assignment.pair_index, 1)
        self.assertEqual(assignment.role, "hole")
        self.assertEqual(assignment.header.shape, (4, 2, 2))
        with CubeValueStream(assignment.header) as stream:
            values = np.concatenate(list(stream.iter_blocks(block_values=5)))
        self.assertEqual(values.size, 16)
        self.assertAlmostEqual(values.sum(), 8.0)

    def test_title_state_is_pair_not_electronic_state(self):
        renamed = self.root / "renamed_hole.cube"
        write_cube(renamed, "hole", 3, [1.0] * 16)
        assignment = discover_cube(renamed)
        self.assertIsNone(assignment.state_index)
        self.assertEqual(assignment.pair_index, 3)

    def test_streaming_analysis_identifies_charge_transfer(self):
        hole = discover_cube(self.hole_path)
        particle = discover_cube(self.particle_path)
        fragments = FragmentSet(
            2,
            [Fragment("Donor", [1], "#111111"), Fragment("Acceptor", [2], "#eeeeee")],
        )
        state = ExcitedState(1, 3.25, 0.12, nto_eigenvalues=[0.9])
        result = CubeStateAnalyzer().analyze(
            state, {1: {"hole": hole, "particle": particle}}, fragments, stride=1
        )
        self.assertGreater(result.omega[0, 1], 0.99)
        self.assertGreater(result.descriptors["CT"], 0.99)
        self.assertIn("Donor → Acceptor", result.character)
        self.assertAlmostEqual(result.omega.sum(), 1.0)

    def test_preview_is_bounded_and_preserves_sign(self):
        signed_path = self.root / "demo-NTO_00102_Hole_State.cube"
        write_cube(signed_path, "hole", 2, [-1.0, 1.0] * 8)
        preview = read_preview_volume(signed_path, max_axis_points=2)
        self.assertEqual(preview.values.shape, (2, 2, 2))
        self.assertLess(preview.values.min(), 0.0)

    def test_multiple_pairs_use_cp2k_eigenvalue_weights(self):
        hole1 = discover_cube(self.hole_path)
        particle1 = discover_cube(self.particle_path)
        hole2_path = self.root / "demo-NTO_00102_Hole_State.cube"
        particle2_path = self.root / "demo-NTO_00102_Particle_State.cube"
        write_cube(hole2_path, "hole", 2, [1.0] * 8 + [0.0] * 8)
        write_cube(particle2_path, "particle", 2, [1.0] * 8 + [0.0] * 8)
        fragments = FragmentSet(2, [Fragment("D", [1]), Fragment("A", [2])])
        state = ExcitedState(1, 3.25, 0.12, nto_eigenvalues=[0.8, 0.2])
        result = CubeStateAnalyzer().analyze(
            state,
            {
                1: {"hole": hole1, "particle": particle1},
                2: {"hole": discover_cube(hole2_path), "particle": discover_cube(particle2_path)},
            },
            fragments,
            stride=1,
        )
        self.assertAlmostEqual(result.omega[0, 1], 0.8)
        self.assertAlmostEqual(result.omega[0, 0], 0.2)
        self.assertAlmostEqual(result.descriptors["CT"], 0.8)
        self.assertAlmostEqual(result.descriptors["loaded_NTO_fraction"], 1.0)
        self.assertTrue(any("interferenza" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
