"""Waypoint editing geometry, persistence and mouse-event regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapwp_data import Combination,InputError
from mapwp_editor import make_draft,seed_controls,save_draft

class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.map=self.root/'map.yaml'
        self.map.write_text('free_thresh: 0.196\nnegate: 0\n')
        self.data=Combination(self.map,Path('unused'),Path('unused'),np.full((240,240),254,dtype=np.uint8),np.zeros((4,4)),.1,(-12.,-12.,0.),[])
        a=np.linspace(0,2*np.pi,16,endpoint=False)
        self.controls=np.column_stack((3*np.cos(a),3*np.sin(a)))

    def test_closed_uniform_route_speed_and_reverse(self):
        for control in [self.controls,self.controls[::-1]]:
            draft=make_draft(control,self.data)
            self.assertEqual(draft.errors,[])
            xy=draft.points[:,:2];ds=np.linalg.norm(np.roll(xy,-1,axis=0)-xy,axis=1)
            self.assertGreater(ds.min(),.09);self.assertLessEqual(ds.max(),.101)
            speed=draft.points[:,-1]
            self.assertLessEqual(speed.max(),5.)
            a=(np.roll(speed,-1)**2-speed**2)/(2*ds)
            self.assertLessEqual(a.max(),1.50001);self.assertGreaterEqual(a.min(),-2.00001)
            signed=np.sum(xy[:,0]*np.roll(xy[:,1],-1)-xy[:,1]*np.roll(xy[:,0],-1))
            self.assertEqual(np.sign(signed),1 if control is self.controls else -1)

    def test_obstacles_and_rotated_map(self):
        baseline=make_draft(self.controls,self.data)
        angle=.6;c,s=np.cos(angle),np.sin(angle)
        self.data.origin=(2.,3.,angle)
        local=self.controls+12
        world=local@np.array([[c,s],[-s,c]])+np.array([2.,3.])
        rotated=make_draft(world,self.data)
        self.assertAlmostEqual(rotated.stats['min_clearance_m'],baseline.stats['min_clearance_m'],places=3)
        self.data.image[:]=205
        draft=make_draft(world,self.data)
        self.assertFalse(draft.errors)
        self.assertTrue(draft.warnings)
        path=save_draft(self.root,'near_obstacles',draft,world,{})
        self.assertTrue(path.is_file())
        report=json.loads(path.with_suffix('.json').read_text())
        self.assertEqual(report['warnings'],draft.warnings)

    def test_invalid_points_rejected_but_tight_bend_can_save(self):
        for control in [self.controls[:3],np.vstack((self.controls[:2],self.controls[1:]))]:
            with self.assertRaises(InputError):make_draft(control,self.data)
        tiny=make_draft(self.controls*.1,self.data)
        self.assertFalse(tiny.errors)
        self.assertTrue(any('steering' in warning for warning in tiny.warnings))
        path=save_draft(self.root,'tight_bend',tiny,self.controls*.1,{})
        self.assertTrue(path.exists())

    def test_self_intersection_warns_but_can_save(self):
        t=np.linspace(0,2*np.pi,32,endpoint=False)
        controls=np.column_stack((3*np.sin(t),3*np.sin(2*t)))
        draft=make_draft(controls,self.data,smoothing=0.)
        self.assertFalse(draft.errors)
        self.assertTrue(any('crosses itself' in warning for warning in draft.warnings))
        self.assertTrue(save_draft(self.root,'crossing',draft,controls,{}).exists())

    def test_save_and_recover_controls_without_touching_other_files(self):
        draft=make_draft(self.controls,self.data)
        path=save_draft(self.root,'my_route',draft,self.controls,dict(smoothing=.12,max_speed=5.))
        points=np.loadtxt(path,delimiter=',',skiprows=1)
        np.testing.assert_allclose(points,draft.points,atol=1e-8)
        report=json.loads(path.with_suffix('.json').read_text())
        np.testing.assert_array_equal(report['control_points'],self.controls)
        with self.assertRaises(FileExistsError):save_draft(self.root,'my_route',draft,self.controls,{})
        with self.assertRaises(InputError):save_draft(self.root,'../escape',draft,self.controls,{})
        save_draft(self.root,'my_route',draft,self.controls,{},overwrite=True)
        self.assertFalse(list(self.root.glob('.editor-*')))

    def test_seeding_avoids_duplicate_closure(self):
        source=np.vstack((self.controls,self.controls[:1]))
        seeds=seed_controls(source)
        self.assertGreater(np.linalg.norm(seeds[0]-seeds[-1]),.5)

if __name__=='__main__':unittest.main()
