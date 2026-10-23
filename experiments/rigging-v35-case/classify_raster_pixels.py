"""Trace red raster pixels back to rest-space surface points, preserving raw evidence."""
import importlib.util,json,sys,math,hashlib
from pathlib import Path
import bpy,numpy as np
from mathutils import Matrix,Vector
from mathutils.geometry import barycentric_transform
from mathutils.bvhtree import BVHTree
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
project=Path(job['case']).parents[1];producer=project/'runs'/job['parameters']['raster_run']
plan=json.loads((producer/'plan.json').read_text(encoding='utf-8'))
assert hashlib.sha256(Path(job['source']).read_bytes()).hexdigest()==plan['source_hash']
evidence=producer/'outputs';raw=json.loads((evidence/'checks.json').read_text(encoding='utf-8'))
context=json.loads((Path(job['case'])/f"iteration-{plan['stage']}-context.json").read_text(encoding='utf-8'))
hashes={r['file']:r['sha256'] for r in context['files']}
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE');body=next(o for o in scene.objects if 'continuous_static_body_base' in o.name)
arm.animation_data.action=bpy.data.actions['00_Source_Pose'];scene.frame_set(1);bpy.context.view_layer.update()
rest=[Vector(p) for p in adapter.coordinates(body)]
tests={r['name']:r for r in json.loads((Path(job['case'])/'trial-03-definition.json').read_text(encoding='utf-8'))['poses']}
center=Vector((0,.25,1.42));directions={'front':(0,-1,0),'side':(1,0,0),'back':(0,1,0),'oblique':(1,-1,.32)}
rows=[];outliers=[];all_points=[]
for row in raw['samples']:
    if row['name'].startswith('proxy-'):
        arm.animation_data.action=None;test=tests[row['name'][6:]];fraction=row['frame']/(test['samples']-1)
        for bone in arm.pose.bones:
            bone.matrix_basis=Matrix.Identity(4);bone.rotation_mode='XYZ';bone.rotation_euler=[math.radians(x)*fraction for x in test['rotations'].get(bone.name,[0,0,0])]
    else:
        for bone in arm.pose.bones:bone.rotation_mode='QUATERNION'
        arm.animation_data.action=bpy.data.actions[row['name']];scene.frame_set(int(row['frame']),subframe=row['frame']-int(row['frame']))
    bpy.context.view_layer.update()
    evaluated=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh();mesh.calc_loop_triangles()
    points=[evaluated.matrix_world@v.co for v in mesh.vertices];triangles=[tuple(t.vertices) for t in mesh.loop_triangles]
    tree=BVHTree.FromPolygons(points,triangles,all_triangles=True);evaluated.to_mesh_clear()
    result=dict(name=row['name'],frame=row['frame'],views={})
    for view,path in row['images'].items():
        source=evidence/path;assert hashlib.sha256(source.read_bytes()).hexdigest()==hashes[source.relative_to(project).as_posix()]
        image=bpy.data.images.load(str(source),check_existing=False);width,height=image.size
        values=np.empty(len(image.pixels),dtype=np.float32);image.pixels.foreach_get(values);values=values.reshape(-1,4)
        red=(values[:,0]>.15)&(values[:,0]>values[:,1]*1.3+.03)&(values[:,0]>values[:,2]*1.3+.03)
        indices=np.flatnonzero(red);bpy.data.images.remove(image)
        camera=center+Vector(directions[view]).normalized()*10;rotation=(center-camera).to_track_quat('-Z','Y')
        right=rotation@Vector((1,0,0));up=rotation@Vector((0,1,0));forward=rotation@Vector((0,0,-1))
        counts=dict(raw_red=len(indices),permitted_neck=0,permitted_neck_antialias=0,internal_body=0,unresolved=0)
        for pixel in indices:
            x=int(pixel%width);y=int(pixel//width);hits=[]
            offsets=[(0,0),(-.499,-.499),(.499,-.499),(-.499,.499),(.499,.499),(-.499,0),(.499,0),(0,-.499),(0,.499)]
            antialias=False
            for dx,dy in offsets:
                origin=camera+right*((x+.5+dx)/width-.5)*4+up*((y+.5+dy)/height-.5)*4
                hit,normal,index,distance=tree.ray_cast(origin,forward,30)
                if index is None:continue
                ids=triangles[index];p=barycentric_transform(hit,*(points[i] for i in ids),*(rest[i] for i in ids));hits.append(p)
            if not hits:
                antialias=True
                for dx,dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                    origin=camera+right*((x+.5+dx)/width-.5)*4+up*((y+.5+dy)/height-.5)*4
                    hit,normal,index,distance=tree.ray_cast(origin,forward,30)
                    if index is not None:
                        ids=triangles[index];hits.append(barycentric_transform(hit,*(points[i] for i in ids),*(rest[i] for i in ids)))
            if not hits:category='unresolved'
            elif all(p.z>=1.925 and abs(p.x)<=.115 and -.065<=p.y<=.085 for p in hits):category='permitted_neck_antialias' if antialias else 'permitted_neck'
            else:category='internal_body'
            counts[category]+=1
            all_points.extend(list(p) for p in hits)
            if not category.startswith('permitted_neck'):outliers.append(dict(name=row['name'],frame=row['frame'],view=view,pixel=[x,y],category=category,rest_points=[list(p) for p in hits]))
        result['views'][view]=counts
    rows.append(result)
summary={k:sum(v[k] for r in rows for v in r['views'].values()) for k in ['raw_red','permitted_neck','permitted_neck_antialias','internal_body','unresolved']}
report=dict(success=True,run_id=job['run_id'],mode='rest_space_pixel_classification',raster_run=job['parameters']['raster_run'],
    frames=len(rows),images=len(rows)*4,classified_exposure_passed=summary['internal_body']==0 and summary['unresolved']==0,
    summary=summary,source_neck_bounds=[[-.101548,-.032096,1.940089],[.101125,.065495,2.046456]],
    neck_policy='rest z>=1.925, abs(x)<=.115, -.065<=y<=.085, including the original neck base; all nine pixel-coverage body intersections must satisfy it; if no coverage hit, one-pixel-neighbour neck-only hits may identify antialias filtering, counted separately',
    red_surface_bounds=[[min(p[i] for p in all_points) for i in range(3)],[max(p[i] for p in all_points) for i in range(3)]] if all_points else None,
    outliers=outliers,samples=rows,ue_verified=False)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(summary=summary,outliers=outliers[:10])))
