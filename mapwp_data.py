"""Discover and validate a ROS map and waypoint CSV."""
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import numpy as np
import yaml
from PIL import Image


class InputError(ValueError):
    """An actionable input problem."""


@dataclass
class Combination:
    map_path: Path
    image_path: Path
    waypoint_path: Path
    image: np.ndarray
    points: np.ndarray
    resolution: float
    origin: tuple
    warnings: list


def select_file(folder, suffixes, label, option):
    if not folder.is_dir():
        raise InputError(f'Input folder does not exist: {folder}. Create it and add a map YAML, its image, and a waypoint CSV.')
    matches = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)
    if not matches:
        raise InputError(f'No {label} found in {folder}. Add one file ending in {" or ".join(suffixes)}.')
    if len(matches) > 1:
        names = ', '.join(p.name for p in matches)
        raise InputError(f'Multiple {label} files found: {names}. Move spare files to buffer/ or select one with {option} PATH.')
    return matches[0]


def load_waypoints(path):
    if not path.is_file():
        raise InputError(f'Waypoint CSV does not exist: {path}')
    lines = [s.strip() for s in path.read_text(encoding='utf-8-sig').splitlines()
             if s.strip() and not s.lstrip().startswith('#')]
    if not lines:
        raise InputError(f'Waypoint CSV is empty: {path}')
    fields = [s.strip() for s in lines[0].split(',')]
    try:
        [float(s) for s in fields]
    except ValueError:
        if len(fields) < 2 or fields[0].lower() not in ('x', 'x_m', 'px', 'p_x') or fields[1].lower() not in ('y', 'y_m', 'py', 'p_y'):
            raise InputError(f'Invalid CSV header in {path.name}. The first two columns must be x and y (or x_m and y_m).') from None
        lines = lines[1:]
    if len(lines) < 2:
        raise InputError(f'{path.name} needs at least two waypoint rows.')
    try:
        points = np.loadtxt(StringIO('\n'.join(lines)), delimiter=',', ndmin=2)
    except ValueError as exc:
        raise InputError(f'Invalid numeric CSV data in {path.name}: {exc}') from None
    if points.shape[1] < 2 or not np.isfinite(points).all():
        raise InputError(f'{path.name} needs at least two columns with finite numeric values in every column.')
    return points


def load_combination(folder, map_path=None, waypoint_path=None):
    folder = Path(folder).expanduser().resolve()
    map_path = Path(map_path).expanduser().resolve() if map_path else select_file(folder, ('.yaml', '.yml'), 'map YAML', '--map')
    waypoint_path = Path(waypoint_path).expanduser().resolve() if waypoint_path else select_file(folder, ('.csv',), 'waypoint CSV', '--waypoints')
    if not map_path.is_file():
        raise InputError(f'Map YAML does not exist: {map_path}')
    try:
        cfg = yaml.safe_load(map_path.read_text())
    except yaml.YAMLError as exc:
        raise InputError(f'Invalid YAML in {map_path.name}: {exc}') from None
    if not isinstance(cfg, dict):
        raise InputError(f'{map_path.name} must contain image, resolution, and origin fields.')
    for key in ('image', 'resolution', 'origin'):
        if key not in cfg:
            raise InputError(f'{map_path.name} is missing the required "{key}" field.')
    if not isinstance(cfg['image'], str) or not cfg['image'].strip():
        raise InputError('The map image field must be a non-empty file path.')
    image_path = Path(cfg['image']).expanduser()
    if not image_path.is_absolute():
        image_path = map_path.parent / image_path
    image_path = image_path.resolve()
    if not image_path.is_file():
        raise InputError(f'Map image does not exist: {image_path}. Copy the image here or correct the YAML image field.')
    try:
        resolution = float(cfg['resolution'])
        origin = np.asarray(cfg['origin'], dtype=float)
    except (ValueError, TypeError):
        raise InputError('Map resolution must be a number and origin must be [x, y, yaw].') from None
    if not np.isfinite(resolution) or resolution <= 0:
        raise InputError('Map resolution must be a positive finite number in meters per pixel.')
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise InputError('Map origin must contain exactly three finite numbers: [x, y, yaw].')
    try:
        with Image.open(image_path) as source:
            image = np.asarray(source.convert('L'))
    except OSError as exc:
        raise InputError(f'Cannot read map image {image_path.name}: {exc}') from None
    points = load_waypoints(waypoint_path)
    warnings = []
    delta = points[:, :2] - origin[:2]
    c, s = np.cos(origin[2]), np.sin(origin[2])
    local = delta @ np.array([[c, -s], [s, c]])
    height, width = image.shape
    outside = ((local[:, 0] < 0) | (local[:, 0] >= width * resolution)
               | (local[:, 1] < 0) | (local[:, 1] >= height * resolution))
    if outside.any():
        warnings.append(f'{outside.sum()} waypoint(s) are outside the map image bounds. Check the map/CSV combination, coordinate frame, and units.')
    gap = float(np.linalg.norm(points[-1, :2] - points[0, :2]))
    if gap > 0.5:
        warnings.append(f'The first and last waypoints are {gap:.2f} m apart. The path is drawn as recorded; no closing segment is added.')
    return Combination(map_path, image_path, waypoint_path, image, points,
                       resolution, tuple(origin), warnings)
