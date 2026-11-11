"""Tests of worker_pool.py and of the steps whose workers it runs: a worker that cannot start or that dies stops the step at once,
with the worker's own error (deadline-squad/deadline-squadcalc#34). Every pool runs in a new process stopped after TIMEOUT_S,
because the failure guarded against is a pool that waits forever.

    docker run --rm -e PYTHONPATH=/py:/hmpy -v tools/maptiles/py:/py:ro -v tools/heightmaps/py:/hmpy:ro -w /py squadcalc-maptiles-py \
        python -m unittest test_worker_pool
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

from test_scene import synthetic_map

HERE = os.path.dirname(os.path.abspath(__file__))
# Each process below ends in a few seconds; one whose pool waits forever (multiprocessing.Pool) is stopped after this
TIMEOUT_S = 30
_state = {}


def offset_by(offset):
    """Initializer of the test pools: the offset that shifted adds."""
    _state["offset"] = offset


def shifted(task):
    return task + _state["offset"]


def killed(task):
    """A task whose worker is killed, as the container's memory limit kills it."""
    os.kill(os.getpid(), signal.SIGKILL)


def run(code, *args):
    """CompletedProcess of Python ``code`` run with ``args`` in a new process in this folder; TimeoutExpired after TIMEOUT_S."""
    return subprocess.run([sys.executable, "-c", code, *args], cwd=HERE, capture_output=True, text=True, timeout=TIMEOUT_S)


def not_found(path):
    """The last line of the traceback of a FileNotFoundError on path."""
    return f"FileNotFoundError: [Errno 2] No such file or directory: {path!r}"


class WorkerPool(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        self.missing = os.path.join(self.directory, "top_meta.json")

    def assert_stopped_by_the_initializer(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], not_found(self.missing))
        self.assertNotIn("Exception in initializer", result.stderr)

    def test_the_workers_run_the_tasks_after_their_initializer(self):
        result = run("import test_worker_pool as t, worker_pool\n"
                     "with worker_pool.Pool(2, t.offset_by, (10,)) as pool:\n"
                     "    print(sorted(pool.imap_unordered(t.shifted, range(6))))\n")
        self.assertEqual((result.returncode, result.stdout), (0, "[10, 11, 12, 13, 14, 15]\n"), result.stderr)

    def test_the_parent_raises_the_initializer_error_once(self):
        result = run("import sys, worker_pool\n"
                     "with worker_pool.Pool(2, open, (sys.argv[1],)) as pool:\n"
                     "    list(pool.imap_unordered(abs, range(100)))\n", self.missing)
        self.assert_stopped_by_the_initializer(result)

    def test_spawned_workers_run_a_submitted_task(self):
        # scene_raster_gpu.py: the workers are spawned (the parent holds a GL context) and the blocks submitted one by one
        result = run("import multiprocessing, test_worker_pool as t, worker_pool\n"
                     "with worker_pool.Pool(2, t.offset_by, (10,), multiprocessing.get_context('spawn')) as pool:\n"
                     "    print(pool.submit(t.shifted, 5).result())\n")
        self.assertEqual((result.returncode, result.stdout), (0, "15\n"), result.stderr)

    def test_a_submitted_task_raises_the_initializer_error_of_spawned_workers(self):
        result = run("import multiprocessing, sys, worker_pool\n"
                     "with worker_pool.Pool(2, open, (sys.argv[1],), multiprocessing.get_context('spawn')) as pool:\n"
                     "    pool.submit(abs, -1).result()\n", self.missing)
        self.assert_stopped_by_the_initializer(result)

    def test_a_killed_worker_stops_the_pool(self):
        result = run("import test_worker_pool as t, worker_pool\n"
                     "with worker_pool.Pool(2, t.offset_by, (0,)) as pool:\n"
                     "    list(pool.imap_unordered(t.killed, range(100)))\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stderr.splitlines()[-1].startswith("concurrent.futures.process.BrokenProcessPool: "), result.stderr)


class Steps(unittest.TestCase):
    """The steps with worker pools on the synthetic map of test_scene: a source their workers load is missing."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        self.slug = synthetic_map(self.directory)
        self.prep = os.path.join(self.directory, "prep")
        self.base = os.path.join(self.prep, self.slug)
        self.out = os.path.join(self.directory, "out")

    def render(self):
        """CompletedProcess of render.py of the map with 2 workers into self.out."""
        heightmaps = os.path.join(self.directory, "heightmaps")
        os.makedirs(os.path.join(heightmaps, self.slug))
        json.dump({"sources": {"terrain": "Squad dedicated server build 0, landscape collision"}},
                  open(os.path.join(heightmaps, self.slug, "meta.json"), "w"))
        return run("import render, sys\n"
                   "render.PREP_DIR, render.HEIGHTMAPS_DIR = sys.argv[1:3]\n"
                   "sys.argv = ['render.py', sys.argv[3], '--workers', '2', '--out', sys.argv[4]]\n"
                   "render.main()\n", self.prep, heightmaps, self.slug, self.out)

    def test_render_draws_every_tile(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, "1"))), ["0_0.webp", "0_1.webp", "1_0.webp", "1_1.webp"])
        self.assertEqual(os.listdir(os.path.join(self.out, "0")), ["0_0.webp"])

    def test_render_without_the_scene_stops_before_it_starts(self):
        scene_report = os.path.join(self.base, "top_meta.json")
        os.remove(scene_report)
        result = self.render()
        self.assertEqual((result.returncode, result.stderr), (1, f"{scene_report} is missing: run maptiles.sh scene {self.slug} first\n"))
        self.assertFalse(os.path.exists(self.out))

    def test_render_names_a_missing_source(self):
        crowns = os.path.join(self.base, "crowns.json")
        os.remove(crowns)
        result = self.render()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], not_found(crowns))

    def test_the_colour_fitting_names_a_missing_basemap(self):
        # fit_palette.py, and fit_fields.py and fit_relief.py, whose workers start with fit_palette.init
        basemap = os.path.join(self.directory, f"{self.slug}.webp")
        result = run("import fit_palette, render, sys\n"
                     "render.PREP_DIR = sys.argv[1]\n"
                     "fit_palette.collect(sys.argv[2], None, 0, 2, sys.argv[3])\n", self.prep, self.slug, basemap)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], not_found(basemap))

    def test_the_scene_raster_names_a_missing_scene(self):
        scene_dir = os.path.join(self.directory, "no-scene")
        result = run("import scene_prep, sys, test_scene\n"
                     "scene_prep.rasterize(sys.argv[1], sys.argv[2], test_scene.BOUNDS, 0.0, scene_prep.level0_shape(test_scene.BOUNDS), 2)\n",
                     scene_dir, self.base)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], not_found(os.path.join(scene_dir, "materials.json")))

    def test_the_collision_raster_names_missing_statics(self):
        statics = os.path.join(self.directory, "no-statics")
        result = run("import prep, sys, test_scene\n"
                     "prep.rasterize_objects(sys.argv[1], test_scene.BOUNDS, (240, 240), sys.argv[2], sys.argv[3], 0.0, 2)\n",
                     statics, os.path.join(self.base, "ground.npy"), self.base)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.splitlines()[-1], not_found(os.path.join(statics, "instances.ndjson")))


if __name__ == "__main__":
    unittest.main()
