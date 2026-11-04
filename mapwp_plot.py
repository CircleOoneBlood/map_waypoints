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


def draw_speed_3d(ax, data, points=None, label=None, fit_route=True):
    """Map at z=0 and route at z=speed (m/s); returns a colorbar mappable."""
    from matplotlib import colormaps
    from matplotlib.colors import Normalize
    from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection
    from mapwp_data import InputError

    points=np.asarray(data.points if points is None else points)
    if points.ndim!=2 or points.shape[1] not in (3,4):
        raise InputError('3D speed requires x,y,v or x,y,yaw,v columns.')
    speed=points[:,-1]
    if len(points)<2 or not np.isfinite(points).all() or np.any(speed<0):
        raise InputError('3D speed requires finite coordinates and nonnegative speeds.')
    ax.clear()
    # Downsample by block minimum so thin dark map walls remain visible.
    h,w=data.image.shape
    stride=max(1,int(np.ceil(max(h,w)/120)))
    rows=np.arange(0,h,stride);cols=np.arange(0,w,stride)
    gray=np.minimum.reduceat(np.minimum.reduceat(np.flipud(data.image),rows,axis=0),cols,axis=1)/255.
    x,y=np.meshgrid(np.r_[cols,w]*data.resolution,np.r_[rows,h]*data.resolution)
    ox,oy,angle=data.origin;c,s=np.cos(angle),np.sin(angle)
    xx=ox+c*x-s*y;yy=oy+s*x+c*y
    colors=colormaps['gray'](.75+.25*gray)
    ax.plot_surface(xx,yy,np.zeros_like(xx),facecolors=colors,rstride=1,cstride=1,
                    shade=False,linewidth=0,antialiased=False,alpha=.2)
    xyz=np.column_stack((points[:,:2],speed))
    if np.linalg.norm(xyz[-1,:2]-xyz[0,:2])<=.5:
        xyz=np.vstack((xyz,xyz[:1]))
    segments=np.stack((xyz[:-1],xyz[1:]),axis=1)
    norm=Normalize(vmin=0.,vmax=max(float(speed.max()),.1))
    lower=xyz.copy();lower[:,2]=0.
    panels=np.stack((lower[:-1],lower[1:],xyz[1:],xyz[:-1]),axis=1)
    wall=Poly3DCollection(panels,facecolors=colormaps['turbo'](norm((xyz[:-1,2]+xyz[1:,2])/2)),
                          edgecolors='none',alpha=.28)
    wall.set_gid('speed_wall')
    ax.add_collection3d(wall)
    line=Line3DCollection(segments,cmap='turbo',norm=norm,linewidths=1.4,alpha=.85)
    line.set_array((xyz[:-1,2]+xyz[1:,2])/2)
    ax.add_collection3d(line)
    ax.plot(xyz[:,0],xyz[:,1],np.zeros(len(xyz)),color='#12344a',lw=3.,alpha=1.,label='Ground route',zorder=10)
    ax.scatter(points[:,0],points[:,1],np.zeros(len(points)),color='#12344a',s=8,depthshade=False,zorder=11)
    ax.scatter(*points[0,:2],speed[0],marker='*',s=100,color='lime',edgecolor='black',label='First waypoint')
    if fit_route:
        low=points[:,:2].min(axis=0);high=points[:,:2].max(axis=0)
        margin=max(.75,float(np.max(high-low))*.08)
        low-=margin;high+=margin
    else:
        low=np.array([xx.min(),yy.min()]);high=np.array([xx.max(),yy.max()])
    ax.set_xlim(low[0],high[0]);ax.set_ylim(low[1],high[1]);ax.set_zlim(0,max(.5,float(speed.max())*1.1))
    span=np.maximum(high-low,.1)
    ax.set_box_aspect((span[0],span[1],max(span)*.5))
    ax.set(xlabel='x [m]',ylabel='y [m]',zlabel='Speed [m/s]',
           title=f'{data.map_path.stem}: {label or data.waypoint_path.name}\nWall height and color = speed; bold line = ground route')
    ax.legend(loc='upper left')
    return line


def nearest_speed_point(ax, points, pixel_x, pixel_y, radius=12):
    """Find a displayed point at the ground or wall top in current camera view."""
    from mpl_toolkits.mplot3d import proj3d
    points=np.asarray(points)
    best=(float('inf'),None)
    for z in (np.zeros(len(points)),points[:,-1]):
        x,y,_=proj3d.proj_transform(points[:,0],points[:,1],z,ax.get_proj())
        screen=ax.transData.transform(np.column_stack((x,y)))
        distance=np.linalg.norm(screen-[pixel_x,pixel_y],axis=1)
        i=int(np.argmin(distance))
        if distance[i]<best[0]:best=(float(distance[i]),i)
    return best[1] if best[0]<=radius else None
