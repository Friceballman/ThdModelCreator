"""Read-only four-view motion rendering; no changes to the delivered model."""
import importlib.util,json,sys
from pathlib import Path
import bpy
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE')
meshes=[o for o in scene.objects if o.type=='MESH'];appearance={o.name:adapter.appearance_data(o) for o in meshes}
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];scene.frame_set(1);bpy.context.view_layer.update()
floor_z=min(p[2] for o in meshes for p in adapter.coordinates(o))
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,floor_z-.001));floor=bpy.context.object
material=bpy.data.materials.new('Preview_Ground');material.diffuse_color=(.18,.19,.21,1);floor.data.materials.append(material)
camera_data=bpy.data.cameras.new('PreviewCamera');camera=bpy.data.objects.new('PreviewCamera',camera_data);scene.collection.objects.link(camera);scene.camera=camera
camera_data.type='ORTHO';camera_data.ortho_scale=3.35;camera_data.clip_end=200
scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.color_type='MATERIAL';scene.display.shading.light='STUDIO'
scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
scene.display.shading.background_type='VIEWPORT';scene.display.shading.background_color=(.2,.2,.2)
scene.render.resolution_x=scene.render.resolution_y=512;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
center=Vector((0,.25,1.42));directions={'front':(0,-1,0),'side':(1,0,0),'back':(0,1,0),'oblique':(1,-1,.32)}
clips=[]
for action in sorted(bpy.data.actions,key=lambda a:a.name):
    if action.name=='00_Source_Pose':continue
    arm.animation_data.action=action;start,end=[int(x) for x in action.frame_range]
    frames=list(range(start,end+1,2));directory=output/action.name;directory.mkdir()
    for frame in frames:
        scene.frame_set(frame);bpy.context.view_layer.update()
        for view,direction in directions.items():
            camera.location=center+Vector(direction).normalized()*10
            camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
            scene.render.filepath=str(directory/f'f{frame:03}-{view}.png');bpy.ops.render.render(write_still=True)
    clips.append(dict(name=action.name,frames=frames,source_fps=30,preview_fps=15,views=list(directions)))
assert all(adapter.appearance_data(o)==appearance[o.name] for o in meshes)
report=dict(success=True,run_id=job['run_id'],mode='four_view_animation_previews',model_unchanged=True,floor_z=floor_z,clips=clips)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))
