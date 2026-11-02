"""Geometric checks for periodic path smoothing."""

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapwp_data import Combination, InputError
from smooth_waypoints import smooth
import tempfile


class SmoothingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.map_path = Path(self.temp.name) / 'map.yaml'
        self.map_path.write_text('image: unused.pgm\nfree_thresh: 0.196\nnegate: 0\n')

    def tearDown(self):
        self.temp.cleanup()

    def circle(self, clockwise=False):
        theta = np.linspace(0, -2*np.pi if clockwise else 2*np.pi, 201)
        points = np.column_stack((3*np.cos(theta), 3*np.sin(theta), theta, np.full(len(theta), 2.0)))
        return Combination(self.map_path, Path('unused.pgm'), Path('circle.csv'),
                           np.full((200, 200), 255, dtype=np.uint8), points,
                           0.1, (-10, -10, 0), [])

    def test_closed_heading_continuity_spacing_and_speed(self):
        output, stats = smooth(self.circle(), rms=0.01)
        self.assertTrue(np.allclose(output[0, :2], output[-1, :2]))
        self.assertAlmostEqual(output[-1, 2] - output[0, 2], 2*np.pi)
        self.assertTrue(np.allclose(output[:, 3], 2.0))
        self.assertTrue(np.isfinite(output).all())
        spacing = np.linalg.norm(np.diff(output[:, :2], axis=0), axis=1)
        self.assertGreater(spacing.min(), 0.09)
        self.assertLessEqual(spacing.max(), 0.101)
        self.assertLess(stats['max_deviation_m'], 0.05)
        self.assertAlmostEqual(stats['max_curvature_per_m'], 1/3, delta=0.08)

    def test_clockwise_direction_is_preserved(self):
        output, _ = smooth(self.circle(clockwise=True), rms=0.01)
        self.assertAlmostEqual(output[-1, 2] - output[0, 2], -2*np.pi)

    def test_open_path_is_rejected(self):
        data = self.circle()
        data.points = data.points[:-20]
        with self.assertRaisesRegex(InputError, 'Path is not closed'):
            smooth(data)


if __name__ == '__main__':
    unittest.main()
