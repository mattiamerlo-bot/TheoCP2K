import unittest

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import numpy as np

from theodore.cp2k_cube.models import Atom, PreviewVolume, StateAnalysis
from theodore.cp2k_cube.plotting import draw_molecule, draw_nto_pair, draw_omega


class PlottingTest(unittest.TestCase):
    def setUp(self):
        self.atoms = [
            Atom(1, 1, "H", np.asarray([0.0, 0.0, 0.0])),
            Atom(2, 1, "H", np.asarray([1.4, 0.0, 0.0])),
        ]

    def test_map_and_geometry_render_on_agg(self):
        figure = Figure(figsize=(4, 3))
        ax = figure.add_subplot(121)
        analysis = StateAnalysis(
            state_index=1,
            omega=np.asarray([[0.1, 0.8], [0.05, 0.05]]),
            omega_raw_sum=1.0,
            fragment_names=["D", "A"],
            hole_population=np.asarray([0.9, 0.1]),
            electron_population=np.asarray([0.15, 0.85]),
            descriptors={"CT": 0.85},
            character="CT D → A",
            dominant_channel="D → A",
            pair_weights_used=[1.0],
            grid_stride=(1, 1, 1),
        )
        image = draw_omega(ax, analysis)
        self.assertEqual(image.get_array().shape, (2, 2))
        draw_molecule(figure.add_subplot(122, projection="3d"), self.atoms)
        figure.canvas.draw()

    def test_nto_fallback_or_surface_renders(self):
        values = np.zeros((7, 7, 7), dtype=np.float32)
        values[2:5, 2:5, 2:5] = 1.0
        values[0:2, 0:2, 0:2] = -0.8
        preview = PreviewVolume(
            values=values,
            origin_bohr=np.zeros(3),
            axes_bohr=np.eye(3),
            sampling_stride=(1, 1, 1),
            atoms=self.atoms,
        )
        figure = Figure(figsize=(4, 3))
        draw_nto_pair(figure.add_subplot(111, projection="3d"), preview, preview, relative_level=0.5)
        figure.canvas.draw()


if __name__ == "__main__":
    unittest.main()
