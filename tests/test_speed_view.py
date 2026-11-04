"""3D speed coordinates and supported CSV formats."""
from pathlib import Path
import sys
import unittest
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mapwp_data import Combination,InputError
from mapwp_plot import draw_speed_3d, nearest_speed_point

class SpeedViewTests(unittest.TestCase):
    def test_height_uses_speed_not_heading(self):
        for points in [np.array([[0,0,1],[1,0,3],[1,1,2.]]),
                       np.array([[0,0,8,1],[1,0,9,3],[1,1,10,2.]])]:
            data=Combination(Path('test.yaml'),Path('map.pgm'),Path('route.csv'),
                             np.full((20,30),254,dtype=np.uint8),points,.1,(-1,-1,.3),[])
            fig=Figure();canvas=FigureCanvasAgg(fig);ax=fig.add_subplot(111,projection='3d')
            line=draw_speed_3d(ax,data)
            segments=np.asarray(line._segments3d)
            np.testing.assert_array_equal(segments[:,0,2],points[:-1,-1])
            np.testing.assert_array_equal(segments[:,1,2],points[1:,-1])
            self.assertEqual(ax.get_zlabel(),'Speed [m/s]')
            walls=[c for c in ax.collections if c.get_gid()=='speed_wall']
            self.assertEqual(len(walls),1)
            self.assertAlmostEqual(walls[0].get_alpha(),.28)
            fig.colorbar(line,ax=ax);canvas.draw()
            from mpl_toolkits.mplot3d import proj3d
            x,y,_=proj3d.proj_transform(points[1,0],points[1,1],points[1,-1],ax.get_proj())
            px,py=ax.transData.transform([x,y])
            self.assertEqual(nearest_speed_point(ax,points,px,py),1)
            self.assertIsNone(nearest_speed_point(ax,points,-10000,-10000))

    def test_missing_speed_is_not_guessed(self):
        data=Combination(Path('test.yaml'),Path('map.pgm'),Path('route.csv'),
                         np.ones((10,10)),np.zeros((3,2)),.1,(0,0,0),[])
        ax=Figure().add_subplot(111,projection='3d')
        with self.assertRaises(InputError):draw_speed_3d(ax,data)
