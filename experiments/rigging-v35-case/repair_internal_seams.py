import importlib.util,json,sys
from pathlib import Path
import bpy,bmesh
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];body=next(o for o in meshes if 'continuous_static_body_base' in o.name)
before={o.name:adapter.appearance_data(o) for o in meshes}
bm=bmesh.new();bm.from_mesh(body.data)
counts_before=dict(boundary=sum(e.is_boundary for e in bm.edges),nonmanifold=sum(not e.is_manifold for e in bm.edges))
bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
boundary=[e for e in bm.edges if e.is_boundary]
result=bmesh.ops.holes_fill(bm,edges=boundary,sides=0) if boundary else {'faces':[]}
bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
counts_after=dict(boundary=sum(e.is_boundary for e in bm.edges),nonmanifold=sum(not e.is_manifold for e in bm.edges))
assert counts_after['nonmanifold']==0,(counts_before,counts_after)
bm.to_mesh(body.data);bm.free();body.data.update();bpy.context.view_layer.update()
assert all(adapter.appearance_data(o)==before[o.name] for o in meshes if o!=body)
report=dict(success=True,run_id=job['run_id'],mode='local_internal_union_seam_repair',before=counts_before,after=counts_after,unchanged_other_meshes=103,quality_passed=False,ue_verified=False)
after={o.name:adapter.appearance_data(o) for o in meshes}
bpy.ops.wm.save_as_mainfile(filepath=str(output/'model.blend'));bpy.ops.wm.open_mainfile(filepath=str(output/'model.blend'),use_scripts=False)
assert all(adapter.appearance_data(bpy.data.objects[n])==v for n,v in after.items())
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))
