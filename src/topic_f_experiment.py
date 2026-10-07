"""Select one KITTI Car cohort and measure camera-y projection perturbations."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from starter import datasets
from starter.kitti_io import KittiObject, frame_paths
from starter.projection import box3d_corners_cam
from src.topic_f_geometry import box_iou, project_box_to_image, rotate_camera_corners


@dataclass
class SelectedObject:
    """Keep the original geometry and calibration for every angle.

    Attributes:
        frame_id: Zero-padded KITTI frame identifier.
        object_index: Zero-based index after the reader removes DontCare.
        obj: Original parsed label, including its continuous pixel bbox.
        P2: Camera projection matrix, shape (3, 4).
        image_shape: Image height, width, and optional channels.
        corners_original: Eight original corners, shape (8, 3), camera metres.
    """

    frame_id: str
    object_index: int
    obj: KittiObject
    P2: np.ndarray
    image_shape: tuple[int, ...]
    corners_original: np.ndarray


def select_objects(data_root: Path, frame_ids: list[str]) -> list[SelectedObject]:
    """Read KITTI frames and select all fully visible, geometrically valid Cars.

    Args:
        data_root: KITTI root containing training/; original files are read only.
        frame_ids: Frame IDs; duplicates are removed and frames sorted.

    Returns:
        Objects in frame/index order. No range or IoU filter is applied. Labels
        must be finite, positive-area, wholly inside the image, unoccluded,
        and untruncated. Off-screen projected boxes do not disqualify a car.

    Raises:
        FileNotFoundError: If any required KITTI file is absent, naming its path.
        ValueError: If candidate 3D data or calibration is invalid, naming the
            frame and object index; invalid geometry is never silently skipped.
    """
    selected = []
    for frame_id in sorted(set(frame_ids)):
        # starter treats missing labels as empty; the experiment requires an error.
        for path in frame_paths(data_root, frame_id).values():
            if not path.is_file():
                raise FileNotFoundError(path)
        frame = datasets.load_frame(data_root, frame_id)
        shape = frame['image'].shape
        height, width = shape[:2]
        for index, obj in enumerate(frame['labels']):
            if obj.type != 'Car' or obj.occluded != 0 or obj.truncated != 0:
                continue
            bbox = np.asarray(obj.bbox)
            if bbox.shape != (4,) or not np.isfinite(bbox).all():
                continue
            x1, y1, x2, y2 = bbox
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                continue
            try:
                dimensions, location = np.asarray(obj.dimensions), np.asarray(obj.location)
                if (dimensions.shape != (3,) or location.shape != (3,)
                        or not np.isfinite(dimensions).all() or np.any(dimensions <= 0)
                        or not np.isfinite(location).all() or not np.isfinite(obj.rotation_y)):
                    raise ValueError('Expected finite 3D geometry and positive dimensions')
                corners = box3d_corners_cam(obj)
                P2 = frame['calib'].P2
                projection = project_box_to_image(corners, P2, shape)
                if projection.status == 'not_projectable':
                    raise ValueError('Original corners are not projectable (minimum depth 0.1 m)')
            except ValueError as exc:
                raise ValueError(f'Frame {frame_id}, object {index}: {exc}') from exc
            selected.append(SelectedObject(frame_id, index, obj, P2.copy(), shape, corners.copy()))
    return selected


@dataclass
class ObjectResult:
    """Store one object's outcome at one angle without dropping failed projections.

    Attributes:
        frame_id: Original frame identifier, preserving leading zeros.
        object_index: Original index in the parsed labels.
        angle_deg: Rotation around camera y, in degrees.
        iou: Continuous pixel intersection-over-union ratio in [0, 1].
        passed: Whether a valid projection meets the inclusive IoU threshold.
        status: Projection status: ok, outside_image, or not_projectable.
        projected_bbox: Shape (4,) clipped continuous pixel box, or None.
    """

    frame_id: str
    object_index: int
    angle_deg: float
    iou: float
    passed: bool
    status: str
    projected_bbox: np.ndarray | None


@dataclass
class SummaryResult:
    """Aggregate measurements at a single angle.

    Attributes:
        angle_deg: Camera-y rotation in degrees.
        n_objects: Number of objects, including failed projections.
        mean_iou: Arithmetic mean IoU across all selected objects.
        pass_rate: Fraction in [0, 1] meeting the IoU threshold.
    """

    angle_deg: float
    n_objects: int
    mean_iou: float
    pass_rate: float


def evaluate_objects(objects: list[SelectedObject],
                     angles_deg: tuple[float, ...] = (0., 1., 2., 3.),
                     iou_threshold: float = .7) -> list[ObjectResult]:
    """Measure every selected object at every supplied angle without side effects.

    Args:
        objects: Fixed cohort with original camera geometry, labels, and P2.
        angles_deg: Nonempty, unique finite angles in degrees, in evaluation order.
        iou_threshold: Inclusive overlap threshold in [0, 1], default 0.7.

    Returns:
        Angle-major results retaining input object order; failed projections
        always receive IoU 0 and passed=False. Input arrays remain unchanged.

    Raises:
        ValueError: If angles, threshold, or geometry configuration are invalid.
    """
    if not angles_deg or not np.isfinite(angles_deg).all() or len(set(angles_deg)) != len(angles_deg):
        raise ValueError('angles_deg must be nonempty, finite, and unique')
    if not np.isfinite(iou_threshold) or not 0 <= iou_threshold <= 1:
        raise ValueError('iou_threshold must be finite and in [0, 1]')
    results = []
    for angle in angles_deg:
        for item in objects:
            # Always restart from original geometry: no cumulative rotation or reselection.
            corners = rotate_camera_corners(item.corners_original, angle)
            projection = project_box_to_image(corners, item.P2, item.image_shape)
            iou = box_iou(projection.bbox, item.obj.bbox) if projection.bbox is not None else 0.
            passed = projection.status == 'ok' and iou >= iou_threshold
            results.append(ObjectResult(item.frame_id, item.object_index, float(angle),
                                        iou, passed, projection.status, projection.bbox))
    return results


def summarize_results(results: list[ObjectResult]) -> list[SummaryResult]:
    """Summarize an equally sized cohort at each angle, sorted by angle.

    Args:
        results: Nonempty per-object measurements with unique identities per angle.

    Returns:
        Mean IoU and pass fraction per angle, counting all failed projections.

    Raises:
        ValueError: If rows are empty, nonfinite, out of range, duplicate, or
            different angles contain different sets of frame/object identities.
    """
    if not results:
        raise ValueError('Cannot summarize an empty result list')
    groups: dict[float, dict[tuple[str, int], ObjectResult]] = {}
    for row in results:
        if not np.isfinite(row.angle_deg) or not np.isfinite(row.iou) or not 0 <= row.iou <= 1:
            raise ValueError('Results must contain finite angles and IoU in [0, 1]')
        group = groups.setdefault(row.angle_deg, {})
        identity = (row.frame_id, row.object_index)
        if identity in group:
            raise ValueError(f'Duplicate object {identity} at angle {row.angle_deg}')
        group[identity] = row
    cohort = set(next(iter(groups.values())))
    summaries = []
    for angle, group in sorted(groups.items()):
        if set(group) != cohort:
            raise ValueError(f'Object cohort differs at angle {angle}')
        rows = [group[key] for key in sorted(group)]
        summaries.append(SummaryResult(angle, len(rows), float(np.mean([r.iou for r in rows])),
                                       sum(r.passed for r in rows) / len(rows)))
    return summaries


def main() -> None:
    """Run the fixed four-angle KITTI experiment and overwrite its evidence files.

    Read --data-root, --frames, and --out-dir from process arguments. Require at
    least ten selected Cars before writing anything. No latency is measured.

    Raises:
        SystemExit: For help, argument errors, missing data, invalid geometry,
            insufficient sample size, or a failed output write (nonzero on errors).
    """
    from src.topic_f_evidence import save_object_comparison, save_pass_rate_plot, write_result_files

    parser = argparse.ArgumentParser(description='Topic F: fixed Car cohort at 0, 1, 2, 3 degrees')
    parser.add_argument('--data-root', type=Path, default=Path('data/kitti_mini'))
    parser.add_argument('--frames', nargs='+', default=['000008', '000010', '000011', '000004', '000016', '000049'])
    parser.add_argument('--out-dir', type=Path, default=Path('results'))
    args = parser.parse_args()
    try:
        frame_ids = sorted(set(args.frames))
        objects = select_objects(args.data_root, frame_ids)
        if len(objects) < 10:
            parser.error(f'Selected {len(objects)} Cars; at least 10 required. No new results written.')
        results = evaluate_objects(objects)
        summaries = summarize_results(results)
        config = {
            'data_root': args.data_root.as_posix(), 'frame_ids': frame_ids,
            'angles_deg': [0., 1., 2., 3.], 'classes': ['Car'], 'range_filter': 'none',
            'iou_threshold': .7, 'claim_pass_rate': .7, 'n_objects': len(objects),
            'rotation_axis': 'camera y through camera origin; x right, y down, z forward',
            'angle_convention': 'corners_original @ R.T; positive angle moves forward points right; P2 fixed',
            'box_convention': 'continuous xyxy; project all 8 corners then clip to [0,width] x [0,height]; no +1',
            'min_depth_m': .1, 'randomness': 'none', 'seed': None, 'measure_latency': False,
            'selection': 'Car; occluded=0; truncated=0; finite in-image label; positive finite 3D dimensions; original corners projectable',
            'object_index_convention': 'zero-based load_frame labels after DontCare removal',
            'projection_denominator_epsilon': 1e-12,
        }
        write_result_files(objects, results, summaries, config, args.out_dir)
        figures = args.out_dir / 'figures'
        save_pass_rate_plot(summaries, figures / 'topic_f_angle_sweep.png')
        example = objects[0]
        image = datasets.load_frame(args.data_root, example.frame_id)['image']
        save_object_comparison(image, example, results, figures / 'topic_f_example_comparison.png')
        baseline = next(row for row in summaries if row.angle_deg == 0)
        supported = baseline.pass_rate >= .70
        print(f'Selected {len(objects)} Cars across {len(frame_ids)} frames. '
              f'Baseline pass rate: {baseline.pass_rate:.2%}; claim supported: {supported}.')
        print(f'Evidence saved to {args.out_dir}')
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
