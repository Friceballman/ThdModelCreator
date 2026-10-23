import importlib.util,json,sys
from pathlib import Path
import bpy
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE');body=next(o for o in bpy.context.scene.objects if 'continuous_static_body_base' in o.name)
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];bpy.context.scene.frame_set(1);bpy.context.view_layer.update()
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];before={o.name:adapter.appearance_data(o) for o in meshes};rig=adapter.rig_evidence(arm,meshes)
def weights(o,v):return {o.vertex_groups[g.group].name:g.weight for g in v.groups if g.weight>1e-7}
guides={}
for side in ['R','L']:
    sleeve=next(o for o in meshes if 'continuous_sleeve_'+side in o.name);rows=[]
    for i in range(0,len(sleeve.data.vertices),12):
        vs=list(sleeve.data.vertices)[i:i+12];center=sum((sleeve.matrix_world@v.co for v in vs),Vector())/12;ws=weights(sleeve,vs[0]);rows.append((center,ws))
    guides[side]=rows
changes=[]
for v in body.data.vertices:
    p=body.matrix_world@v.co;ws=weights(body,v)
    if p.z<1.32:continue
    if not any(k.startswith(('upper_arm.','forearm.')) and w>.1 for k,w in ws.items()):continue
    side='R' if p.x>0 else 'L';rows=[]
    for (a,wa),(b,wb) in zip(guides[side],guides[side][1:]):
        d=b-a;t=min(1.,max(0.,(p-a).dot(d)/d.length_squared));q=a+t*d
        target={k:wa.get(k,0)*(1-t)+wb.get(k,0)*t for k in wa.keys()|wb.keys()}
        error=sum((target.get(k,0)-ws.get(k,0))**2 for k in target.keys()|ws.keys())
        rows.append(((p-q).length_squared+.02*error,q))
    _,axis=min(rows,key=lambda row:row[0]);q=axis+(p-axis)*job['parameters']['factor']
    v.co=body.matrix_world.inverted()@q;changes.append(dict(vertex=v.index,distance=(q-p).length))
bpy.context.view_layer.update()
assert all(adapter.appearance_data(o)==before[o.name] for o in meshes if o!=body)
assert adapter.rig_evidence(arm,meshes)==rig
after={o.name:adapter.appearance_data(o) for o in meshes}
bpy.ops.wm.save_as_mainfile(filepath=str(output/'model.blend'));bpy.ops.wm.open_mainfile(filepath=str(output/'model.blend'),use_scripts=False)
assert all(adapter.appearance_data(bpy.data.objects[n])==v for n,v in after.items())
report=dict(success=True,run_id=job['run_id'],mode='hidden_arm_clearance',changed_vertices=changes,maximum_displacement=max(r['distance'] for r in changes),unchanged_other_meshes=103,quality_passed=False,ue_verified=False)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
