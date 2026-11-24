# SPDX-License-Identifier: GPL-3.0-or-later


from array import array
from collections import deque
import bpy
import time
import types


KEY = '_scene_content_browser_runtime'


TREE = 'SCB_BrowserTree'


R = types.ModuleType(KEY)


R.alive = False


R.views = {}


R.editor_returns = {}


R.scene_loose = {}


R.running = set()


R.handles = []


R.classes = []


R.filters = []


R.textures = {}


R.wires = {}


R.queue = deque()


R.group_children={}


R.attempted = set()


R.mesh_pixels={}


R.curve_lines={}


R.pending_flat={}


R.ids = {}


R.edges = {}


R.cards={}


R.font_cache = {}


R.last_index = 0


R.drag = None


R.message = ''


R.undo_seeded = False


R.header_original = None


R.dirty_previews={}


R.material_context={}


R.generating=False


R.index_dirty=False


R.object_axes={}


R.slot_ids={}


R.glyphs={}


R.type_batches={}


R.geometry_outputs={}


def socket_value(data,depth=0):
    if isinstance(data,bpy.types.ID): return data.session_uid
    if isinstance(data,bpy.types.bpy_struct):
        if depth>=4: return data.bl_rna.identifier
        return tuple((p.identifier,socket_value(getattr(data,p.identifier),depth+1)) for p in data.bl_rna.properties
                     if p.identifier not in {'rna_type','id_data','select','is_valid'} and (not p.is_readonly or p.type in {'POINTER','COLLECTION'}))
    if isinstance(data,(str,int,float,bool,type(None))): return data
    try: return tuple(socket_value(x,depth+1) for x in data)
    except TypeError: return str(data)


def geometry_output_state(tree):
    """Describe the evaluated branch, excluding node-editor layout and selection."""
    incoming={}
    for link in tree.links:
        if link.is_valid and not link.is_muted:
            incoming.setdefault(link.to_socket.as_pointer(),[]).append(link)
    todo=[node for node in tree.nodes if node.type=='GROUP_OUTPUT' and node.is_active_output]
    visited=set()
    rows=[]
    groups=set()
    while todo:
        node=todo.pop()
        ptr=node.as_pointer()
        if ptr in visited: continue
        visited.add(ptr)
        group=getattr(node,'node_tree',None)
        if group: groups.add(group.session_uid)
        props=tuple((p.identifier,socket_value(getattr(node,p.identifier))) for p in node.bl_rna.properties
                    if p.identifier not in bpy.types.Node.bl_rna.properties and not p.identifier.startswith('bl_')
                    and (not p.is_readonly or p.type in {'POINTER','COLLECTION'}))
        inputs=[]
        for socket in node.inputs:
            if not socket.enabled: continue
            links=incoming.get(socket.as_pointer(),())
            if links:
                inputs.append((socket.identifier,tuple((l.from_node.as_pointer(),l.from_socket.identifier,l.multi_input_sort_id) for l in links)))
                todo.extend(l.from_node for l in links)
            else: inputs.append((socket.identifier,socket_value(getattr(socket,'default_value',None))))
        # Value and RGB nodes store their editable constants on output sockets.
        outputs=tuple((sock.identifier,socket_value(sock.default_value)) for sock in node.outputs if hasattr(sock,'default_value'))
        rows.append((ptr,node.bl_idname,node.mute,props,tuple(inputs),outputs))
    return hash(repr(sorted(rows))),groups


def all_ids():
    if hasattr(bpy.data,'all_ids'): return bpy.data.all_ids
    return bpy.data.user_map().keys()


def rebuild():
    # Rebuild after undo/load or periodically; never cache RNA references.
    R.group_children.clear()
    users = bpy.data.user_map()
    R.ids = {x.session_uid: x for x in all_ids()}
    R.edges = {}
    R.material_owner={mat.node_tree.session_uid:mat.session_uid for mat in bpy.data.materials if mat.node_tree}
    for dependency, owners in users.items():
        for owner in owners:
            R.edges.setdefault(owner.session_uid, set()).add(dependency.session_uid)
    parents={}
    def link(child,owner):
        if child: parents.setdefault(child.session_uid,set()).add(owner.session_uid)
    R.slot_ids.clear()
    for obj in bpy.data.objects:
        materials=tuple(slot.material for slot in obj.material_slots)
        R.slot_ids[obj.session_uid]=tuple(mat.session_uid if mat else 0 for mat in materials)
        link(obj.data,obj)
        for mat in materials: link(mat,obj)
        for mod in obj.modifiers: link(getattr(mod,'node_group',None),obj)
    for owner in (*bpy.data.node_groups,*bpy.data.materials):
        tree=owner.node_tree if isinstance(owner,bpy.types.Material) else owner
        if tree:
            for node in tree.nodes:
                link(getattr(node,'node_tree',None),owner)
                link(getattr(node,'image',None),owner)
    for tree in bpy.data.node_groups:
        if isinstance(tree,bpy.types.GeometryNodeTree) and tree.session_uid not in R.geometry_outputs:
            R.geometry_outputs[tree.session_uid]=geometry_output_state(tree)
    for uid in R.geometry_outputs.keys()-R.ids.keys(): del R.geometry_outputs[uid]
    R.preview_parents=parents
    R.last_index = time.monotonic()
    R.index_dirty=False


def resolve(uid):
    if not uid: return None
    # Main IDs and embedded IDs have different RNA collections; user_map is authoritative.
    item=R.ids.get(uid)
    try:
        if item and item.session_uid==uid: return item
    except ReferenceError: pass
    return None


def akey(window, area):
    if window is None or area is None or window.screen is None: return None
    return (window.as_pointer(), window.screen.as_pointer(), area.as_pointer())


def view(context):
    return R.views.get(akey(context.window, context.area)) if context.window and context.area else None


def new_view():
    return dict(path=[], selected=0, scroll=0, tree_scroll=0, search='', hits=[],
                last=(0, 0.0), max_scroll=0, max_tree=0, region=None, nav_hidden=False)


def current(v):
    if v['path'] and resolve(v['path'][-1]) is None: rebuild()
    while v['path'] and resolve(v['path'][-1]) is None: v['path'].pop()
    return resolve(v['path'][-1]) if v['path'] else None


def direct_group_ids(tree):
    uid=tree.session_uid
    if uid not in R.group_children:
        R.group_children[uid]=tuple(dict.fromkeys(group.session_uid for node in tree.nodes
                                    if (group:=getattr(node,'node_tree',None))))
    return R.group_children[uid]


def group_folder(item,owner):
    return isinstance(item,(bpy.types.GeometryNodeTree,bpy.types.ShaderNodeTree)) and (
        root_modifier(owner,item) or direct_group_ids(item))


def preview_pixels(values):
    pixels=array('f',[0])*len(values)
    values.foreach_get(pixels)
    return pixels


def remember_loose(scene,block):
    R.scene_loose.setdefault(scene.session_uid,set()).add(block.session_uid)


def scene_loose(scene):
    return [block for uid in R.scene_loose.get(scene.session_uid,())
            if (block:=resolve(uid)) and block.users<=int(block.use_fake_user)]


def children(item):
    if isinstance(item,bpy.types.TextCurve) or (isinstance(item,bpy.types.Object) and item.type=='FONT'):
        data=item.data if isinstance(item,bpy.types.Object) else item
        fonts={font for font in (data.font,data.font_bold,data.font_italic,data.font_bold_italic) if font}
        materials=({slot.material for slot in item.material_slots if slot.material}
                   if isinstance(item,bpy.types.Object) else {mat for mat in data.materials if mat})
        return sorted(fonts,key=lambda f:f.name.casefold())+sorted(materials,key=lambda m:m.name.casefold())
    if item is None:
        result = list(bpy.data.scenes)
    elif isinstance(item, bpy.types.Scene):
        result = list(item.collection.children) + list(item.collection.objects)
        result.extend(bpy.data.palettes)
        result.extend(scene_loose(item))
    elif isinstance(item,bpy.types.Object):
        result={slot.material for slot in item.material_slots if slot.material}
    elif isinstance(item,bpy.types.Material):
        result=set()
        pending=[item.node_tree] if item.node_tree else []
        visited=set()
        while pending:
            tree=pending.pop()
            if tree in visited: continue
            visited.add(tree)
            for node in tree.nodes:
                image=getattr(node,'image',None)
                if image: result.add(image)
                group=getattr(node,'node_tree',None)
                if group: pending.append(group)
    elif isinstance(item,bpy.types.GeometryNodeTree):
        result=set()
    elif isinstance(item, bpy.types.Collection):
        result = list(item.children) + list(item.objects)
    else:
        uids = R.edges.get(item.session_uid, ())
        result = [x for uid in uids if (x:=resolve(uid))
                  and not isinstance(x, (bpy.types.Scene, bpy.types.Collection, bpy.types.Object))]
        # Embedded shader trees may be omitted by user_map. Their images still
        # appear when traversing the independently stored node groups/materials.
        tree = getattr(item, 'node_tree', None)
        if tree:
            for node in tree.nodes:
                for attr in ('image', 'node_tree'):
                    dep = getattr(node, attr, None)
                    if dep and dep not in result: result.append(dep)
    result=set(result)
    owners=[item]
    if isinstance(item,bpy.types.Object):
        result.update(mod.node_group for mod in item.modifiers if mod.type=='NODES' and mod.node_group)
        owners.extend((item.data,getattr(item.data,'shape_keys',None)))
    tree=getattr(item,'node_tree',None)
    if isinstance(item,bpy.types.NodeTree): tree=item
    if tree:
        result.update(group for uid in direct_group_ids(tree) if (group:=resolve(uid)))
        owners.append(tree)
    for owner in owners:
        animation=getattr(owner,'animation_data',None)
        if animation:
            if animation.action: result.add(animation.action)
            strips=[strip for track in animation.nla_tracks for strip in track.strips]
            while strips:
                strip=strips.pop()
                if strip.action: result.add(strip.action)
                strips.extend(strip.strips)
    return sorted((x for x in result if not isinstance(x,(bpy.types.Mesh,bpy.types.Screen,bpy.types.WorkSpace)) or (isinstance(item,bpy.types.Scene) and isinstance(x,bpy.types.Mesh))), key=lambda x: (0 if isinstance(x, (bpy.types.Scene, bpy.types.Collection)) else 1,
                                         x.bl_rna.identifier, x.name.casefold()))


def navigate(v, uid, path=None):
    v.pop('pin_contents',None)
    v.pop('scroll_to',None)
    v['path'] = list(path) if path is not None else v['path'] + [uid]
    v['scroll'] = 0
    v['search'] = ''
    v['selected'] = 0
    v['multi']=set()
    v['slot_selection']=set()
    v['clicked_path']=()
    v['offset_x']=0


def tree_rows(v):
    key=(R.last_index,tuple(v['path'][:1]))
    if v.get('tree_key')==key: return v['tree_rows']
    rows = [('All Scenes', [], 0, 0)]
    def branch(col, path, depth):
        rows.append((col.name, path+[col.session_uid], col.session_uid, depth))
        for child in sorted(col.children, key=lambda x: x.name.casefold()):
            branch(child, path+[col.session_uid], depth+1)
    for scene in bpy.data.scenes:
        path = [scene.session_uid]
        rows.append((scene.name, path, scene.session_uid, 1))
        if v['path'] and v['path'][0] == scene.session_uid:
            for col in scene.collection.children: branch(col, path, 2)
    v['tree_key'],v['tree_rows']=key,rows
    return rows


def root_modifier(owner,group):
    if isinstance(owner,bpy.types.Object) and isinstance(group,bpy.types.GeometryNodeTree):
        return next((m for m in owner.modifiers if getattr(m,'node_group',None)==group),None)


FILTER_ICONS={'Scene':'SCENE_DATA','Collection':'OUTLINER_COLLECTION','Mesh':'MESH_DATA',
              'Material':'MATERIAL','NodeGroup':'NODETREE','Image':'IMAGE_DATA',
              'Curve':'CURVE_DATA','Armature':'ARMATURE_DATA','Action':'ACTION','Light':'LIGHT_DATA',
              'Camera':'CAMERA_DATA','Fonts':'FILE_FONT','Palette':'COLOR'}


GROUPS=tuple(FILTER_ICONS)


OBJECT_GROUPS={'MESH':'Mesh','CURVE':'Curve','CURVES':'Curve','ARMATURE':'Armature','CAMERA':'Camera','LIGHT':'Light'}


def matches_type(item,enabled):
    if isinstance(item,bpy.types.Mesh): return item.users<=int(item.use_fake_user) and (not enabled or "Mesh" in enabled)
    if isinstance(item,(bpy.types.Screen,bpy.types.WorkSpace)): return False
    if isinstance(item,bpy.types.NodeTree): return not item.is_embedded_data and (not enabled or 'NodeGroup' in enabled and isinstance(item,(bpy.types.GeometryNodeTree,bpy.types.ShaderNodeTree)))
    if isinstance(item,bpy.types.Palette): return 'Palette' in enabled
    if isinstance(item,bpy.types.VectorFont): return 'Fonts' in enabled
    if not enabled: return True
    if isinstance(item,bpy.types.Object):
        return OBJECT_GROUPS.get(item.type) in enabled
    if isinstance(item,bpy.types.Curves): return 'Curve' in enabled
    return any(isinstance(item,getattr(bpy.types,g)) for g in enabled if g not in {'Mesh','Text','Fonts','NodeGroup'})


def content_entries(parent,state,browse_result=False):
    query='' if browse_result else state.query.strip().casefold()
    recursive=(not browse_result and state.expanded) or (query and state.scope=='SUB')
    text_folder=isinstance(parent,bpy.types.TextCurve) or (isinstance(parent,bpy.types.Object) and parent.type=='FONT')
    roots=children(parent)
    if query and state.scope=='ALL':
        roots=sorted((x for uid in R.ids if (x:=resolve(uid))),key=lambda x:x.name.casefold())
    enabled={g for g in GROUPS if getattr(state,'filter_'+g)}
    if 'Fonts' in enabled and not text_folder:
        roots=list(bpy.data.fonts)+roots
    if 'Palette' in enabled and not text_folder:
        roots=list(bpy.data.palettes)+roots
    pending=[(x,()) for x in reversed(roots)]
    seen=set()
    while pending:
        item,ancestors=pending.pop()
        uid=item.session_uid
        if uid in seen: continue
        seen.add(uid)
        path=ancestors+(uid,)
        local_font=text_folder and not enabled and not ancestors and isinstance(item,bpy.types.VectorFont)
        if (local_font or matches_type(item,enabled)) and query in item.name.casefold():
            yield item,path
        if recursive:
            pending.extend((child,path) for child in reversed(children(item)))


def results(parent,state):
    return [item for item,path in content_entries(parent,state)]


def scene_path_to(item, preferred):
    """Find a real browser path, preferring the scene being browsed."""
    scenes=[preferred]+[s for s in bpy.data.scenes if s!=preferred]
    seen=set()
    pending=[(s,()) for s in reversed(scenes) if s]
    while pending:
        entry,path=pending.pop()
        uid=entry.session_uid
        if uid in seen: continue
        seen.add(uid)
        path=path+(uid,)
        if entry==item: return list(path)
        pending.extend((child,path) for child in reversed(children(entry)))
    return []


def reveal_path(scene,obj):
    pending=[(scene.collection,[scene.session_uid])]
    visited=set()
    while pending:
        col,path=pending.pop()
        if col.session_uid in visited: continue
        visited.add(col.session_uid)
        if obj.name in col.objects: return path
        pending.extend((child,path+[child.session_uid]) for child in col.children)
    return []


R.remap_pairs={}


R.undo_snapshot=None


def sync_pin(window,v):
    if not v.get('pin'): return
    scene=window.scene
    layer=window.view_layer
    obj=layer.objects.active
    if obj and not obj.select_get(view_layer=layer): obj=None
    target=(scene.session_uid,obj.session_uid if obj else 0)
    if v.get('pin_target')==target: return
    v['pin_target']=target
    path=reveal_path(scene,obj) if obj else [scene.session_uid]
    if not path: return
    navigate(v,0,path)
    v['pin_contents']=True
    if obj:
        v['selected']=obj.session_uid
        v['multi']={obj.session_uid}
        v['scroll_to']=obj.session_uid
    v.pop('layout_key',None)
