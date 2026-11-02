#!/usr/bin/env python3
"""Interactively compose maps and waypoints, or validate/render focus from the CLI."""
import argparse
import os
import sys
from pathlib import Path
from mapwp_data import InputError, load_combination


def main():
    folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--focus', type=Path, default=folder / 'focus')
    parser.add_argument('--map', type=Path, help='Override the selected map YAML')
    parser.add_argument('--waypoints', type=Path, help='Override the selected CSV')
    parser.add_argument('--save', type=Path, default=folder / 'output' / 'overlay.png')
    parser.add_argument('--no-show', action='store_true', help='Save without opening a window')
    parser.add_argument('--check', action='store_true', help='Validate without plotting')
    parser.add_argument('--static', action='store_true', help='Open the original single-plot viewer')
    args = parser.parse_args()
    try:
        if not (args.check or args.no_show or args.static or args.map or args.waypoints
                or args.focus != folder / 'focus' or args.save != folder / 'output' / 'overlay.png'):
            if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                raise InputError('No graphical display is available. Run mapwp --check or mapwp --no-show.')
            from mapwp_gui import open_composer
            open_composer(folder)
            return 0
        data = load_combination(args.focus, args.map, args.waypoints)
        print(f'Map: {data.map_path}')
        print(f'Image: {data.image_path}')
        print(f'Waypoints: {data.waypoint_path} ({len(data.points)} points)')
        for warning in data.warnings:
            print(f'Warning: {warning}', file=sys.stderr)
        if args.check:
            print('Input validation passed. This does not check collision clearance.')
            return 0
        if not args.no_show and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            raise InputError('No graphical display is available. Run mapwp --no-show to save an image.')
        from mapwp_plot import plot_combination
        plot_combination(data, args.save, show=not args.no_show)
        return 0
    except (InputError, OSError, ImportError, RuntimeError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
