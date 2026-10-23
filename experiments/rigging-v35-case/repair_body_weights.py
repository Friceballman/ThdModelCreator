import importlib.util,json,sys,math
from pathlib import Path
import bpy
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE');body=next(o for o in bpy.context.scene.objects if 'continuous_static_body_base' in o.name)
if arm.animation_data:arm.animation_data.action=bpy.data.actions.get('00_Source_Pose')
bpy.context.scene.frame_set(1);bpy.context.view_layer.update()
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];before={o.name:adapter.appearance_data(o) for o in meshes}
def ramp(x,a,b):return min(1.,max(0.,(x-a)/(b-a)))
def set_weights(v,ws):
    for g in body.vertex_groups:g.remove([v.index])
    for k,w in ws.items():
        if w>1e-8:body.vertex_groups[k].add([v.index],w,'REPLACE')
changes=[]
for v in body.data.vertices:
    p=body.matrix_world@v.co;ws={body.vertex_groups[g.group].name:g.weight for g in v.groups};reason=[]
    if p.z<1.32 and any(k.startswith(('upper_arm','forearm','hand','spine','neck','head','eye')) and w>1e-6 for k,w in ws.items()):
        side='R' if p.x>0 else 'L';t=1-ramp(p.z,.66,.86)
        set_weights(v,{'thigh.'+side:1-t,'calf.'+side:t});reason.append('invalid_arm_in_lower_body')
    q=p.copy()
    if 1.365-1e-5<=p.z<1.51 and abs(p.x)<.15:
        t=1-ramp(p.z,1.40,1.51);q.y=.02+(p.y-.02)*(1-.60*t)
        reason.append('hidden_pelvis_depth')
    if reason:
        v.co=body.matrix_world.inverted()@q;changes.append(dict(vertex=v.index,reasons=reason,before=list(p),after=list(q),old_weights=ws))
bpy.context.view_layer.update()
assert all(adapter.appearance_data(o)==before[o.name] for o in meshes if o!=body)
for v in body.data.vertices:
    p=body.matrix_world@v.co
    if p.z<1.32:assert all(not body.vertex_groups[g.group].name.startswith(('upper_arm','forearm','hand','spine','neck','head','eye')) for g in v.groups if g.weight>1e-6)
after={o.name:adapter.appearance_data(o) for o in meshes}
bpy.ops.wm.save_as_mainfile(filepath=str(output/'model.blend'));bpy.ops.wm.open_mainfile(filepath=str(output/'model.blend'),use_scripts=False)
assert all(adapter.appearance_data(bpy.data.objects[n])==v for n,v in after.items())
report=dict(success=True,run_id=job['run_id'],mode='invalid_body_weights_and_pelvis_depth',changes=changes,unchanged_other_meshes=103,quality_passed=False,ue_verified=False)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(changes=len(changes))))
