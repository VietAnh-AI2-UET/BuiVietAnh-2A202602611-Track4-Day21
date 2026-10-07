"""Selection and evaluation contracts using hand-checked camera fixtures."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from starter.kitti_io import KittiCalib, KittiObject, frame_paths
from src.topic_f_experiment import (
    ObjectResult, SelectedObject, evaluate_objects, select_objects, summarize_results,
)
from starter.projection import box3d_corners_cam


def make_label(**changes: object) -> KittiObject:
    """Build a cuboid whose unperturbed pixel rectangle is [40, 40, 60, 60].

    Args:
        **changes: KittiObject fields to override for individual test cases.

    Returns:
        A fresh label centred at camera (0, 1, 15) metres, with h/w/l=2/10/2.
    """
    obj = KittiObject('Car', 0., 0, 0., np.array([40., 40., 60., 60.]),
                      np.array([2., 10., 2.]), np.array([0., 1., 15.]), 0.)
    return replace(obj, **changes)


def make_frame(labels: list[KittiObject]) -> dict:
    """Create a complete in-memory frame with a hand-selected projection matrix.

    Args:
        labels: Parsed objects in the order returned by the KITTI reader.

    Returns:
        Reader-compatible frame with a black BGR image of shape (100, 100, 3).
    """
    P2 = np.array([[100., 0, 50, 0], [0, 100, 50, 0], [0, 0, 1, 0]])
    return dict(frame_id='000001', points=np.zeros((0, 4)),
                calib=KittiCalib(P2, np.eye(3), np.zeros((3, 4))),
                image=np.zeros((100, 100, 3), dtype=np.uint8), labels=labels)


def touch_frame_files(root: Path, frame_id: str) -> None:
    """Create placeholder paths for a mocked reader inside a temporary root.

    Args:
        root: Temporary dataset directory; missing parents are created.
        frame_id: KITTI identifier whose four required files are touched.
    """
    for path in frame_paths(root, frame_id).values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def make_selected(count: int = 10) -> list[SelectedObject]:
    """Create independent, identically shaped Cars with unique object indices.

    Args:
        count: Number of objects to produce, default ten.

    Returns:
        Selected objects in frame 000001 whose baseline bbox is [40,40,60,60].
    """
    objects = []
    for index in range(count):
        label = make_label()
        frame = make_frame([label])
        objects.append(SelectedObject('000001', index, label, frame['calib'].P2,
                                      frame['image'].shape, box3d_corners_cam(label)))
    return objects


class EvaluationTests(unittest.TestCase):
    """The four angles share exactly the same labels, calibration, and cohort."""

    def test_baseline_and_four_angle_cohort(self) -> None:
        """Ten known boxes produce forty rows and perfect baseline IoUs."""
        objects = make_selected()
        originals = [(o.corners_original.copy(), o.P2.copy(), o.obj.bbox.copy()) for o in objects]
        results = evaluate_objects(objects)
        self.assertEqual(len(results), 40)
        for angle in (0, 1, 2, 3):
            rows = [r for r in results if r.angle_deg == angle]
            self.assertEqual([(r.frame_id, r.object_index) for r in rows], [('000001', i) for i in range(10)])
            if angle == 0:
                self.assertTrue(all(r.iou == 1 and r.passed for r in rows))
        for obj, (corners, P2, bbox) in zip(objects, originals):
            np.testing.assert_array_equal(obj.corners_original, corners)
            np.testing.assert_array_equal(obj.P2, P2)
            np.testing.assert_array_equal(obj.obj.bbox, bbox)
        for together, alone in zip([r for r in results if r.angle_deg == 2], evaluate_objects(objects, (2.,))):
            np.testing.assert_array_equal(together.projected_bbox, alone.projected_bbox)
            self.assertEqual(together.iou, alone.iou)

    def test_invalid_projection_keeps_zero_iou_rows(self) -> None:
        """Off-screen and behind-camera cases keep their identities and count."""
        objects = make_selected(1)
        # Narrow field of view puts +3 deg outside; +90 puts corners behind.
        objects[0].P2[0] = [1000, 0, 50, 0]
        objects[0].corners_original[:, 0] *= .01
        rows = evaluate_objects(objects, (0., 3., 90.))
        self.assertEqual([r.status for r in rows], ['ok', 'outside_image', 'not_projectable'])
        for row in rows[1:]:
            self.assertEqual((row.object_index, row.iou, row.passed), (0, 0., False))
            self.assertIsNone(row.projected_bbox)
        self.assertEqual([s.n_objects for s in summarize_results(rows)], [1, 1, 1])

    def test_known_summary_and_inclusive_threshold(self) -> None:
        """Seven good and three bad rows average 0.62 and pass at rate 0.7."""
        rows = [ObjectResult('000001', i, 0., value, value >= .7, 'ok', None)
                for i, value in enumerate([.8] * 7 + [.2] * 3)]
        summary = summarize_results(rows)[0]
        self.assertEqual(summary.n_objects, 10)
        self.assertAlmostEqual(summary.mean_iou, .62)
        self.assertAlmostEqual(summary.pass_rate, .7)
        # Area of [40,40,54,60] is exactly 70% of the projected 20x20 box.
        objects = make_selected(1)
        objects[0].obj.bbox = np.array([40., 40., 54., 60.])
        row = evaluate_objects(objects, (0.,))[0]
        self.assertEqual(row.iou, .7)
        self.assertTrue(row.passed)

    def test_reject_inconsistent_or_duplicate_groups(self) -> None:
        """Incomplete or duplicate identities cannot look like a valid comparison."""
        rows = evaluate_objects(make_selected(2), (1., 0.))
        self.assertEqual([s.angle_deg for s in summarize_results(rows)], [0, 1])
        for bad in ([], rows[:-1], rows + [rows[0]]):
            with self.assertRaises(ValueError):
                summarize_results(bad)
        for angles in ((), (0., 0.), (np.nan,)):
            with self.assertRaises(ValueError):
                evaluate_objects(make_selected(1), angles)
        for threshold in (-.1, 1.1, np.nan):
            with self.assertRaises(ValueError):
                evaluate_objects(make_selected(1), iou_threshold=threshold)


class SelectionTests(unittest.TestCase):
    """Selection is stable and does not use projection overlap as a filter."""

    def test_select_all_eligible_labels_in_stable_order(self) -> None:
        """Reject visibility/class/label failures and retain even off-screen projections."""
        labels = [make_label(), make_label(occluded=1), make_label(truncated=.1),
                  make_label(type='Van'), make_label(bbox=np.array([-1, 0, 10, 10])),
                  make_label(bbox=np.array([0, 0, np.nan, 10])),
                  make_label(location=np.array([100., 1., 15.])),
                  make_label(location=np.array([0., 1., 1000.]))]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for frame_id in ('000001', '000002'):
                touch_frame_files(root, frame_id)
            with patch('src.topic_f_experiment.datasets.load_frame', return_value=make_frame(labels)):
                objects = select_objects(root, ['000002', '000001', '000002'])
                again = select_objects(root, ['000001', '000002'])
        expected = [(frame_id, index) for frame_id in ('000001', '000002') for index in (0, 6, 7)]
        self.assertEqual([(o.frame_id, o.object_index) for o in objects], expected)
        self.assertEqual([(o.frame_id, o.object_index) for o in again], expected)

    def test_bad_geometry_has_object_context(self) -> None:
        """Corrupt candidate geometry raises instead of silently changing the cohort."""
        invalid = [dict(dimensions=np.array([0, 2, 2])), dict(dimensions=np.array([1, 2])),
                   dict(location=np.array([0, 1, np.nan])), dict(rotation_y=np.inf),
                   dict(location=np.array([0, 1, -10]))]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            touch_frame_files(root, '000001')
            for changes in invalid:
                with self.subTest(changes=changes):
                    with patch('src.topic_f_experiment.datasets.load_frame', return_value=make_frame([make_label(**changes)])):
                        with self.assertRaisesRegex(ValueError, '000001.*object 0'):
                            select_objects(root, ['000001'])

    def test_missing_file_names_exact_path(self) -> None:
        """Every missing file, including the optional-to-starter label, must fail."""
        for kind in ('label', 'image', 'calib', 'velodyne'):
            with self.subTest(kind=kind), TemporaryDirectory() as temp:
                root = Path(temp)
                touch_frame_files(root, '000001')
                missing = frame_paths(root, '000001')[kind]
                missing.unlink()
                with self.assertRaises(FileNotFoundError) as caught:
                    select_objects(root, ['000001'])
                self.assertIn(str(missing), str(caught.exception))
