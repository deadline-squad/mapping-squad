"""Tests of the GPU scene rasterizer (scene_raster_gpu.py) against the CPU one, on the host (the pipeline's container has no GPU):

    cd tools/maptiles/py && PYTHONPATH=.:../../heightmaps/py ~/data/venv-torch/bin/python -m unittest test_scene_gpu

Skipped where no OpenGL 3.3 context can be made (EGL).
"""

import shutil
import tempfile
import unittest

import numpy as np

import features
import scene_objects as so
from test_scene import BOUNDS, OPAQUE, Scene, flat_ground

SKIP_REASON = ""
try:
    import scene_raster_gpu
    SAMPLER = scene_raster_gpu.GpuSampler(-100.0, 200.0)
except Exception as error:  # no moderngl or no EGL driver: nothing to test here
    SAMPLER, SKIP_REASON = None, str(error)


@unittest.skipIf(SAMPLER is None, f"no GPU context: {SKIP_REASON}")
class GpuMatchesCpu(unittest.TestCase):
    def scene(self, build):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        build(s)
        s.write()
        return so.SceneObjects(directory)

    def both(self, scene, ground, z_min=0.0, cells=600):
        cpu = so.raster_block(scene, ground, z_min, BOUNDS, 0, cells, 0, cells)
        gpu = so.raster_block(scene, ground, z_min, BOUNDS, 0, cells, 0, cells, sampler=SAMPLER)
        return cpu, gpu

    def test_boxes_on_whole_centimetres_give_the_same_bytes(self):
        def build(s):
            house = s.add_mesh("House", [((0, 0, 0, 1000, 600, 500), OPAQUE), ((0, 0, 500, 400, 600, 700), OPAQUE)])
            wall = s.add_mesh("Wall_Fence", [((0, 0, 0, 1500, 10, 150), OPAQUE)])
            pole = s.add_mesh("Pole", [((0, 0, 0, 35, 35, 800), OPAQUE)])
            s.place(house, (20.05, 20))
            s.place(wall, (5, 5))
            s.place(pole, (50, 50))
        ground = flat_ground()
        ground[:, 30:] = 1.5
        cpu, gpu = self.both(self.scene(build), ground, z_min=-2.0)
        for a, b in zip(cpu, gpu):
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_turned_and_scaled_instances_agree_but_for_edge_points(self):
        rng = np.random.default_rng(7)

        def build(s):
            box = s.add_mesh("Crate", [((-150, -100, 0, 150, 100, 250), OPAQUE)])
            roof = s.add_mesh("Shed", [((-300, -200, 0, 300, 200, 320), OPAQUE), ((-300, -50, 320, 300, 50, 420), OPAQUE)])
            for _ in range(60):
                s.place(box if rng.random() < 0.5 else roof,
                        (rng.uniform(4, 56), rng.uniform(4, 56), rng.uniform(0, 1), rng.uniform(0, 360), rng.uniform(0.6, 1.8)))
        (h_cpu, c_cpu, v_cpu), (h_gpu, c_gpu, v_gpu) = self.both(self.scene(build), flat_ground())
        objects = (h_cpu > 0) | (h_gpu > 0)
        self.assertGreater(int(objects.sum()), 50_000)
        self.assertGreaterEqual(float(np.mean(h_cpu[objects] == h_gpu[objects])), 0.999)
        self.assertEqual(int((c_cpu[objects] != c_gpu[objects]).sum()), 0)
        self.assertLess(float(np.abs(v_cpu.astype(int) - v_gpu.astype(int)).mean()), 0.05)

    def test_the_higher_surface_wins_and_a_tie_goes_to_the_lower_class(self):
        def build(s):
            low_wall = s.add_mesh("Wall_Low", [((0, 0, 0, 1000, 1000, 300), OPAQUE)])
            house = s.add_mesh("House", [((0, 0, 0, 500, 1000, 400), OPAQUE), ((500, 0, 0, 1000, 1000, 300), OPAQUE)])
            s.place(low_wall, (10, 10))
            s.place(house, (10, 10))
        (h, c, _), (h_gpu, c_gpu, _) = self.both(self.scene(build), flat_ground())
        self.assertEqual(int(h_gpu[150, 125]), 400)
        self.assertEqual(int(c_gpu[150, 125]), features.STRUCTURE)
        # Both are 3 m high on the east half: the CPU keeps the lower class index, and so must the GPU
        self.assertEqual(int(c_gpu[150, 175]), int(c[150, 175]))
        self.assertEqual(int(c_gpu[150, 175]), min(features.STRUCTURE, features.WALL))


if __name__ == "__main__":
    unittest.main()
