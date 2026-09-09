from pathlib import Path
import unittest

from theodore.cp2k_cube.output_parser import CP2KOutputParser


DATA = Path(__file__).parent / "data" / "cp2k_tddfpt_sample.out"


class CP2KOutputParserTest(unittest.TestCase):
    def test_final_table_not_davidson_iterations_is_used(self):
        run = CP2KOutputParser().parse(DATA)
        self.assertEqual(run.cp2k_version, "2025.2")
        self.assertEqual(len(run.atoms), 2)
        self.assertEqual(len(run.states), 2)
        self.assertAlmostEqual(run.states[0].energy_ev, 3.25)
        self.assertAlmostEqual(run.states[0].oscillator_strength, 0.1234)
        self.assertEqual(run.states[0].nto_eigenvalues, [0.9, 0.08])
        self.assertEqual(len(run.states[0].transitions), 2)
        self.assertAlmostEqual(run.states[0].exciton["d_eh"], 1.5)
        self.assertAlmostEqual(run.states[1].exciton["R_eh"], 0.2)


if __name__ == "__main__":
    unittest.main()
