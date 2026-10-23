"""Read-only raster audit of hidden body visibility at every authored frame."""
import importlib.util,json,sys,math
from pathlib import Path
import bpy,numpy as np
from mathutils import Matrix,Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE');meshes=[o for o in scene.objects if o.type=='MESH']
body=next(o for o in meshes if 'continuous_static_body_base' in o.name)
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];scene.frame_set(1);bpy.context.view_layer.update()
rest=adapter.coordinates(body)
red=bpy.data.materials.new('RasterAudit_Internal_Red');red.diffuse_color=(1,0,0,1)
gray=bpy.data.materials.new('RasterAudit_Other_Gray');gray.diffuse_color=(.35,.35,.35,1)
allowed=[]
for o in meshes:
    o.data.materials.clear();o.data.materials.append(gray if o!=body else red)
    if o==body:o.data.materials.append(gray)
    for face in o.data.polygons:
        face.material_index=0
        if o==body:
            center=sum((Vector(rest[i]) for i in face.vertices),Vector())/len(face.vertices)
            if center.z>=1.925 and abs(center.x)<.10 and -.065<center.y<.085:
                face.material_index=1;allowed.append(face.index)
camera_data=bpy.data.cameras.new('RasterAuditCamera');camera=bpy.data.objects.new('RasterAuditCamera',camera_data);scene.collection.objects.link(camera);scene.camera=camera
camera_data.type='ORTHO';camera_data.ortho_scale=4.;camera_data.clip_end=100
scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.color_type='MATERIAL';scene.display.shading.light='FLAT'
scene.display.shading.show_shadows=False;scene.display.shading.show_cavity=False;scene.display.shading.show_specular_highlight=False
scene.display.shading.background_type='VIEWPORT';scene.display.shading.background_color=(.2,.2,.2)
scene.render.resolution_x=scene.render.resolution_y=768;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
scene.render.film_transparent=False
center=Vector((0,.25,1.42));directions={'front':(0,-1,0),'side':(1,0,0),'back':(0,1,0),'oblique':(1,-1,.32)}
rows=[]
def capture(name,frame):
    row=dict(name=name,frame=frame,pixels={},images={})
    directory=output/name;directory.mkdir(exist_ok=True)
    for view,direction in directions.items():
        camera.location=center+Vector(direction).normalized()*10;camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        path=directory/f'f{frame:05.1f}-{view}.png';scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        image=bpy.data.images.load(str(path),check_existing=False)
        pixels=np.empty(len(image.pixels),dtype=np.float32);image.pixels.foreach_get(pixels);pixels=pixels.reshape(-1,4)
        visible=(pixels[:,0]>.15)&(pixels[:,0]>pixels[:,1]*1.3+.03)&(pixels[:,0]>pixels[:,2]*1.3+.03)
        row['pixels'][view]=int(visible.sum());row['images'][view]=path.relative_to(output).as_posix();bpy.data.images.remove(image)
    rows.append(row)
capture('00_Source_Pose',1)
for action in sorted(bpy.data.actions,key=lambda a:a.name):
    if action.name=='00_Source_Pose':continue
    arm.animation_data.action=action;start,end=[int(x) for x in action.frame_range]
    frames=[i/2 for i in range(start*2,end*2+1)] if job['parameters'].get('half_frames') else range(start,end+1)
    for frame in frames:
        scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update();capture(action.name,frame)
arm.animation_data.action=None
definition=json.loads((Path(job['case'])/'trial-03-definition.json').read_text(encoding='utf-8'))
for test in definition['poses']:
    for i in range(test['samples']):
        t=i/(test['samples']-1)
        for bone in arm.pose.bones:
            bone.matrix_basis=Matrix.Identity(4);bone.rotation_mode='XYZ';bone.rotation_euler=[math.radians(x)*t for x in test['rotations'].get(bone.name,[0,0,0])]
        bpy.context.view_layer.update();capture('proxy-'+test['name'],i)
failures=[r for r in rows if any(r['pixels'].values())]
report=dict(success=True,run_id=job['run_id'],mode='body_visibility_raster_audit',frames=len(rows),images=len(rows)*4,
    segmentation_exposure_passed=not failures,maximum_red_pixels=max(max(r['pixels'].values()) for r in rows),failures=failures,
    allowed_original_neck_faces=allowed,neck_policy='Only original body faces with rest centroid z>=1.925, abs(x)<.10, -.065<y<.085 are permitted visible neck; independent ray audit uses surface point coordinates instead',
    threshold='linear image R>.15, R>1.3*G+.03, R>1.3*B+.03; 768px, flat material shading, four orthographic views',samples=rows,
    limitations=['finite pixel resolution and four views are not a continuous all-angle intersection proof','UE not verified'])
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(frames=len(rows),images=len(rows)*4,failures=len(failures),maximum_red_pixels=report['maximum_red_pixels'])))
