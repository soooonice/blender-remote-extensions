# SPDX-License-Identifier: GPL-3.0-or-later
from .browser_data import GROUPS
from .browser_data import R
from .browser_data import TREE
from .browser_data import akey
from .browser_data import children
from .browser_data import current
from .browser_data import direct_group_ids
from .browser_data import group_folder
from .browser_data import navigate
from .browser_data import rebuild
from .browser_data import remember_loose
from .browser_data import resolve
from .browser_data import results
from .browser_data import reveal_path
from .browser_data import root_modifier
from .browser_data import scene_path_to
from .browser_data import sync_pin
from .browser_data import view
from .previews import discard_previews
from .previews import refresh_previews
from .ui import CARD_FOOTER
from .ui import geometry
from .ui import restore_nav
from .ui import ui_state
from bl_operators.wm import BatchRenameAction
from bl_operators.wm import WM_OT_batch_rename
from bpy.props import BoolProperty
from bpy.props import CollectionProperty
from bpy.props import FloatVectorProperty
from bpy.props import StringProperty
from mathutils import Vector
import bpy


def editor_window(context,v,kind,create):
    if not create: return
    win=context.window
    origin=next((a for a in win.screen.areas if R.views.get(akey(win,a)) is v),None)
    if not origin: return
    wanted={'image':'IMAGE_EDITOR','group':'GeometryNodeTree','shader':'ShaderNodeTree'}[kind]
    def compatible(area):
        if area.ui_type!=wanted: return False
        space=area.spaces.active
        return not getattr(space,'pin',getattr(space,'use_image_pin',False))
    candidates=[a for a in win.screen.areas if compatible(a) and akey(win,a) not in R.editor_returns]
    area=max(candidates,key=lambda a:a.width*a.height,default=origin)
    if area==origin:
        R.editor_returns[akey(win,area)]=(origin.as_pointer(),v,wanted)
        area.ui_type=wanted
    return win,area


def return_to_browser(win,area):
    record=R.editor_returns.pop(akey(win,area),None)
    if not record: return False
    ptr,v,wanted=record
    if area.ui_type!=wanted: return False
    origin=next((a for a in win.screen.areas if a.as_pointer()==ptr),None)
    if origin==area:
        area.type='PROPERTIES'
        area.spaces.active.context='SCENE'
        R.views[akey(win,area)]=v
    else: return False
    origin.tag_redraw()
    return True


def parent_object(v,mat,scene):
    for uid in reversed(v['path']):
        obj=resolve(uid)
        if isinstance(obj,bpy.types.Object) and any(s.material==mat for s in obj.material_slots): return obj
    return next((obj for obj in scene.objects if any(s.material==mat for s in obj.material_slots)),None)


def shader_route(root,target):
    pending=[(root,())]
    seen=set()
    while pending:
        tree,path=pending.pop()
        if tree==target: return path
        if tree in seen: continue
        seen.add(tree)
        pending.extend((node.node_tree,path+(node,)) for node in reversed(list(tree.nodes))
                       if node.type=='GROUP' and node.node_tree)
    return None


def show_shader(context,v,mat,create):
    if isinstance(mat,bpy.types.Material):
        path=list(v['path'])+list(v.get('clicked_path',()))
        owner=next((uid for uid in reversed(path) if uid in R.preview_parents.get(mat.session_uid,())),None)
        if owner: R.material_context[mat.session_uid]=owner
        else: R.material_context.pop(mat.session_uid,None)
    group=isinstance(mat,bpy.types.NodeTree)
    tree=mat if group else mat.node_tree
    if not tree: return
    kind='group' if isinstance(tree,bpy.types.GeometryNodeTree) else 'shader'
    result=editor_window(context,v,kind,create)
    if not result: return
    window,area=result
    area.ui_type=tree.bl_idname
    space=area.spaces.active
    if kind=='shader': space.shader_type='OBJECT'
    temporary=akey(window,area) in R.editor_returns
    if temporary: space.pin=True
    chain=[]
    if group:
        clicked=v.get('clicked_path',())
        ids=list(v['path'])+(list(clicked[:-1]) if clicked and clicked[-1]==mat.session_uid else [])
        for uid in ids:
            owner=resolve(uid)
            candidate=owner.node_tree if isinstance(owner,bpy.types.Material) else owner
            if isinstance(candidate,type(tree)) and candidate!=tree:
                chain.append(candidate)
    if group and kind=='shader' and not any(isinstance(resolve(uid),bpy.types.Material) for uid in ids):
        for material in bpy.data.materials:
            if material.node_tree and shader_route(material.node_tree,chain[0] if chain else tree) is not None:
                chain.insert(0,material.node_tree)
                break
    chain.append(tree)
    if not temporary:
        path=[resolve(uid) for uid in (*v['path'],*v.get('clicked_path',()))]
        owners=[o for o in reversed(path) if isinstance(o,bpy.types.Object)]
        root=chain[0]
        for obj in (*owners,*window.view_layer.objects):
            if window.view_layer.objects.get(obj.name)!=obj: continue
            if kind=='shader':
                slot=next((i for i,s in enumerate(obj.material_slots) if s.material and s.material.node_tree==root),None)
                if slot is None: continue
                obj.active_material_index=slot
            else:
                modifier=root_modifier(obj,root)
                if not modifier: continue
                obj.modifiers.active=modifier
            window.view_layer.objects.active=obj
            break
    if group and kind=='shader':
        # Let Blender establish the unpinned editor's owner before entering groups.
        region=next((r for r in area.regions if r.type=='WINDOW'),None)
        with context.temp_override(window=window,area=area,region=region):
            if not temporary: bpy.ops.node.group_edit.poll()
            if not space.path or space.path[0].node_tree!=chain[0]:
                space.path.start(chain[0])
            else:
                while len(space.path)>1: space.path.pop()
            for parent,child in zip(chain,chain[1:]):
                for node in shader_route(parent,child) or ():
                    node.id_data.nodes.active=node
                    space.path.append(node.node_tree,node=node)
        area.tag_redraw()
        return
    space.path.start(chain[0])
    for parent,child in zip(chain,chain[1:]):
        node=next((n for n in parent.nodes if getattr(n,'node_tree',None)==child),None)
        if node: space.path.append(child,node=node)
        else: space.path.start(child)
    area.tag_redraw()


def open_item(context,v,uid):
    item=resolve(uid)
    if item is None:
        rebuild(); item=resolve(uid)
    # A window modal can receive clicks without an active area after a popup.
    # Re-enter the originating browser region before touching any editor UI.
    origin=next(((w,a) for w in context.window_manager.windows for a in w.screen.areas
                 if R.views.get(akey(w,a)) is v),None)
    if origin and (context.window!=origin[0] or context.area!=origin[1]):
        w,a=origin
        region=next((r for r in a.regions if r.type=='WINDOW'),None)
        with context.temp_override(window=w,area=a,region=region):
            return open_item(context,v,uid)
    state=ui_state(context,v)
    if state is None: return
    clicked=v.get('clicked_path',())
    owner=resolve(clicked[-2]) if len(clicked)>1 else current(v)
    if isinstance(item,(bpy.types.GeometryNodeTree,bpy.types.ShaderNodeTree)) and not group_folder(item,owner):
        show_shader(context,v,item,True)
        return
    if state.query.strip() and not v.get('pin_contents') and not v.get('browse_result') and item:
        clicked=v.get('clicked_path',())
        if state.scope=='ALL' or not clicked or clicked[-1]!=uid:
            scene=resolve(v['path'][0]) if v['path'] else context.window.scene
            path=scene_path_to(item,scene)
        else:
            path=list(v['path'])+list(clicked)
        if path:
            leaf=not children(item)
            navigate(v,0,path[:-1] if leaf else path)
            if leaf: v['selected']=uid; v['multi']={uid}
            v['browse_result']=True
            v.pop('layout_key',None)
        else:
            R.message='No scene hierarchy references this data-block'
        if not path and isinstance(item,bpy.types.NodeTree) and direct_group_ids(item):
            navigate(v,uid,[uid])
            v['browse_result']=True
        if not isinstance(item,bpy.types.Image): return
    if isinstance(item,bpy.types.Image):
        result=editor_window(context,v,'image',True)
        if not result: return
        window,area=result
        area.type='IMAGE_EDITOR'
        area.spaces.active.image=item
        ptr=window.as_pointer()
        area_ptr=area.as_pointer()
        def fit():
            win=next((w for w in bpy.context.window_manager.windows if w.as_pointer()==ptr),None)
            if not win: return
            ed=next((a for a in win.screen.areas if a.as_pointer()==area_ptr and a.type=='IMAGE_EDITOR'),None)
            if ed:
                with bpy.context.temp_override(window=win,area=ed,region=next(r for r in ed.regions if r.type=='WINDOW')):
                    if bpy.ops.image.view_all.poll(): bpy.ops.image.view_all(fit_view=True)
        bpy.app.timers.register(fit,first_interval=.25)
        area.tag_redraw()
    elif item and children(item):
        path=v.get('clicked_path',())
        navigate(v,uid,v['path']+list(path) if path and path[-1]==uid else None)


class SCB_OT_native(bpy.types.Operator):
    bl_idname='scb.native'
    bl_label='QuickBrowser'
    action:StringProperty()
    path:StringProperty()
    def execute(self,context):
        v=view(context)
        if not v: return {'CANCELLED'}
        if self.action=='PIN':
            v['pin']=not v.get('pin',False)
            if v['pin']:
                v.pop('pin_target',None)
                sync_pin(context.window,v)
            space=context.area.spaces.active
            if v['pin']: space.pin_id=context.window.scene
            space.use_pin_id=v['pin']
        elif self.action=='SIDE': v['hidden']=not v.get('hidden',False)
        elif self.action=='ROOT': navigate(v,0,[])
        elif self.action=='UP': navigate(v,0,v['path'][:-1])
        elif self.action=='PATH': navigate(v,0,[int(x) for x in self.path.split('/') if x])
        elif self.action=='OPEN' and v['selected']: open_item(context,v,v['selected'])
        elif self.action=='REFRESH':
            refresh_previews()
        elif self.action=='EXIT':
            restore_nav(context.window,context.area,v)
            R.views.pop(akey(context.window,context.area),None)

        context.area.tag_redraw()
        return {'FINISHED'}


def image_nodes(material):
    pending=[material.node_tree] if material.node_tree else []
    seen=set()
    while pending:
        tree=pending.pop()
        if tree in seen: continue
        seen.add(tree)
        for node in tree.nodes:
            yield tree,node
            group=getattr(node,'node_tree',None)
            if group: pending.append(group)


def remove_material_slots(objects,materials,only=None):
    """Group identical edits so objects can keep sharing their geometry."""
    plans={}
    removed=set()
    for obj in objects:
        indices=tuple(i for i,slot in enumerate(obj.material_slots) if slot.material in materials and (only is None or only.get(i)==slot.material.session_uid))
        if not indices: continue
        if not obj.is_editable or obj.mode!='OBJECT':
            raise ValueError(f'Cannot edit material slots on {obj.name}')
        removed.update(obj.material_slots[i].material for i in indices)
        plans.setdefault(obj.data,{}).setdefault(indices,[]).append(obj)
    for data,groups in plans.items():
        # Isolate only groups whose edits would also change other users.
        for indices,owners in groups.items():
            editable=data
            if data.users!=len(owners) or not data.is_editable:
                editable=data.copy()
                for obj in owners: obj.data=editable
            obj=owners[0]
            with bpy.context.temp_override(object=obj,active_object=obj):
                for index in reversed(indices):
                    obj.active_material_index=index
                    if 'FINISHED' not in bpy.ops.object.material_slot_remove('EXEC_DEFAULT',False):
                        raise ValueError(f'Could not remove slot {index+1} from {obj.name}')
    return removed


def detach_resource(scene,item):
    materials={slot.material for obj in scene.objects for slot in obj.material_slots if slot.material}
    hits={(tree,node) for mat in materials for tree,node in image_nodes(mat) if getattr(node,'image',None)==item}
    if not hits: return False
    external={slot.material for other in bpy.data.scenes if other!=scene for obj in other.objects for slot in obj.material_slots if slot.material}
    shared={tree for mat in external for tree,node in image_nodes(mat)}
    if any(tree in shared or not tree.is_editable for tree,node in hits): return False
    item.use_fake_user=True
    for tree,node in hits: node.image=None
    return True


class SCB_OT_reveal(bpy.types.Operator):
    bl_idname='scb.reveal'
    bl_label='Reveal in Browser'
    @classmethod
    def poll(cls,context): return context.mode=='OBJECT' and context.active_object is not None
    def execute(self,context):
        windows=[context.window]+[w for w in context.window_manager.windows if w!=context.window]
        target=next(((w,a,v) for w in windows for a in w.screen.areas if (v:=R.views.get(akey(w,a))) and a.type=='PROPERTIES'),None)
        if not target:
            self.report({'WARNING'},'Open a QuickBrowser first')
            return {'CANCELLED'}
        w,a,v=target
        obj=context.active_object
        path=reveal_path(context.window.scene,obj)
        if not path: return {'CANCELLED'}
        navigate(v,0,path)
        v['selected']=obj.session_uid
        if v.get('pin'): w.scene=context.window.scene
        with context.temp_override(window=w,area=a):
            state=ui_state(context)
            state.query=''
            state.expanded=False
            for group in GROUPS:
                setattr(state,'filter_'+group,False)
            items=results(current(v),state)
            region=next(r for r in a.regions if r.type=='WINDOW')
            scale=context.preferences.system.ui_scale
            _,tile,_,_,cols=geometry(region.width,region.height,scale,v)
            if obj in items: v['scroll']=(items.index(obj)//cols)*(tile+CARD_FOOTER*scale)
        a.tag_redraw()
        return {'FINISHED'}


def reveal_menu(self,context):
    if SCB_OT_reveal.poll(context): self.layout.operator('scb.reveal',icon='FILE_FOLDER')


class SCB_OT_item_action(bpy.types.Operator):
    bl_idname='scb.item_action'
    bl_label='Data-Block Action'
    bl_options={'UNDO'}
    action:StringProperty()
    source:StringProperty()
    target:StringProperty()
    def execute(self,context):
        v=view(context)
        if self.action not in {'DELETE','UNLINK','FRAME','FAKE_USER','REFRESH','REMAP'}: return {'CANCELLED'}
        item=resolve(int(self.target) if self.target else v['selected'] if v else 0)
        if not item: return {'CANCELLED'}
        scene=next((resolve(uid) for uid in (v['path'] if v else []) if isinstance(resolve(uid),bpy.types.Scene)),context.window.scene)
        if self.action in {'DELETE','UNLINK'}:
            uid=item.session_uid
            ids=set(v.get('multi',())) if v and uid in v.get('multi',()) else {uid}
            done=set()
            blocks=[block for key in ids if (block:=resolve(key)) is not None]
            if self.action=='DELETE':
                protected=(bpy.types.Scene,bpy.types.Screen,bpy.types.WorkSpace,bpy.types.WindowManager,bpy.types.Library)
                blocks=[x for x in blocks if not (x.is_embedded_data or x.library or isinstance(x,protected))]
                done={x.session_uid for x in blocks}
                mats={x for x in blocks if isinstance(x,bpy.types.Material)}
                if mats:
                    try: remove_material_slots(bpy.data.objects,mats)
                    except ValueError as error:
                        self.report({'WARNING'},str(error))
                        return {'CANCELLED'}
                if blocks: bpy.data.batch_remove(ids=blocks)
            else:
                parent=current(v) if v else None
                for block in blocks:
                    if isinstance(block,bpy.types.Image) and block.is_editable and detach_resource(scene,block):
                        done.add(block.session_uid)
                mats={x for x in blocks if isinstance(x,bpy.types.Material) and x.is_editable}
                if mats and isinstance(parent,bpy.types.Object):
                    chosen={i:uid for obj,i,uid in v.get('slot_selection',()) if obj==parent.session_uid}
                    exact={mat for mat in mats if mat.session_uid in chosen.values()}
                    if exact:
                        try: detached=remove_material_slots([parent],exact,chosen)
                        except ValueError as error:
                            self.report({'WARNING'},str(error))
                            return {'CANCELLED'}
                        for mat in detached:
                            remember_loose(scene,mat)
                            done.add(mat.session_uid)
                        mats-=exact
                if mats:
                    entries=dict(v.get('entries',())) if v else {}
                    targets={}
                    for mat in mats:
                        path=entries.get(mat.session_uid,())
                        owner=resolve(path[-2]) if len(path)>1 else parent
                        owner=owner if isinstance(owner,bpy.types.Object) else None
                        targets.setdefault(owner,set()).add(mat)
                    scoped={}
                    for owner,subset in targets.items():
                        for obj in ((owner,) if owner else scene.objects):
                            scoped.setdefault(obj,set()).update(subset)
                    groups={}
                    for obj,subset in scoped.items():
                        groups.setdefault(frozenset(subset),[]).append(obj)
                    for subset,objects in groups.items():
                        try: detached=remove_material_slots(objects,subset)
                        except ValueError as error:
                            self.report({'WARNING'},str(error))
                            continue
                        for mat in detached:
                            remember_loose(scene,mat)
                            done.add(mat.session_uid)
                if isinstance(parent,bpy.types.Scene): parent=parent.collection
                owners_by_scene={}
                for block in blocks:
                    if isinstance(block,bpy.types.Object) and block.is_editable:
                        owner_scene=scene if block.name in scene.objects else next(iter(block.users_scene),None)
                        if owner_scene is None: continue
                        if owner_scene not in owners_by_scene:
                            root=owner_scene.collection
                            owners_by_scene[owner_scene]={root,*root.children_recursive}
                        owners=owners_by_scene[owner_scene].intersection(block.users_collection)
                        if parent in owners: owners={parent}
                        if len(owners)!=1: continue
                        col=next(iter(owners))
                        if col.is_editable:
                            block.use_fake_user=True
                            col.objects.unlink(block)
                            done.add(block.session_uid)
            if done:
                rebuild()
                if v:
                    v['slot_selection']=set()
                    v['multi']=ids-done
                    v['selected']=next(iter(v['multi']),0)
                    context.area.tag_redraw()
            if len(done)!=len(ids):
                self.report({'WARNING'},f'Processed {len(done)} of {len(ids)} selected items')
            return {'FINISHED'} if done else {'CANCELLED'}
        if isinstance(item,bpy.types.Object) and item.users_scene and scene not in item.users_scene:
            scene=context.window.scene if context.window.scene in item.users_scene else item.users_scene[0]
        if self.action=='FAKE_USER':
            if item.library or item.is_property_readonly('use_fake_user'):
                self.report({'WARNING'},'This data-block is read-only')
                return {'CANCELLED'}
            item.use_fake_user = not item.use_fake_user
            context.area.tag_redraw() if context.area else None
            return {'FINISHED'}
        if self.action=='REFRESH':
            uid=item.session_uid
            for key in list(getattr(R,'viewport_cache',{})):
                if key[0]==uid: R.viewport_cache.pop(key).free()
            refresh_previews(uid)
            context.area.tag_redraw() if context.area else None
        elif self.action=='FRAME':
            if isinstance(item,bpy.types.Material):
                mat=item
                item=parent_object(v,mat,scene) if v else None
                if not item: return {'CANCELLED'}
                item.active_material_index=next(i for i,slot in enumerate(item.material_slots) if slot.material==mat)
            if not isinstance(item,bpy.types.Object): return {'CANCELLED'}
            scene=scene if item in scene.objects[:] else next(iter(item.users_scene),None)
            if not scene: return {'CANCELLED'}
            windows=[context.window]+[w for w in context.window_manager.windows if w!=context.window]
            target=next(((w,a) for w in windows for a in w.screen.areas if a.type=='VIEW_3D'),None)
            if not target:
                self.report({'WARNING'},'Open a 3D Viewport to frame this object')
                return {'CANCELLED'}
            win,area=target
            win.scene=scene
            layer=next((vl for vl in [win.view_layer,*scene.view_layers] if item.name in vl.objects),None)
            if not layer:
                self.report({'WARNING'},'Object is excluded from all view layers')
                return {'CANCELLED'}
            win.view_layer=layer
            region=next(r for r in area.regions if r.type=='WINDOW')
            with context.temp_override(window=win,area=area,region=region):
                for other in layer.objects:
                    if other.select_get(view_layer=layer): other.select_set(False,view_layer=layer)
                item.hide_set(False,view_layer=layer)
                if area.spaces.active.local_view: item.local_view_set(area.spaces.active,True)
                item.select_set(True,view_layer=layer)
                layer.objects.active=item
                layer.update()
                if not bpy.ops.view3d.view_selected.poll(): return {'CANCELLED'}
                bpy.ops.view3d.view_selected('EXEC_DEFAULT',use_all_regions=False)
        else:
            if item.is_embedded_data or item.library or isinstance(item,(bpy.types.Scene,bpy.types.Screen,bpy.types.WorkSpace,bpy.types.WindowManager,bpy.types.Library)): return {'CANCELLED'}
            if self.action=='REMAP':
                src=resolve(int(self.source))
                if not can_replace(src,item): return {'CANCELLED'}
                if isinstance(item,bpy.types.Material):
                    owners={obj.session_uid for obj in bpy.data.objects if any(slot.material==item for slot in obj.material_slots)}
                    uid=item.session_uid
                    item.user_remap(src)
                    remember_loose(scene,item)
                    rebuild()
                    discard_previews(owners|{uid})
                    if v:
                        v['selected']=src.session_uid
                        v['multi']={src.session_uid}
                    return {'FINISHED'}
                old=item.data
                replacement=src.data
                uid=item.session_uid
                old_uid=old.session_uid
                R.generating=True
                try:
                    item.data=replacement
                    R.remap_pairs.setdefault(uid,set()).add(frozenset((old_uid,replacement.session_uid)))
                    remember_loose(scene,old)
                    context.view_layer.update()
                finally:
                    R.generating=False
                rebuild()
                discard_previews({uid,old_uid} if not resolve(old_uid) else {uid})
                return {'FINISHED'}
            return {'CANCELLED'}
        return {'FINISHED'}


def can_replace(source,target):
    if isinstance(source,bpy.types.Material) and isinstance(target,bpy.types.Material):
        return source!=target and target.is_editable and not target.library and not target.override_library
    return (isinstance(source,bpy.types.Object) and isinstance(target,bpy.types.Object)
            and source!=target and target.is_editable and not target.library
            and source.type==target.type and source.data is not None and target.data is not None
            and source.data!=target.data and type(source.data)==type(target.data))


def move_object(obj, target, source=None, keep=False):
    if not isinstance(obj,bpy.types.Object) or not isinstance(target,bpy.types.Collection):
        raise ValueError('Drop an Object onto a Collection or Scene folder')
    if not target.is_editable: raise ValueError('Target collection is read-only')
    if not keep and source and source != target and not source.is_editable:
        raise ValueError('Source collection is read-only')
    if obj.name not in target.objects: target.objects.link(obj)
    if not keep and source and source!=target and obj.name in source.objects:
        source.objects.unlink(obj)


def place_id(item, context, location):
    target=context.collection or context.scene.collection
    if not target.is_editable: raise ValueError('Target collection is read-only')
    if isinstance(item,bpy.types.Object):
        matrix=item.matrix_world.copy()
        obj=item.copy()
        obj.parent=None
        try:
            if item.data: obj.data=item.data.copy()
        except RuntimeError:
            bpy.data.objects.remove(obj)
            raise
    elif isinstance(item,bpy.types.Collection):
        obj=bpy.data.objects.new(item.name,None)
        obj.instance_type='COLLECTION'
        obj.instance_collection=item
        target=context.scene.collection  # avoid instancing inside itself
        if item==target: 
            bpy.data.objects.remove(obj)
            raise ValueError('Cannot instance the scene master collection')
    elif isinstance(item,bpy.types.Image):
        obj=bpy.data.objects.new(item.name,None)
        obj.empty_display_type='IMAGE'
        obj.data=item
    elif isinstance(item,(bpy.types.Mesh,bpy.types.Camera,bpy.types.Light,bpy.types.Curve,
                          bpy.types.Armature,bpy.types.MetaBall,bpy.types.Lattice,
                          bpy.types.Volume,bpy.types.PointCloud,bpy.types.Curves)):
        obj=bpy.data.objects.new(item.name,item)
    else: raise ValueError('This data type cannot be placed as a scene object')
    target.objects.link(obj)
    if not isinstance(item,bpy.types.Object): matrix=obj.matrix_world.copy()
    matrix.translation=location
    obj.matrix_world=matrix
    context.view_layer.update()
    if obj.name in context.view_layer.objects:
        for selected in context.selected_objects: selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active=obj
    return obj


def drop_selection(context,press,**params):
    members=dict(press.get('group') or [(press['uid'],press['source'])])
    if len(members)==1:
        uid,source=next(iter(members.items()))
        return bpy.ops.scb.drop(uid=str(uid),source=str(source),**params)
    objects=[item for uid in members if isinstance((item:=resolve(uid)),bpy.types.Object)]
    anchor=resolve(press['uid'])
    if objects and anchor not in objects: anchor=objects[0]
    origin=anchor.matrix_world.translation.copy() if objects else None
    record=not bpy.app.background and context.preferences.edit.use_global_undo
    if record: bpy.ops.ed.undo_push(message='Before group drop')
    count=0
    R.group_drop=True
    try:
        for uid,source in members.items():
            args=dict(params)
            obj=resolve(uid)
            if obj is None: continue
            if 'location' in args and isinstance(obj,bpy.types.Object):
                args['location']=Vector(args['location'])+obj.matrix_world.translation-origin
            result=bpy.ops.scb.drop(uid=str(uid),source=str(source),**args)
            count+=int('FINISHED' in result)
    finally:
        R.group_drop=False
        rebuild()
        if record and count: bpy.ops.ed.undo_push(message='QuickBrowser group drop')
    R.message=f'Dropped {count} of {len(members)} selected items'
    return {'FINISHED'} if count else {'CANCELLED'}


class SCB_OT_drop(bpy.types.Operator):
    bl_idname='scb.drop'
    bl_label='QuickBrowser Drop'
    # Explicit checkpoints are required inside the long-lived mouse modal.
    uid:StringProperty()
    target:StringProperty()
    source:StringProperty()
    hover:StringProperty()
    keep:BoolProperty()
    location:FloatVectorProperty(size=3)
    def execute(self,context):
        item=resolve(int(self.uid))
        if item is None: return {'CANCELLED'}
        record = not getattr(R,'group_drop',False) and not bpy.app.background and context.preferences.edit.use_global_undo
        if record and not R.undo_seeded:
            bpy.ops.ed.undo_push(message='Before QuickBrowser drop')
            R.undo_seeded=True
        try:
            if isinstance(item,(bpy.types.GeometryNodeTree,bpy.types.ShaderNodeTree)):
                owner=resolve(int(self.source)) if self.source else None
                modifier=root_modifier(owner,item)
                if modifier:
                    dest=resolve(int(self.target or self.hover or '0'))
                    if not isinstance(dest,bpy.types.Object) or dest.type!='MESH' or not dest.is_editable or dest==owner:
                        raise ValueError('Drop this modifier onto another editable mesh object')
                    with context.temp_override(object=owner,active_object=owner,selected_objects=[owner,dest],selected_editable_objects=[owner,dest]):
                        before=len(dest.modifiers)
                        bpy.ops.object.modifier_copy_to_selected(modifier=modifier.name)
                        if len(dest.modifiers)==before: raise ValueError('Modifier could not be copied')
                else:
                    space=context.space_data
                    tree=getattr(space,'edit_tree',None)
                    if not tree or tree.bl_idname!=item.bl_idname or not tree.is_editable or tree==item or item.contains_tree(tree):
                        raise ValueError('Drop into a compatible editable node tree')
                    node=tree.nodes.new('GeometryNodeGroup' if isinstance(item,bpy.types.GeometryNodeTree) else 'ShaderNodeGroup')
                    node.node_tree=item
                    node.location=self.location[:2]
                    tree.nodes.active=node
            elif self.target:
                target=resolve(int(self.target))
                if isinstance(target,bpy.types.Scene): target=target.collection
                source=resolve(int(self.source)) if self.source else None
                if isinstance(source,bpy.types.Scene): source=source.collection
                if isinstance(item,bpy.types.Collection):
                    if target==item or target in item.children_recursive:
                        raise ValueError('A collection cannot contain itself or an ancestor')
                    if source==target: return {'FINISHED'}
                    if not target.is_editable: raise ValueError('Target collection is read-only')
                    if not self.keep and (not source or not isinstance(source,bpy.types.Collection) or item not in source.children[:] or not source.is_editable):
                        raise ValueError('Drag from the parent collection you want to move from')
                    if item not in target.children[:]: target.children.link(item)
                    if not self.keep: source.children.unlink(item)
                else:
                    move_object(item,target,source,self.keep)
            else:
                if context.mode!='OBJECT': raise ValueError('Switch to Object Mode before placing assets')
                if isinstance(item,bpy.types.Material):
                    hit=resolve(int(self.hover)) if self.hover else None
                    if not isinstance(hit,bpy.types.Object) or not hit.is_editable or not hasattr(hit.data,'materials'):
                        raise ValueError('Drop a material onto an editable object surface')
                    if hit.material_slots:
                        slot=hit.material_slots[0]
                        if slot.material==item: return {'CANCELLED'}
                        if slot.link=='DATA' and (hit.data.users>1 or not hit.data.is_editable):
                            slot.link='OBJECT'
                        previous=slot.material
                        slot.material=item
                        if previous: remember_loose(context.scene,previous)
                    else:
                        if hit.data.users>1 or not hit.data.is_editable: hit.data=hit.data.copy()
                        hit.data.materials.append(item)
                        hit.active_material_index=0
                    discard_previews({hit.session_uid},direct=True)
                elif isinstance(item,bpy.types.World):
                    context.scene.world=item
                else:
                    place_id(item,context,Vector(self.location))
            if not getattr(R,'group_drop',False): rebuild()
            if record: bpy.ops.ed.undo_push(message='QuickBrowser drop')
            R.message='Drop completed — Ctrl+Z to undo'
            return {'FINISHED'}
        except (ValueError,RuntimeError,TypeError) as exc:
            R.message=str(exc)
            self.report({'WARNING'},str(exc))
            return {'CANCELLED'}


class SCB_OT_search(bpy.types.Operator):
    bl_idname='scb.search'
    bl_label='Search current folder'
    query:StringProperty(name='Search')
    def invoke(self,context,event):
        self.key=akey(context.window,context.area)
        self.query=R.views[self.key]['search']
        return context.window_manager.invoke_props_dialog(self,width=320)
    def draw(self,context): self.layout.prop(self,'query')
    def execute(self,context):
        v=R.views.get(self.key)
        if v: v['search']=self.query; v['scroll']=0
        return {'FINISHED'}


class SCB_OT_rename(bpy.types.Operator):
    bl_idname='scb.rename'
    bl_label='Rename'
    bl_options={'UNDO'}
    value:StringProperty(name='Name')
    batch:BoolProperty()
    actions:CollectionProperty(type=BatchRenameAction)
    def invoke(self,context,event):
        v=view(context)
        ids=(v.get('multi') or {v['selected']}) if self.batch else {v['selected']}
        self.targets=[uid for uid in sorted(ids) if (item:=resolve(uid)) and item.is_editable]
        if not self.targets: return {'CANCELLED'}
        self.value=resolve(self.targets[0]).name
        if self.batch and not self.actions: self.actions.add()
        return context.window_manager.invoke_props_dialog(self,width=460,title='Batch Rename' if self.batch else 'Rename')
    def draw(self,context):
        if not self.batch:
            self.layout.prop(self,'value'); return
        self.layout.label(text=f'{len(self.targets)} selected data-blocks')
        for act in self.actions:
            box=self.layout.box()
            box.prop(act,'type')
            fields={'SET':['set_method','set_name'],'STRIP':['strip_chars','strip_part'],'CASE':['case_method'],
                    'REPLACE':['replace_src','replace_dst','replace_match_case','use_replace_regex_src','use_replace_regex_dst']}
            for field in fields[act.type]: box.prop(act,field)
            row=box.row(align=True); row.prop(act,'op_add',text='',icon='ADD'); row.prop(act,'op_remove',text='',icon='REMOVE')
    def check(self,context):
        for i,act in enumerate(self.actions):
            if act.op_add:
                act.op_add=False; self.actions.add(); self.actions.move(len(self.actions)-1,i+1); return True
            if act.op_remove:
                act.op_remove=False
                if len(self.actions)>1: self.actions.remove(i)
                return True
        return False
    def execute(self,context):
        try:
            changes=[(item,WM_OT_batch_rename._apply_actions(self.actions,item.name) if self.batch else self.value)
                     for uid in self.targets if (item:=resolve(uid)) and item.is_editable]
        except Exception as exc:
            self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        for item,name in changes:
            if name: item.name=name
        rebuild()
        return {'FINISHED'}


def defer_item_edit(window,area,action,target,source=0):
    # Nested bpy.ops calls in a modal callback do not get their own undo step.
    window_id,screen_id,area_id=akey(window,area)
    def commit():
        if not R.alive: return
        win=next((w for w in bpy.context.window_manager.windows if w.as_pointer()==window_id),None)
        if not win: return
        browser=next((a for a in win.screen.areas if a.as_pointer()==area_id),None)
        if not browser: return
        region=next((r for r in browser.regions if r.type=='WINDOW'),None)
        if not region: return
        with bpy.context.temp_override(window=win,area=browser,region=region):
            bpy.ops.scb.item_action('EXEC_DEFAULT',True,action=action,target=str(target),source=str(source))
    bpy.app.timers.register(commit,first_interval=0.0)


class SCB_OT_open_browser(bpy.types.Operator):
    bl_idname='scb.open_browser'
    bl_label='QuickBrowser'
    @classmethod
    def poll(cls,context):
        return bool(context.area and context.area.type not in {'TOPBAR','STATUSBAR'})
    def execute(self,context):
        if not view(context):
            context.area.ui_type=TREE
        context.area.tag_redraw()
        return {'FINISHED'}
