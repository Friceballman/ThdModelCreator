"""Run a fixed Codex geometry recipe in Blender and produce inspectable artifacts.

action.py must define build(job). It may create meshes but must not save a project;
this adapter owns the output files and verification.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import runpy
import sys

import bpy
import bmesh
from mathutils import Vector


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main(job_file):
    job = json.loads(Path(job_file).read_text(encoding='utf-8'))
    output = Path(job['output'])
    output.mkdir(parents=True, exist_ok=False)
    if job.get('source_blend'):
        bpy.ops.wm.open_mainfile(filepath=job['source_blend'], use_scripts=False)
    else:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0

    namespace = runpy.run_path(job['script'])
    if not callable(namespace.get('build')):
        raise ValueError('action.py must define build(job)')
    namespace['build'](job)
    objects = [obj for obj in scene.objects if obj.type == 'MESH']
    if not objects:
        raise ValueError('No mesh objects were produced')
    faces = 0
    vertices = 0
    all_world = []
    duplicate_vertices = 0
    boundary_edges = 0
    non_manifold_edges = 0
    loose_edges = 0
    degenerate_faces = 0
    for obj in objects:
        obj['mwb_part_id'] = job['part_id']
        obj['mwb_source_candidate_id'] = job.get('source_candidate_id', '')
        obj['mwb_object_role'] = obj.get('mwb_object_role', 'geometry')
        mesh = obj.data
        if not mesh.vertices or not mesh.polygons:
            raise ValueError(f'Empty mesh object: {obj.name}')
        local = set()
        for vertex in mesh.vertices:
            if not all(math.isfinite(x) for x in vertex.co):
                raise ValueError(f'Non-finite vertex: {obj.name}')
            key = tuple(round(x, 8) for x in vertex.co)
            duplicate_vertices += key in local
            local.add(key)
        for polygon in mesh.polygons:
            if len(polygon.vertices) < 3 or any(i < 0 or i >= len(mesh.vertices) for i in polygon.vertices):
                raise ValueError(f'Invalid polygon: {obj.name}')
        bm = bmesh.new()
        bm.from_mesh(mesh)
        boundary_edges += sum(edge.is_boundary for edge in bm.edges)
        non_manifold_edges += sum(not edge.is_manifold for edge in bm.edges)
        loose_edges += sum(edge.is_wire for edge in bm.edges)
        degenerate_faces += sum(face.calc_area() <= 1e-12 for face in bm.faces)
        bm.free()
        faces += len(mesh.polygons)
        vertices += len(mesh.vertices)
        all_world.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if faces > job['face_limit']['max_faces']:
        raise ValueError(f'Face limit exceeded: {faces} > {job["face_limit"]["max_faces"]}')

    mins = [min(v[i] for v in all_world) for i in range(3)]
    maxs = [max(v[i] for v in all_world) for i in range(3)]
    span = max(maxs[i] - mins[i] for i in range(3))
    if span <= 0 or not math.isfinite(span):
        raise ValueError('Invalid bounding box')
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'model.blend'))
    bpy.ops.wm.obj_export(filepath=str(output / 'model.obj'))
    checks = {'success': True, 'part_id': job['part_id'], 'vertices': vertices, 'faces': faces,
              'blender_version': bpy.app.version_string,
              'target_faces': job['face_limit']['target_faces'],
              'max_faces': job['face_limit']['max_faces'], 'duplicate_vertices': duplicate_vertices,
              'boundary_edges': boundary_edges, 'non_manifold_edges': non_manifold_edges,
              'loose_edges': loose_edges, 'degenerate_faces': degenerate_faces,
              'self_intersections': 'not_checked',
              'bbox_min': mins, 'bbox_max': maxs, 'unit': 'm', 'up_axis': 'Z', 'front_axis': '-Y',
              'visual_review': 'deferred_to_final_character'}
    save_json(output / 'checks.json', checks)
    save_json(output / 'intent.json', job['intent'])


if __name__ == '__main__':
    arguments = sys.argv[sys.argv.index('--') + 1:]
    main(arguments[0])
