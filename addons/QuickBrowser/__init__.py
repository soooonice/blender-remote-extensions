# SPDX-License-Identifier: GPL-3.0-or-later
from .browser_data import R
from .browser_data import TREE
from .browser_data import akey
from .browser_data import all_ids
from .browser_data import new_view
from .browser_data import rebuild
from .browser_data import sync_pin
from .browser_data import view
from .events import SCB_OT_events
from .events import clear_drag
from .events import drag_preview
from .operators import SCB_OT_drop
from .operators import SCB_OT_item_action
from .operators import SCB_OT_native
from .operators import SCB_OT_open_browser
from .operators import SCB_OT_rename
from .operators import SCB_OT_reveal
from .operators import SCB_OT_search
from .operators import reveal_menu
from .previews import affected_tiles
from .previews import discard_previews
from .previews import flush_preview_changes
from .previews import preview_changes
from .previews import run_preview_job
from .ui import SCB_BrowserTree
from .ui import SCB_MT_context
from .ui import SCB_PG_ui
from .ui import SCB_PT_directories
from .ui import draw
from .ui import header_draw
from .ui import restore_nav
from .ui import ui_state
from bpy.app.handlers import persistent
from bpy.props import CollectionProperty
import blf
import bpy
import time


def history_snapshot():
    objects={o.session_uid:o.data.session_uid if o.data else 0 for o in bpy.data.objects}
    pointers={block.session_uid:block.as_pointer() for block in all_ids()}
    return objects,pointers


@persistent
def before_history(*args):
    R.undo_snapshot=history_snapshot()
    R.generating=True


@persistent
def after_history(*args):
    try:
        before=R.undo_snapshot
        current,pointers=history_snapshot()
        rebuild()
        if before:
            objects,old_pointers=before
            removed=old_pointers.keys()-pointers.keys()
            changed={uid for uid in current.keys() & objects.keys() if objects[uid]!=current[uid]}
            remap=bool(changed) and all(frozenset((objects[u],current[u])) in R.remap_pairs.get(u,()) for u in changed)
            if remap:
                discard_previews(changed | removed)
            else:
                changed.update(uid for uid,ptr in pointers.items() if old_pointers.get(uid)!=ptr)
                discard_previews(affected_tiles(changed) | removed)
        clear_drag()
        if bpy.context.view_layer: bpy.context.view_layer.update()
    finally:
        R.undo_snapshot=None
        R.generating=False


@persistent
def invalidate(*args):
    R.geometry_outputs.clear()
    R.object_axes.clear()
    R.slot_ids.clear()
    R.glyphs.clear()
    R.material_context.clear()
    R.cards.clear()
    R.dirty_previews.clear()
    R.pending_flat.clear()
    R.curve_lines.clear()
    R.mesh_pixels.clear()
    R.textures.clear(); R.wires.clear(); R.queue.clear(); R.attempted.clear()
    R.ids.clear(); R.edges.clear(); R.last_index=0; clear_drag()
    rebuild()


@persistent
def load_reset(*args):
    R.remap_pairs.clear()
    R.scene_loose.clear()
    R.editor_returns.clear()
    invalidate()
    R.views.clear(); R.running.clear()


def tick():
    if not R.alive: return None
    preview_active=bool(R.queue or R.pending_flat or R.dirty_previews) or bpy.app.is_job_running('RENDER_PREVIEW')
    if preview_active: R.redraw_until=time.monotonic()+.8
    if R.index_dirty and R.views and not any(v.get('box') for v in R.views.values()) and time.monotonic()-R.last_index>3: rebuild()
    live=set()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            key=akey(window,area)
            live.add(key)
            if area.type=='NODE_EDITOR' and area.ui_type==TREE:
                area.type='PROPERTIES'
                area.spaces.active.pin_id=window.scene
                area.spaces.active.use_pin_id=False
                area.spaces.active.context='SCENE'
                R.views[key]=new_view()
                R.views[key]['tile_size']=ui_state(bpy.context,R.views[key]).tile_size
                nav=next((r for r in area.regions if r.type=='NAVIGATION_BAR'),None)
                if nav and nav.width>4:
                    with bpy.context.temp_override(window=window,area=area):
                        bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
                    R.views[key]['nav_hidden']=True
            if key in R.views:
                if area.type!='PROPERTIES': R.views.pop(key,None); continue
                v=R.views[key]
                space=area.spaces.active
                if v.get('pin',False)!=space.use_pin_id:
                    v['pin']=space.use_pin_id
                    v.pop('pin_target',None)
                sync_pin(window,v)
                if v.get('pin') and space.pin_id!=window.scene: space.pin_id=window.scene
                if space.context!='SCENE': space.context='SCENE'
                stamp=(R.last_index,tuple(v['path']),v.get('selected'),len(v.get('multi',())),v.get('pin'),v.get('hidden'),v.get('scroll'))
                if v.get('paint_stamp')!=stamp or time.monotonic()<getattr(R,'redraw_until',0):
                    area.tag_redraw()
                    v['paint_stamp']=stamp
                if window.as_pointer() not in R.running:
                    region=next((r for r in area.regions if r.type=='WINDOW'),None)
                    if region:
                        with bpy.context.temp_override(window=window,area=area,region=region):
                            bpy.ops.scb.events('INVOKE_DEFAULT')
    for key in R.editor_returns.keys()-live: R.editor_returns.pop(key,None)
    for key in list(R.views):
        if key not in live: R.views.pop(key)
    flush_preview_changes()
    run_preview_job()
    return .2


def install_filters():
    seen=set(); pending=list(bpy.types.Panel.__subclasses__())
    while pending:
        cls=pending.pop()
        if cls in seen: continue
        seen.add(cls); pending.extend(cls.__subclasses__())
        cls=getattr(bpy.types,cls.__name__,cls)
        if cls==SCB_PT_directories or not getattr(cls,'is_registered',False): continue
        if getattr(cls,'bl_space_type','')!='PROPERTIES' or getattr(cls,'bl_region_type','')!='WINDOW': continue
        if getattr(cls,'bl_context','') not in {'scene',''}: continue
        original=getattr(cls,'poll',None)
        had='poll' in cls.__dict__; own=cls.__dict__.get('poll')
        def wrap(fn):
            def poll(cls,context): return False if view(context) else (fn(context) if fn else True)
            return classmethod(poll)
        replacement=wrap(original)
        cls.poll=replacement
        R.filters.append((cls,had,own,replacement))
        bpy.utils.unregister_class(cls)
        bpy.utils.register_class(cls)


def unregister():
    R.type_batches.clear()
    bpy.types.VIEW3D_MT_object_context_menu.remove(reveal_menu)
    for km,binding in getattr(R,'keybindings',[]): km.keymap_items.remove(binding)
    for path,font in R.font_cache.items():
        if font>=0: blf.unload(path)
    R.font_cache.clear()
    R.alive=False; clear_drag()
    getattr(R,'viewport_cache',{}).clear()
    if bpy.app.timers.is_registered(build_initial_index): bpy.app.timers.unregister(build_initial_index)
    if bpy.app.timers.is_registered(tick): bpy.app.timers.unregister(tick)
    for space,handle in R.handles: space.draw_handler_remove(handle,'WINDOW')
    R.handles.clear()
    for cls,had,own,replacement in reversed(R.filters):
        if cls.__dict__.get('poll') is replacement:
            if had: cls.poll=own
            else: delattr(cls,'poll')
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)
    R.filters.clear()
    for handlers,fn in ((bpy.app.handlers.depsgraph_update_post,preview_changes),(bpy.app.handlers.undo_pre,before_history),(bpy.app.handlers.redo_pre,before_history),(bpy.app.handlers.undo_post,after_history),(bpy.app.handlers.redo_post,after_history),
                        (bpy.app.handlers.load_pre,load_reset)):
        if fn in handlers: handlers.remove(fn)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            v=R.views.get(akey(window,area))
            if v: restore_nav(window,area,v)
    for screen in getattr(bpy.data,'screens',()):
        for area in screen.areas:
            if area.type=='NODE_EDITOR' and area.ui_type==TREE: area.type='PROPERTIES'
            area.tag_redraw()
    from bl_ui.space_properties import PROPERTIES_HT_header
    if PROPERTIES_HT_header.draw is header_draw and R.header_original:
        PROPERTIES_HT_header.draw=R.header_original
    if hasattr(bpy.types.WindowManager,'scb_ui_states'): del bpy.types.WindowManager.scb_ui_states
    for cls in reversed(R.classes): bpy.utils.unregister_class(cls)
    R.classes.clear(); R.views.clear(); R.textures.clear(); R.wires.clear()


from .ui import QuickBrowserPreferences


def build_initial_index():
    if R.alive: rebuild()


def register():
    R.alive=True
    try:
        for cls in (QuickBrowserPreferences,SCB_PG_ui,SCB_BrowserTree,SCB_OT_open_browser,SCB_OT_drop,SCB_OT_search,SCB_OT_native,SCB_OT_reveal,SCB_OT_item_action,SCB_MT_context,SCB_PT_directories,SCB_OT_rename,SCB_OT_events):
            bpy.utils.register_class(cls); R.classes.append(cls)
        bpy.types.WindowManager.scb_ui_states=CollectionProperty(type=SCB_PG_ui)
        from bl_ui.space_properties import PROPERTIES_HT_header
        R.header_original=PROPERTIES_HT_header.draw
        PROPERTIES_HT_header.draw=header_draw
        bpy.types.VIEW3D_MT_object_context_menu.append(reveal_menu)
        install_filters()
        bpy.app.timers.register(build_initial_index,first_interval=0.0,persistent=True)
        bpy.app.handlers.depsgraph_update_post.append(preview_changes)
        bpy.app.handlers.undo_pre.append(before_history)
        bpy.app.handlers.redo_pre.append(before_history)
        bpy.app.handlers.undo_post.append(after_history)
        bpy.app.handlers.redo_post.append(after_history)
        bpy.app.handlers.load_pre.append(load_reset)
        if not bpy.app.background:
            R.handles.append((bpy.types.SpaceProperties,bpy.types.SpaceProperties.draw_handler_add(draw,(),'WINDOW','POST_PIXEL')))
            for space in bpy.types.Space.__subclasses__():
                if hasattr(space,'draw_handler_add'):
                    try: R.handles.append((space,space.draw_handler_add(drag_preview,(),'WINDOW','POST_PIXEL')))
                    except (TypeError,RuntimeError): pass
            bpy.app.timers.register(tick,first_interval=.2,persistent=True)
    except Exception:
        unregister(); raise
