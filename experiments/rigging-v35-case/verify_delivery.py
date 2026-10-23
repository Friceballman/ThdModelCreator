"""Independent preservation, rig, eye, contact and saved-action checks on delivery."""
import importlib.util,json,sys,math,hashlib,ctypes
from pathlib import Path
import bpy,bmesh
from mathutils import Matrix,Vector
from mathutils.bvhtree import BVHTree
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output']);project=Path(job['case']).parents[1]
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
static=project/'exports/fd13ce2d-48f8-4a61-b359-9a136387f79b/outputs/model.blend'
assert hashlib.sha256(static.read_bytes()).hexdigest()=='f69f023673167b00b333bbfe132632f54ad4ad4d0fcf19e8f3dcee6bb7a3558f'
bpy.ops.wm.open_mainfile(filepath=str(static),use_scripts=False)
source_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];source={o.name:adapter.appearance_data(o) for o in source_meshes};source_points={o.name:adapter.coordinates(o) for o in source_meshes}
profile=adapter.frame_profile(source_meshes);adapter.render_views(output,'source',profile)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE');meshes=[o for o in scene.objects if o.type=='MESH'];body=next(o for o in meshes if 'continuous_static_body_base' in o.name)
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];scene.frame_set(1);bpy.context.view_layer.update()
assert {o.name for o in meshes}==set(source)
protected={o.name:adapter.appearance_data(o)==source[o.name] for o in meshes if o!=body}
assert all(protected.values()) and len(protected)==103
rest_errors={o.name:max((Vector(a)-Vector(b)).length for a,b in zip(source_points[o.name],adapter.coordinates(o))) for o in meshes if o!=body}
assert max(rest_errors.values())<1e-6
neck=[Vector(p) for p in source_points[body.name] if p[2]>=1.925 and abs(p[0])<.115]
current=[Vector(p) for p in adapter.coordinates(body)]
neck_error=max(min((p-q).length for q in current) for p in neck);assert neck_error<1e-6
body_materials=adapter.appearance_data(body)['materials']
if body_materials!=source[body.name]['materials']:
    (output/'body-material-comparison.json').write_text(json.dumps(dict(source=source[body.name]['materials'],delivery=body_materials),indent=2),encoding='utf-8')
source_materials=source[body.name]['materials']
assert body_materials[:len(source_materials)]==source_materials
assert all(m is None for m in body_materials[len(source_materials):])
body_tree=BVHTree.FromPolygons(current,[tuple(p.vertices) for p in body.data.polygons],all_triangles=False)
neck_material_samples=0;neck_surface_error=0.
for ids,material_index,smooth in source[body.name]['faces']:
    p=sum((Vector(source_points[body.name][i]) for i in ids),Vector())/len(ids)
    if all(source_points[body.name][i][2]>=1.925 and abs(source_points[body.name][i][0])<.115 for i in ids):
        hit,n,index,distance=body_tree.find_nearest(p)
        # The body was retopologized: unchanged vertices do not imply identical
        # interpolation across a dissolved/retriangulated neck face. Measure it.
        neck_surface_error=max(neck_surface_error,distance)
        assert body.data.polygons[index].material_index==material_index,(list(p),material_index,body.data.polygons[index].material_index)
        neck_material_samples+=1
assert neck_material_samples>0
adapter.render_views(output,'delivery-source-pose',profile)
weights_error=0.;max_influences=0
for o in meshes:
    for v in o.data.vertices:
        ws={o.vertex_groups[g.group].name:g.weight for g in v.groups if g.weight>1e-8}
        assert ws and set(ws)<=set(arm.data.bones.keys())
        weights_error=max(weights_error,abs(sum(ws.values())-1));max_influences=max(max_influences,len(ws))
assert weights_error<1e-6
bm=bmesh.new();bm.from_mesh(body.data);nonmanifold=sum(not e.is_manifold for e in bm.edges)
unvisited=set(bm.verts);components=0
while unvisited:
    components+=1;stack=[unvisited.pop()]
    while stack:
        v=stack.pop()
        for e in v.link_edges:
            q=e.other_vert(v)
            if q in unvisited:unvisited.remove(q);stack.append(q)
bm.free();assert components==1 and nonmanifold==0,(components,nonmanifold)
foot_objects={side:[o for o in meshes if all(len([g for g in v.groups if g.weight>1e-8])==1 and any(o.vertex_groups[g.group].name=='foot.'+side and g.weight>.99999 for g in v.groups) for v in o.data.vertices)] for side in ['R','L']}
foot_floor={side:min(p[2] for o in objects for p in adapter.coordinates(o)) for side,objects in foot_objects.items()}
animation=json.loads((project/'runs'/job['parameters']['animation_run']/'outputs/checks.json').read_text(encoding='utf-8'))
states={a['name']:{r['frame']:r for r in a['frames']} for a in animation['animation_actions']}
eye=next(o for o in meshes if 'floating_true_sphere' in o.name);cube=Matrix.Translation((-.03,0,2.22))@Matrix.Rotation(math.radians(24),4,'Z')
rest_eye=arm.data.bones['eye'].head_local.copy();eye_error=0.;eye_bound=0.;contact_error=0.;ankle_error=0.;samples=0;contact_samples=0
head_objects=[o for o in meshes if 'cube_' in o.name];hands=[o for o in meshes if '56dc332d-8393-499a-bc01-a3dc0bcc9604' in o.name];head_hand=0
assert head_objects and hands
def tree(objects):
    vs=[];ps=[]
    for o in objects:
        offset=len(vs);vs+=adapter.coordinates(o);ps += [tuple(i+offset for i in p.vertices) for p in o.data.polygons]
    return BVHTree.FromPolygons(vs,ps,all_triangles=False)
for action in sorted(bpy.data.actions,key=lambda a:a.name):
    if action.name=='00_Source_Pose':continue
    arm.animation_data.action=action;start,end=[int(x) for x in action.frame_range]
    for step in range(start*2,end*2+1):
        frame=step/2;scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update();samples+=1
        inverse=(arm.pose.bones['head'].matrix@arm.data.bones['head'].matrix_local.inverted()).inverted()
        local=[cube.inverted()@(inverse@Vector(p)) for p in adapter.coordinates(eye)]
        eye_bound=max(eye_bound,max(abs(x) for p in local for x in p));eye_error=max(eye_error,(inverse@arm.pose.bones['eye'].matrix.translation-rest_eye).length)
        head_hand=max(head_hand,len(tree(head_objects).overlap(tree(hands))))
        assert all(math.isfinite(x) for o in meshes for p in adapter.coordinates(o) for x in p)
        if frame.is_integer():
            state=states[action.name][int(frame)]
            for side in ['R','L']:
                if state['feet'][side]['stance']:
                    contact_samples+=1
                    ankle_error=max(ankle_error,(arm.pose.bones['foot.'+side].head-Vector(state['feet'][side]['target'])).length)
                    floor=min(p[2] for o in foot_objects[side] for p in adapter.coordinates(o))
                    contact_error=max(contact_error,abs(floor-foot_floor[side]))
assert eye_bound<=.180001 and eye_error<1e-6 and head_hand==0
assert contact_error<1e-5 and ankle_error<1e-5,(contact_error,ankle_error)
memory=None
if sys.platform=='win32':
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    counter=Counters();counter.cb=ctypes.sizeof(counter);kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(kernel.GetCurrentProcess()),ctypes.byref(counter),counter.cb):memory=counter.PeakWorkingSetSize
report=dict(success=True,run_id=job['run_id'],mode='delivery_preservation_and_motion_proof',mesh_count=len(meshes),part_ids=sorted({o.get('part_id') or o.get('mwb_part_id') for o in meshes}),bones=len(arm.data.bones),
    body_vertices=len(body.data.vertices),body_faces=len(body.data.polygons),body_components=components,body_nonmanifold_edges=nonmanifold,
    protected_meshes=protected,maximum_protected_rest_error=max(rest_errors.values()),original_neck_vertex_error=neck_error,body_original_materials_preserved=True,
    body_additional_empty_material_slots=len(body_materials)-len(source_materials),original_neck_material_samples=neck_material_samples,
    maximum_neck_surface_centroid_error=neck_surface_error,
    maximum_weight_sum_error=weights_error,maximum_influences=max_influences,half_frame_samples=samples,eye_bound=eye_bound,eye_center_error=eye_error,head_hand_triangle_pairs_maximum=head_hand,
    integer_stance_foot_samples=contact_samples,maximum_stance_floor_deviation=contact_error,maximum_stance_ankle_target_error=ankle_error,original_foot_floor_z=foot_floor,
    validation_peak_working_set_bytes=memory,ue_verified=False,formal_adoption=False)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='protected_meshes'}))
