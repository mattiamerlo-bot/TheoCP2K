import json
import tempfile
from pathlib import Path
import unittest

from theodore.cp2k_cube.fragments import FragmentSet
from theodore.cp2k_cube.models import Fragment


class FragmentSetTest(unittest.TestCase):
    def test_assignment_is_complete_and_exclusive(self):
        fragments = FragmentSet(3, [Fragment("A", [1, 2]), Fragment("B", [3])])
        fragments.assign([2], 1)
        self.assertEqual(fragments.fragments[0].atom_indices, [1])
        self.assertEqual(fragments.fragments[1].atom_indices, [2, 3])
        self.assertEqual(fragments.atom_to_fragment().tolist(), [0, 1, 1])

    def test_json_round_trip(self):
        fragments = FragmentSet(2, [Fragment("D", [1]), Fragment("A", [2])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fragments.json"
            fragments.save(path)
            loaded = FragmentSet.load(path, expected_n_atoms=2)
        self.assertEqual(loaded.names, ["D", "A"])
        self.assertEqual(loaded.atom_to_fragment().tolist(), [0, 1])

    def test_moving_entire_earlier_fragment_keeps_target(self):
        fragments = FragmentSet(2, [Fragment("A", [1]), Fragment("B", [2])])
        fragments.assign([1], 1)
        self.assertEqual(fragments.names, ["B"])
        self.assertEqual(fragments.fragments[0].atom_indices, [1, 2])


if __name__ == "__main__":
    unittest.main()
