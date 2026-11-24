# SPDX-License-Identifier: GPL-3.0-or-later
from .browser_data import R
from .browser_data import geometry_output_state
from .browser_data import preview_pixels
from .browser_data import rebuild
from .browser_data import resolve
from .browser_data import root_modifier
from bpy.app.handlers import persistent
from collections import deque
from gpu_extras.presets import draw_texture_2d
from mathutils import Matrix
from mathutils import Vector
import bpy
import gpu
import math
import time


from .browser_data import socket_value

R.material_states={}
R.material_jobs=set()


def material_state(mat):
    tree=mat.node_tree
    if not tree: return (tuple(mat.diffuse_color),mat.metallic,mat.roughness),set()
    rows=[]
    dependencies=set()
    visited=set()
    links={}
    def walk(node,socket,stack):
        key=(tuple(n.as_pointer() for n in stack),node.as_pointer(),socket.identifier if socket else '')
        if key in visited: return
        visited.add(key)
        def follow(inp):
            tree_id=inp.id_data.as_pointer()
            if tree_id not in links:
                links[tree_id]={l.to_socket.as_pointer():l for l in inp.id_data.links if l.is_valid and not l.is_muted}
            link=links[tree_id].get(inp.as_pointer())
            if link:
                rows.append((key,inp.identifier,link.from_socket.as_pointer()))
                walk(link.from_node,link.from_socket,stack)
            else: rows.append((key,inp.identifier,socket_value(getattr(inp,'default_value',None))))
        rows.append((key,node.bl_idname,node.mute))
        if node.mute and socket:
            for link in node.internal_links:
                if link.to_socket==socket: follow(link.from_socket)
            return
        if node.type=='GROUP_INPUT' and stack and socket:
            outer=stack[-1]
            inp=next((i for i in outer.inputs if i.identifier==socket.identifier),None)
            if inp is not None:
                stack=stack[:-1]
                follow(inp)
            return
        group=getattr(node,'node_tree',None)
        if group and socket:
            dependencies.add(group.session_uid)
            out=next((n for n in group.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output),None)
            if out:
                inp=next((i for i in out.inputs if i.identifier==socket.identifier),None)
                if inp is not None:
                    stack=stack+(node,)
                    follow(inp)
            return
        image=getattr(node,'image',None)
        if image: dependencies.add(image.session_uid)
        for prop in node.bl_rna.properties:
            if prop.identifier in bpy.types.Node.bl_rna.properties or prop.identifier.startswith('bl_'): continue
            if not prop.is_readonly or prop.type in {'POINTER','COLLECTION'}:
                rows.append((key,prop.identifier,socket_value(getattr(node,prop.identifier))))
        if socket and hasattr(socket,'default_value'): rows.append((key,socket_value(socket.default_value)))
        for inp in node.inputs:
            if inp.enabled: follow(inp)
    for node in tree.nodes:
        if node.type=='OUTPUT_MATERIAL' and node.is_active_output: walk(node,None,())
    return hash(repr(rows)),dependencies


def enqueue(item):
    uid = item.session_uid
    if isinstance(item,bpy.types.Material) and uid not in R.material_states:
        R.material_states[uid]=material_state(item)
    if uid not in R.attempted:
        R.attempted.add(uid)
        R.queue.append(uid)


def preview_group_material(key,own):
    blocks=[resolve(uid) for uid in key]
    source=blocks[0] if isinstance(blocks[0],bpy.types.Material) else None
    mat=own(source.copy() if source else bpy.data.materials.new('Preview shader'))
    tree=mat.node_tree
    if tree is None: return None
    groups=blocks[1:] if source else [blocks[-1]]
    output=tree.get_output_node('CYCLES') or tree.nodes.new('ShaderNodeOutputMaterial')
    target=output.inputs['Surface']
    for idx,group in enumerate(groups):
        if not isinstance(group,bpy.types.ShaderNodeTree): return None
        node=next((n for n in tree.nodes if getattr(n,'node_tree',None)==group),None)
        if node is None:
            node=tree.nodes.new('ShaderNodeGroup')
            node.node_tree=group
        if idx==len(groups)-1:
            socket=next((s for s in node.outputs if s.type=='SHADER'),None)
            if socket is None: socket=next((s for s in node.outputs if s.type in {'RGBA','VALUE','VECTOR','INT','BOOLEAN'}),None)
            if socket is None: return None
            if socket.type!='SHADER':
                emission=tree.nodes.new('ShaderNodeEmission')
                tree.links.new(socket,emission.inputs['Color'])
                socket=emission.outputs[0]
            tree.links.new(socket,target)
        else:
            copied=own(group.copy())
            node.node_tree=copied
            port=copied.interface.new_socket(name='Preview',in_out='OUTPUT',socket_type='NodeSocketShader')
            tree.links.new(next(s for s in node.outputs if s.identifier==port.identifier),target)
            tree=copied
            out=next((n for n in tree.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output),None)
            if not out: out=tree.nodes.new('NodeGroupOutput')
            target=next(s for s in out.inputs if s.identifier==port.identifier)
    return mat


def needs_component_preview(obj):
    geometry=obj.evaluated_geometry()
    return bool(geometry.instance_references() or geometry.curves or geometry.pointcloud
                or geometry.volume or geometry.grease_pencil)


def append_preview_conversion(clone,own):
    # Only the temporary stack gets this modifier. Keep point clouds native
    # rather than allocating a sphere mesh for every point.
    tree=own(bpy.data.node_groups.new('.SCB display components','GeometryNodeTree'))
    for direction in ('INPUT','OUTPUT'):
        tree.interface.new_socket(name='Geometry',in_out=direction,socket_type='NodeSocketGeometry')
    node=tree.nodes.new
    link=tree.links.new
    realize=node('GeometryNodeRealizeInstances')
    link(node('NodeGroupInput').outputs[0],realize.inputs[0])
    parts=node('GeometryNodeSeparateComponents')
    link(realize.outputs[0],parts.inputs[0])
    join=node('GeometryNodeJoinGeometry')
    for component in ('Mesh','Point Cloud'):
        link(parts.outputs[component],join.inputs[0])
    strokes=node('GeometryNodeGreasePencilToCurves')
    strokes.inputs['Layers as Instances'].default_value=False
    link(parts.outputs['Grease Pencil'],strokes.inputs[0])
    curves=node('GeometryNodeJoinGeometry')
    link(strokes.outputs[0],curves.inputs[0])
    link(parts.outputs['Curve'],curves.inputs[0])
    tube=node('GeometryNodeCurveToMesh')
    profile=node('GeometryNodeCurvePrimitiveCircle')
    profile.inputs['Resolution'].default_value=6
    profile.inputs['Radius'].default_value=.01
    link(curves.outputs[0],tube.inputs['Curve'])
    link(profile.outputs[0],tube.inputs['Profile Curve'])
    link(tube.outputs[0],join.inputs[0])
    surface=node('GeometryNodeVolumeToMesh')
    link(parts.outputs['Volume'],surface.inputs[0])
    link(surface.outputs[0],join.inputs[0])
    link(join.outputs[0],node('NodeGroupOutput').inputs[0])
    clone.modifiers.new('Preview components','NODES').node_group=tree


def snapshot_components(obj,graph,studio,own,white):
    geometry=obj.evaluated_geometry()
    mesh=own(geometry.mesh.copy() if geometry.mesh else bpy.data.meshes.new('Preview mesh'))
    matrix=obj.matrix_world.copy()
    bounds=[]
    if mesh.vertices:
        bounds.extend(matrix @ Vector(c) for c in obj.bound_box)
    if geometry.pointcloud and len(geometry.pointcloud.points):
        cloud=own(geometry.pointcloud.copy())
        if white: cloud.materials.clear()
        points=own(bpy.data.objects.new('Preview points',cloud))
        studio.collection.objects.link(points)
        points.matrix_world=matrix
        import numpy as np
        n=len(cloud.points)
        xyz=np.empty(n*3,dtype=np.float32)
        cloud.attributes['position'].data.foreach_get('vector',xyz)
        xyz=xyz.reshape(-1,3)
        radius=np.full(n,.01,dtype=np.float32)
        if attr:=cloud.attributes.get('radius'): attr.data.foreach_get('value',radius)
        lo=(xyz-radius[:,None]).min(axis=0)
        hi=(xyz+radius[:,None]).max(axis=0)
        bounds.extend(matrix @ Vector((x,y,z)) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2]))
    if not bounds: bounds=[matrix.translation.copy()]
    return mesh,matrix,bounds


def curve_camera_fit(mesh,matrix,rotation):
    import numpy as np
    coords=np.empty(len(mesh.vertices)*3,dtype=np.float32)
    mesh.vertices.foreach_get('co',coords)
    basis=rotation.to_matrix()
    transform=np.asarray(basis.transposed() @ matrix.to_3x3())
    projected=coords.reshape(-1,3) @ transform.T
    low,high=projected.min(axis=0),projected.max(axis=0)
    span=high-low
    center=matrix.translation+basis @ Vector((low+high)*.5)
    return center,max(1e-6,float(np.linalg.norm(span))*.5),max(1e-6,max(span[:2])/.9)


def render_mesh_preview(item,key=None):
    # Render evaluated geometry with the actual material output in an isolated studio.
    import tempfile, os
    source_scene=resolve(key[0]) if key and isinstance(item,bpy.types.Object) else None
    graph=bpy.context.evaluated_depsgraph_get() if not key else None
    obj=item.evaluated_get(graph) if graph else None
    temporary=[]
    def own(block):
        temporary.append(block)
        return block
    try:
        studio=own(bpy.data.scenes.new('.SCB preview'))
        if isinstance(item,bpy.types.Curve):
            source=own(bpy.data.objects.new('Preview spline',item))
            bpy.context.scene.collection.objects.link(source)
            graph=bpy.context.evaluated_depsgraph_get()
            obj=source.evaluated_get(graph)
        if source_scene:
            layer=bpy.context.view_layer if source_scene==bpy.context.scene else None
            if not layer or layer.objects.get(item.name)!=item:
                layer=next((layer for layer in source_scene.view_layers if layer.objects.get(item.name)==item),None)
            if not layer:
                for candidate in source_scene.view_layers:
                    candidate.update()
                    if candidate.objects.get(item.name)==item:
                        layer=candidate
                        break
            if not layer: return
            with bpy.context.temp_override(scene=source_scene,view_layer=layer):
                graph=bpy.context.evaluated_depsgraph_get()
                obj=item.evaluated_get(graph)
                R.object_axes[item.session_uid]=tuple(v for row in obj.matrix_world.to_3x3() for v in row)
                components=obj.evaluated_geometry()
                classic_curve=obj.type in {'CURVE','FONT'} and not (components.instance_references() or components.pointcloud or components.volume or components.grease_pencil)
                if classic_curve:
                    mesh=own(bpy.data.meshes.new_from_object(obj,depsgraph=graph))
                    if not mesh.polygons:
                        R.curve_lines[key]=curve_projection(mesh)
                        return
                    matrix=obj.matrix_world.copy()
                    corners=[matrix @ Vector(c) for c in obj.bound_box]
                elif needs_component_preview(obj):
                    clone=own(item.copy())
                    source_scene.collection.objects.link(clone)
                    append_preview_conversion(clone,own)
                    graph=bpy.context.evaluated_depsgraph_get()
                    obj=clone.evaluated_get(graph)
                if not classic_curve:
                    mesh,matrix,corners=snapshot_components(obj,graph,studio,own,False)
                for index,slot in enumerate(obj.material_slots):
                    if index<len(mesh.materials): mesh.materials[index]=slot.material
        elif key:
            owner=resolve(key[-2])
            mod=root_modifier(owner,item)
            if not mod: return
            clone=own(owner.copy())
            scene=resolve(key[0]) if len(key)==3 else None
            if not isinstance(scene,bpy.types.Scene): scene=next(iter(owner.users_scene),None)
            if not scene: return
            # Evaluate a private stack, preserving dependencies in the source scene.
            scene.collection.objects.link(clone)
            for later in list(clone.modifiers)[list(owner.modifiers).index(mod)+1:]:
                clone.modifiers.remove(later)
            with bpy.context.temp_override(scene=scene,view_layer=scene.view_layers[0]):
                graph=bpy.context.evaluated_depsgraph_get()
                obj=clone.evaluated_get(graph)
                if needs_component_preview(obj):
                    append_preview_conversion(clone,own)
                    graph=bpy.context.evaluated_depsgraph_get()
                    obj=clone.evaluated_get(graph)
                mesh,matrix,corners=snapshot_components(obj,graph,studio,own,True)
            mesh.materials.clear()
            for face in mesh.polygons: face.material_index=0
        else:
            mesh=own(bpy.data.meshes.new_from_object(obj,depsgraph=graph))
            if obj.type in {'CURVE','FONT'} and not mesh.polygons:
                R.curve_lines[item.session_uid]=curve_projection(mesh)
                return
            matrix=obj.matrix_world.copy()
            corners=[matrix @ Vector(c) for c in obj.bound_box]
        subject=own(bpy.data.objects.new('Preview subject',mesh))
        studio.collection.objects.link(subject)
        subject.matrix_world=matrix
        if not key:
            for index,slot in enumerate(obj.material_slots):
                if index<len(mesh.materials): mesh.materials[index]=slot.material
        center=sum(corners,Vector())/len(corners)
        radius=max(.001,max((c-center).length for c in corners))
        direction=Vector((1.4,-2,1.25)).normalized()
        rotation=(-direction).to_track_quat('-Z','Y')
        frame_size=radius*2.12
        curve=item.data if isinstance(item,bpy.types.Object) else item
        if isinstance(curve,bpy.types.TextCurve) and mesh.vertices:
            import numpy as np
            coords=np.empty(len(mesh.vertices)*3,dtype=np.float32)
            mesh.vertices.foreach_get('co',coords)
            spans=np.ptp(coords.reshape(-1,3),axis=0)
            if spans[2]<=max(1e-8,max(spans[:2])*1e-7):
                rotation=matrix.to_quaternion()
                direction=rotation @ Vector((0,0,1))
        if isinstance(curve,bpy.types.Curve) and mesh.vertices and len(corners)==8:
            center,radius,frame_size=curve_camera_fit(mesh,matrix,rotation)
        cam=own(bpy.data.cameras.new('Preview lens'))
        camera=own(bpy.data.objects.new('Preview camera',cam))
        studio.collection.objects.link(camera)
        camera.location=center+direction*radius*4
        camera.rotation_euler=rotation.to_euler()
        cam.type='ORTHO'; cam.ortho_scale=frame_size
        cam.clip_start=radius*.01; cam.clip_end=radius*12
        studio.camera=camera
        for direction,power in [((2,-3,4),480),((-2,1,2),280)]:
            light=own(bpy.data.lights.new('Preview softbox','AREA'))
            lamp=own(bpy.data.objects.new('Preview light',light))
            studio.collection.objects.link(lamp)
            lamp.location=center+Vector(direction).normalized()*radius*3
            lamp.rotation_euler=(center-lamp.location).to_track_quat('-Z','Y').to_euler()
            light.energy = .1 * power * radius**2; light.size=radius*2
        studio.render.engine='CYCLES'; studio.cycles.samples=8
        studio.render.film_transparent=True
        studio.render.resolution_x=studio.render.resolution_y=128
        studio.render.resolution_percentage=100
        studio.render.image_settings.file_format='PNG'
        studio.render.image_settings.color_mode='RGBA'
        with tempfile.TemporaryDirectory() as folder:
            studio.render.filepath=os.path.join(folder,'preview.png')
            bpy.ops.render.render(scene=studio.name,write_still=True)
            image=own(bpy.data.images.load(studio.render.filepath,check_existing=False))
            pixels=preview_pixels(image.pixels)
            R.mesh_pixels[key or item.session_uid]=pixels
            R.textures.pop(key or item.session_uid,None)
    finally:
        bpy.data.batch_remove(ids=temporary)


def flat_group_preview(key):
    token=object()
    R.pending_flat[key]=token
    owned=[]
    def own(block):
        owned.append(block)
        return block
    try:
        mat=preview_group_material(key,own)
        if not mat: return
        mat.preview_render_type='FLAT'
        mat.asset_generate_preview()
        def finish():
            if bpy.app.is_job_running('RENDER_PREVIEW'): return .1
            try:
                if R.alive and R.pending_flat.get(key) is token and key in R.attempted and mat.preview and tuple(mat.preview.image_size)==(128,128):
                    R.mesh_pixels[key]=preview_pixels(mat.preview.image_pixels_float)
                    R.textures.pop(key,None)
            except ReferenceError: return
            finally:
                if R.pending_flat.get(key) is token: R.pending_flat.pop(key,None)
                previous=R.generating
                R.generating=True
                try:
                    bpy.data.batch_remove(ids=owned)
                    if bpy.context.view_layer: bpy.context.view_layer.update()
                except ReferenceError: pass
                finally: R.generating=previous
        if bpy.app.is_job_running('RENDER_PREVIEW'):
            bpy.app.timers.register(finish,first_interval=.1)
        else: finish()
    except Exception:
        if owned: bpy.data.batch_remove(ids=owned)
        raise


def refresh_previews(uid=None):
    if uid is None:
        rebuild()
        R.cards.clear()
        R.glyphs.clear()
        R.pending_flat.clear()
        R.curve_lines.clear()
        R.mesh_pixels.clear()
        R.textures.clear()
        R.wires.clear()
        R.queue.clear()
        R.attempted.clear()
        return
    discard_previews({uid})


def discard_previews(ids, *, direct=False):
    keys=set(ids)
    for k in tuple(R.glyphs):
        if (isinstance(k,tuple) and not ids.isdisjoint(k)) or k in ids: R.glyphs.pop(k,None)
    for cache in (R.attempted,R.mesh_pixels,R.textures,R.pending_flat,R.curve_lines):
        keys.update(k for k in cache if isinstance(k,tuple) and (k[-1] in ids if direct else not ids.isdisjoint(k)))
    R.queue=deque(k for k in R.queue if k not in keys)
    R.attempted.difference_update(keys)
    for key in keys:
        R.pending_flat.pop(key,None)
        R.curve_lines.pop(key,None)
        R.mesh_pixels.pop(key,None)
        R.textures.pop(key,None)
    for uid in ids:
        R.curve_lines.pop(uid,None)
        R.wires.pop(uid,None)
        R.cards.pop(uid,None)


@persistent
def preview_changes(scene,graph):
    if R.generating or not R.alive or not R.views: return
    deadline=time.monotonic()+.5
    edits=set()
    objects=set()
    for update in graph.updates:
        block=update.id.original
        if block.session_uid not in R.ids and block.session_uid not in R.material_owner:
            R.index_dirty=True
            continue
        if isinstance(block,(bpy.types.Collection,bpy.types.Scene,bpy.types.NodeTree,bpy.types.Material)):
            R.index_dirty=True
        if isinstance(block,bpy.types.Object):
            axes=tuple(v for row in update.id.matrix_world.to_3x3() for v in row)
            previous=R.object_axes.get(block.session_uid)
            R.object_axes[block.session_uid]=axes
            shading_changed=False
            if update.is_updated_shading:
                slots=tuple(slot.material.session_uid if slot.material else 0 for slot in block.material_slots)
                shading_changed=slots!=R.slot_ids.get(block.session_uid,slots)
                R.slot_ids[block.session_uid]=slots
                if shading_changed: R.index_dirty=True
            if update.is_updated_geometry or shading_changed or (update.is_updated_transform and previous is not None and axes!=previous):
                objects.add(block.session_uid)
        elif isinstance(block,(bpy.types.Mesh,bpy.types.Curve,bpy.types.Key,bpy.types.Material,
                               bpy.types.NodeTree,bpy.types.Image,bpy.types.Armature,bpy.types.Action,bpy.types.Palette,bpy.types.Light,bpy.types.Camera,bpy.types.VectorFont)):
            edits.add(R.material_owner.get(block.session_uid,block.session_uid))
    # Shader edits can also tag object shading indirectly. Resolve those owners
    # from actual Browser relationships instead of treating every tag as an edit.
    resource_edit=any(isinstance(resolve(uid),(bpy.types.Material,bpy.types.NodeTree,bpy.types.Image)) for uid in edits)
    for uid in edits | (set() if resource_edit else objects):
        R.dirty_previews[uid]=deadline


def affected_tiles(changes):
    affected=set(changes)
    visited=set()
    pending=[(uid,isinstance(resolve(uid),bpy.types.Material)) for uid in changes]
    while pending:
        uid,local_material=pending.pop()
        if (uid,local_material) in visited: continue
        visited.add((uid,local_material))
        parents=R.preview_parents.get(uid,())
        if local_material:
            owner=R.material_context.get(uid)
            if owner not in parents:
                owner=next((p for view_state in R.views.values() for p in reversed(view_state.get('path',())) if p in parents),None)
            if owner in parents: parents=(owner,)
        for parent in parents:
            if isinstance(resolve(uid),bpy.types.GeometryNodeTree) and parent in R.geometry_outputs:
                if uid not in R.geometry_outputs[parent][1]: continue
            affected.add(parent)
            pending.append((parent,False))
    return affected


def flush_preview_changes():
    if R.material_jobs and not bpy.app.is_job_running('RENDER_PREVIEW'):
        for uid in R.material_jobs: R.textures.pop(uid,None)
        R.material_jobs.clear()
        R.redraw_until=time.monotonic()+.5
    if not R.dirty_previews: return
    now=time.monotonic()
    pending=[uid for uid,deadline in R.dirty_previews.items() if deadline<=now]
    if not pending: return
    for uid in pending: del R.dirty_previews[uid]
    changed=[]
    for uid in pending:
        tree=resolve(uid)
        if isinstance(tree,bpy.types.GeometryNodeTree):
            state=geometry_output_state(tree)
            previous=R.geometry_outputs.get(uid)
            R.geometry_outputs[uid]=state
            if previous==state: continue
        changed.append(uid)
    if changed:
        affected=affected_tiles(changed)
        keep_parents=set(changed)
        skip_parents=set()
        for uid in tuple(affected):
            material=resolve(uid)
            if not isinstance(material,bpy.types.Material): continue
            state=material_state(material)
            previous=R.material_states.get(uid)
            R.material_states[uid]=state
            image_edit=any(dep in state[1] and isinstance(resolve(dep),bpy.types.Image) for dep in changed)
            if previous==state and not image_edit:
                affected.discard(uid)
                skip_parents.update(R.preview_parents.get(uid,()))
            else:
                keep_parents.update(R.preview_parents.get(uid,()))
        affected.difference_update(skip_parents-keep_parents)
        discard_previews(affected,direct=True)
    for uid in pending: R.group_children.pop(uid,None)


def run_preview_job():
    if not R.queue or any(v.get('box') for v in R.views.values()): return
    visible={path[-1] for v in R.views.values() for *_,path in v.get('tile_paths',()) if path}
    if visible:
        while R.queue:
            key=R.queue[0]
            if (key[-1] if isinstance(key,tuple) else key) in visible: break
            R.attempted.discard(R.queue.popleft())
        if not R.queue: return
    # Deliver outstanding user edits before suppressing our own scene changes.
    layer=bpy.context.view_layer
    if layer: layer.update()
    R.generating=True
    try:
        preview_tick()
    finally:
        try:
            # Removing the temporary studio also tags the original graph.
            # Consume that deferred update before re-enabling edit notifications.
            if layer: layer.update()
        finally:
            R.generating=False


def preview_tick():
    if not R.queue or any(v.get('box') for v in R.views.values()): return
    key=R.queue.popleft()
    if isinstance(key,tuple):
        if resolve(key[-1]):
            try:
                if isinstance(resolve(key[-1]),bpy.types.ShaderNodeTree): flat_group_preview(key)
                else: render_mesh_preview(resolve(key[-1]),key)
            except (RuntimeError,ValueError,TypeError) as exc: print('QuickBrowser shader preview:',exc)
        return
    item = resolve(key)
    if item is None: return
    if isinstance(item,bpy.types.Curve) or isinstance(item,bpy.types.Object) and item.type in {'CURVE','FONT','MESH'}:
        try: render_mesh_preview(item)
        except (RuntimeError,ValueError) as exc: print('QuickBrowser preview:',exc)
        return
    # Native rendering where supported, semantic drawings everywhere else.
    if isinstance(item, (bpy.types.Object, bpy.types.Collection, bpy.types.Material,
                         bpy.types.World, bpy.types.NodeTree, bpy.types.Action)):
        try:
            item.asset_generate_preview()
            if isinstance(item,bpy.types.Material): R.material_jobs.add(item.session_uid)
        except (RuntimeError, TypeError): pass


def raster_thumbnail(shape,paint):
    result=gpu.types.GPUTexture(shape,format='RGBA16F')
    fb=gpu.types.GPUFrameBuffer(color_slots=result)
    blend=gpu.state.blend_get()
    viewport=gpu.state.viewport_get()
    scissor=gpu.state.scissor_get()
    try:
        with fb.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
            gpu.state.viewport_set(0,0,*shape)
            gpu.state.scissor_set(0,0,*shape)
            gpu.state.blend_set('NONE')
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix(((2/shape[0],0,0,-1),(0,2/shape[1],0,-1),(0,0,1,0),(0,0,0,1))))
            fb.clear(color=(0,0,0,0))
            paint(*shape)
    finally:
        gpu.state.viewport_set(*viewport)
        gpu.state.scissor_set(*scissor)
        gpu.state.blend_set(blend)
    return result


def image_thumbnail(image):
    width,height=image.size
    scale=128/max(width,height)
    shape=(max(1,round(width*scale)),max(1,round(height*scale)))
    return raster_thumbnail(shape,lambda w,h:draw_texture_2d(gpu.texture.from_image(image),(0,0),w,h))


def native_texture(item,key=None):
    uid = key or item.session_uid
    now = time.monotonic()
    cached = R.textures.get(uid)
    if cached and (now-cached[0] < .4 or cached[1] is not None): return cached[1:]
    tex, aspect, linear = None, 1.0, False
    try:
        if uid in R.mesh_pixels:
            pixels=R.mesh_pixels[uid]
            side=math.isqrt(len(pixels)//4)
            tex=gpu.types.GPUTexture((side,side),format='RGBA32F',data=gpu.types.Buffer('FLOAT',len(pixels),pixels))
            linear=True
        elif isinstance(item,bpy.types.Object) and item.type=='MESH':
            return None,1.0,False
        elif isinstance(item, bpy.types.Image) and item.size[0] and item.size[1]:
            tex = image_thumbnail(item)
            aspect = item.size[0]/item.size[1]
            linear = True
        else:
            p = item.preview
            if p and p.image_size[0] and p.image_size[1]:
                w,h = p.image_size
                pixels = preview_pixels(p.image_pixels_float)
                if pixels and any(pixels[3::4]):
                    tex = gpu.types.GPUTexture((w,h), format='RGBA32F',
                          data=gpu.types.Buffer('FLOAT', len(pixels), pixels))
                    aspect = w/h
    except (RuntimeError, ValueError): pass
    R.textures[uid] = (now, tex, aspect, linear)
    # Bound GPU cache while browsing large files.
    if len(R.textures) > 256: R.textures.pop(next(iter(R.textures)))
    return tex, aspect, linear


def curve_projection(mesh):
    import numpy as np
    if not mesh.edges: return []
    vertices=np.empty(len(mesh.vertices)*3,dtype=np.float32)
    mesh.vertices.foreach_get('co',vertices)
    coords=vertices.reshape(-1,3)
    coords=coords-coords.mean(axis=0)
    # Face the best-fit plane. Keep local Y up when looking down local Z.
    _,axes=np.linalg.eigh(coords.T @ coords)
    normal=axes[:,0]
    if normal[np.argmax(np.abs(normal))]<0: normal=-normal
    up=np.array((0,1,0) if abs(normal[2])>.85 else (0,0,1))
    right=np.cross(up,normal)
    right/=np.linalg.norm(right)
    xy=coords @ np.column_stack((right,np.cross(normal,right)))
    low,high=xy.min(axis=0),xy.max(axis=0)
    xy=(xy-(low+high)*.5)/max(float((high-low).max()),1e-12)+.5
    edges=np.empty(len(mesh.edges)*2,dtype=np.int32)
    mesh.edges.foreach_get('vertices',edges)
    return xy[edges.reshape(-1,2)[::max(1,math.ceil(len(mesh.edges)/8192))].ravel()].tolist()


def mesh_wire(mesh):
    key = mesh.session_uid
    cached = R.wires.get(key)
    if cached and time.monotonic()-cached[0] < 3: return cached[1]
    edges = mesh.edges
    chosen = list(range(0, len(edges), max(1, len(edges)//1500)))[:1500]
    points = []
    for index in chosen:
        for vi in edges[index].vertices:
            co = mesh.vertices[vi].co
            points.append((.80*co.x-.60*co.y, .35*co.x+.47*co.y+.81*co.z))
    if points:
        minx,maxx = min(p[0] for p in points),max(p[0] for p in points)
        miny,maxy = min(p[1] for p in points),max(p[1] for p in points)
        scale = max(maxx-minx,maxy-miny,1e-5)
        points = [((x-(minx+maxx)/2)/scale+.5,(y-(miny+maxy)/2)/scale+.5) for x,y in points]
    R.wires[key] = (time.monotonic(), points)
    if len(R.wires)>256: R.wires.pop(next(iter(R.wires)))
    return points
