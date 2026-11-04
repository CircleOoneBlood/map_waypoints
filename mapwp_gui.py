"""Small native map/waypoint composer. All UI messages are in English."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import json
import numpy as np

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from mapwp_data import InputError, load_combination
from mapwp_library import Library, digest, map_signature
from mapwp_plot import draw_combination, draw_speed_3d, nearest_speed_point
from mapwp_editor import make_draft, seed_controls, save_draft


class Composer:
    def __init__(self, window, root):
        self.window = window
        self.library = Library(root)
        self.data = None
        self.map_paths = []
        self.wp_paths = []
        self.control_points=[]
        self.edit_history=[]
        self.draft=None
        self.speed_window=None
        self.drag_index=None
        self.edit_mode=tk.BooleanVar(value=False)
        self.smoothing=tk.StringVar(value='0.12')
        self.editor_speed=tk.StringVar(value='5.0')
        self.editor_name=tk.StringVar(value='my_route')
        self.window.title('MapWP — Map and Waypoint Composer')
        self.window.geometry('1250x900')
        self.window.minsize(900, 650)
        controls = ttk.Frame(window, padding=10)
        controls.pack(fill='x')
        ttk.Label(controls, text='Map').grid(row=0, column=0, sticky='w')
        self.map_choice = ttk.Combobox(controls, state='readonly', width=40)
        self.map_choice.grid(row=0, column=1, padx=(8, 20), sticky='ew')
        ttk.Label(controls, text='Waypoints').grid(row=0, column=2, sticky='w')
        self.wp_choice = ttk.Combobox(controls, state='readonly', width=45)
        self.wp_choice.grid(row=0, column=3, padx=(8, 0), sticky='ew')
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)
        self.map_choice.bind('<<ComboboxSelected>>', self.preview)
        self.wp_choice.bind('<<ComboboxSelected>>', self.preview)

        buttons = ttk.Frame(window, padding=(10, 0, 10, 5))
        buttons.pack(fill='x')
        for label, action in [('Preview', self.preview), ('Apply to focus', self.apply),
                              ('Load focus', self.load_focus),
                              ('Refresh', self.refresh), ('Save preview', self.save),
                              ('3D speed', self.open_speed_view)]:
            button = ttk.Button(buttons, text=label, command=action)
            button.pack(side='left', padx=(0, 8))
            if label == 'Apply to focus':
                self.apply_button = button
        self.fit_route = tk.BooleanVar(value=True)
        ttk.Checkbutton(buttons, text='Fit route', variable=self.fit_route,
                        command=self.redraw).pack(side='right')

        editor=ttk.LabelFrame(window,text='Waypoint editor',padding=(8,4))
        editor.pack(fill='x',padx=10,pady=4)
        row=ttk.Frame(editor);row.pack(fill='x')
        ttk.Checkbutton(row,text='Edit / pick points',variable=self.edit_mode,command=self.toggle_editor).pack(side='left',padx=(0,8))
        for label,action in [('Use current route',self.editor_seed),('Undo',self.editor_undo),
                             ('Clear',self.editor_clear),('Reverse',self.editor_reverse),
                             ('Smooth preview',self.editor_preview)]:
            ttk.Button(row,text=label,command=action).pack(side='left',padx=3)
        row=ttk.Frame(editor);row.pack(fill='x',pady=4)
        for label,var,width in [('Smoothing (m)',self.smoothing,6),('Max speed (m/s)',self.editor_speed,6),('Name',self.editor_name,24)]:
            ttk.Label(row,text=label).pack(side='left',padx=(6,4))
            ttk.Entry(row,textvariable=var,width=width).pack(side='left')
        ttk.Button(row,text='Save CSV',command=self.editor_save).pack(side='left',padx=8)
        ttk.Label(editor,text='Left-click: add | Drag: move | Right-click: undo | Shift-click: delete | Ctrl-click: insert | Closed loop.').pack(anchor='w')
        self.smoothing.trace_add('write',self.editor_changed)
        self.editor_speed.trace_add('write',self.editor_changed)

        self.status = tk.StringVar()
        self.status_label = ttk.Label(window, textvariable=self.status, padding=(10, 5),
                                      wraplength=1180, justify='left')
        self.status_label.pack(fill='x')
        self.active = tk.StringVar()
        ttk.Label(window, textvariable=self.active, padding=(10, 0, 10, 5)).pack(fill='x')
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=window)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.toolbar = NavigationToolbar2Tk(self.canvas, window, pack_toolbar=False)
        self.toolbar.pack(fill='x')
        ttk.Label(window, text='Selections are previews until applied. Changes affect local focus only; Jetson is not modified.',
                  padding=6).pack(fill='x')
        self.canvas.mpl_connect('button_press_event',self.editor_press)
        self.canvas.mpl_connect('motion_notify_event',self.editor_motion)
        self.canvas.mpl_connect('button_release_event',self.editor_release)
        self.refresh(load_focus=True)

    def message(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(foreground='#ad2323' if error else '#164d2b')

    def update_active(self):
        try:
            focus = load_combination(self.library.focus)
            self.active.set(f'Active focus: {focus.map_path.stem} + {focus.waypoint_path.name}')
        except (OSError, ValueError) as exc:
            self.active.set(f'Active focus error: {exc}')

    def refresh(self, load_focus=False):
        current_map = self.map_paths[self.map_choice.current()] if self.map_paths and self.map_choice.current() >= 0 else None
        current_wp = self.wp_paths[self.wp_choice.current()] if self.wp_paths and self.wp_choice.current() >= 0 else None
        self.map_paths = self.library.maps()
        self.wp_paths = self.library.waypoints()
        self.map_choice['values'] = [str(p.relative_to(self.library.maps_dir).with_suffix('')) for p in self.map_paths]
        self.wp_choice['values'] = [str(p.relative_to(self.library.waypoints_dir)) for p in self.wp_paths]
        if not self.map_paths or not self.wp_paths:
            self.data = None
            self.apply_button.configure(state='disabled')
            self.message('Library is empty. Add map YAML/image bundles under buffer/maps/ and CSVs under buffer/waypoints/, then click Refresh.', True)
            self.update_active()
            return
        self.map_choice.current(self.map_paths.index(current_map) if current_map in self.map_paths else 0)
        self.wp_choice.current(self.wp_paths.index(current_wp) if current_wp in self.wp_paths else 0)
        if load_focus:
            self.load_focus()
        else:
            self.preview()
            self.update_active()

    def selected(self):
        mi, wi = self.map_choice.current(), self.wp_choice.current()
        if mi < 0 or wi < 0:
            raise InputError('Select both a map and a waypoint file.')
        return self.map_paths[mi], self.wp_paths[wi]

    def show_data(self, data, prefix):
        if not self.accept_editor_map(data): return
        self.data = data
        self.apply_button.configure(state='disabled' if self.edit_mode.get() else 'normal')
        self.redraw()
        details = f'{prefix}\n{data.map_path.stem} + {data.waypoint_path.name} | {len(data.points)} points | {data.points.shape[1]} columns'
        if data.warnings:
            details += '\nWarning: ' + ' '.join(data.warnings)
        self.message(details, bool(data.warnings))

    def preview(self, event=None):
        try:
            map_path, wp_path = self.selected()
            data = load_combination(self.library.focus, map_path, wp_path)
            self.show_data(data, 'Preview only. Focus has not changed.')
        except (OSError, ValueError) as exc:
            self.data = None
            self.apply_button.configure(state='disabled')
            self.ax.clear()
            self.ax.text(0.5, 0.5, 'Preview unavailable', ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw_idle()
            self.message(f'Error: {exc}', True)

    def redraw(self,keep_view=False):
        if self.data is not None:
            limits=(self.ax.get_xlim(),self.ax.get_ylim())
            draw_combination(self.ax,self.data,fit_route=self.fit_route.get())
            if self.edit_mode.get():
                if self.ax.lines:self.ax.lines[0].set_alpha(.3)
                if self.control_points:
                    p=np.asarray(self.control_points)
                    self.ax.plot(p[:,0],p[:,1],'o--',color='#168dcc',ms=6,lw=.8,label='Control points')
                    if len(p)<80:
                        for i,(x,y) in enumerate(p):self.ax.annotate(str(i+1),(x,y),xytext=(5,5),textcoords='offset points',fontsize=8)
                if self.draft is not None:
                    p=self.draft.points;closed=np.vstack((p,p[:1]))
                    self.ax.plot(closed[:,0],closed[:,1],color='#d88300' if self.draft.errors or self.draft.warnings else '#009b70',lw=2,label='Smooth draft')
                self.ax.legend()
            if keep_view:
                self.ax.set_xlim(limits[0]);self.ax.set_ylim(limits[1])
            self.figure.tight_layout()
            self.canvas.draw_idle()

    def load_focus(self):
        try:
            data = load_combination(self.library.focus)
            signature = map_signature(data.map_path)
            map_match = next((p for p in self.map_paths if map_signature(p) == signature), None)
            wp_match = next((p for p in self.wp_paths if digest(p) == digest(data.waypoint_path)), None)
            if map_match is not None:
                self.map_choice.current(self.map_paths.index(map_match))
            else:
                self.map_choice.set('Focus map is not in the library')
            if wp_match is not None:
                self.wp_choice.current(self.wp_paths.index(wp_match))
            else:
                self.wp_choice.set('Focus waypoints are not in the library')
            self.show_data(data, 'Showing the active focus combination.')
            if map_match is None or wp_match is None:
                self.apply_button.configure(state='disabled')
            self.update_active()
        except (OSError, ValueError) as exc:
            self.message(f'Error: {exc}', True)

    def apply(self):
        if self.edit_mode.get():
            self.message('Save the draft and leave edit mode before applying a route.',True);return
        try:
            map_path, wp_path = self.selected()
            data = self.library.apply(map_path, wp_path)
            self.load_focus()
            text = 'Applied to focus. The old focus combination has been replaced.'
            if data.warnings:
                text += '\nWarning: ' + ' '.join(data.warnings)
            self.message(text, bool(data.warnings))
        except (OSError, ValueError) as exc:
            self.message(f'Error: {exc}', True)

    def editor_options(self):
        try:
            return dict(smoothing=float(self.smoothing.get()),max_speed=float(self.editor_speed.get()))
        except ValueError:
            raise InputError('Enter numeric smoothing and maximum speed values.') from None

    def toggle_editor(self):
        self.apply_button.configure(state='disabled' if self.edit_mode.get() or self.data is None else 'normal')
        self.redraw(keep_view=True)
        if self.edit_mode.get():
            self.message('Click points in driving order; drag a point to move it. Right-click or Undo to undo. The route closes automatically. Turn off toolbar pan/zoom to place points.')

    def remember_edit(self):
        self.edit_history.append(list(self.control_points))
        self.edit_history=self.edit_history[-100:]
        self.draft=None

    def editor_changed(self, *args):
        self.draft=None
        if hasattr(self,'canvas'): self.redraw(keep_view=True)

    def editor_undo(self):
        if self.edit_history:
            self.control_points=self.edit_history.pop()
            self.draft=None
            self.redraw(keep_view=True)

    def editor_clear(self):
        if self.control_points:
            self.remember_edit();self.control_points=[]
            self.redraw(keep_view=True)

    def editor_reverse(self):
        if self.control_points:
            self.remember_edit()
            self.control_points=[self.control_points[0]]+self.control_points[:0:-1]
            self.redraw(keep_view=True)

    def editor_seed(self):
        if self.data is None:return
        try:
            controls=seed_controls(self.data.points)
            report=self.data.waypoint_path.with_suffix('.json')
            if report.is_file():
                saved=json.loads(report.read_text())
                if saved.get('editor_version')==1:
                    controls=np.asarray(saved['control_points'],dtype=float)
                    if controls.ndim!=2 or controls.shape[1]!=2 or not np.isfinite(controls).all():
                        raise InputError('Invalid saved control points.')
                    for key,var in [('smoothing',self.smoothing),('max_speed',self.editor_speed)]:
                        if key in saved.get('options',{}):var.set(str(saved['options'][key]))
            self.remember_edit();self.control_points=[tuple(p) for p in controls]
            self.edit_mode.set(True);self.toggle_editor()
        except (OSError,ValueError,KeyError) as exc:self.message(f'Error: {exc}',True)

    def editor_press(self,event):
        if not self.edit_mode.get() or self.data is None or event.inaxes is not self.ax or self.toolbar.mode:return
        if event.button==3:
            self.editor_undo();return
        if event.button!=1 or event.xdata is None or event.ydata is None:return
        if self.control_points:
            pixels=self.ax.transData.transform(np.asarray(self.control_points))
            distances=np.linalg.norm(pixels-np.array([event.x,event.y]),axis=1)
            if distances.min()<12:
                self.remember_edit()
                index=int(distances.argmin())
                if getattr(event,'key',None)=='shift':
                    self.control_points.pop(index);self.redraw(keep_view=True)
                else:self.drag_index=index
                return
        if getattr(event,'key',None)=='shift':return
        point=(float(event.xdata),float(event.ydata))
        self.remember_edit()
        if getattr(event,'key',None) in ('control','ctrl') and len(self.control_points)>1:
            p=np.asarray(self.control_points);v=np.roll(p,-1,axis=0)-p
            t=np.clip(np.sum((np.array(point)-p)*v,axis=1)/np.maximum(np.sum(v*v,axis=1),1e-12),0,1)
            index=int(np.argmin(np.linalg.norm(p+t[:,None]*v-point,axis=1)))
            self.control_points.insert(index+1,point)
        else:self.control_points.append(point)
        self.redraw(keep_view=True)

    def editor_motion(self,event):
        if self.drag_index is None or event.inaxes is not self.ax or self.toolbar.mode:return
        if event.xdata is None or event.ydata is None:return
        self.control_points[self.drag_index]=(float(event.xdata),float(event.ydata))
        self.draft=None;self.redraw(keep_view=True)

    def editor_release(self,event):
        self.drag_index=None

    def editor_preview(self):
        if self.data is None:
            self.message('Select a map first.',True);return
        try:
            self.draft=make_draft(self.control_points,self.data,**self.editor_options())
            self.edit_mode.set(True);self.apply_button.configure(state='disabled')
            self.redraw(keep_view=True)
            s=self.draft.stats
            text=f"Draft: {s['points']} points | {s['length_m']:.2f} m | speed {s['min_speed_mps']:.2f}–{s['max_speed_mps']:.2f} m/s | clearance {s['min_clearance_m']:.2f} m"
            if self.draft.errors:text+='\n'+' '.join(self.draft.errors)
            if self.draft.warnings:text+='\nWarning: '+' '.join(self.draft.warnings)
            if not self.draft.errors:
                text+='\nSave CSV is available; geometry warnings do not block saving.' if self.draft.warnings else '\nStatic geometry checks passed. Save CSV to add this route to the library.'
            self.message(text,bool(self.draft.errors or self.draft.warnings))
        except (OSError,ValueError,TypeError) as exc:
            self.draft=None;self.redraw(keep_view=True);self.message(f'Error: {exc}',True)

    def editor_save(self):
        self.editor_preview()
        if self.draft is None or self.draft.errors:return
        name=self.editor_name.get().strip()
        try:
            options=self.editor_options()
            saved_warnings=list(self.draft.warnings)
            try:
                path=save_draft(self.library.waypoints_dir,name,self.draft,self.control_points,options)
            except FileExistsError:
                if not messagebox.askyesno('Replace route',f'Replace {name}.csv and its editing report?',parent=self.window):return
                path=save_draft(self.library.waypoints_dir,name,self.draft,self.control_points,options,overwrite=True)
            self.control_points=[];self.edit_history=[];self.draft=None
            self.edit_mode.set(False)
            self.refresh()
            self.wp_choice.current(self.wp_paths.index(path))
            self.preview()
            text=f'Saved {path.name} to buffer/waypoints. Focus has not changed. Use current route to edit it again.'
            if saved_warnings:text+='\nWarning: '+' '.join(saved_warnings)
            self.message(text,bool(saved_warnings))
        except (OSError,ValueError) as exc:self.message(f'Error: {exc}',True)

    def accept_editor_map(self,data):
        if self.control_points and self.data is not None and map_signature(data.map_path)!=map_signature(self.data.map_path):
            if not messagebox.askyesno('Change map','Discard the unsaved control points and change maps?',parent=self.window):
                old_signature=map_signature(self.data.map_path)
                for i,path in enumerate(self.map_paths):
                    if map_signature(path)==old_signature:self.map_choice.current(i);break
                return False
            self.control_points=[];self.edit_history=[];self.draft=None
        return True

    def open_speed_view(self):
        if self.data is None:
            self.message('Select a valid map and waypoint combination first.',True);return
        if self.speed_window is not None and self.speed_window.winfo_exists():
            self.refresh_speed_view();self.speed_window.lift();return
        self.speed_window=tk.Toplevel(self.window)
        self.speed_window.title('MapWP — 3D speed')
        self.speed_window.geometry('1050x800')
        row=ttk.Frame(self.speed_window,padding=8);row.pack(fill='x')
        ttk.Button(row,text='Refresh from main view',command=self.refresh_speed_view).pack(side='left')
        ttk.Label(row,text='Drag to rotate; click the ground route or wall top to inspect a point.').pack(side='left',padx=12)
        row=ttk.Frame(self.speed_window,padding=(8,0));row.pack(fill='x')
        self.speed_ids=tk.BooleanVar(value=True)
        ttk.Checkbutton(row,text='Show point IDs',variable=self.speed_ids,command=self.refresh_speed_view).pack(side='left')
        ttk.Label(row,text='Point #').pack(side='left',padx=(12,4))
        self.speed_index=tk.StringVar(value='1')
        self.speed_spin=ttk.Spinbox(row,from_=1,to=1,width=7,textvariable=self.speed_index,command=self.select_speed_point)
        self.speed_spin.pack(side='left')
        self.speed_spin.bind('<Return>',lambda event:self.select_speed_point())
        ttk.Button(row,text='Go',command=self.select_speed_point).pack(side='left',padx=4)
        ttk.Label(row,text='1-based CSV data row; header excluded.').pack(side='left',padx=8)
        self.speed_point_info=tk.StringVar(value='Click a point to inspect its row number, coordinates and speed.')
        ttk.Label(self.speed_window,textvariable=self.speed_point_info,padding=6).pack(fill='x')
        self.speed_status=tk.StringVar()
        ttk.Label(self.speed_window,textvariable=self.speed_status,padding=6).pack(fill='x')
        self.speed_figure=Figure(figsize=(10,7),dpi=100)
        self.speed_canvas=FigureCanvasTkAgg(self.speed_figure,master=self.speed_window)
        self.speed_canvas.get_tk_widget().pack(fill='both',expand=True)
        self.speed_toolbar=NavigationToolbar2Tk(self.speed_canvas,self.speed_window)
        self.speed_press_position=None
        self.speed_highlights=[]
        self.speed_points=None
        self.speed_canvas.mpl_connect('button_press_event',self.speed_point_press)
        self.speed_canvas.mpl_connect('button_release_event',self.speed_point_release)
        self.speed_ax=None
        self.refresh_speed_view()

    def refresh_speed_view(self):
        if self.data is None:
            self.speed_status.set('Select a valid combination in the main window, then refresh.');return
        angles=(self.speed_ax.elev,self.speed_ax.azim) if self.speed_ax is not None else (35,-65)
        self.speed_figure.clear()
        self.speed_ax=self.speed_figure.add_subplot(111,projection='3d')
        use_draft=self.edit_mode.get() and self.draft is not None
        points=self.draft.points if use_draft else self.data.points
        label='Unsaved smooth draft' if use_draft else self.data.waypoint_path.name
        self.speed_points=None
        self.speed_highlights=[]
        self.speed_point_info.set('Click a point to inspect its row number, coordinates and speed.')
        try:
            line=draw_speed_3d(self.speed_ax,self.data,points,label,self.fit_route.get())
            self.speed_figure.colorbar(line,ax=self.speed_ax,shrink=.65,pad=.1,label='Speed [m/s]')
            self.speed_points=np.array(points,copy=True)
            self.speed_source=label
            self.speed_is_draft=use_draft
            self.speed_spin.configure(to=len(points))
            self.speed_index.set('1')
            if self.speed_ids.get():
                for i in range(0,len(points),max(1,int(np.ceil(len(points)/20)))):
                    self.speed_ax.text(points[i,0],points[i,1],.025,f'#{i+1}',fontsize=8,color='#12344a',
                                       bbox=dict(facecolor='white',edgecolor='none',alpha=.7,pad=1))
            self.speed_ax.view_init(*angles)
            self.speed_figure.tight_layout()
            text=f'{label} | {len(points)} points | speed {points[:,-1].min():.2f}–{points[:,-1].max():.2f} m/s'
            if self.edit_mode.get() and self.control_points and not use_draft:
                text+=' | Control points have changed: Smooth preview first to view the new draft.'
            self.speed_status.set(text)
        except (ValueError,OSError) as exc:
            self.speed_status.set(f'Error: {exc}')
        self.speed_canvas.draw_idle()

    def speed_point_press(self,event):
        self.speed_press_position=None
        if event.button==1 and event.inaxes is self.speed_ax and not self.speed_toolbar.mode:
            self.speed_press_position=(event.x,event.y)

    def speed_point_release(self,event):
        start=self.speed_press_position;self.speed_press_position=None
        if start is None or self.speed_points is None or event.inaxes is not self.speed_ax:return
        if self.speed_toolbar.mode or np.linalg.norm(np.array(start)-[event.x,event.y])>5:return
        index=nearest_speed_point(self.speed_ax,self.speed_points,event.x,event.y)
        if index is not None:
            self.speed_index.set(str(index+1));self.select_speed_point()

    def select_speed_point(self):
        if self.speed_points is None:return
        try:
            index=int(self.speed_index.get())-1
            if not 0<=index<len(self.speed_points):raise ValueError()
        except ValueError:
            self.speed_point_info.set(f'Enter a point number from 1 to {len(self.speed_points)}.');return
        for artist in self.speed_highlights:artist.remove()
        p=self.speed_points[index];x,y=p[:2];v=p[-1]
        ground=self.speed_ax.scatter([x],[y],[0],s=65,color='#ffb000',edgecolor='black',depthshade=False,zorder=20)
        top=self.speed_ax.scatter([x],[y],[v],s=45,color='#ffb000',edgecolor='black',depthshade=False,zorder=20)
        vertical,=self.speed_ax.plot([x,x],[y,y],[0,v],color='#bc6c00',lw=1.4,ls='--')
        label=self.speed_ax.text(x,y,v,f'  #{index+1} / {v:.2f} m/s',fontsize=10,color='#673b00')
        self.speed_highlights=[ground,top,vertical,label]
        kind='Draft point' if self.speed_is_draft else 'CSV point'
        self.speed_point_info.set(f'{self.speed_source} | {kind} #{index+1} | x={x:.4f} m, y={y:.4f} m | speed={v:.3f} m/s')
        self.speed_canvas.draw_idle()

    def save(self):
        if self.data is None:
            self.message('Error: Select a valid combination before saving.', True)
            return
        try:
            path = self.library.root / 'output' / 'preview.png'
            path.parent.mkdir(exist_ok=True)
            self.figure.savefig(path, dpi=180)
            self.message(f'Preview saved: {path}')
        except OSError as exc:
            self.message(f'Error: {exc}', True)


def open_composer(root):
    try:
        window = tk.Tk()
        Composer(window, root)
        window.mainloop()
    except tk.TclError as exc:
        raise InputError(f'Cannot open the desktop viewer: {exc}. Use --check or --no-show from a terminal.') from None
