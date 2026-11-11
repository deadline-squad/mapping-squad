"""Level 0 of the scene raster of scene_prep.py (top_h0, top_c0, top_v0) drawn on the GPU.

Usage: scene_raster_gpu.py <map> --scene <scene dir> --prep <prep dir> [--workers N]

Runs on the host, outside the pipeline's container, which has no GPU: Python with numpy, scipy and moderngl
(tools/maprender uses the same, PYTHON of maptiles.sh) and an EGL driver. scene_prep.py --rasterized then continues from the
rasters written here.

The highest surface over each sample point is what an orthographic camera looking down with a "greater" depth test keeps: every
mesh is one instanced draw of its triangles, its placements the instances, and the fragment writes its height and class.
Everything else (the ground below, the 2 x 2 samples of a cell, coverage, thin objects) is scene_objects.raster_block, shared with
the CPU path, so the two differ only in the points that lie on a triangle's edge to within the rasteriser's sub-pixel precision
(1/256 of a 5 cm sample): the CPU counts an edge point in, the GPU follows the top-left rule. test_scene_gpu.py measures the
difference.
"""

import argparse
import json
import multiprocessing
import os
import time

import moderngl
import numpy as np
from numpy.lib.format import open_memmap

import scene_objects as scene
import scene_prep
import worker_pool

GL_DEPTH_CLAMP = 0x864F
# Cleared "no surface" height, far below any map (read back as -inf)
NO_SURFACE = -3.0e38
# Heights below the map's lowest ground and above its highest ground are clamped, not clipped (GL_DEPTH_CLAMP): the depth range only
# needs to resolve which surface is higher, 24 bits over a few kilometres is a fraction of a millimetre
DEPTH_BELOW_M = 500.0
DEPTH_ABOVE_M = 1500.0
MESH_CACHE_BYTES = 1024 * 2 ** 20

VERTEX = """
#version 330
in vec3 corner;
in vec3 row_x;
in vec3 row_y;
in vec3 row_z;
in vec3 offset;
uniform vec2 window_m;
uniform float half_step;
uniform float z_low;
uniform float z_span;
out float height;
void main() {
    vec3 p = corner.x * row_x + corner.y * row_y + corner.z * row_z + offset;
    height = p.z;
    gl_Position = vec4((p.xy + half_step) / window_m * 2.0 - 1.0, (p.z - z_low) / z_span * 2.0 - 1.0, 1.0);
}
"""

FRAGMENT = """
#version 330
in float height;
uniform float object_class;
out vec2 surface;
void main() {
    surface = vec2(height, object_class);
}
"""


class GpuSampler:
    """scene_objects.sample_tops on the GPU: a callable with its signature, for scene_objects.raster_block(sampler=...).

    z_low, z_high: absolute metres the depth test resolves (outside them heights are kept, their order is not).
    The triangles of the meshes stay on the GPU up to MESH_CACHE_BYTES, then the cache is emptied.
    """

    def __init__(self, z_low, z_high):
        self.ctx = moderngl.create_standalone_context(require=330, backend="egl", libgl="libGL.so.1", libegl="libEGL.so.1")
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.depth_func = ">"
        self.ctx.enable_direct(GL_DEPTH_CLAMP)
        self.program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.program["z_low"] = z_low
        self.program["z_span"] = z_high - z_low
        self.renderer = self.ctx.info["GL_RENDERER"]
        self.framebuffers = {}
        self.meshes = {}
        self.mesh_bytes = 0
        self.instances = None

    def _framebuffer(self, rows, cols):
        key = (rows, cols)
        if key not in self.framebuffers:
            colour = self.ctx.texture((cols, rows), 2, dtype="f4")
            self.framebuffers[key] = self.ctx.framebuffer(colour, self.ctx.depth_renderbuffer((cols, rows)))
        return self.framebuffers[key]

    def _instance_buffer(self, count):
        """The shared buffer of per-placement rows (12 float32), grown when needed; growing invalidates the cached vertex arrays."""
        size = count * 12 * 4
        if self.instances is None or self.instances.size < size:
            self._release_meshes()
            if self.instances is not None:
                self.instances.release()
            self.instances = self.ctx.buffer(reserve=max(size, 2 ** 20))
        return self.instances

    def _release_meshes(self):
        for vbo, vao in self.meshes.values():
            vao.release()
            vbo.release()
        self.meshes, self.mesh_bytes = {}, 0

    def _mesh(self, scene_objects, group):
        """(vbo, vao) of a group's triangles, or None for a group without triangles."""
        key = id(group)
        if key in self.meshes:
            return self.meshes[key]
        corners = scene_objects.triangles(group)
        if not len(corners):
            return None
        if self.mesh_bytes + corners.nbytes > MESH_CACHE_BYTES:
            self._release_meshes()
        vbo = self.ctx.buffer(np.ascontiguousarray(corners, np.float32).tobytes())
        vao = self.ctx.vertex_array(self.program, [(vbo, "3f", "corner"), (self.instances, "3f 3f 3f 3f/i", "row_x", "row_y", "row_z", "offset")])
        self.meshes[key] = (vbo, vao)
        self.mesh_bytes += corners.nbytes
        return self.meshes[key]

    def __call__(self, scene_objects, hits, x0, y0, step, rows, cols):
        """(top [rows, cols] float64, absolute metres, -inf where no surface; class [rows, cols] int) at (x0 + i * step, y0 + j * step).

        Drawn in ascending class order with a strict depth test, so of equal heights the lowest class index wins, as on the CPU.
        """
        framebuffer = self._framebuffer(rows, cols)
        framebuffer.use()
        framebuffer.clear(NO_SURFACE, 0.0, 0.0, 0.0, depth=0.0)
        self.program["window_m"] = (cols * step, rows * step)
        self.program["half_step"] = step / 2
        self._instance_buffer(max(int(hit.sum()) for _, hit in hits))
        origin = np.array([x0, y0, 0.0])
        for group, hit in sorted(hits, key=lambda item: item[0]["cls"]):
            mesh = self._mesh(scene_objects, group)
            if mesh is None:
                continue
            matrices = group["matrices"][hit]
            rows_of = np.concatenate([matrices[:, 0, :3], matrices[:, 1, :3], matrices[:, 2, :3], matrices[:, 3, :3] - origin * 100], axis=1) / 100
            # A fresh store for every draw: overwriting the one the previous draw still reads would wait for the GPU
            self.instances.orphan()
            self.instances.write(rows_of.astype(np.float32).tobytes())
            self.program["object_class"] = float(group["cls"])
            mesh[1].render(moderngl.TRIANGLES, instances=len(matrices))
        surface = np.frombuffer(framebuffer.read(components=2, dtype="f4"), np.float32).reshape(rows, cols, 2)
        top = surface[..., 0].astype(np.float64)
        top[top < NO_SURFACE / 2] = -np.inf
        return top, np.rint(surface[..., 1]).astype(np.int64)


def depth_range(meta, ground):
    """(z_low, z_high) absolute metres of the depth test of a map: its ground's range with DEPTH_BELOW_M and DEPTH_ABOVE_M around."""
    return meta["z_min_m"] - DEPTH_BELOW_M, meta["z_min_m"] + float(np.max(ground)) + DEPTH_ABOVE_M


_worker = {}


def _init_worker(prep_dir, z_min, bounds):
    _worker.update(ground=np.load(os.path.join(prep_dir, "ground.npy")), prep=prep_dir, z_min=z_min, bounds=bounds)


def _finish_block(task):
    """scene_objects.block_cells of one block in a worker, written into the level 0 rasters; returns its covered cells."""
    (r0, r1, c0, c1), top, top_class = task
    height, cls, cover = scene.block_cells((top.astype(np.float64), top_class), _worker["ground"], _worker["z_min"], _worker["bounds"], r0, r1, c0, c1)
    if not height.any():
        return 0
    for name, array in (("h", height), ("c", cls), ("v", cover)):
        out = open_memmap(os.path.join(_worker["prep"], f"top_{name}0.npy"), mode="r+")
        out[r0:r1, c0:c1] = array
        out.flush()
    return int((cover > 0).sum())


def rasterize(scene_dir, prep_dir, workers, log=print):
    """Write top_h0 / top_c0 / top_v0 of a map (scene_prep.py's level 0, in its BLOCK blocks) and top_raster.json; returns its content.

    This process draws one block after the other on the GPU (the GL context belongs to it); ``workers`` processes turn the samples
    into cells meanwhile (scene_objects.block_cells), at most 2 * workers blocks waiting. Blocks no placement reaches stay zero.
    """
    started = time.time()
    meta = json.load(open(os.path.join(prep_dir, "meta.json")))
    bounds, z_min = meta["bounds_m"], meta["z_min_m"]
    shape = scene_prep.level0_shape(bounds)
    for name, dtype in (("h", np.uint16), ("c", np.uint8), ("v", np.uint8)):
        open_memmap(os.path.join(prep_dir, f"top_{name}0.npy"), mode="w+", dtype=dtype, shape=shape).flush()
    ground = np.load(os.path.join(prep_dir, "ground.npy"))
    objects_of_scene = scene.SceneObjects(scene_dir)
    sampler = GpuSampler(*depth_range(meta, ground))
    del ground
    tasks = scene_prep.blocks_of(shape)
    covered, pending, sampled_s = 0, [], 0.0
    with worker_pool.Pool(workers, _init_worker, (prep_dir, z_min, bounds), multiprocessing.get_context("spawn")) as pool:
        for done, block in enumerate(tasks, 1):
            t = time.time()
            samples = scene.block_samples(objects_of_scene, bounds, *block, sampler)
            sampled_s += time.time() - t
            if samples is not None:
                top, top_class = samples
                pending.append(pool.submit(_finish_block, (block, top.astype(np.float32), top_class.astype(np.uint8))))
            while len(pending) > 2 * workers or (pending and pending[0].done()):
                covered += pending.pop(0).result()
            if done % max(1, len(tasks) // 10) == 0:
                log(f"scene objects {done}/{len(tasks)} blocks (GPU)")
        covered += sum(future.result() for future in pending)
    result = {"sampler": "gpu", "renderer": sampler.renderer, "shape": list(shape), "covered_cells": covered, "blocks": len(tasks),
              "gpu_seconds": round(sampled_s, 1), "seconds": round(time.time() - started, 1)}
    json.dump(result, open(os.path.join(prep_dir, "top_raster.json"), "w"), indent=1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--scene", required=True, help="the map's client scene directory")
    parser.add_argument("--prep", required=True, help="the map's prep directory (meta.json, ground.npy; the rasters are written here)")
    parser.add_argument("--workers", type=int, default=4, help="processes that turn the GPU's samples into cells")
    args = parser.parse_args()

    def log(*parts):
        print(time.strftime("%H:%M:%S"), args.map, *parts, flush=True)
    result = rasterize(args.scene, args.prep, args.workers, log)
    log(f"scene objects rasterized on {result['renderer']}, {result['covered_cells']} covered cells, {result['seconds']} s")


if __name__ == "__main__":
    main()
