"""Export one skeleton and separate baked clips; verify Blender round trips."""
import importlib.util,json,sys,struct
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE');meshes=[o for o in scene.objects if o.type=='MESH']
appearance={o.name:adapter.appearance_data(o) for o in meshes};rig=adapter.rig_evidence(arm,meshes)
parents={b.name:b.parent.name if b.parent else None for b in arm.data.bones}
for o in meshes:o['mwb_source_object_name']=o.name
actions=sorted([a for a in bpy.data.actions if a.name!='00_Source_Pose'],key=lambda a:a.name)
reference={};clip_meta=[]
for action in actions:
    arm.animation_data.action=action;start,end=[int(x) for x in action.frame_range]
    samples=sorted({start,start+(end-start)//4,(start+end)//2,start+3*(end-start)//4,end})
    frames={}
    for frame in range(start,end+1):
        scene.frame_set(frame);bpy.context.view_layer.update()
        frames[frame]=dict(heads={b.name:list(arm.matrix_world@b.head) for b in arm.pose.bones})
        if frame in samples:frames[frame]['geometry']={o.name:adapter.coordinates(o) for o in meshes}
    reference[action.name]=frames;clip_meta.append(dict(name=action.name,start=start,end=end,frames=end-start+1,samples=samples))
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];scene.frame_set(1);bpy.context.view_layer.update()
rest_geometry={o.name:adapter.coordinates(o) for o in meshes}
scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1.;scene.render.fps=30
settings=dict(check_existing=False,use_selection=True,global_scale=1.,apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',
    axis_forward='-Y',axis_up='Z',use_space_transform=True,bake_space_transform=False,
    use_mesh_modifiers=True,mesh_smooth_type='FACE',use_triangles=True,add_leaf_bones=False,
    primary_bone_axis='Y',secondary_bone_axis='X',use_armature_deform_only=True,armature_nodetype='NULL',
    use_custom_props=True,path_mode='AUTO',bake_anim_use_all_bones=True,bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False,bake_anim_force_startend_keying=True,bake_anim_step=1.,bake_anim_simplify_factor=0.)
bpy.ops.object.select_all(action='DESELECT')
for o in meshes+[arm]:o.select_set(True)
bpy.context.view_layer.objects.active=arm
fbx=output/'fbx';fbx.mkdir()
bpy.ops.export_scene.fbx(filepath=str(fbx/'SK_ClockCharacter.fbx'),object_types={'ARMATURE','MESH'},bake_anim=False,**settings)
# Include the same skinned geometry in each clip so its FBX bind pose remains
# explicit. Bone-only exports imported their first animated pose as rest.
for action,meta in zip(actions,clip_meta):
    arm.animation_data.action=action;scene.frame_start=meta['start'];scene.frame_end=meta['end'];scene.frame_set(meta['start'])
    bpy.ops.export_scene.fbx(filepath=str(fbx/('A_'+meta['name']+'.fbx')),object_types={'ARMATURE','MESH'},bake_anim=True,**settings)
# Make the editable file immediately playable; retain the original pose action.
arm.animation_data.action=bpy.data.actions['01_Idle'];scene.frame_start=1;scene.frame_end=61;scene.frame_set(1)
arm.show_in_front=False
profile=adapter.frame_profile(meshes)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            space=area.spaces.active;space.shading.type='SOLID';space.shading.color_type='MATERIAL'
            space.region_3d.view_location=Vector(profile['center']);space.region_3d.view_distance=profile['ortho_scale']*.9
            space.region_3d.view_rotation=Vector((1,-2,.6)).to_track_quat('Z','Y');space.region_3d.view_perspective='ORTHO'
        elif area.type=='DOPESHEET_EDITOR':
            area.ui_type='DOPESHEET';area.spaces.active.ui_mode='ACTION'
assert all(adapter.appearance_data(o)==appearance[o.name] for o in meshes)
assert adapter.rig_evidence(arm,meshes)==rig
bpy.ops.wm.save_as_mainfile(filepath=str(output/'model.blend'))

def nearest_error(actual,expected):
    tree=KDTree(len(expected))
    for i,p in enumerate(expected):tree.insert(Vector(p),i)
    tree.balance()
    return max(tree.find(Vector(p))[2] for p in actual)
def import_fbx(path):
    bpy.ops.import_scene.fbx(filepath=str(path),use_custom_props=True,automatic_bone_orientation=False,ignore_leaf_bones=False)
def hierarchy(a):return {b.name:b.parent.name if b.parent else None for b in a.data.bones}

bpy.ops.wm.read_factory_settings(use_empty=True)
import_fbx(fbx/'SK_ClockCharacter.fbx')
mesh_arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
assert hierarchy(mesh_arm)==parents,(hierarchy(mesh_arm),parents)
imported={o.get('mwb_source_object_name',o.name):o for o in bpy.context.scene.objects if o.type=='MESH'}
assert set(imported)==set(rest_geometry),(len(imported),len(rest_geometry))
rest_errors={name:nearest_error(adapter.coordinates(imported[name]),points) for name,points in rest_geometry.items()}
assert max(rest_errors.values())<2e-5,max(rest_errors.values())
weight_max_error=0.
for name,obj in imported.items():
    source_points=rest_geometry[name];tree=KDTree(len(source_points))
    for i,p in enumerate(source_points):tree.insert(Vector(p),i)
    tree.balance()
    for v,p in zip(obj.data.vertices,adapter.coordinates(obj)):
        index=tree.find(Vector(p))[1];expected=rig['weights'][name][index]
        actual={obj.vertex_groups[g.group].name:g.weight for g in v.groups if g.weight>1e-7}
        weight_max_error=max(weight_max_error,max(abs(actual.get(k,0)-expected.get(k,0)) for k in actual.keys()|expected.keys()))
assert weight_max_error<2e-5,weight_max_error
clip_results=[]
for meta in clip_meta:
    previous=set(bpy.context.scene.objects);import_fbx(fbx/('A_'+meta['name']+'.fbx'))
    added=set(bpy.context.scene.objects)-previous
    clip_arm=next(o for o in added if o.type=='ARMATURE')
    assert hierarchy(clip_arm)==parents
    action=clip_arm.animation_data.action;assert action is not None
    start,end=list(action.frame_range);assert abs((end-start)-(meta['end']-meta['start']))<1e-3,(meta,start,end)
    if mesh_arm.animation_data is None:mesh_arm.animation_data_create()
    mesh_arm.animation_data.action=action
    mesh_arm.animation_data.action_slot=clip_arm.animation_data.action_slot
    for b in mesh_arm.pose.bones:b.rotation_mode=clip_arm.pose.bones[b.name].rotation_mode
    assert max((b.head_local-clip_arm.data.bones[b.name].head_local).length for b in mesh_arm.data.bones)<2e-5
    max_head=0.;max_mesh=0.
    for source_frame,expected in reference[meta['name']].items():
        frame=start+source_frame-meta['start'];bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
        for name,head in expected['heads'].items():
            max_head=max(max_head,(mesh_arm.matrix_world@mesh_arm.pose.bones[name].head-Vector(head)).length)
        if 'geometry' in expected:
            for name,points in expected['geometry'].items():
                max_mesh=max(max_mesh,nearest_error(adapter.coordinates(imported[name]),points))
    row=dict(name=meta['name'],imported_start=start,imported_end=end,maximum_bone_head_error=max_head,maximum_sampled_surface_error=max_mesh,
             bone_frames_checked=meta['frames'],geometry_frames_checked=meta['samples'])
    clip_results.append(row);print('ROUNDTRIP',json.dumps(row),flush=True)
    assert max_head<5e-5 and max_mesh<5e-5,row
    for obj in added:bpy.data.objects.remove(obj,do_unlink=True)
versions={p.name:struct.unpack('<I',p.read_bytes()[23:27])[0] for p in sorted(fbx.glob('*.fbx'))}
bpy.ops.wm.open_mainfile(filepath=str(output/'model.blend'),use_scripts=False)
saved_arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
saved_maximum_error=0.
for meta in clip_meta:
    saved_arm.animation_data.action=bpy.data.actions[meta['name']]
    for frame,expected in reference[meta['name']].items():
        bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
        for name,head in expected['heads'].items():saved_maximum_error=max(saved_maximum_error,(saved_arm.matrix_world@saved_arm.pose.bones[name].head-Vector(head)).length)
        if 'geometry' in expected:
            for name,points in expected['geometry'].items():saved_maximum_error=max(saved_maximum_error,nearest_error(adapter.coordinates(bpy.data.objects[name]),points))
assert saved_maximum_error<1e-6,saved_maximum_error
report=dict(success=True,run_id=job['run_id'],mode='skeletal_fbx_and_five_baked_clips',blender_version=bpy.app.version_string,
    ue_version=None,ue_verified=False,quality_passed=False,export_settings=settings,fbx_binary_versions=versions,
    saved_animation_maximum_error=saved_maximum_error,
    animation_fbx_contains_reference_mesh=True,
    roundtrip=dict(mesh_count=len(imported),bones=len(parents),maximum_rest_surface_error=max(rest_errors.values()),maximum_weight_error=weight_max_error,clips=clip_results),
    material_limitations='FBX preserves assigned material identities/basic values; Unreal material appearance is not verified',
    coordinate_note='Blender metres, -Y forward / Z up recorded; verify UE import orientation and centimetre size in target UE version')
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report))
