"""Draw a validated map and waypoint combination."""
import numpy as np


def draw_combination(ax, data, fit_route=False):
    """Draw into an existing axes for both the desktop composer and CLI."""
    from matplotlib.transforms import Affine2D

    ax.clear()
    height, width = data.image.shape
    width_m, height_m = width * data.resolution, height * data.resolution
    x0, y0, yaw = data.origin
    world = Affine2D().rotate(yaw).translate(x0, y0)
    ax.imshow(data.image, cmap='gray', vmin=0, vmax=255, origin='upper',
              extent=[0, width_m, 0, height_m], transform=world + ax.transData)
    ax.plot(data.points[:, 0], data.points[:, 1], color='red', linewidth=1,
            marker='.', markersize=3, label=f'Waypoints ({len(data.points)})')
    ax.scatter(data.points[0, 0], data.points[0, 1], s=120, marker='*', color='lime',
               edgecolor='black', label='First waypoint', zorder=5)
    corners = world.transform([[0, 0], [width_m, 0],
                               [0, height_m], [width_m, height_m]])
    ax.dataLim.set_points(np.array([[np.inf, np.inf], [-np.inf, -np.inf]]))
    ax.update_datalim(np.vstack((corners, data.points[:, :2])))
    ax.autoscale(enable=True)
    ax.set(xlabel='x [m]', ylabel='y [m]', title=f'{data.map_path.stem}: map and waypoints')
    ax.set_aspect('equal')
    ax.legend()
    if fit_route:
        low = data.points[:, :2].min(axis=0)
        high = data.points[:, :2].max(axis=0)
        margin = max(1.0, float(np.max(high - low)) * 0.08)
        ax.set_xlim(low[0] - margin, high[0] + margin)
        ax.set_ylim(low[1] - margin, high[1] + margin)


def plot_combination(data, save_path, show=True):
    import matplotlib
    if not show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 10))
    draw_combination(ax, data)
    fig.tight_layout()
    save_path = save_path.expanduser().resolve()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=200)
    print(f'Saved: {save_path}')
    if show:
        plt.show()
    plt.close(fig)
