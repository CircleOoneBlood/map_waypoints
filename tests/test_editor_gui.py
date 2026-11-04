from pathlib import Path
import sys,tempfile,tkinter as tk
from types import SimpleNamespace
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapwp_library import Library,digest
from mapwp_gui import Composer
import unittest

class EditorGuiTests(unittest.TestCase):
    def test_click_drag_preview_save_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
         root=Path(tmp);m=root/'buffer/maps/test';m.mkdir(parents=True)
         wp=root/'buffer/waypoints';wp.mkdir()
         Image.fromarray(np.full((240,240),254,dtype=np.uint8)).save(m/'test.pgm')
         (m/'test.yaml').write_text('image: test.pgm\nresolution: 0.1\norigin: [-12, -12, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n')
         a=np.linspace(0,2*np.pi,200,endpoint=False)
         np.savetxt(wp/'circle.csv',np.column_stack((3*np.cos(a),3*np.sin(a),a,np.ones_like(a))),delimiter=',',header='x,y,yaw,v',comments='')
         lib=Library(root);lib.apply(m/'test.yaml',wp/'circle.csv')
         before=digest(root/'focus/circle.csv')
         try:window=tk.Tk()
         except tk.TclError as exc:self.skipTest(str(exc))
         window.withdraw()
         try:
          c=Composer(window,root);window.update();c.canvas.draw()
          c.edit_mode.set(True);c.toggle_editor()
          def event(x,y,button=1):
           px,py=c.ax.transData.transform([x,y])
           return SimpleNamespace(inaxes=c.ax,x=px,y=py,xdata=x,ydata=y,button=button)
          for angle in np.linspace(0,2*np.pi,16,endpoint=False):c.editor_press(event(3*np.cos(angle),3*np.sin(angle)))
          assert len(c.control_points)==16
          old=list(c.control_points)
          c.editor_press(event(*old[4]));c.editor_motion(event(.1,3.1));c.editor_release(event(.1,3.1))
          assert c.control_points[4]==(.1,3.1)
          c.editor_undo();assert c.control_points==old
          mode=c.toolbar.mode;c.toolbar.mode='pan/zoom'
          c.editor_press(event(8,8));assert len(c.control_points)==16
          c.toolbar.mode=mode
          c.editor_preview();assert c.draft is not None and not c.draft.errors,c.status.get()
          c.editor_name.set('clicked_route');c.editor_save()
          assert (wp/'clicked_route.csv').is_file(),c.status.get()
          assert digest(root/'focus/circle.csv')==before
          c.editor_seed();assert len(c.control_points)==16
          c.editor_preview();assert c.draft is not None
          c.smoothing.set('.2');assert c.draft is None
          c.editor_preview()
          before_controls=list(c.control_points)
          c.open_speed_view();c.speed_window.withdraw();c.speed_canvas.draw()
          assert c.speed_ax.name=='3d'
          assert 'Unsaved smooth draft' in c.speed_status.get()
          assert c.control_points==before_controls
          c.edit_mode.set(False);c.refresh_speed_view();c.speed_canvas.draw()
          assert 'clicked_route.csv' in c.speed_status.get()
          c.speed_index.set('42');c.select_speed_point();c.speed_canvas.draw()
          assert 'CSV point #42' in c.speed_point_info.get()
          assert f"speed={c.data.points[41,-1]:.3f}" in c.speed_point_info.get()
          c.speed_index.set('0');c.select_speed_point()
          assert 'Enter a point number' in c.speed_point_info.get()
          c.speed_ids.set(False);c.refresh_speed_view();c.speed_canvas.draw()
          assert c.control_points==before_controls

          assert digest(root/'focus/circle.csv')==before
          c.speed_window.destroy()

          print('Real Tk smoke test passed: click, drag, undo, toolbar isolation, preview, save, reopen; focus unchanged.')
         finally:window.destroy()
