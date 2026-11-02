# MapWP: map and waypoint composer

A standalone Python desktop tool for previewing occupancy maps with waypoint
routes, selecting combinations, and smoothing closed paths. No ROS installation,
simulator, or workspace build is required.

Supports Linux desktops with Python 3.10 or newer. Native Windows is currently
unsupported because focus updates use Unix file locking (`fcntl`). A graphical
desktop is needed for the GUI; validation and image export work headlessly.

## Install and launch (Ubuntu)

```bash
git clone https://github.com/CircleOoneBlood/map_waypoints.git
cd map_waypoints
sudo apt update
sudo apt install python3 python3-tk python3-numpy python3-matplotlib python3-pil python3-yaml python3-scipy
/usr/bin/python3 -E -B visualize.py
```

The library starts empty. No real maps, waypoint routes, or generated images
are included. The application displays instructions for adding your own data.
There is no shell alias to configure.

Alternatively, on Linux, install Python, Tk, and venv support using your system
package manager, then use a Python 3.12 virtual environment. The requirements
file records the dependency versions used for verification:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python visualize.py
```

Tkinter is a system dependency and is not installed by pip. SciPy is needed for
the smoothing utility and its tests.

## Add your own map and waypoints

Use this layout, replacing `my_map` and `my_route` with your own names:

```text
buffer/
  maps/
    my_map/
      my_map.yaml
      my_map.pgm
  waypoints/
    my_route.csv
focus/                  # Active combination, created by Apply to focus
output/                 # Saved images, created as needed
```

Example map YAML (set resolution and origin to your map's actual values):

```yaml
image: my_map.pgm
resolution: 0.05
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
```

Image paths are relative to the YAML file. PNG and PGM images are supported.
Optional `centerline` and `raceline` CSV references must also point to existing
files; keep those assets with the map.

Waypoint CSVs must have x and y as their first two numeric columns, in meters
in the map coordinate frame. Extra numeric columns such as yaw and speed are
accepted. Headers (`x,y,...` or `x_m,y_m,...`), `#` comments, and headerless CSVs
are supported. At least two numeric rows are required.

Click **Refresh**, select a map and waypoint file, then click **Preview**.
Inspect the alignment and click **Apply to focus** to save the active combination.
On a fresh installation, use Preview before applying because no focus exists yet.
The library, focus contents, and generated images are ignored by Git.

## Controls

- **Map / Waypoints:** select independent inputs and preview their combination.
- **Preview:** reload and validate the selected files.
- **Apply to focus:** copy a portable combination into focus, replacing the old one.
- **Load focus:** show the current active combination.
- **Refresh:** rescan the library after adding files.
- **Save preview:** save `output/preview.png`.
- **Fit route:** zoom around waypoints; the plot toolbar also supports pan and zoom.

Apply stages and validates the new combination before replacing focus. A failed
swap rolls back. A successful Apply deletes the old combination; there is no
focus history. Library files remain available. Avoid editing focus during Apply.

## Command line

After applying a combination to focus:

```bash
/usr/bin/python3 -E -B visualize.py --check
/usr/bin/python3 -E -B visualize.py --static
/usr/bin/python3 -E -B visualize.py --no-show
```

The last command writes `output/overlay.png` without opening a window.
You can also use explicit inputs without first creating focus:

```bash
/usr/bin/python3 -E -B visualize.py --map /path/to/map.yaml --waypoints /path/to/route.csv --check
/usr/bin/python3 -E -B visualize.py --map /path/to/map.yaml --waypoints /path/to/route.csv --no-show
```

Checks validate file structure and report map bounds and endpoint-gap warnings.
Inspect alignment yourself: validation does not prove coordinate-frame agreement
or collision clearance. Changes affect this local tool only; no robot deployment
or controller configuration is performed.

## Closed-path smoothing

```bash
/usr/bin/python3 -E -B smooth_waypoints.py --map /path/to/map.yaml --source /path/to/route.csv --output /tmp/route_smooth.csv --max-deviation 0.45
```

The smoother uses a periodic cubic spline, approximately 0.1 m arc-length
resampling, continuous heading, and the input speed profile. It reports path
deviation, steering demand, closure, and distance to occupied or unknown cells.
These checks do not model the full vehicle footprint or localization error.
Use a new output filename to preserve the original route.

## Tests

The tests generate synthetic data in temporary directories and need no real maps:

```bash
/usr/bin/python3 -E -B -m unittest discover -s tests -v
```
