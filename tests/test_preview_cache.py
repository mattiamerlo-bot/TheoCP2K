import tempfile
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from theodore.cp2k_cube.gui import CP2KCubeApp
from theodore.cp2k_cube.models import PreviewVolume
from theodore.cp2k_cube.preview_cache import NTOPreviewCache


def preview(value=1.0):
    return PreviewVolume(
        values=np.full((3, 3, 3), value, dtype=np.float32),
        origin_bohr=np.zeros(3),
        axes_bohr=np.eye(3),
        sampling_stride=(1, 1, 1),
        atoms=[],
    )


class PreviewCacheTest(unittest.TestCase):
    def test_cache_is_lru_bounded_and_detects_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assignments = []
            for name in ("a.cube", "b.cube", "c.cube"):
                path = root / name
                path.write_text(name, encoding="utf-8")
                assignments.append(SimpleNamespace(path=path))

            item = preview()
            cache = NTOPreviewCache(max_bytes=2 * item.values.nbytes)
            cache.put(assignments[0], 90, item)
            cache.put(assignments[1], 90, item)
            self.assertIs(cache.get(assignments[0], 90), item)
            cache.put(assignments[2], 90, item)
            self.assertIsNone(cache.get(assignments[1], 90))
            self.assertEqual(len(cache), 2)

            assignments[0].path.write_text("file modificato", encoding="utf-8")
            self.assertIsNone(cache.get(assignments[0], 90))

    def test_gui_preloads_pair_once_and_reuses_it_for_every_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hole_path = root / "hole.cube"
            particle_path = root / "particle.cube"
            hole_path.write_text("hole", encoding="utf-8")
            particle_path.write_text("particle", encoding="utf-8")
            roles = {
                "hole": SimpleNamespace(path=hole_path, header=object()),
                "particle": SimpleNamespace(path=particle_path, header=object()),
            }

            app = CP2KCubeApp.__new__(CP2KCubeApp)
            app.worker = None
            app.project = Mock()
            app.project.pairs_for_state.return_value = {1: roles}
            app.nto_state = Mock()
            app.nto_state.get.return_value = "S1"
            app.nto_pair = Mock()
            app.nto_pair.get.return_value = "1"
            app.nto_view = Mock()
            app.nto_view.get.return_value = "pair"
            app.nto_resolution = Mock()
            app.nto_resolution.get.return_value = 90
            app.nto_level = Mock()
            app.nto_level.get.return_value = 12.0
            app.nto_preview_cache = NTOPreviewCache()
            app.cancel_event = threading.Event()
            app._display_nto = Mock()
            app._show_error = Mock()

            worker_results = []

            def run_worker(kind, function, message):
                worker_results.append(function(lambda fraction, text: None))

            app._start_worker = Mock(side_effect=run_worker)
            with patch("theodore.cp2k_cube.gui.read_preview_volume", side_effect=(preview(1.0), preview(2.0))) as reader:
                self.assertTrue(app._render_nto())
                self.assertEqual(reader.call_count, 2)
                self.assertEqual(len(app.nto_preview_cache), 2)

                app._refresh_nto_pairs = Mock()
                app.nto_view.get.return_value = "hole"
                app._on_nto_view_change()
                app.nto_view.get.return_value = "particle"
                app._on_nto_view_change()

                self.assertEqual(reader.call_count, 2)
                self.assertEqual(app._start_worker.call_count, 1)
                self.assertEqual(len(worker_results), 1)
                self.assertEqual(app._refresh_nto_pairs.call_count, 2)
                self.assertEqual(app._display_nto.call_count, 2)
                self.assertTrue(app._display_nto.call_args.kwargs["cached"])


if __name__ == "__main__":
    unittest.main()
