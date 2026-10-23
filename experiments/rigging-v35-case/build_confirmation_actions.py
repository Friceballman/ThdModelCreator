"""Author real baked FK actions from analytic limb targets, without addons."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Matrix,Vector,Euler,Quaternion

job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('rig_adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
appearance_before={o.name:adapter.appearance_data(o) for o in meshes}
rig_before=adapter.rig_evidence(arm,meshes)
arm.show_in_front=True;arm.data.display_type='OCTAHEDRAL'
arm['mwb_animation_note']='確認用に作成したin-place歩行・走行、待機、被弾・吹き飛び。UE実機未確認。00_Source_Poseで元ポーズへ戻す。'
scene=bpy.context.scene;scene.render.fps=30
rest={b.name:b.matrix_local.copy() for b in arm.data.bones}
actions=[];reports=[]
profile=adapter.frame_profile(meshes)

def reset():
    for b in arm.pose.bones:
        b.rotation_mode='QUATERNION';b.matrix_basis=Matrix.Identity(4)
    bpy.context.view_layer.update()

def local_rotation(name,angles):
    arm.pose.bones[name].rotation_quaternion=Euler(tuple(math.radians(x) for x in angles),'XYZ').to_quaternion()

def translation(name,world_delta):
    arm.pose.bones[name].location=rest[name].to_3x3().inverted()@Vector(world_delta)

def direction(name,vector):
    b=arm.pose.bones[name];head=b.head.copy();rest_direction=rest[name].to_3x3()@Vector((0,1,0))
    rotation=rest_direction.rotation_difference(Vector(vector).normalized())@rest[name].to_quaternion()
    b.matrix=Matrix.Translation(head)@rotation.to_matrix().to_4x4()
    bpy.context.view_layer.update()

def solve_limb(upper,lower,target,pole):
    head=arm.pose.bones[upper].head.copy();target=Vector(target);toward=target-head
    a=arm.data.bones[upper].length;b=arm.data.bones[lower].length
    length=min(a+b-.002,max(abs(a-b)+.002,toward.length));axis=toward.normalized()
    along=(a*a-b*b+length*length)/(2*length);height=math.sqrt(max(0.,a*a-along*along))
    bend=Vector(pole)-axis*Vector(pole).dot(axis)
    bend.normalize();joint=head+axis*along+bend*height
    ankle=head+axis*length
    rest_upper=arm.data.bones[upper].tail_local-arm.data.bones[upper].head_local
    rest_lower=arm.data.bones[lower].tail_local-arm.data.bones[lower].head_local
    rest_normal=rest_upper.cross(rest_lower).normalized()
    target_normal=(joint-head).cross(ankle-joint).normalized()
    def orient(name,source_y,target_y):
        source_y=source_y.normalized();target_y=target_y.normalized()
        source_basis=Matrix((rest_normal.cross(source_y),source_y,rest_normal)).transposed()
        target_basis=Matrix((target_normal.cross(target_y),target_y,target_normal)).transposed()
        rotation=target_basis@source_basis.inverted()@rest[name].to_3x3()
        bone=arm.pose.bones[name]
        bone.matrix=Matrix.Translation(bone.head.copy())@rotation.to_4x4()
        bpy.context.view_layer.update()
    orient(upper,rest_upper,joint-head);orient(lower,rest_lower,ankle-joint)
    return dict(target=list(target),achieved=list(arm.pose.bones[lower].tail),target_error=(arm.pose.bones[lower].tail-target).length)

def foot_path(phase,stride,lift,stance):
    phase%=1.
    if phase<stance:
        return -stride+2*stride*phase/stance,0.,True
    t=(phase-stance)/(1-stance)
    return stride*math.cos(math.pi*t),lift*math.sin(math.pi*t),False

def apply_pose(kind,t):
    reset();root=arm.pose.bones['root'];pelvis=arm.pose.bones['pelvis']
    root.location=(0,0,0);recoil=0.;flight=0.;root_y=0.;root_z=0.
    if kind=='walk':
        phase=t*2;cycle=2*math.pi*phase;drop=-.040+.007*math.cos(2*cycle);lean=2.
        stride=.20;lift=.10;stance=.60
    elif kind=='run':
        phase=t*2;cycle=2*math.pi*phase;drop=-.080+.022*math.cos(2*cycle);lean=8.
        stride=.30;lift=.23;stance=.40
    else:
        phase=t;cycle=2*math.pi*t;drop=-.018;lean=0.;stride=0.;lift=0.;stance=1.
        if kind=='idle':
            drop+=.003*math.sin(cycle);lean=1.*math.sin(cycle)
        elif kind=='hit':
            recoil=math.sin(math.pi*min(1.,t/.8))*math.exp(-1.4*t)
            lean=-22*recoil;drop-=.015*recoil
        elif kind=='knockback':
            flight=math.sin(math.pi*t)**1.2;root_y=.9*(t*t*(3-2*t));root_z=.40*flight
            recoil=math.sin(math.pi*t);lean=-28*recoil;drop-=.10*max(0.,math.sin(math.pi*min(1.,max(0.,(t-.68)/.32))))
    translation('root',(0,root_y,root_z));translation('pelvis',(0,0,drop))
    local_rotation('spine_01',(lean*.55,0,0));local_rotation('spine_02',(lean*.45,0,0))
    local_rotation('head',(-lean*.2,5*math.sin(cycle) if kind=='idle' else 0,0))
    local_rotation('eye',(3*math.sin(cycle),0,7*math.sin(cycle)))
    bpy.context.view_layer.update()
    legs={};feet={}
    for side,offset,x in [('R',0.,.18),('L',.5,-.15)]:
        if kind in ('walk','run'):
            y,z,on_ground=foot_path(phase+offset,stride,lift,stance)
        else:
            y,z,on_ground=0.,.12*flight,flight<1e-6
        target=Vector((x,y+root_y,.21+z+root_z))
        legs[side]=solve_limb('thigh.'+side,'calf.'+side,target,(0,-1,0))
        direction('foot.'+side,rest['foot.'+side].to_3x3()@Vector((0,1,0)))
        feet[side]=dict(stance=on_ground,target=list(target),height=z+root_z)
    for side,sign,offset in [('R',1,0.),('L',-1,.5)]:
        shoulder=arm.pose.bones['upper_arm.'+side].head.copy()
        swing=math.sin(2*math.pi*(phase+offset)) if kind in ('walk','run') else .03*math.sin(cycle)
        reach=.13 if kind=='walk' else .18 if kind=='run' else .015
        target=shoulder+Vector((sign*.125,-.045-reach*swing,-(.47 if side=='R' else .54)+.12*flight))
        if kind=='hit':target.y-=.12*recoil
        if kind=='knockback':target.y+=.12*flight;target.z+=.10*flight
        solve_limb('upper_arm.'+side,'forearm.'+side,target,(0,1,0))
        # Preserve the authored wrist angle relative to the forearm so that
        # gloves continue to cover the sleeve opening during these previews.
    bpy.context.view_layer.update()
    return dict(feet=feet,limb_targets=legs,root=[0,root_y,root_z])

previous_quaternions={}
def key_all(frame):
    for b in arm.pose.bones:
        if b.name in previous_quaternions and b.rotation_quaternion.dot(previous_quaternions[b.name])<0:
            q=b.rotation_quaternion.copy();q.negate();b.rotation_quaternion=q
        previous_quaternions[b.name]=b.rotation_quaternion.copy()
        for field in ('location','rotation_quaternion','scale'):
            b.keyframe_insert(data_path=field,frame=frame,group=b.name)

arm.animation_data_create()
arm.animation_data.action=None
for action in list(bpy.data.actions):bpy.data.actions.remove(action)
source=bpy.data.actions.new('00_Source_Pose');source.use_fake_user=True;arm.animation_data.action=source
reset();key_all(1);actions.append(source)
for name,kind,frames in [('01_Idle','idle',61),('02_Walk','walk',61),('03_Run','run',49),('04_Hit_Recoil','hit',45),('05_Knockback','knockback',61)]:
    action=bpy.data.actions.new(name);action.use_fake_user=True;arm.animation_data.action=action
    previous_quaternions.clear()
    action['mwb_preview_kind']=kind;action['mwb_fps']=30;action['mwb_in_place']=kind!='knockback'
    action['mwb_scope']='confirmation animation; not a final game-motion asset; UE not verified'
    frames_report=[]
    for frame in range(1,frames+1):
        scene.frame_set(frame);state=apply_pose(kind,(frame-1)/(frames-1));key_all(frame)
        frames_report.append(dict(frame=frame,**state))
    actions.append(action)
    reports.append(dict(name=name,kind=kind,frame_start=1,frame_end=frames,frames=frames_report))
    for frame in sorted({1,1+(frames-1)//4,1+(frames-1)//2,1+3*(frames-1)//4,frames}):
        scene.frame_set(frame);bpy.context.view_layer.update()
        adapter.render_views(output,f'{name}-f{frame:03}',profile)

arm.animation_data.action=source;scene.frame_set(1);reset()
scene.frame_start=1;scene.frame_end=61
bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);bpy.context.view_layer.objects.active=arm
assert all(adapter.appearance_data(obj)==appearance_before[obj.name] for obj in meshes)
assert adapter.rig_evidence(arm,meshes)==rig_before
model=output/'model.blend';bpy.ops.wm.save_as_mainfile(filepath=str(model))
bpy.ops.wm.open_mainfile(filepath=str(model),use_scripts=False);bpy.context.view_layer.update()
assert all(adapter.appearance_data(bpy.data.objects[name])==value for name,value in appearance_before.items())
assert all(bpy.data.actions.get(a['name']) is not None for a in reports)
report=dict(success=True,run_id=job['run_id'],animation_actions=reports,source_pose_action='00_Source_Pose',fps=30,
            mesh_materials_and_weights_unchanged=True,quality_passed=False,ue_verified=False,
            in_place_speed_hints_m_s=dict(walk=.40/.60,run=.60/(.40*.8)))
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(actions=[r['name'] for r in reports],frames=sum(len(r['frames']) for r in reports))))
