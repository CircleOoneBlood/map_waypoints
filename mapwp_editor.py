"""Closed waypoint editing and static geometry checks; no ROS dependencies."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

import numpy as np
from scipy.interpolate import splprep, splev
from scipy.ndimage import distance_transform_edt, map_coordinates
import yaml

from mapwp_data import InputError


@dataclass
class Draft:
    points: np.ndarray
    stats: dict
    errors: list
    warnings: list = field(default_factory=list)


def seed_controls(points, spacing=1.0):
    xy=np.asarray(points)[:,:2]
    if np.linalg.norm(xy[-1]-xy[0])<1e-6: xy=xy[:-1]
    closed=np.vstack((xy,xy[:1]))
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(closed,axis=0),axis=1))]
    target=np.linspace(0,arc[-1],max(6,int(np.ceil(arc[-1]/spacing))),endpoint=False)
    return np.column_stack([np.interp(target,arc,closed[:,i]) for i in (0,1)])


def intersects(xy):
    end=np.roll(xy,-1,axis=0)
    def cross(a,b): return a[...,0]*b[...,1]-a[...,1]*b[...,0]
    for i,(a,b) in enumerate(zip(xy,end)):
        ids=np.arange(i+2,len(xy))
        if i==0: ids=ids[ids!=len(xy)-1]
        c,d=xy[ids],end[ids]
        box=np.all(np.maximum(np.minimum(a,b),np.minimum(c,d))<=np.minimum(np.maximum(a,b),np.maximum(c,d))+1e-10,axis=1)
        hit=(cross(b-a,c-a)*cross(b-a,d-a)<=1e-12)&(cross(d-c,a-c)*cross(d-c,b-c)<=1e-12)
        if np.any(box&hit):return True
    return False


def make_draft(controls,data,smoothing=.12,max_speed=5.):
    xy=np.asarray(controls,dtype=float)
    if xy.ndim!=2 or xy.shape[1]!=2 or len(xy)<4 or not np.isfinite(xy).all():
        raise InputError('Place at least four distinct control points in driving order.')
    if not np.isfinite([smoothing,max_speed]).all() or not 0<=smoothing<=1 or not 0<max_speed<=10:
        raise InputError('Smoothing must be 0–1 m; maximum speed must be in (0, 10] m/s.')
    if len(xy)>500:raise InputError('Use at most 500 control points.')
    if np.linalg.norm(xy[-1]-xy[0])<1e-6:xy=xy[:-1]
    closed=np.vstack((xy,xy[:1]))
    steps=np.linalg.norm(np.diff(closed,axis=0),axis=1)
    if len(xy)<4 or np.any(steps<.02):raise InputError('Keep adjacent control points at least 2 cm apart. Do not repeat the first point.')
    arc=np.r_[0.,np.cumsum(steps)]
    spline,_=splprep(closed.T,u=arc/arc[-1],s=len(closed)*smoothing**2,per=True,k=3)
    u=np.linspace(0,1,min(100000,max(5001,int(arc[-1]/.005))))
    dense=np.asarray(splev(u,spline)).T
    d1=np.asarray(splev(u,spline,der=1)).T
    d2=np.asarray(splev(u,spline,der=2)).T
    norm=np.linalg.norm(d1,axis=1)
    if norm.min()<1e-7:raise InputError('The curve folds back on itself. Move or remove nearby control points.')
    curvature=(d1[:,0]*d2[:,1]-d1[:,1]*d2[:,0])/norm**3
    length=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(dense,axis=0),axis=1))]
    count=max(8,int(np.ceil(length[-1]/.1)))
    if count>20000:raise InputError('Route is too long for the editor.')
    out_u=np.interp(np.linspace(0,length[-1],count,endpoint=False),length,u)
    output_xy=np.asarray(splev(out_u,spline)).T
    tangent=np.asarray(splev(out_u,spline,der=1)).T
    yaw=np.arctan2(tangent[:,1],tangent[:,0])
    speed=np.minimum(max_speed,np.sqrt(4.5/np.maximum(np.abs(np.interp(out_u,u,curvature)),1e-6)))
    ds=np.linalg.norm(np.roll(output_xy,-1,axis=0)-output_xy,axis=1)
    for _ in range(4):
        for i in range(count):
            j=(i+1)%count;speed[j]=min(speed[j],np.sqrt(speed[i]**2+3*ds[i]))
        for i in range(count-1,-1,-1):
            j=(i+1)%count;speed[i]=min(speed[i],np.sqrt(speed[j]**2+4*ds[i]))
    cfg=yaml.safe_load(data.map_path.read_text())
    probability=data.image/255. if cfg.get('negate',0) else 1-data.image/255.
    free=probability<float(cfg.get('free_thresh',.196))
    distances=distance_transform_edt(np.pad(free,1))[1:-1,1:-1]*data.resolution-data.resolution/np.sqrt(2)
    x0,y0,angle=data.origin;c,s=np.cos(angle),np.sin(angle)
    def clearance(p):
        local=(p-np.array([x0,y0]))@np.array([[c,-s],[s,c]])
        cells=local/data.resolution
        return map_coordinates(distances,[data.image.shape[0]-.5-cells[:,1],cells[:,0]-.5],order=1,mode='constant',cval=-1.)
    center=float(clearance(dense).min())
    # Current MPC footprint plus 3 cm margin; evaluate on the dense curve.
    xx=np.linspace(-.14855,.49145,28);yy=np.linspace(-.185,.185,18)
    edge=np.vstack([np.column_stack((xx,np.full_like(xx,y))) for y in (-.185,.185)]+
                   [np.column_stack((np.full_like(yy,x),yy)) for x in (-.14855,.49145)])
    heading=d1/norm[:,None]
    min_foot=float('inf')
    for start in range(0,len(dense),500):
        h=heading[start:start+500];q=dense[start:start+500]
        footprint=q[:,None,:]+np.stack((h[:,None,0]*edge[:,0]-h[:,None,1]*edge[:,1],
                                       h[:,None,1]*edge[:,0]+h[:,None,0]*edge[:,1]),axis=-1)
        min_foot=min(min_foot,float(clearance(footprint.reshape(-1,2)).min()))
    steering=float(np.arctan(.33*np.abs(curvature)).max())
    errors=[]
    warnings=[]
    if center<.3:warnings.append('Curve is too close to occupied/unknown space (minimum center clearance: 0.30 m).')
    if min_foot<0:warnings.append('The vehicle footprint overlaps occupied/unknown space.')
    if steering>.40:warnings.append('Estimated steering exceeds 0.40 rad at a bend.')
    if intersects(output_xy):warnings.append('The closed route crosses itself.')
    stats=dict(length_m=float(length[-1]),points=count,min_clearance_m=center,
               min_footprint_clearance_m=min_foot,max_steering_rad=steering,
               min_speed_mps=float(speed.min()),max_speed_mps=float(speed.max()),
               lateral_acceleration_target_mps2=4.5,acceleration_limit_mps2=1.5,braking_limit_mps2=2.,
               assumptions='Static map; wheelbase .33 m, front .46145, rear .11855, half-width .155, margin .03 m. Physical tracking is not validated.')
    return Draft(np.column_stack((output_xy,yaw,speed)),stats,errors,warnings)


def save_draft(folder,name,draft,controls,options,overwrite=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',name):
        raise InputError('Name must contain only letters, digits, underscores or hyphens (without .csv).')
    if draft.errors:raise InputError('Fix the preview errors before saving.')
    path=Path(folder)/(name+'.csv');report=path.with_suffix('.json')
    if not overwrite and (path.exists() or report.exists()):raise FileExistsError(name)
    if path.is_symlink() or report.is_symlink():raise InputError('Cannot overwrite a symbolic link.')
    payload=dict(editor_version=1,control_points=np.asarray(controls).tolist(),options=options,warnings=draft.warnings,**draft.stats)
    # Each file is staged and replaced; keep CSV last so it selects a complete draft.
    import tempfile,os
    stages=[]
    try:
        for target,content in [(report,json.dumps(payload,indent=2)+'\n'),(path,None)]:
            fd,temp=tempfile.mkstemp(dir=folder,prefix='.editor-')
            stages.append((Path(temp),target))
            with os.fdopen(fd,'w') as stream:
                if content is None:np.savetxt(stream,draft.points,delimiter=',',header='x,y,yaw,v',comments='',fmt='%.8f')
                else:stream.write(content)
        for temp,target in stages:os.replace(temp,target)
    finally:
        for temp,_ in stages:temp.unlink(missing_ok=True)
    return path
