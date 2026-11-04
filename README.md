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
the waypoint editor, smoothing utility, and their tests.

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

## 3D speed view

Click **3D speed** to open a rotatable view: X/Y are map coordinates and Z is
speed in m/s. A translucent colored wall rises from the bold ground route to
its speed profile. The map is faint so the route stays prominent.
Drag to rotate and use the navigation toolbar to adjust the view.

Click the ground route or the wall's upper edge to inspect the nearest point.
The readout gives its **1-based CSV data-row number (header excluded)**, x/y and
speed. Enter a number in **Point #** and press **Go** or Enter to locate it
precisely. **Show point IDs** adds sparse labels to avoid crowding; every point
is still selectable. A drag rotates the view without selecting a point.
For example, “my_route.csv points 40–65” identifies a section unambiguously.
Unsaved previews are labeled **Draft point**; their numbers may change when
control points or smoothing settings change.

The view uses the selected CSV, or the unsaved smooth draft when editing with
a valid preview. Click **Refresh from main view** after changing the selection
or generating a new preview. If control points have changed, click **Smooth
preview** first. Point picking and dragging stay in the main 2D window.
Opening or refreshing the 3D view does not change route data or focus.
Supported CSV formats are `x,y,v` and `x,y,yaw,v`.

## Draw and edit waypoints

Restart MapWP after updating the code. Select the map, then enable
**Edit / pick points**. The existing route stays faintly visible as a reference.

1. Left-click points in driving order. Use fewer points on straight sections;
   add a few around corners. The route closes automatically: do not repeat the first point.
2. Drag a control point to move it. **Shift-click** deletes a point;
   **Ctrl-click** inserts a point into the nearest segment. **Undo** or right-click
   undoes the last edit. **Clear** starts over; **Reverse** changes driving direction.
3. **Use current route** loads saved editor controls, or samples the selected CSV
   roughly every metre if it was not created in the editor.
4. Set **Smoothing (m)** and **Max speed (m/s)**, then click **Smooth preview**.
   Larger smoothing permits more deviation from the clicked points. Use evenly
   spaced controls and avoid clicking every small hand-drawn fluctuation.
5. Enter a name without `.csv` and click **Save CSV**. The CSV and its control-point
   report are saved under `buffer/waypoints/`. Replacing an existing name requires
   confirmation. Saving selects the new route but does not change focus or Jetson.

Turn off toolbar pan/zoom before clicking or dragging points. Navigation still
works normally outside editing operations. Apply to focus is disabled while
editing; save the route first, then explicitly apply it if desired.

The preview is a periodic cubic spline, sampled about every 0.1 m, with columns
`x,y,yaw,v`. The maximum-speed setting is a ceiling; speed can be lower in bends.
The profile uses a 4.5 m/s² lateral-acceleration target, 1.5 m/s² acceleration,
and 2 m/s² braking. These are design assumptions, not measured vehicle grip.
Obstacle proximity (including center clearance below 0.30 m) and footprint
overlap with occupied/unknown space are warnings only: they do not block saving
or require an extra confirmation. Warnings are retained in the saved JSON report.
Self-intersections and steering above 0.40 rad at a 0.33 m wheelbase are also
warnings only. Geometry warnings never block saving; malformed or degenerate
input that cannot produce a finite curve is still rejected. The footprint check uses the current MPC dimensions plus 3 cm margin. Static checks
do not account for tracking/localization errors or replace low-speed testing.

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

The tests generate synthetic data in temporary directories and need no real maps.
The GUI test requires a display and is skipped if Tk cannot open one:

```bash
/usr/bin/python3 -E -B -m unittest discover -s tests -v
```
