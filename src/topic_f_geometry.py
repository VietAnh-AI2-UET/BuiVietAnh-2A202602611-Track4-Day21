"""Pure geometry for a camera-y rotation and continuous pixel rectangles."""
from dataclasses import dataclass

import numpy as np


@dataclass
class ProjectionResult:
    """Describe a projected rectangle or why no rectangle can be used.

    Attributes:
        bbox: Continuous pixel coordinates (x1, y1, x2, y2), shape (4,), or None.
        status: One of 'ok', 'not_projectable', or 'outside_image'.
    """

    bbox: np.ndarray | None
    status: str


def rotate_camera_corners(corners: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate eight corners about the camera origin without modifying input.

    Args:
        corners: Shape (8, 3), camera metres: x right, y down, z forward.
        angle_deg: Finite angle in degrees; positive moves forward points right.

    Returns:
        Newly allocated (8, 3) camera coordinates, including at zero degrees.

    Raises:
        ValueError: If the corner shape or angle is invalid.
    """
    corners = np.asarray(corners, dtype=float)
    if corners.shape != (8, 3) or not np.isfinite(angle_deg):
        raise ValueError('Expected corners (8, 3) and a finite angle_deg')
    theta = np.deg2rad(angle_deg)
    c, s = np.cos(theta), np.sin(theta)
    # Rotate around camera y, not the car centre; the sign is tested at +90 deg.
    rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return corners @ rotation.T


def project_box_to_image(corners: np.ndarray, P2: np.ndarray,
                         image_shape: tuple[int, ...]) -> ProjectionResult:
    """Project all eight corners, enclose them, then clip to image boundaries.

    Args:
        corners: Shape (8, 3), camera coordinates in metres; never mutated.
        P2: Finite projection matrix, shape (3, 4); never mutated.
        image_shape: Image height and width, optionally followed by channels.

    Returns:
        Continuous pixel box clipped to [0, width] and [0, height]. Invalid
        geometry (nonfinite, depth <= 0.1 m, denominator <= 1e-12) yields
        'not_projectable'; zero clipped area yields 'outside_image'.

    Raises:
        ValueError: If shapes, image dimensions, or matrix values are invalid.
    """
    corners = np.asarray(corners, dtype=float)
    P2 = np.asarray(P2, dtype=float)
    if corners.shape != (8, 3) or P2.shape != (3, 4) or not np.isfinite(P2).all():
        raise ValueError('Expected corners (8, 3) and finite P2 (3, 4)')
    if len(image_shape) < 2 or any(not np.isfinite(v) or v <= 0 or int(v) != v for v in image_shape[:2]):
        raise ValueError('Image height and width must be positive integers')
    if not np.isfinite(corners).all() or np.any(corners[:, 2] <= 0.1):
        return ProjectionResult(None, 'not_projectable')
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        homogeneous = np.column_stack((corners, np.ones(8))) @ P2.T
        if not np.isfinite(homogeneous).all() or np.any(homogeneous[:, 2] <= 1e-12):
            return ProjectionResult(None, 'not_projectable')
        pixels = homogeneous[:, :2] / homogeneous[:, 2, None]
    if not np.isfinite(pixels).all():
        return ProjectionResult(None, 'not_projectable')
    # Off-screen corners must influence min/max before clipping the whole box.
    box = np.concatenate((pixels.min(axis=0), pixels.max(axis=0)))
    height, width = image_shape[:2]
    box = np.clip(box, 0, [width, height, width, height])
    if box[2] <= box[0] or box[3] <= box[1]:
        return ProjectionResult(None, 'outside_image')
    return ProjectionResult(box, 'ok')


def box_iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
    """Compute intersection over union using continuous pixel areas, without +1.

    Args:
        box_a: Shape (4,), finite ordered (x1, y1, x2, y2) in pixels.
        box_b: Same convention as box_a; neither input is mutated.

    Returns:
        Overlap ratio in [0, 1]; zero if either rectangle has zero area.

    Raises:
        ValueError: If a box has invalid shape, nonfinite or reversed coordinates.
    """
    a, b = np.asarray(box_a, dtype=float), np.asarray(box_b, dtype=float)
    for box in (a, b):
        if box.shape != (4,) or not np.isfinite(box).all() or np.any(box[2:] < box[:2]):
            raise ValueError('Boxes must be finite ordered arrays of shape (4,)')
    area_a, area_b = np.prod(a[2:] - a[:2]), np.prod(b[2:] - b[:2])
    if area_a == 0 or area_b == 0:
        return 0.0
    intersection = np.prod(np.maximum(0, np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2])))
    return float(intersection / (area_a + area_b - intersection))
