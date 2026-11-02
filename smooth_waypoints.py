#!/usr/bin/env python3
"""Smooth a closed x,y,yaw,v reference with a periodic spline and map checks."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import splprep, splev
from scipy.ndimage import distance_transform_edt, map_coordinates
from scipy.spatial import cKDTree
import yaml

from mapwp_data import InputError, load_combination


def smooth(data, rms=0.12, spacing=0.1):
    if data.points.shape[1] != 4:
        raise InputError('Smoothing requires x,y,yaw,v columns.')
    if not np.isfinite(rms) or rms <= 0 or not np.isfinite(spacing) or spacing <= 0:
        raise InputError('Smoothing RMS and waypoint spacing must be positive finite numbers.')
    source = data.points.copy()
    gap = np.linalg.norm(source[-1, :2] - source[0, :2])
    if gap > 0.25:
        raise InputError(f'Path is not closed: endpoint gap is {gap:.2f} m.')
    if gap < 1e-8:
        source = source[:-1]
    if len(source) < 8:
        raise InputError('At least eight distinct waypoints are required.')
    closed = np.vstack((source, source[:1]))
    lengths = np.linalg.norm(np.diff(closed[:, :2], axis=0), axis=1)
    if np.any(lengths < 1e-8):
        raise InputError('Adjacent waypoint positions must be distinct.')
    arc = np.r_[0.0, np.cumsum(lengths)]
    source_u = arc / arc[-1]
    spline, _ = splprep(closed[:, :2].T, u=source_u,
                        s=len(closed) * rms * rms, per=True, k=3)
    # Dense evaluation supports arc-length resampling and geometric checks.
    dense_u = np.linspace(0, 1, max(10001, len(source) * 20))
    dense = np.asarray(splev(dense_u, spline)).T
    d1 = np.asarray(splev(dense_u, spline, der=1)).T
    d2 = np.asarray(splev(dense_u, spline, der=2)).T
    tangent_norm = np.linalg.norm(d1, axis=1)
    if np.any(tangent_norm < 1e-8):
        raise InputError('Spline contains a degenerate tangent.')
    curvature = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / tangent_norm ** 3
    smooth_arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
    count = max(8, int(np.ceil(smooth_arc[-1] / spacing)))
    output_u = np.interp(np.linspace(0, smooth_arc[-1], count + 1), smooth_arc, dense_u)
    xy = np.asarray(splev(output_u, spline)).T
    tangent = np.asarray(splev(output_u, spline, der=1)).T
    yaw = np.unwrap(np.arctan2(tangent[:, 1], tangent[:, 0]))
    speeds = np.interp(output_u, source_u, closed[:, 3])
    output = np.column_stack((xy, yaw, speeds))
    output[-1, :2] = output[0, :2]
    # Heading is continuous; the endpoint differs by an integer number of turns.
    output[-1, 2] = output[0, 2] + 2 * np.pi * np.round((output[-1, 2] - output[0, 2]) / (2 * np.pi))

    raw_u = np.linspace(0, 1, len(dense_u))
    raw_dense = np.column_stack([np.interp(raw_u, source_u, closed[:, i]) for i in (0, 1)])
    deviation = max(cKDTree(raw_dense).query(dense)[0].max(), cKDTree(dense).query(raw_dense)[0].max())
    config = yaml.safe_load(data.map_path.read_text())
    probability = data.image / 255.0 if config.get('negate', 0) else 1.0 - data.image / 255.0
    free = probability < float(config.get('free_thresh', 0.196))
    # Treat outside-image space as non-free too, and account for cell extent.
    padded = np.pad(free, 1, constant_values=False)
    distances = distance_transform_edt(padded)[1:-1, 1:-1] * data.resolution
    x0, y0, theta = data.origin
    c, s = np.cos(theta), np.sin(theta)
    local = (dense - np.array([x0, y0])) @ np.array([[c, -s], [s, c]])
    cells = local / data.resolution
    coords = np.array([data.image.shape[0] - 0.5 - cells[:, 1], cells[:, 0] - 0.5])
    clearance = map_coordinates(distances, coords, order=1, mode='constant', cval=0)
    conservative_clearance = np.maximum(0, clearance - data.resolution / np.sqrt(2))
    stats = {
        'source_points': len(data.points), 'output_points': len(output),
        'length_m': float(smooth_arc[-1]), 'max_deviation_m': float(deviation),
        'max_curvature_per_m': float(curvature.max()),
        'min_centerline_clearance_m': float(conservative_clearance.min()),
        'rms_target_m': rms, 'spacing_target_m': spacing,
        'heading_recomputed': True, 'closed_periodic_spline': True,
    }
    return output, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rms', type=float, default=0.12)
    parser.add_argument('--spacing', type=float, default=0.1)
    parser.add_argument('--max-deviation', type=float, default=0.35)
    parser.add_argument('--min-clearance', type=float, default=0.30)
    parser.add_argument('--wheelbase', type=float, default=0.33)
    parser.add_argument('--max-steer', type=float, default=0.4189)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists():
        parser.error('Output or its report already exists; choose a new output name.')
    try:
        data = load_combination(args.map.parent, args.map, args.source)
        output, stats = smooth(data, args.rms, args.spacing)
        steering = np.arctan(args.wheelbase * stats['max_curvature_per_m'])
        stats['max_required_steering_rad'] = float(steering)
        if stats['max_deviation_m'] > args.max_deviation:
            raise InputError(f"Maximum path deviation is {stats['max_deviation_m']:.3f} m; limit is {args.max_deviation:.3f} m.")
        if stats['min_centerline_clearance_m'] < args.min_clearance:
            raise InputError(f"Minimum map clearance is {stats['min_centerline_clearance_m']:.3f} m; required {args.min_clearance:.3f} m.")
        if steering > args.max_steer:
            raise InputError(f'Required steering is {steering:.3f} rad; limit is {args.max_steer:.3f} rad.')
        if not np.isfinite(output).all():
            raise InputError('The smoothed reference contains non-finite values.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        np.savetxt(args.output, output, delimiter=',', header='x,y,yaw,v', comments='', fmt='%.10f')
        args.output.with_suffix('.json').write_text(json.dumps({
            'map': str(data.map_path), 'source': str(data.waypoint_path), **stats,
            'limits': {'max_deviation_m': args.max_deviation, 'min_centerline_clearance_m': args.min_clearance,
                       'wheelbase_m': args.wheelbase, 'max_steering_rad': args.max_steer},
            'note': 'Map checks cover the reference centerline, not the full vehicle footprint or localization error.',
        }, indent=2) + '\n')
        print(json.dumps(stats, indent=2))
        print(f'Saved: {args.output}')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
