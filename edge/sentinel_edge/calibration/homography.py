from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("sentinel.edge.calibration")


@dataclass
class CameraCalibration:
    """
    Planar Homography Camera Calibration Model for Physical Speed Estimation.
    Maps 2D camera image coordinates (pixels) to real-world ground coordinates (meters).
    """
    id: str = "CALIB_DEFAULT"
    camera_id: str = "CAM_DEFAULT"
    image_width: int = 1920
    image_height: int = 1080
    # 4 image points [[u1, v1], [u2, v2], [u3, v3], [u4, v4]]
    ground_plane_points: List[List[float]] = field(default_factory=list)
    # 4 real-world ground coordinates in meters [[X1, Y1], [X2, Y2], [X3, Y3], [X4, Y4]]
    reference_distances: List[List[float]] = field(default_factory=list)
    homography_matrix: List[List[float]] = field(default_factory=list)
    calibration_method: str = "4_POINT_PLANAR_HOMOGRAPHY"
    version: int = 1
    is_active: bool = True
    calibrated_by: str = "SYSTEM"
    calibrated_at: Optional[str] = None
    max_plausible_speed_kmh: float = 220.0
    min_displacement_meters: float = 0.05
    min_dt_seconds: float = 0.01

    def __init__(
        self,
        id: str = "CALIB_DEFAULT",
        camera_id: str = "CAM_DEFAULT",
        image_width: int = 1920,
        image_height: int = 1080,
        ground_plane_points: Optional[List[Any]] = None,
        reference_distances: Optional[List[Any]] = None,
        homography_matrix: Optional[List[Any]] = None,
        calibration_method: str = "4_POINT_PLANAR_HOMOGRAPHY",
        version: int = 1,
        is_active: bool = True,
        calibrated_by: str = "SYSTEM",
        calibrated_at: Optional[str] = None,
        max_plausible_speed_kmh: float = 220.0,
        min_displacement_meters: float = 0.05,
        min_dt_seconds: float = 0.01,
        # Convenience aliases for initialization
        calibration_id: Optional[str] = None,
        image_polygon: Optional[List[Any]] = None,
        real_width_meters: Optional[float] = None,
        real_length_meters: Optional[float] = None,
    ):
        self.id = calibration_id or id
        self.camera_id = camera_id
        self.image_width = image_width
        self.image_height = image_height

        if image_polygon is not None:
            self.ground_plane_points = [list(pt) for pt in image_polygon]
        else:
            self.ground_plane_points = [list(pt) for pt in (ground_plane_points or [])]

        if real_width_meters is not None and real_length_meters is not None:
            self.reference_distances = [
                [0.0, 0.0],
                [float(real_width_meters), 0.0],
                [float(real_width_meters), float(real_length_meters)],
                [0.0, float(real_length_meters)],
            ]
        elif reference_distances is not None:
            self.reference_distances = [list(pt) for pt in reference_distances]
        else:
            self.reference_distances = []

        self.homography_matrix = homography_matrix or []
        self.calibration_method = calibration_method
        self.version = version
        self.is_active = is_active
        self.calibrated_by = calibrated_by
        self.calibrated_at = calibrated_at
        self.max_plausible_speed_kmh = float(max_plausible_speed_kmh)
        self.min_displacement_meters = float(min_displacement_meters)
        self.min_dt_seconds = float(min_dt_seconds)

    def validate(self) -> bool:
        """Ensure the calibration points form a valid, non-degenerate quadrilateral."""
        if len(self.ground_plane_points) != 4 or len(self.reference_distances) != 4:
            return False
        try:
            pts = np.array(self.ground_plane_points, dtype=np.float32)
            if pts.shape != (4, 2):
                return False
            area = cv2.contourArea(pts)
            if area < 50.0:
                return False
            return True
        except Exception:
            return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraCalibration:
        return cls(
            id=str(data.get("id", data.get("calibration_id", "CALIB_DEFAULT"))),
            camera_id=str(data.get("camera_id", "CAM_DEFAULT")),
            image_width=int(data.get("image_width", 1920)),
            image_height=int(data.get("image_height", 1080)),
            ground_plane_points=data.get("ground_plane_points", data.get("image_polygon", [])),
            reference_distances=data.get("reference_distances", []),
            homography_matrix=data.get("homography_matrix", []),
            calibration_method=data.get("calibration_method", "4_POINT_PLANAR_HOMOGRAPHY"),
            version=int(data.get("version", 1)),
            is_active=bool(data.get("is_active", True)),
            calibrated_by=str(data.get("calibrated_by", "SYSTEM")),
            calibrated_at=data.get("calibrated_at"),
            max_plausible_speed_kmh=float(data.get("max_plausible_speed_kmh", 220.0)),
            min_displacement_meters=float(data.get("min_displacement_meters", 0.05)),
            min_dt_seconds=float(data.get("min_dt_seconds", 0.01)),
            real_width_meters=data.get("real_width_meters"),
            real_length_meters=data.get("real_length_meters"),
        )


class HomographyCalibrator:
    """
    Mathematical calibration engine utilizing OpenCV perspective transformations.
    Validates geometric constraints and computes transformations between image plane
    and real-world road plane.
    """

    def __init__(self, calibration: Optional[CameraCalibration] = None):
        self.calibration = calibration
        self.H: Optional[np.ndarray] = None
        self.H_inv: Optional[np.ndarray] = None
        self.image_poly: Optional[np.ndarray] = None
        if self.calibration is not None:
            self._initialize_homography()

    @property
    def is_calibrated(self) -> bool:
        return self.calibration is not None and self.H is not None and bool(self.calibration.is_active)

    @property
    def inv_homography_matrix(self) -> Optional[np.ndarray]:
        return self.H_inv

    def _initialize_homography(self) -> None:
        if self.calibration is None:
            return

        src = self.calibration.ground_plane_points
        dst = self.calibration.reference_distances

        if len(src) != 4 or len(dst) != 4:
            raise ValueError(
                f"Homography calibration requires exactly 4 correspondence points. Got src={len(src)}, dst={len(dst)}"
            )

        src_pts = np.array(src, dtype=np.float32)
        dst_pts = np.array(dst, dtype=np.float32)

        # 1. Geometric validation of source image quadrilateral
        self._validate_quadrilateral(src_pts)

        # 2. Geometric validation of destination real-world distances
        self._validate_physical_dimensions(dst_pts)

        # 3. Compute 3x3 Homography Matrix via cv2.getPerspectiveTransform
        self.H = cv2.getPerspectiveTransform(src_pts, dst_pts)
        if self.H is None or np.isnan(self.H).any() or np.isinf(self.H).any():
            raise ValueError("Perspective transformation computation yielded an invalid/singular matrix")

        # 4. Invert matrix for reverse projection
        try:
            self.H_inv = np.linalg.inv(self.H)
        except np.linalg.LinAlgError:
            self.H_inv = None
            logger.warning("Homography matrix is singular; inverse mapping unavailable")

        # 5. Store matrix in calibration object if not already serialized
        self.calibration.homography_matrix = self.H.tolist()

        # 6. Store convex polygon for region-of-interest testing
        self.image_poly = src_pts.reshape((-1, 1, 2)).astype(np.int32)

    @staticmethod
    def _validate_quadrilateral(pts: np.ndarray) -> None:
        """Ensure the 4 points form a non-degenerate, non-collinear convex quadrilateral."""
        if pts.shape != (4, 2):
            raise ValueError(f"Points array must have shape (4, 2), got {pts.shape}")

        # Check for duplicate coordinates
        for i in range(4):
            for j in range(i + 1, 4):
                if np.linalg.norm(pts[i] - pts[j]) < 1.0:
                    raise ValueError(f"Points {i} and {j} are nearly identical in image space")

        # Check area of polygon using cross-product / cv2.contourArea
        area = cv2.contourArea(pts.astype(np.float32))
        if area < 50.0:
            raise ValueError(f"Image calibration quadrilateral area is too small or degenerate: {area:.1f} px²")

        # Verify convexity
        is_convex = cv2.isContourConvex(pts.astype(np.int32))
        if not is_convex:
            logger.warning("Source image calibration quadrilateral is non-convex. Points should be ordered clockwise.")

    @staticmethod
    def _validate_physical_dimensions(pts: np.ndarray) -> None:
        """Validate physical ground-plane coordinates in meters."""
        if pts.shape != (4, 2):
            raise ValueError(f"Physical points must have shape (4, 2), got {pts.shape}")

        p0, p1, p2, p3 = pts[0], pts[1], pts[2], pts[3]
        width1 = np.linalg.norm(p1 - p0)
        width2 = np.linalg.norm(p2 - p3)
        len1 = np.linalg.norm(p3 - p0)
        len2 = np.linalg.norm(p2 - p1)

        min_dim = min(width1, width2, len1, len2)
        max_dim = max(width1, width2, len1, len2)

        if min_dim < 0.2:
            raise ValueError(f"Physical distance between calibration vertices is unrealistically small: {min_dim:.2f} m")
        if max_dim > 5000.0:
            raise ValueError(f"Physical distance exceeds plausible camera coverage (> 5km): {max_dim:.2f} m")

    def image_to_ground(self, *args) -> Tuple[float, float]:
        """
        Transforms an image coordinate (u, v) in pixels to ground-plane coordinate (X, Y) in meters.
        Accepts either image_to_ground((u, v)) or image_to_ground(u, v).
        P_ground = H * [u, v, 1]^T -> (x'/z', y'/z')
        """
        if len(args) == 1 and isinstance(args[0], (tuple, list, np.ndarray)):
            u, v = float(args[0][0]), float(args[0][1])
        elif len(args) == 2:
            u, v = float(args[0]), float(args[1])
        else:
            raise ValueError(f"image_to_ground requires (u, v) or u, v; got {args}")

        if self.H is None:
            raise RuntimeError("Homography matrix is uninitialized")

        vec = np.array([u, v, 1.0], dtype=np.float64)
        projected = self.H @ vec
        z = projected[2]

        if abs(z) < 1e-7:
            raise ValueError(f"Point ({u}, {v}) projected onto horizon or vanishing line (z ~ 0)")

        x_meters = float(projected[0] / z)
        y_meters = float(projected[1] / z)
        return x_meters, y_meters

    def is_point_in_calibrated_region(self, u: float, v: float) -> bool:
        """Checks if image coordinate is located within the calibrated road polygon."""
        if self.image_poly is None:
            return False
        dist = cv2.pointPolygonTest(self.image_poly, (float(u), float(v)), measureDist=False)
        return dist >= 0

    def compute_ground_speed(
        self,
        prev_image_point: Tuple[float, float],
        curr_image_point: Tuple[float, float],
        dt_seconds: float,
    ) -> Tuple[Optional[float], str, Optional[str]]:
        """
        Computes calibrated physical ground speed in km/h.
        Returns:
            (speed_kmh, speed_status, speed_display_reason)
            status: "VALID" | "INVALID_MEASUREMENT" | "CALIBRATION_REQUIRED"
        """
        if self.calibration is None or not self.calibration.is_active or self.H is None:
            return None, "CALIBRATION_REQUIRED", "SPEED UNAVAILABLE — CAMERA CALIBRATION REQUIRED"

        if dt_seconds < self.calibration.min_dt_seconds:
            return None, "INVALID_MEASUREMENT", f"Delta timestamp too small ({dt_seconds*1000:.1f}ms < {self.calibration.min_dt_seconds*1000:.1f}ms)"

        try:
            x0, y0 = self.image_to_ground(prev_image_point[0], prev_image_point[1])
            x1, y1 = self.image_to_ground(curr_image_point[0], curr_image_point[1])
        except Exception as exc:
            return None, "INVALID_MEASUREMENT", f"Projection failed: {exc}"

        dx = x1 - x0
        dy = y1 - y0
        displacement_meters = math.hypot(dx, dy)

        # 1. Jitter filter: Sub-5cm displacement is detector bounding box jitter / stationary vehicle
        if displacement_meters < self.calibration.min_displacement_meters:
            return 0.0, "VALID", None

        v_mps = displacement_meters / dt_seconds
        v_kmh = v_mps * 3.6

        # 2. Plausibility limit check
        if v_kmh > self.calibration.max_plausible_speed_kmh:
            return None, "INVALID_MEASUREMENT", f"Speed {v_kmh:.1f} km/h exceeds physical plausibility ({self.calibration.max_plausible_speed_kmh:.1f} km/h)"

        return round(v_kmh, 1), "VALID", None

    def calculate_speed_kmh(
        self,
        prev_point: Tuple[float, float],
        curr_point: Tuple[float, float],
        dt_seconds: float,
    ) -> Tuple[Optional[float], str]:
        """Convenience method returning (speed_kmh, status)."""
        if not self.is_calibrated:
            return None, "CALIBRATION_REQUIRED"
        if dt_seconds < self.calibration.min_dt_seconds:
            return None, "INVALID_DT"
        speed, status, reason = self.compute_ground_speed(prev_point, curr_point, dt_seconds)
        if status == "VALID":
            return speed, "CALIBRATED_METRIC"
        elif reason and "exceeds physical plausibility" in str(reason):
            return None, "UNREALISTIC_PHYSICS"
        elif reason and "Delta timestamp too small" in str(reason):
            return None, "INVALID_DT"
        else:
            return None, status


class CalibrationStorage:
    """
    Per-camera calibration persistence engine.
    Saves and loads calibrations with local filesystem cache.
    Never stores calibrations globally; isolates geometry per camera_id.
    """
    import json
    from pathlib import Path

    @classmethod
    def get_default_config_dir(cls) -> Path:
        from pathlib import Path
        config_dir = Path(__file__).resolve().parent / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @classmethod
    def save_to_file(cls, calibration: CameraCalibration, config_dir: Optional[Any] = None) -> Any:
        import json
        from pathlib import Path
        target_dir = Path(config_dir) if config_dir else cls.get_default_config_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{calibration.camera_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(calibration.to_dict(), f, indent=2)
        logger.info("[%s] Saved calibration configuration to %s", calibration.camera_id, file_path)
        return file_path

    @classmethod
    def load_from_file(cls, camera_id: str, config_dir: Optional[Any] = None) -> Optional[CameraCalibration]:
        import json
        from pathlib import Path
        target_dir = Path(config_dir) if config_dir else cls.get_default_config_dir()
        file_path = target_dir / f"{camera_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            calib = CameraCalibration.from_dict(data)
            if calib.is_active and calib.validate():
                return calib
            return None
        except Exception as e:
            logger.warning("[%s] Error loading calibration file: %s", camera_id, e)
            return None

    @classmethod
    def clear_file(cls, camera_id: str, config_dir: Optional[Any] = None) -> bool:
        from pathlib import Path
        target_dir = Path(config_dir) if config_dir else cls.get_default_config_dir()
        file_path = target_dir / f"{camera_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info("[%s] Cleared calibration file %s", camera_id, file_path)
            return True
        return False


def validate_calibration_geometry(
    image_points: List[Any],
    real_width: Optional[float] = None,
    real_length: Optional[float] = None,
    reference_distances: Optional[List[Any]] = None,
) -> Tuple[bool, str]:
    """
    Validates calibration quadrilateral geometry and physical dimensions.
    Returns (True, "Valid") or (False, error_message).
    """
    if not image_points or len(image_points) != 4:
        return False, f"Expected exactly 4 ground plane image points, got {len(image_points) if image_points else 0}"

    if real_width is not None and real_width <= 0:
        return False, f"Real width must be strictly positive (> 0), got {real_width}"

    if real_length is not None and real_length <= 0:
        return False, f"Real length must be strictly positive (> 0), got {real_length}"

    try:
        pts = np.array(image_points, dtype=np.float32)
        if pts.shape != (4, 2):
            return False, f"Points must have shape (4, 2), got {pts.shape}"

        area = cv2.contourArea(pts)
        if area < 50.0:
            return False, f"Contour area {area:.1f} px^2 is too small or points are collinear"

        if not cv2.isContourConvex(pts.astype(np.int32)):
            return False, "Image polygon must be convex (self-intersecting or bowtie quads rejected)"

        # Check homography solvability
        if real_width is not None and real_length is not None:
            dst = np.array([
                [0.0, 0.0],
                [float(real_width), 0.0],
                [float(real_width), float(real_length)],
                [0.0, float(real_length)],
            ], dtype=np.float32)
        elif reference_distances is not None and len(reference_distances) == 4:
            dst = np.array(reference_distances, dtype=np.float32)
        else:
            return False, "Either (real_width, real_length) or reference_distances (4 points) must be provided"

        H = cv2.getPerspectiveTransform(pts, dst)
        if H is None or abs(np.linalg.det(H)) < 1e-12:
            return False, "Perspective transform matrix is singular or non-invertible"

        return True, "Valid"
    except Exception as exc:
        return False, f"Validation error: {exc}"

