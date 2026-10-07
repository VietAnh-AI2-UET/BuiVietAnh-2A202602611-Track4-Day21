def velo_to_cam(points_xyz: np.ndarray, calib: KittiCalib) -> np.ndarray:
    """Transform LiDAR points into the rectified camera coordinate system.

    Args:
        points_xyz: Array of shape (N, 3), in meters, with LiDAR axes
            x forward, y left, and z up. The input is not modified.
        calib: Calibration providing the (4, 4) transform T_cam_velo.

    Returns:
        Array of shape (N, 3), in meters, with camera axes x right,
        y down, and z forward. Point order is preserved; an empty input
        of shape (0, 3) produces an output of shape (0, 3).
    """
    points_hom = np.concatenate(
        [points_xyz, np.ones((points_xyz.shape[0], 1), dtype=points_xyz.dtype)],
        axis=1,
    )
    points_cam = points_hom @ calib.T_cam_velo.T
    return points_cam[:, :3]


def cam_to_image(points_cam: np.ndarray, P2: np.ndarray, image_shape: tuple[int, ...],
                 min_depth: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project camera points onto the image and keep valid pixels.

    Args:
        points_cam: Array of shape (N, 3) in camera coordinates, in meters.
        P2: Camera projection matrix of shape (3, 4).
        image_shape: Image dimensions, starting with (height, width).
        min_depth: Exclusive lower bound on camera z, in meters.

    Returns:
        Tuple (uv, depth, mask). The floating-point pixel coordinates uv
        have shape (M, 2); camera z values depth have shape (M,); the
        boolean mask has shape (N,) and selects retained input points.
        Retained points are finite, have z > min_depth, have a finite
        nonzero projection denominator, and lie within the image bounds.
        Input order is preserved and inputs are not modified.
    """
    height, width = image_shape[:2]
    depth = points_cam[:, 2]
    mask = np.isfinite(points_cam).all(axis=1) & (depth > min_depth)
    indices = np.flatnonzero(mask)
    points_hom = np.concatenate(
        [points_cam[mask], np.ones((len(indices), 1))], axis=1,
    )
    projected = points_hom @ P2.T
    denominator = projected[:, 2]
    projectable = np.isfinite(projected).all(axis=1) & (denominator != 0)
    uv = np.full((len(indices), 2), np.nan)
    with np.errstate(over="ignore", invalid="ignore"):
        uv[projectable] = projected[projectable, :2] / denominator[projectable, None]
    inside = (
        np.isfinite(uv).all(axis=1)
        & (uv[:, 0] >= 0) & (uv[:, 0] < width)
        & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    )
    mask[indices] = inside
    return uv[inside], depth[mask], mask
