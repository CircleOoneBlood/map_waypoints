"""Separate map/waypoint libraries and staged local focus changes."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import yaml

from mapwp_data import InputError, load_combination


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_map(path):
    try:
        config = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        raise InputError(f'Invalid map YAML: {path}: {exc}') from None
    if not isinstance(config, dict) or not isinstance(config.get('image'), str):
        raise InputError(f'Map YAML must contain an image path: {path}')
    return config


def referenced_path(map_path, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(map_path).parent / path


def map_signature(path):
    config = read_map(path)
    for key in ('image', 'centerline', 'raceline'):
        if key in config:
            asset = referenced_path(path, config[key])
            if not asset.is_file():
                raise InputError(f'Map {path.name} references a missing file: {asset}')
            config[key] = digest(asset)
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def copy_map(path, destination):
    """Make referenced files portable; CSV assets stay below assets/."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    config = read_map(path)
    for key in ('image', 'centerline', 'raceline'):
        if key not in config:
            continue
        source = referenced_path(path, config[key])
        if not source.is_file():
            raise InputError(f'Missing {key} file: {source}')
        relative = Path('assets') / f'{key}_{source.name}'
        target = destination / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        config[key] = relative.as_posix()
    target = destination / Path(path).name
    target.write_text(yaml.safe_dump(config, sort_keys=False))
    return target


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.buffer = self.root / 'buffer'
        self.maps_dir = self.buffer / 'maps'
        self.waypoints_dir = self.buffer / 'waypoints'
        self.focus = self.root / 'focus'

    def maps(self):
        return sorted((p for p in self.maps_dir.rglob('*')
                       if p.is_file() and p.suffix.lower() in ('.yaml', '.yml')),
                      key=lambda p: str(p.relative_to(self.maps_dir)).lower())

    def waypoints(self):
        return sorted(self.waypoints_dir.rglob('*.csv'), key=lambda p: p.name.lower())

    @contextmanager
    def lock(self):
        with (self.root / '.focus.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InputError('Another viewer is changing focus. Try again when it finishes.') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def apply(self, map_path, waypoint_path):
        """Validate in staging, replace focus, and discard the old combination."""
        with self.lock(), tempfile.TemporaryDirectory(prefix='.focus-stage-', dir=self.root) as tmp:
            data = load_combination(self.focus, map_path, waypoint_path)
            stage = Path(tmp) / 'focus'
            copy_map(data.map_path, stage)
            shutil.copy2(data.waypoint_path, stage / data.waypoint_path.name)
            (stage / '.combo.json').write_text(json.dumps({
                'map_source': str(data.map_path), 'waypoints_source': str(data.waypoint_path),
            }, indent=2) + '\n')
            load_combination(stage)
            old_focus = Path(tmp) / 'old_focus'
            had_focus = self.focus.exists()
            if had_focus:
                self.focus.rename(old_focus)
            try:
                stage.rename(self.focus)
            except Exception:
                if had_focus:
                    old_focus.rename(self.focus)
                raise
        return load_combination(self.focus)


def migrate_legacy(root):
    """Split and deduplicate old combos, then delete old mixed folders."""
    library = Library(root)
    if library.maps_dir.exists() or library.waypoints_dir.exists():
        raise InputError('The separate libraries already exist; migration was not repeated.')
    with library.lock(), tempfile.TemporaryDirectory(prefix='.library-stage-', dir=library.root) as tmp:
        stage = Path(tmp) / 'buffer'
        maps = stage / 'maps'
        waypoints = stage / 'waypoints'
        maps.mkdir(parents=True)
        waypoints.mkdir()
        candidates = sorted(library.buffer.rglob('*')) + sorted(library.focus.rglob('*'))
        configs = [p for p in candidates if p.is_file() and p.suffix.lower() in ('.yaml', '.yml')]
        map_hashes = {}
        excluded_csvs = set()
        for path in configs:
            config = read_map(path)
            for key in ('centerline', 'raceline'):
                if key in config:
                    excluded_csvs.add(referenced_path(path, config[key]).resolve())
            signature = map_signature(path)
            if signature in map_hashes:
                continue
            folder = maps / path.stem
            if folder.exists():
                folder = maps / f'{path.stem}_{signature[:8]}'
            copied = copy_map(path, folder)
            assert map_signature(copied) == signature
            map_hashes[signature] = copied
        csv_hashes = {}
        for path in candidates:
            if not path.is_file() or path.suffix.lower() != '.csv' or path.resolve() in excluded_csvs:
                continue
            from mapwp_data import load_waypoints
            load_waypoints(path)
            signature = digest(path)
            if signature in csv_hashes:
                continue
            target = waypoints / path.name
            if target.exists():
                target = waypoints / f'{path.stem}_{signature[:8]}.csv'
            shutil.copy2(path, target)
            assert digest(target) == signature
            csv_hashes[signature] = target
        if not map_hashes or not csv_hashes:
            raise InputError('Migration needs at least one valid map and waypoint CSV. Old files were not deleted.')
        # All input assets are verified before removing the legacy directories.
        legacy = Path(tmp) / 'legacy_buffer'
        library.buffer.rename(legacy)
        try:
            stage.rename(library.buffer)
        except Exception:
            legacy.rename(library.buffer)
            raise
        print(f'Library ready: {len(map_hashes)} maps, {len(csv_hashes)} waypoint files. Legacy mixed folders deleted.')
    return library
