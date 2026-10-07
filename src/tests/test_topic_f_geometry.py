"""Analytic checks for camera rotation, clipping, and continuous box IoU."""
import itertools
import unittest

import numpy as np

from src.topic_f_geometry import box_iou, project_box_to_image, rotate_camera_corners


class GeometryTests(unittest.TestCase):
    """Catch sign, corner-discarding, mutation, and area convention errors."""

    def setUp(self) -> None:
        """Create an eight-corner cuboid in camera metres and a pixel projection."""
        self.corners = np.array(list(itertools.product((-1, 1), (-1, 1), (10, 20))), dtype=float)
        self.P2 = np.array([[100, 0, 50, 0], [0, 100, 50, 0], [0, 0, 1, 0]], dtype=float)

    def test_rotation_identity_sign_and_no_mutation(self) -> None:
        """Positive yaw moves forward points right and never rotates inputs in place."""
        before = self.corners.copy()
        zero = rotate_camera_corners(self.corners, 0)
        np.testing.assert_array_equal(zero, before)
        self.assertFalse(np.shares_memory(zero, self.corners))
        forward = np.tile([0., 0., 10.], (8, 1))
        np.testing.assert_allclose(rotate_camera_corners(forward, 90), np.tile([10, 0, 0], (8, 1)), atol=1e-12)
        np.testing.assert_array_equal(self.corners, before)

    def test_projection_uses_all_corners_before_clipping(self) -> None:
        """Off-screen corners still determine the enclosing rectangle."""
        before = self.corners.copy()
        result = project_box_to_image(self.corners, self.P2, (100, 100, 3))
        self.assertEqual(result.status, 'ok')
        np.testing.assert_allclose(result.bbox, [40, 40, 60, 60])
        wide = self.corners.copy()
        wide[wide[:, 0] == -1, 0] = -10
        np.testing.assert_allclose(project_box_to_image(wide, self.P2, (100, 100)).bbox, [0, 40, 60, 60])
        np.testing.assert_array_equal(self.corners, before)

    def test_projection_failure_statuses(self) -> None:
        """Behind-camera, nonfinite, and off-screen geometry have explicit statuses."""
        outside = self.corners + [100, 0, 0]
        result = project_box_to_image(outside, self.P2, (100, 100))
        self.assertEqual(result.status, 'outside_image')
        self.assertIsNone(result.bbox)
        for depth in (-1, 0.1, np.nan, np.inf):
            with self.subTest(depth=depth):
                corners = self.corners.copy()
                corners[0, 2] = depth
                result = project_box_to_image(corners, self.P2, (100, 100))
                self.assertEqual(result.status, 'not_projectable')
                self.assertIsNone(result.bbox)
        for denominator in (0., -1., 1e-12):
            matrix = self.P2.copy()
            matrix[2] = [0, 0, 0, denominator]
            self.assertEqual(project_box_to_image(self.corners, matrix, (100, 100)).status, 'not_projectable')

    def test_iou_known_areas(self) -> None:
        """Continuous areas give exact overlap, disjoint, and degenerate cases."""
        for a, b, expected in [([0, 0, 2, 2], [0, 0, 2, 2], 1),
                               ([0, 0, 2, 2], [3, 3, 4, 4], 0),
                               ([0, 0, 2, 2], [1, 1, 3, 3], 1/7),
                               ([0, 0, 0, 2], [0, 0, 2, 2], 0)]:
            with self.subTest(a=a, b=b):
                self.assertAlmostEqual(box_iou(np.array(a), np.array(b)), expected)

    def test_configuration_errors_are_not_silent_zeroes(self) -> None:
        """Malformed shapes, angles, matrices, and image sizes raise ValueError."""
        for bad in (np.zeros((7, 3)), np.zeros((8, 4))):
            with self.assertRaises(ValueError):
                rotate_camera_corners(bad, 0)
            with self.assertRaises(ValueError):
                project_box_to_image(bad, self.P2, (100, 100))
        for angle in (np.nan, np.inf):
            with self.assertRaises(ValueError):
                rotate_camera_corners(self.corners, angle)
        for shape in ((0, 100), (100, -1), (100,), (np.nan, 100)):
            with self.assertRaises(ValueError):
                project_box_to_image(self.corners, self.P2, shape)
        for matrix in (np.zeros((3, 3)), np.full((3, 4), np.nan)):
            with self.assertRaises(ValueError):
                project_box_to_image(self.corners, matrix, (100, 100))
        for box in ([0, 0, 1], [2, 0, 1, 1], [0, 2, 1, 1], [0, 0, np.nan, 1]):
            with self.assertRaises(ValueError):
                box_iou(np.array(box), np.array([0, 0, 1, 1]))
