"""Export deterministic Topic F measurements and visual evidence."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from src.topic_f_experiment import ObjectResult, SelectedObject, SummaryResult


def write_result_files(objects: list[SelectedObject], results: list[ObjectResult],
                       summaries: list[SummaryResult], config: dict[str, object],
                       output_dir: Path) -> None:
    """Create directories and overwrite the three fixed CSV files and config JSON.

    Args:
        objects: Selected cohort, sorted here by frame and object index.
        results: Per-object measurements, sorted here by angle/frame/index.
        summaries: Per-angle aggregates, sorted here by increasing angle.
        config: JSON-compatible configuration; keys are sorted when serialized.
        output_dir: Destination directory, created with parents if missing.

    Raises:
        OSError: If directories or files cannot be written.
        TypeError: If config contains a value that cannot be serialized as JSON.
        ValueError: If config contains nonfinite JSON numbers.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_rows = [(o.frame_id, o.object_index) for o in sorted(objects, key=lambda o: (o.frame_id, o.object_index))]
    detail_rows = [(r.frame_id, r.object_index, format(r.angle_deg, '.17g'), format(r.iou, '.17g'),
                    str(bool(r.passed)), r.status)
                   for r in sorted(results, key=lambda r: (r.angle_deg, r.frame_id, r.object_index))]
    summary_rows = [(format(s.angle_deg, '.17g'), s.n_objects, format(s.mean_iou, '.17g'), format(s.pass_rate, '.17g'))
                    for s in sorted(summaries, key=lambda s: s.angle_deg)]
    tables = [
        ('topic_f_selected_objects.csv', ['frame_id', 'object_index'], selected_rows),
        ('topic_f_object_results.csv', ['frame_id', 'object_index', 'angle_deg', 'iou', 'passed', 'status'], detail_rows),
        ('topic_f_angle_sweep.csv', ['angle_deg', 'n_objects', 'mean_iou', 'pass_rate'], summary_rows),
    ]
    for name, header, rows in tables:
        with (output_dir / name).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle, lineterminator='\n')
            writer.writerow(header)
            writer.writerows(rows)
    serialized = json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    (output_dir / 'topic_f_config.json').write_text(serialized + '\n', encoding='utf-8', newline='\n')


def save_pass_rate_plot(summaries: list[SummaryResult], output_path: Path) -> None:
    """Save a headless percentage plot with the fixed 70% claim reference line.

    Args:
        summaries: Per-angle measurements; displayed in increasing angle order.
        output_path: PNG destination, overwritten; missing parents are created.

    Raises:
        OSError: If directories or the image cannot be written.
    """
    rows = sorted(summaries, key=lambda row: row.angle_deg)
    # Use an unmanaged Agg figure so no GUI or pyplot figure registry is opened.
    figure = Figure(figsize=(8, 4.8), layout='constrained')
    FigureCanvasAgg(figure)
    try:
        axis = figure.subplots()
        angles = [row.angle_deg for row in rows]
        rates = [100 * row.pass_rate for row in rows]
        axis.plot(angles, rates, 'o-', color='#1769aa', linewidth=2, label='Cars with IoU >= 0.7')
        axis.axhline(70, linestyle='--', color='#b54524', label='Claim threshold: 70%')
        for angle, rate in zip(angles, rates):
            axis.annotate(f'{rate:.2f}%', (angle, rate), xytext=(0, 9), textcoords='offset points', ha='center')
        axis.set(xlabel='Camera-y angle offset (degrees)', ylabel='Pass rate (%)',
                 title=f'Topic F: fixed cohort ({rows[0].n_objects} Cars)', xticks=angles, ylim=(-5, 112))
        axis.grid(alpha=.25)
        axis.legend(loc='upper right')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=160)
    finally:
        figure.clear()


def save_object_comparison(image: np.ndarray, obj: SelectedObject,
                           results: list[ObjectResult], output_path: Path) -> None:
    """Save four panels of the same original image and Car at the fixed angles.

    Args:
        image: Original uint8 BGR frame, shape (height, width, 3); never modified.
        obj: Selected Car whose label is drawn green and projections drawn red.
        results: Measurements including exactly one row for this object at each
            of 0, 1, 2, 3 degrees; rows for other objects are ignored.
        output_path: PNG destination, overwritten; missing parents are created.

    Raises:
        ValueError: If this object's results do not contain the four fixed angles.
        OSError: If directories cannot be created or OpenCV cannot save the PNG.
    """
    rows = sorted((r for r in results if (r.frame_id, r.object_index) == (obj.frame_id, obj.object_index)),
                  key=lambda row: row.angle_deg)
    if [r.angle_deg for r in rows] != [0, 1, 2, 3]:
        raise ValueError('Comparison requires exactly one row at each of 0, 1, 2, 3 degrees')
    height, width = image.shape[:2]
    panels = []
    for row in rows:
        panel = np.full((height + 90, width, 3), 245, dtype=np.uint8)
        panel[90:] = image
        for bbox, color in ((obj.obj.bbox, (0, 255, 0)), (row.projected_bbox, (0, 0, 255))):
            if bbox is not None:
                # Rounding is only for drawing; metric calculations retain floats.
                x1, y1, x2, y2 = np.rint(bbox).astype(int)
                cv2.rectangle(panel, (x1, y1 + 90), (x2, y2 + 90), color, 2)
        font_scale = min(.7, width / 720)
        lines = [f'Frame {obj.frame_id} | object {obj.object_index} | angle {row.angle_deg:g} deg',
                 f'IoU {row.iou:.4f} | {row.status} | {"PASS" if row.passed else "FAIL"}',
                 'Green: label | Red: projected 3D box']
        for line_index, line in enumerate(lines):
            cv2.putText(panel, line, (8, 24 + line_index * 27), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, (30, 30, 30), 1, cv2.LINE_AA)
        panels.append(panel)
    comparison = np.vstack((np.hstack(panels[:2]), np.hstack(panels[2:])))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), comparison):
        raise OSError(f'OpenCV failed to write {output_path}')
