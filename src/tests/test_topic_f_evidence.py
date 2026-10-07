"""Check exported measurements and the minimum-cohort CLI gate."""
import contextlib
import csv
import io
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from src.topic_f_evidence import save_object_comparison, save_pass_rate_plot, write_result_files
from src.topic_f_experiment import evaluate_objects, main, summarize_results
from src.tests.test_topic_f_experiment import make_frame, make_label, make_selected


class EvidenceTests(unittest.TestCase):
    """Exports preserve row identity, fixed schemas, and byte reproducibility."""

    def test_writer_schemas_counts_and_reproducibility(self) -> None:
        """Shuffled input cannot change sorted CSV/JSON or leading-zero IDs."""
        objects = make_selected()
        rows = evaluate_objects(objects)
        summaries = summarize_results(rows)
        config = {'n_objects': 10, 'angles_deg': [0, 1, 2, 3], 'seed': None}
        with TemporaryDirectory() as temp:
            first, second = Path(temp) / 'first', Path(temp) / 'second'
            write_result_files(objects, rows, summaries, config, first)
            write_result_files(objects[::-1], rows[::-1], summaries[::-1], dict(reversed(list(config.items()))), second)
            expected = {
                'topic_f_selected_objects.csv': (['frame_id', 'object_index'], 10),
                'topic_f_object_results.csv': (['frame_id', 'object_index', 'angle_deg', 'iou', 'passed', 'status'], 40),
                'topic_f_angle_sweep.csv': (['angle_deg', 'n_objects', 'mean_iou', 'pass_rate'], 4),
            }
            self.assertEqual({p.name for p in first.iterdir()}, set(expected) | {'topic_f_config.json'})
            for name, (header, count) in expected.items():
                with (first / name).open(encoding='utf-8', newline='') as handle:
                    reader = csv.DictReader(handle)
                    records = list(reader)
                    self.assertEqual(reader.fieldnames, header)
                self.assertEqual(len(records), count)
                if 'frame_id' in header:
                    self.assertTrue(all(row['frame_id'] == '000001' for row in records))
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            self.assertEqual(json.loads((first / 'topic_f_config.json').read_text()), config)
            self.assertEqual((first / 'topic_f_config.json').read_bytes(), (second / 'topic_f_config.json').read_bytes())

    def test_cli_nine_objects_errors_without_writing(self) -> None:
        """The claim cannot be published when fewer than ten objects qualify."""
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'results'
            args = ['experiment', '--data-root', 'data/kitti_mini', '--out-dir', str(output)]
            with patch('sys.argv', args), patch('src.topic_f_experiment.select_objects', return_value=make_selected(9)):
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                    main()
            self.assertNotEqual(caught.exception.code, 0)
            self.assertIn('9', error.getvalue())
            self.assertFalse(output.exists())

    def test_cli_ten_objects_runs_all_angles_and_records_config(self) -> None:
        """A successful CLI writes the four fixed levels with fair-comparison settings."""
        with TemporaryDirectory() as temp:
            output = Path(temp) / 'results'
            args = ['experiment', '--data-root', 'data/kitti_mini', '--frames', '000001', '--out-dir', str(output)]
            with (patch('sys.argv', args),
                  patch('src.topic_f_experiment.select_objects', return_value=make_selected()),
                  patch('src.topic_f_experiment.datasets.load_frame', return_value=make_frame([make_label()]))):
                main()
            with (output / 'topic_f_angle_sweep.csv').open(newline='') as handle:
                records = list(csv.DictReader(handle))
            self.assertEqual([float(r['angle_deg']) for r in records], [0, 1, 2, 3])
            self.assertEqual([int(r['n_objects']) for r in records], [10] * 4)
            config = json.loads((output / 'topic_f_config.json').read_text())
            for key, expected in {'frame_ids': ['000001'], 'angles_deg': [0, 1, 2, 3],
                                  'classes': ['Car'], 'range_filter': 'none', 'n_objects': 10,
                                  'iou_threshold': .7, 'claim_pass_rate': .7, 'min_depth_m': .1,
                                  'randomness': 'none', 'seed': None, 'measure_latency': False}.items():
                self.assertEqual(config[key], expected)
            for key in ('rotation_axis', 'angle_convention', 'box_convention', 'data_root'):
                self.assertTrue(config[key])
            for name in ('topic_f_angle_sweep.png', 'topic_f_example_comparison.png'):
                self.assertIsNotNone(cv2.imread(str(output / 'figures' / name)))

    def test_plots_are_readable_and_do_not_mutate_image(self) -> None:
        """Both figures are readable, retain four panels, and leave source pixels intact."""
        objects = make_selected(1)
        rows = evaluate_objects(objects)
        image = np.zeros((100, 500, 3), dtype=np.uint8)
        original = image.copy()
        with TemporaryDirectory() as temp:
            plot_path = Path(temp) / 'figures' / 'plot.png'
            comparison_path = Path(temp) / 'figures' / 'comparison.png'
            save_pass_rate_plot(summarize_results(rows), plot_path)
            save_object_comparison(image, objects[0], rows, comparison_path)
            normal = cv2.imread(str(comparison_path))
            for path in (plot_path, comparison_path):
                loaded = cv2.imread(str(path))
                self.assertIsNotNone(loaded)
                self.assertGreater(loaded.size, 0)
            missing = rows.copy()
            missing[2] = replace(rows[2], projected_bbox=None, status='not_projectable', iou=0., passed=False)
            save_object_comparison(image, objects[0], missing, comparison_path)
            failed = cv2.imread(str(comparison_path))
            self.assertEqual(failed.shape, normal.shape)
            self.assertEqual(failed.shape[1], 2 * image.shape[1])
            self.assertGreater(failed.shape[0], 2 * image.shape[0])
            self.assertFalse(np.array_equal(failed, normal))
        np.testing.assert_array_equal(image, original)

    def test_comparison_reports_write_failure(self) -> None:
        """An unsuccessful OpenCV write cannot be reported as saved evidence."""
        objects = make_selected(1)
        with TemporaryDirectory() as temp, patch('src.topic_f_evidence.cv2.imwrite', return_value=False):
            with self.assertRaises(OSError):
                save_object_comparison(np.zeros((100, 500, 3), dtype=np.uint8), objects[0],
                                       evaluate_objects(objects), Path(temp) / 'comparison.png')
