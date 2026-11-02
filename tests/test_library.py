"""Behavior checks for library migration and staged focus replacement."""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapwp_data import InputError, load_combination
from mapwp_library import Library, migrate_legacy


def write_combo(folder, name='a', value=1):
    folder.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((20, 20), 255, dtype=np.uint8)).save(folder / f'{name}.pgm')
    (folder / f'{name}.yaml').write_text(yaml.safe_dump({
        'image': f'{name}.pgm', 'resolution': 1.0, 'origin': [0, 0, 0],
    }))
    (folder / f'{name}.csv').write_text(f'x,y,yaw,v\n{value},1,0,1\n{value+1},1,0,1\n')


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_combo(self.root / 'focus')
        (self.root / 'focus/reference').mkdir()
        (self.root / 'focus/reference/raw.txt').write_text('original ancillary file')
        write_combo(self.root / 'buffer/old_combo', 'b', 4)

    def tearDown(self):
        self.temp.cleanup()

    def migrated(self):
        return migrate_legacy(self.root)

    def test_migration_splits_deduplicates_and_deletes_legacy(self):
        shutil.copytree(self.root / 'buffer/old_combo', self.root / 'buffer/duplicate')
        config = self.root / 'buffer/old_combo/b.yaml'
        data = yaml.safe_load(config.read_text())
        data['centerline'] = 'centerline.csv'
        config.write_text(yaml.safe_dump(data))
        (config.parent / 'centerline.csv').write_text('x,y\n1,1\n2,2\n')
        library = self.migrated()
        self.assertEqual(set(p.name for p in library.buffer.iterdir()), {'maps', 'waypoints'})
        self.assertEqual(len(library.waypoints()), 2)
        self.assertTrue((library.focus / 'reference/raw.txt').is_file())
        self.assertFalse((library.buffer / 'old_combo').exists())
        for map_path in library.maps():
            cfg = yaml.safe_load(map_path.read_text())
            self.assertTrue((map_path.parent / cfg['image']).is_file())
        self.assertFalse(any(p.name == 'centerline.csv' for p in library.waypoints()))

    def test_apply_replaces_focus_without_retaining_old_combination(self):
        library = self.migrated()
        map_path = next(p for p in library.maps() if p.stem == 'b')
        wp_path = next(p for p in library.waypoints() if p.stem == 'b')
        data = library.apply(map_path, wp_path)
        self.assertEqual(data.waypoint_path.name, 'b.csv')
        self.assertFalse((library.focus / 'reference/raw.txt').exists())
        self.assertFalse((self.root / '.previous_focus').exists())
        self.assertFalse(list(self.root.glob('.focus-stage-*')))

    def test_invalid_preview_does_not_replace_focus(self):
        library = self.migrated()
        with self.assertRaisesRegex(InputError, 'Map YAML does not exist'):
            library.apply(self.root / 'missing.yaml', library.waypoints()[0])
        self.assertTrue((library.focus / 'a.csv').is_file())
        self.assertFalse((self.root / '.previous_focus').exists())

    def test_failed_focus_swap_rolls_back(self):
        library = self.migrated()
        map_path = next(p for p in library.maps() if p.stem == 'b')
        wp_path = next(p for p in library.waypoints() if p.stem == 'b')
        original_rename = Path.rename

        def fail_stage(path, target):
            if path.name == 'focus' and path.parent.name.startswith('.focus-stage-'):
                raise OSError('Injected staging failure')
            return original_rename(path, target)

        with patch.object(Path, 'rename', fail_stage):
            with self.assertRaisesRegex(OSError, 'Injected staging failure'):
                library.apply(map_path, wp_path)
        self.assertTrue((library.focus / 'a.csv').is_file())
        self.assertTrue((library.focus / 'reference/raw.txt').is_file())
        self.assertFalse((self.root / '.previous_focus').exists())


if __name__ == '__main__':
    unittest.main()
