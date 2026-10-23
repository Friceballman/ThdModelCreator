"""Replace only hidden limb topology; preserve the original neck and all clothing."""
import importlib.util,json,sys,math
from pathlib import Path
import bpy,bmesh
from mathutils import Matrix,Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'));output=Path(job['output'])
spec=importlib.util.spec_from_file_location('adapter',job['adapter']);adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
bpy.ops.wm.open_mainfile(filepath=job['source'],use_scripts=False)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
for bone in arm.pose.bones:bone.matrix_basis=Matrix.Identity(4)
bpy.context.view_layer.update()
body=next(o for o in meshes if 'continuous_static_body_base' in o.name)
before={o.name:adapter.appearance_data(o) for o in meshes}
group_names=[g.name for g in body.vertex_groups]
def weights(o,v):return {o.vertex_groups[g.group].name:g.weight for g in v.groups if g.weight>1e-8}
def coordkey(p):return tuple(round(x,6) for x in p)
known={coordkey(body.matrix_world@v.co):weights(body,v) for v in body.data.vertices}
neck_original=[body.matrix_world@v.co for v in body.data.vertices if abs((body.matrix_world@v.co).x)<.10 and (body.matrix_world@v.co).z>=1.925]
def rings(o,size):
    rows=[]
    for i in range(0,len(o.data.vertices),size):
        vs=list(o.data.vertices)[i:i+size];points=[o.matrix_world@v.co for v in vs]
        center=sum(points,Vector())/len(vs);ws={}
        for v in vs:
            for k,w in weights(o,v).items():ws[k]=ws.get(k,0)+w/len(vs)
        rows.append((center,points,ws))
    return rows
guides={}
for side,suffix in [('R','_1'),('L','_-1')]:
    guides['arm.'+side]=rings(next(o for o in meshes if 'continuous_sleeve_'+side in o.name),12)
    guides['leg.'+side]=rings(next(o for o in meshes if 'shaped_trouser_leg' in o.name and o.name.endswith(suffix)),10)
    assert all(a[0].z>b[0].z for a,b in zip(guides['leg.'+side],guides['leg.'+side][1:]))
# Exact local cuts remove the fused posed limbs while retaining the neck/trunk.
bm=bmesh.new();bm.from_mesh(body.data)
for normal,position in [(Vector((1,0,0)),Vector((.145,0,0))),(Vector((-1,0,0)),Vector((-.145,0,0))),(Vector((0,0,-1)),Vector((0,0,1.365)))]:
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,
                          plane_co=body.matrix_world.inverted()@position,
                          plane_no=body.matrix_world.to_3x3().transposed()@normal,
                          clear_outer=True,clear_inner=False)
boundary=[e for e in bm.edges if e.is_boundary]
if boundary:bmesh.ops.holes_fill(bm,edges=boundary,sides=0)
bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(body.data);bm.free();body.data.update()
bm=bmesh.new();bm.from_mesh(body.data)
print('TRUNK',len(bm.verts),len(bm.faces),'BOUNDARY',sum(e.is_boundary for e in bm.edges),'NONMANIFOLD',sum(not e.is_manifold for e in bm.edges),flush=True);bm.free()
def mix(a,b,t):return {k:a.get(k,0)*(1-t)+b.get(k,0)*t for k in a.keys()|b.keys() if a.get(k,0)*(1-t)+b.get(k,0)*t>1e-8}
def torso(p):
    levels=[(1.50,'pelvis'),(1.68,'spine_01'),(1.90,'spine_02'),(2.04,'neck')]
    for (a,ka),(b,kb) in zip(levels,levels[1:]):
        if p.z<=b:return mix({ka:1.},{kb:1.},min(1.,max(0.,(p.z-a)/(b-a))))
    return {'neck':1.}
def project(p,rows):
    found=[]
    for (a,_,wa),(b,_,wb) in zip(rows,rows[1:]):
        d=b-a;t=min(1.,max(0.,(p-a).dot(d)/d.length_squared));q=a+t*d
        found.append(((p-q).length_squared,mix(wa,wb,t)))
    return min(found,key=lambda row:row[0])[1]
def assign(obj,rows):
    for g in list(obj.vertex_groups):obj.vertex_groups.remove(g)
    groups={n:obj.vertex_groups.new(name=n) for n in group_names}
    for v,ws in zip(obj.data.vertices,rows):
        total=sum(ws.values());assert total>0
        for k,w in ws.items():groups[k].add([v.index],w/total,'REPLACE')
operands=[]
for key,rows in guides.items():
    points=[];all_weights=[];size=len(rows[0][1]);factor=job['parameters']['limb_radius_factor']
    center,ring,ws=rows[0]
    extension=center.copy()
    if key.startswith('arm'):extension.x=.10 if center.x>0 else -.10;extweights={'spine_02':1.}
    else:extension.z=1.52;extension.x=.06 if center.x>0 else -.06;extweights={'pelvis':1.}
    for p in ring:
        q=extension+(p-center)*factor;points.append(q);all_weights.append(extweights)
    for center,ring,ws in rows:
        for p in ring:
            q=center+(p-center)*factor;points.append(q);all_weights.append(ws)
    faces=[tuple(reversed(range(size)))]
    for i in range(len(rows)):
        for j in range(size):
            a=i*size+j;b=i*size+(j+1)%size;c=(i+1)*size+(j+1)%size;d=(i+1)*size+j
            faces.append((a,b,c,d))
    faces.append(tuple(range(len(points)-size,len(points))))
    data=bpy.data.meshes.new('Internal_'+key);data.from_pydata([body.matrix_world.inverted()@p for p in points],[],faces);data.update()
    operand=bpy.data.objects.new('Internal_'+key,data);bpy.context.scene.collection.objects.link(operand);operand.matrix_world=body.matrix_world.copy()
    bm=bmesh.new();bm.from_mesh(data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free()
    assign(operand,all_weights)
    known.update({coordkey(p):ws for p,ws in zip(points,all_weights)})
    operands.append(operand)
bpy.ops.object.select_all(action='DESELECT');body.select_set(True);bpy.context.view_layer.objects.active=body
# Boolean changes only the four intersecting roots, without a whole-body remesh.
for operand in operands:
    modifier=body.modifiers.new('local_hidden_limb_union','BOOLEAN');modifier.operation='UNION';modifier.solver='EXACT';modifier.object=operand
    bpy.ops.object.modifier_move_up(modifier=modifier.name)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    print('UNION',operand.name,len(body.data.vertices),len(body.data.polygons),flush=True)
    bpy.data.objects.remove(operand,do_unlink=True)
rows=[]
for v in body.data.vertices:
    p=body.matrix_world@v.co;ws=known.get(coordkey(p))
    if ws is None:
        if abs(p.x)>.15:ws=project(p,guides['arm.'+('R' if p.x>0 else 'L')])
        elif p.z<1.37:ws=project(p,guides['leg.'+('R' if p.x>0 else 'L')])
        else:ws=torso(p)
    rows.append(ws)
assign(body,rows);bpy.context.view_layer.update()
afterpoints=[body.matrix_world@v.co for v in body.data.vertices]
neck_error=max(min((a-b).length for b in afterpoints) for a in neck_original)
assert neck_error<1e-6,neck_error
assert all(adapter.appearance_data(o)==before[o.name] for o in meshes if o!=body)
bm=bmesh.new();bm.from_mesh(body.data)
loose=[e for e in bm.edges if not e.link_faces]
if loose:bmesh.ops.delete(bm,geom=loose,context='EDGES')
loose=[v for v in bm.verts if not v.link_edges]
if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
nonmanifold=sum(not e.is_manifold for e in bm.edges)
unvisited=set(bm.verts);components=0;component_rows=[]
while unvisited:
    components+=1;stack=[unvisited.pop()];component=[]
    while stack:
        v=stack.pop();component.append(v.co.copy())
        for e in v.link_edges:
            n=e.other_vert(v)
            if n in unvisited:unvisited.remove(n);stack.append(n)
    component_rows.append(dict(vertices=len(component),min=[min(v[i] for v in component) for i in range(3)],max=[max(v[i] for v in component) for i in range(3)]))
print('COMPONENTS',component_rows,'NONMANIFOLD',nonmanifold,flush=True)
bm.to_mesh(body.data);bm.free();body.data.update()
if components!=1:bpy.ops.wm.save_as_mainfile(filepath=str(output/'debug.blend'))
assert components==1,(components,nonmanifold)
after={o.name:adapter.appearance_data(o) for o in meshes};body_vertices=len(body.data.vertices)
adapter.render_views(output,'rest',adapter.frame_profile(meshes))
bpy.ops.wm.save_as_mainfile(filepath=str(output/'model.blend'));bpy.ops.wm.open_mainfile(filepath=str(output/'model.blend'),use_scripts=False)
assert all(adapter.appearance_data(bpy.data.objects[n])==v for n,v in after.items())
report=dict(success=True,run_id=job['run_id'],mode='local_hidden_limb_retopology',unchanged_other_meshes=103,visible_neck_position_error=neck_error,
    body_vertices=body_vertices,connected_components=components,nonmanifold_edges=nonmanifold,
    quality_passed=False,ue_verified=False)
(output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report))
