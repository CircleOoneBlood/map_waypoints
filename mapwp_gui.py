"""Small native map/waypoint composer. All UI messages are in English."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from mapwp_data import InputError, load_combination
from mapwp_library import Library, digest, map_signature
from mapwp_plot import draw_combination


class Composer:
    def __init__(self, window, root):
        self.window = window
        self.library = Library(root)
        self.data = None
        self.map_paths = []
        self.wp_paths = []
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
                              ('Refresh', self.refresh), ('Save preview', self.save)]:
            button = ttk.Button(buttons, text=label, command=action)
            button.pack(side='left', padx=(0, 8))
            if label == 'Apply to focus':
                self.apply_button = button
        self.fit_route = tk.BooleanVar(value=True)
        ttk.Checkbutton(buttons, text='Fit route', variable=self.fit_route,
                        command=self.redraw).pack(side='right')

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
        toolbar = NavigationToolbar2Tk(self.canvas, window, pack_toolbar=False)
        toolbar.pack(fill='x')
        ttk.Label(window, text='Selections are previews until applied. Changes affect local focus only; Jetson is not modified.',
                  padding=6).pack(fill='x')
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
        self.data = data
        self.apply_button.configure(state='normal')
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

    def redraw(self):
        if self.data is not None:
            draw_combination(self.ax, self.data, fit_route=self.fit_route.get())
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
