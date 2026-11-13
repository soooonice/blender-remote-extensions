# QuickScene 1.2.4 — SPDX-License-Identifier: GPL-3.0-or-later
# Scene and view-layer browser with linked-object single-user actions.
# Press V in a Blender editor to open the scene/view-layer browser.
import bpy
import blf
import math
from bpy.props import StringProperty

KEY = '_quickscene_cleanup'
# Column widths in Blender UI units; rerun the script after changing them.
LEFT_WIDTH = 30
RIGHT_WIDTH = 15
AUTO_WIDTH = True
LEFT_MIN_WIDTH, LEFT_MAX_WIDTH = 7, 13
RIGHT_MIN_WIDTH, RIGHT_MAX_WIDTH = 4, 10
ACTION_BUTTON_WIDTH = 1.2
ACTION_WIDTH = 3 * ACTION_BUTTON_WIDTH
BOX_PADDING = 0.2
MENU_WIDTH = LEFT_WIDTH + RIGHT_WIDTH
POPUP_WIDTHS = (LEFT_WIDTH, RIGHT_WIDTH)
DIALOG_WIDTH = 200
NEW_MENU_WIDTH = 120
PENDING_TIMERS = set()
_POPUP_REGIONS = {}
_REFRESH_QUEUED = False


# Experimental cursor-anchor memory, per Blender window (session only).
POSITION_MEMORY = {}
OPEN_ANCHORS = {}

def remember_click(context, event):
    if event.type != 'LEFTMOUSE' or context.window is None:
        return
    key = context.window.as_pointer()
    anchor = OPEN_ANCHORS.get(key)
    if anchor is not None:
        scale = max(context.preferences.system.ui_scale, 0.1)
        POSITION_MEMORY[key] = ((event.mouse_x - anchor[0]) / scale,
                                (event.mouse_y - anchor[1]) / scale)

def prune_window_memory(context):
    live = {window.as_pointer() for window in context.window_manager.windows}
    for memory in (POSITION_MEMORY, OPEN_ANCHORS):
        for key in tuple(memory):
            if key not in live:
                memory.pop(key, None)

def prepare_widths(context):
    """Measure on opening and after confirmed renames, not on every draw."""
    global POPUP_WIDTHS
    if AUTO_WIDTH:
        scale = max(context.preferences.system.ui_scale, 0.1)
        points = context.preferences.ui_styles[0].widget.points
        blf.size(0, points * scale)
        def measure(items, minimum, maximum):
            pixels = 0.0
            overhead = ACTION_WIDTH + BOX_PADDING + 1.2
            limit_pixels = max(0.0, (maximum - overhead) * 20.0 * scale)
            for item in items:
                pixels = max(pixels, blf.dimensions(0, item.name)[0])
                if pixels >= limit_pixels:
                    return max(minimum, maximum)
            # Three action buttons plus text padding and box margins.
            units = math.ceil((pixels / (20.0 * scale) + ACTION_WIDTH + BOX_PADDING + 1.2) * 2) / 2
            return max(minimum, min(maximum, units))
        POPUP_WIDTHS = (
            measure(bpy.data.scenes, LEFT_MIN_WIDTH, LEFT_MAX_WIDTH),
            measure(context.window.scene.view_layers, RIGHT_MIN_WIDTH, RIGHT_MAX_WIDTH),
        )
    else:
        POPUP_WIDTHS = (LEFT_WIDTH, RIGHT_WIDTH)
    QUICKSCENE_PT_browser.bl_ui_units_x = math.ceil(sum(POPUP_WIDTHS) + (LINK_BUTTON_WIDTH if selected_active(context) else 0))

def refresh_popup_regions():
    # The native popup is a temporary region, outside screen.areas.
    for key, region in tuple(_POPUP_REGIONS.items()):
        if key not in _POPUP_WATCH:
            _POPUP_REGIONS.pop(key, None)
            continue
        try:
            region.tag_refresh_ui()
            region.tag_redraw()
        except (ReferenceError, RuntimeError):
            _POPUP_REGIONS.pop(key, None)


def redraw():
    global _REFRESH_QUEUED
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    refresh_popup_regions()
    # A one-shot follow-up runs after undo / child-menu completion has settled.
    # Multiple updates in the same event are coalesced, not continuously polled.
    if not bpy.app.background and _POPUP_REGIONS and not _REFRESH_QUEUED:
        _REFRESH_QUEUED = True
        def refresh_after_operation():
            global _REFRESH_QUEUED
            try:
                _PADDING_CACHE.clear()
                refresh_popup_regions()
            finally:
                _REFRESH_QUEUED = False
                PENDING_TIMERS.discard(refresh_after_operation)
            return None
        PENDING_TIMERS.add(refresh_after_operation)
        bpy.app.timers.register(refresh_after_operation, first_interval=0.0)

def reopen_browser(window, area):
    """Recreate popup after the confirmation dialog has finished closing."""
    if bpy.app.background:
        return
    def reopen():
        try:
            if window not in tuple(bpy.context.window_manager.windows):
                return None
            if area not in tuple(window.screen.areas):
                return None
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region and hasattr(bpy.types, 'QUICKSCENE_PT_browser'):
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.quickscene.open('INVOKE_DEFAULT')
        except (ReferenceError, RuntimeError):
            pass
        finally:
            PENDING_TIMERS.discard(reopen)
        return None
    PENDING_TIMERS.add(reopen)
    bpy.app.timers.register(reopen, first_interval=0.1)

class QUICKSCENE_OT_select(bpy.types.Operator):
    bl_idname = 'quickscene.select'
    bl_label = 'Switch Scene / View Layer'
    scene: StringProperty()
    layer: StringProperty()
    def invoke(self, context, event):
        target = bpy.data.scenes.get(self.scene)
        if context.window is None or target is None or (self.layer and self.layer not in target.view_layers):
            return {'CANCELLED'}
        remember_click(context, event)
        if not self.layer and event.type == 'LEFTMOUSE' and context.window:
            # Native popover placement follows the first active (scene) row.
            # Moving scene rows changes that baseline before our saved offset
            # is applied. Compensate once, rather than applying the row travel twice.
            scenes = sorted(bpy.data.scenes, key=lambda item: item.name.lower())
            names = [scene.name for scene in scenes]
            current = context.window.scene.name
            if current in names and self.scene in names:
                key = context.window.as_pointer()
                if key in POSITION_MEMORY:
                    dx, dy = POSITION_MEMORY[key]
                    row_delta = names.index(self.scene) - names.index(current)
                    # Native aligned button rows use one UI unit (20 px at scale 1).
                    POSITION_MEMORY[key] = (dx, dy + row_delta * 20.0)
        return self.execute(context)

    def execute(self, context):
        stop_popup_watch(context)
        scene = bpy.data.scenes.get(self.scene)
        if scene is None or context.window is None:
            return {'CANCELLED'}
        if self.layer and self.layer not in scene.view_layers:
            self.report({'WARNING'}, 'The view layer no longer exists')
            return {'CANCELLED'}
        if context.window.scene != scene:
            context.window.scene = scene
        if self.layer:
            context.window.view_layer = scene.view_layers[self.layer]
        redraw()
        return {'FINISHED'}

class QUICKSCENE_OT_edit(bpy.types.Operator):
    bl_idname = 'quickscene.edit'
    bl_label = 'Rename'
    bl_options = {'UNDO'}
    scene: StringProperty()
    layer: StringProperty()
    name: StringProperty(name='Name')
    def invoke(self, context, event):
        remember_click(context, event)
        self.name = self.layer or self.scene
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH)
    def draw(self, context):
        self.layout.prop(self, 'name', text='Name')
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        target = scene.view_layers.get(self.layer) if scene and self.layer else scene
        if target is None or not self.name.strip():
            return {'CANCELLED'}
        new_name = self.name.strip()
        if target.name == new_name:
            return {'FINISHED'}
        target.name = new_name
        # Update the existing popup's layout before Blender redraws it after
        # dismissing this child dialog. Do not open another popup at the mouse.
        prepare_widths(context)
        if context.region is not None:
            context.region.tag_redraw()
        redraw()
        return {'FINISHED'}

class QUICKSCENE_OT_delete(bpy.types.Operator):
    bl_idname = 'quickscene.delete'
    bl_label = 'Delete'
    bl_options = {'UNDO'}
    scene: StringProperty()
    layer: StringProperty()
    def invoke(self, context, event):
        remember_click(context, event)
        stop_popup_watch(context)
        self._popup_context = (context.window, context.area)
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH)
    def cancel(self, context):
        if hasattr(self, '_popup_context'):
            reopen_browser(*self._popup_context)

    def draw(self, context):
        self.layout.label(text='Delete: ' + (self.layer or self.scene), icon='ERROR')
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        if scene is None:
            return {'CANCELLED'}
        if self.layer:
            layer = scene.view_layers.get(self.layer)
            if layer is None or len(scene.view_layers) <= 1:
                self.report({'WARNING'}, 'Keep at least one view layer')
                return {'CANCELLED'}
            for window in context.window_manager.windows:
                if window.scene == scene and window.view_layer == layer:
                    window.view_layer = next(x for x in scene.view_layers if x != layer)
            scene.view_layers.remove(layer)
        else:
            if len(bpy.data.scenes) <= 1:
                self.report({'WARNING'}, 'Keep at least one scene')
                return {'CANCELLED'}
            other = next(x for x in bpy.data.scenes if x != scene)
            for window in context.window_manager.windows:
                if window.scene == scene:
                    window.scene = other
            bpy.data.scenes.remove(scene)
        redraw()
        if hasattr(self, '_popup_context'):
            reopen_browser(*self._popup_context)
        return {'FINISHED'}

class QUICKSCENE_OT_new(bpy.types.Operator):
    bl_idname = 'quickscene.new'
    bl_label = 'New'
    bl_options = {'UNDO'}
    scene: StringProperty()
    layer: StringProperty()
    mode: StringProperty(default='NEW')
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        if scene is None or context.window is None:
            return {'CANCELLED'}
        allowed = {'NEW', 'COPY', 'EMPTY'} if self.layer else {'NEW', 'EMPTY', 'LINK_COPY', 'FULL_COPY'}
        if self.mode not in allowed or (self.layer and self.layer not in scene.view_layers):
            self.report({'WARNING'}, 'Invalid target or creation mode')
            return {'CANCELLED'}
        if context.window.scene != scene:
            context.window.scene = scene
        if self.layer:
            source = scene.view_layers.get(self.layer)
            if source is None:
                return {'CANCELLED'}
            context.window.view_layer = source
            with context.temp_override(scene=scene, view_layer=source):
                result = bpy.ops.scene.view_layer_add(type=self.mode)
        else:
            result = bpy.ops.scene.new(type=self.mode)
        if 'FINISHED' in result:
            prepare_widths(context)
        redraw()
        return result

class QUICKSCENE_OT_new_menu(bpy.types.Operator):
    bl_idname = 'quickscene.new_menu'
    bl_label = 'New Options'
    scene: StringProperty()
    layer: StringProperty()
    def invoke(self, context, event):
        remember_click(context, event)
        scene_name, layer_name = self.scene, self.layer
        def draw_menu(menu, ctx):
            # Native popup menus close after executing a choice.
            width = NEW_MENU_WIDTH
            menu.layout.ui_units_x = width / 20.0
            col = menu.layout.column(align=True)
            choices = ([('NEW', 'New'), ('COPY', 'Copy Settings'), ('EMPTY', 'Blank')]
                       if layer_name else [('NEW', 'New'), ('EMPTY', 'Copy Settings'),
                                           ('LINK_COPY', 'Linked Copy'), ('FULL_COPY', 'Full Copy')])
            for mode, label in choices:
                op = col.operator('quickscene.new', text=label)
                op.scene, op.layer, op.mode = scene_name, layer_name, mode
        context.window_manager.popup_menu(draw_menu, title='New')
        return {'FINISHED'}
    def execute(self, context):
        return {'FINISHED'}


LINK_BUTTON_WIDTH = 1.2

def selected_active(context):
    vl = context.view_layer
    obj = vl.objects.active if vl else None
    return obj if obj and obj.select_get(view_layer=vl) else None

def scene_collections(scene):
    found = {}
    def walk(col):
        if col.as_pointer() in found:
            return
        found[col.as_pointer()] = col
        for child in col.children:
            walk(child)
    walk(scene.collection)
    return tuple(found.values())

def layer_settings(scene):
    records = []
    flags = ('exclude', 'hide_viewport', 'holdout', 'indirect_only')
    def walk(vl, lc, path):
        path = path + (lc.collection.as_pointer(),)
        records.append((vl.name, path, {key: getattr(lc, key) for key in flags}))
        for child in lc.children:
            walk(vl, child, path)
    for vl in scene.view_layers:
        vl.update()
        walk(vl, vl.layer_collection, ())
    return records

def restore_layer_settings(scene, records, replacements):
    remap = {key: value.as_pointer() for key, value in replacements.items()}
    wanted = {(name, tuple(remap.get(key, key) for key in path)): flags
              for name, path, flags in records}
    def walk(vl, lc, path):
        path = path + (lc.collection.as_pointer(),)
        flags = wanted.get((vl.name, path))
        if flags:
            for key, value in flags.items():
                setattr(lc, key, value)
        for child in lc.children:
            walk(vl, child, path)
    for vl in scene.view_layers:
        vl.update()
        walk(vl, vl.layer_collection, ())

def make_scene_single_user(scene, obj, mode):
    if mode not in {'OBJECT', 'DATA', 'MATERIALS'}:
        raise ValueError('Invalid mode')
    if scene.library or scene.override_library:
        raise ValueError('Target scene must be local and editable')
    if scene.objects.get(obj.name) != obj:
        raise ValueError('The object is no longer linked to this scene')
    if obj.override_library:
        raise ValueError('Library override objects are not supported in this test')
    shared_object = obj.library is not None or any(other != scene for other in obj.users_scene)
    records = layer_settings(scene)
    created, rollback, memo = [], [], {}
    foreign = {c.as_pointer() for other in bpy.data.scenes if other != scene
               for c in scene_collections(other)} if shared_object else set()
    def link(collection, item):
        collection.link(item)
        rollback.append(lambda: collection.unlink(item))
    def unlink(collection, item):
        collection.unlink(item)
        rollback.append(lambda: collection.link(item))
    def isolate(col, inherited=False):
        if col.all_objects.get(obj.name) != obj:
            return col
        key = col.as_pointer()
        if key in memo:
            return memo[key]
        shared = inherited or key in foreign or col.library is not None or col.users > 1
        result = col.copy() if shared else col
        if result != col:
            created.append(result)
        memo[key] = result
        for child in tuple(result.children):
            replacement = isolate(child, shared)
            if replacement != child:
                link(result.children, replacement)
                unlink(result.children, child)
        return result
    clone = obj
    try:
        if shared_object:
            clone = obj.copy()
            created.append(clone)
        if mode in {'DATA', 'MATERIALS'} and clone.data is not None:
            original_data = clone.data
            if original_data.users > 1 or original_data.library:
                copied = original_data.copy()
                created.append(copied)
                rollback.append(lambda: setattr(clone, 'data', original_data))
                clone.data = copied
        if mode == 'MATERIALS':
            materials = {}
            for index, slot in enumerate(clone.material_slots):
                material = slot.material
                if material and (material.users > 1 or material.library):
                    key = material.as_pointer()
                    if key not in materials:
                        materials[key] = material.copy()
                        created.append(materials[key])
                    rollback.append(lambda i=index, m=material: setattr(clone.material_slots[i], 'material', m))
                    slot.material = materials[key]
        if shared_object:
            for child in tuple(scene.collection.children):
                replacement = isolate(child)
                if replacement != child:
                    link(scene.collection.children, replacement)
                    unlink(scene.collection.children, child)
            owners = [col for col in scene_collections(scene) if col.objects.get(obj.name) == obj]
            for col in owners:
                link(col.objects, clone)
            for col in owners:
                unlink(col.objects, obj)
            restore_layer_settings(scene, records, memo)
        return clone
    except Exception:
        # Reverse all membership/data changes before removing newly created IDs.
        errors = []
        for undo in reversed(rollback):
            try:
                undo()
            except Exception as error:
                errors.append(str(error))
        if not errors and created:
            bpy.data.batch_remove(ids=created)
        try:
            restore_layer_settings(scene, records, {})
        except Exception as error:
            errors.append(str(error))
        if errors:
            raise RuntimeError('Rollback incomplete: ' + '; '.join(errors))
        raise

class QUICKSCENE_OT_single_user(bpy.types.Operator):
    bl_idname = 'quickscene.single_user'
    bl_label = 'Make Single User'
    bl_options = {'UNDO'}
    scene: StringProperty()
    object_name: StringProperty()
    object_uid: StringProperty()
    mode: StringProperty(default='OBJECT')

    def execute(self, context):
        _CHILD_MENU.discard(context.window.as_pointer())
        scene = bpy.data.scenes.get(self.scene)
        obj = bpy.data.objects.get(self.object_name)
        if scene is None or obj is None or str(obj.session_uid) != self.object_uid:
            self.report({'WARNING'}, 'The source object or scene has changed')
            return {'CANCELLED'}
        # Preserve the active/selected state when separating the current scene.
        states = []
        for vl in scene.view_layers:
            if vl.objects.get(obj.name) == obj:
                states.append((vl, vl.objects.active == obj, obj.select_get(view_layer=vl)))
        try:
            clone = make_scene_single_user(scene, obj, self.mode)
        except (RuntimeError, ValueError, TypeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        for vl, active, selected in states:
            vl.update()
            if vl.objects.get(clone.name) == clone:
                clone.select_set(selected, view_layer=vl)
                if active:
                    vl.objects.active = clone
        prepare_widths(context)
        if context.region:
            context.region.tag_redraw()
        redraw()
        return {'FINISHED'}

class QUICKSCENE_OT_single_menu(bpy.types.Operator):
    bl_idname = 'quickscene.single_menu'
    bl_label = 'Make Single User'
    bl_description = 'Make the selected active object single-user in this scene only'
    scene: StringProperty()
    object_name: StringProperty()
    object_uid: StringProperty()

    def invoke(self, context, event):
        if context.region_popup is not None:
            _POPUP_REGIONS[context.window.as_pointer()] = context.region_popup
        _CHILD_MENU.add(context.window.as_pointer())
        remember_click(context, event)
        scene_name, name, uid = self.scene, self.object_name, self.object_uid
        def draw_menu(menu, ctx):
            menu.layout.ui_units_x = 10
            for mode, label in (('OBJECT','Object'), ('DATA','Object&Data'),
                                ('MATERIALS','Object&Data&Materials')):
                op = menu.layout.operator('quickscene.single_user', text=label)
                op.scene, op.object_name, op.object_uid, op.mode = scene_name, name, uid, mode
        context.window_manager.popup_menu(draw_menu, title='Make Single User')
        return {'FINISHED'}

PAD_NAMES = True
_PADDING_CACHE = {}

def padded_names(context, items, column_width, column_key):
    names = tuple(item.name for item in items)
    scale = max(context.preferences.system.ui_scale, 0.1)
    points = context.preferences.ui_styles[0].widget.points
    signature = (names, column_width, scale, points, PAD_NAMES)
    cached = _PADDING_CACHE.get(column_key)
    if cached and cached[0] == signature:
        return cached[1]
    labels = dict.fromkeys(names)
    if not PAD_NAMES:
        labels = {name: name for name in names}
    else:
        blf.size(0, points * scale)
        widths = {name: blf.dimensions(0, name)[0] for name in names}
        # Do not widen the accepted layout just to accommodate padding.
        available = max(0.0, (column_width - ACTION_WIDTH - BOX_PADDING - 1.2) * 20.0 * scale)
        target = min(max(widths.values(), default=0.0), available)
        space = max(blf.dimensions(0, ' ')[0], 0.01)
        for name, width in widths.items():
            count = max(0, min(512, int((target - width) / space)))
            label = name + ' ' * count
            # Account for font metrics and never introduce clipping with padding.
            while count and blf.dimensions(0, label)[0] > target:
                count -= 1
                label = name + ' ' * count
            labels[name] = label
    _PADDING_CACHE[column_key] = (signature, labels)
    return labels


def draw_browser_item(context, layout, item, column_width, display_name, link_object=None):
    is_scene = isinstance(item, bpy.types.Scene)
    scene = item if is_scene else context.window.scene
    layer = '' if is_scene else item.name
    active = (context.window.scene == item if is_scene else context.window.view_layer == item)
    # Fixed cells prevent per-name text measurements from changing the
    # minimum width of a column when the filtered item set changes.
    # The split operates inside the box: exclude its horizontal padding.
    action_width = ACTION_WIDTH + (LINK_BUTTON_WIDTH if is_scene and link_object else 0.0)
    inner_width = max(column_width - BOX_PADDING, action_width + 1.0)
    row = layout.split(factor=1.0 - action_width / inner_width, align=True)
    name_button = row.row(align=True)
    name_button.active_default = active
    name_button.operator_context = 'INVOKE_DEFAULT'
    op = name_button.template_popup_confirm('quickscene.select', text=display_name, cancel_text='', cancel_default=True)
    op.scene, op.layer = scene.name, layer
    actions = row.row(align=True)
    actions.ui_units_x = action_width
    for identifier, icon_name in [('quickscene.edit', 'BACK'), ('quickscene.new_menu', 'ADD'), ('quickscene.delete', 'REMOVE')]:
        button = actions.row(align=True)
        button.ui_units_x = ACTION_BUTTON_WIDTH
        if identifier == 'quickscene.delete':
            button.enabled = len(bpy.data.scenes if is_scene else scene.view_layers) > 1
        button.operator_context = 'INVOKE_DEFAULT'
        if identifier == 'quickscene.delete':
            # Close the parent popup before showing the confirmation dialog.
            op = button.template_popup_confirm(identifier, text=' ', icon=icon_name, cancel_text='', cancel_default=True)
        else:
            op = button.operator(identifier, text='', icon=icon_name)
        op.scene, op.layer = scene.name, layer
    if is_scene and link_object:
        button = actions.row(align=True)
        button.ui_units_x = LINK_BUTTON_WIDTH
        button.enabled = scene.objects.get(link_object.name) == link_object
        button.operator_context = 'INVOKE_DEFAULT'
        op = button.operator('quickscene.single_menu', text='', icon='LINKED')
        op.scene, op.object_name, op.object_uid = scene.name, link_object.name, str(link_object.session_uid)



def undo_context(context):
    area = context.area
    if area is None:
        return None
    return next((region for region in area.regions if region.type == 'WINDOW'), None)

class QUICKSCENE_OT_popup_undo(bpy.types.Operator):
    bl_idname = 'quickscene.popup_undo'
    bl_label = 'Undo Last Operation'
    bl_description = 'Undo the latest Blender operation and refresh this popup'
    # Deliberately no UNDO flag: undo itself must not create another undo step.

    @classmethod
    def poll(cls, context):
        if context.window is None or undo_context(context) is None:
            return False
        with context.temp_override(region=undo_context(context)):
            return bpy.ops.ed.undo.poll()

    def execute(self, context):
        # Preserve only window/area references across undo, never scene/object IDs.
        window, area = context.window, context.area
        region = undo_context(context)
        if window is None or area is None or region is None:
            return {'CANCELLED'}
        with context.temp_override(window=window, area=area, region=region):
            if not bpy.ops.ed.undo.poll():
                return {'CANCELLED'}
            result = bpy.ops.ed.undo()
        if 'FINISHED' in result:
            _PADDING_CACHE.clear()
            # Reacquire all scene and layer data after Blender's undo rebuild.
            with context.temp_override(window=window, area=area, region=region):
                prepare_widths(bpy.context)
            redraw()
        return result


_WATCH_TIMERS = {}
_CHILD_MENU = set()
_POPUP_WATCH = {}
_POPUP_BOUNDS = {}

def stop_popup_watch(context):
    if context.window:
        key = context.window.as_pointer()
        _POPUP_WATCH.pop(key, None)
        _POPUP_REGIONS.pop(key, None)
        _POPUP_BOUNDS.pop(key, None)
        _CHILD_MENU.discard(key)

class QUICKSCENE_OT_undo_watch(bpy.types.Operator):
    bl_idname = 'quickscene.undo_watch'
    bl_label = 'QuickScene Popup Keyboard'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._key = context.window.as_pointer()
        self._token = object()
        _POPUP_WATCH[self._key] = self._token
        self._area = context.area
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        _WATCH_TIMERS[self._token] = self._timer
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def finish(self, context):
        timer = _WATCH_TIMERS.pop(self._token, None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
        self._timer = None
        if _POPUP_WATCH.get(self._key) is self._token:
            _POPUP_WATCH.pop(self._key, None)
            _POPUP_REGIONS.pop(self._key, None)
            _POPUP_BOUNDS.pop(self._key, None)
            _CHILD_MENU.discard(self._key)
        return {'FINISHED'}

    def modal(self, context, event):
        if _POPUP_WATCH.get(self._key) is not self._token:
            return self.finish(context)
        if event.type in {'ESC', 'RIGHTMOUSE'} and self._key in _CHILD_MENU:
            _CHILD_MENU.discard(self._key)
            return {'PASS_THROUGH'}
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'}:
            self.finish(context)
            return {'FINISHED', 'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            bounds = _POPUP_BOUNDS.get(self._key)
            if bounds and bounds[0] <= event.mouse_x <= bounds[2] and bounds[1] <= event.mouse_y <= bounds[3]:
                _CHILD_MENU.discard(self._key)
            if self._key not in _CHILD_MENU and bounds and not (bounds[0] <= event.mouse_x <= bounds[2] and
                               bounds[1] <= event.mouse_y <= bounds[3]):
                # Do not capture editor shortcuts after an outside click closes the popup.
                self.finish(context)
                return {'FINISHED', 'PASS_THROUGH'}
        if event.type == 'Z' and event.ctrl and not event.shift and not event.alt:
            if event.value == 'PRESS':
                try:
                    with context.temp_override(area=self._area):
                        if bpy.ops.quickscene.popup_undo.poll():
                            bpy.ops.quickscene.popup_undo()
                except (ReferenceError, RuntimeError):
                    self.finish(context)
                    return {'FINISHED'}
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        self.finish(context)


def open_with_keyboard(context):
    result = bpy.ops.wm.call_panel('INVOKE_DEFAULT', name='QUICKSCENE_PT_browser', keep_open=True)
    if 'INTERFACE' in result:
        # Install after the native popup so Ctrl+Z is seen before its event handler.
        bpy.ops.quickscene.undo_watch('INVOKE_DEFAULT')
    return result

class QUICKSCENE_PT_browser(bpy.types.Panel):
    bl_label = 'Scenes & View Layers'
    bl_idname = 'QUICKSCENE_PT_browser'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_ui_units_x = MENU_WIDTH

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def draw(self, context):
        layout = self.layout
        popup_region = context.region_popup
        if popup_region is not None and context.window:
            key = context.window.as_pointer()
            _POPUP_REGIONS[key] = popup_region
            _POPUP_BOUNDS[key] = (popup_region.x, popup_region.y,
                                  popup_region.x + popup_region.width,
                                  popup_region.y + popup_region.height)
        link_object = selected_active(context)
        left_width, right_width = POPUP_WIDTHS
        if link_object:
            left_width += LINK_BUTTON_WIDTH
        total_width = left_width + right_width
        layout.ui_units_x = total_width
        scene = context.window.scene
        columns = layout.split(factor=left_width / total_width, align=True)
        left_box = columns.box()
        right_box = columns.box()
        left_box.ui_units_x = left_width
        right_box.ui_units_x = right_width
        left, right = left_box.column(align=True), right_box.column(align=True)
        row_count = max(1, len(bpy.data.scenes), len(scene.view_layers))
        # Use Blender's own alphabetical-order helper, with no UIList footer.
        for column, items, width, cache_key in ((left, bpy.data.scenes, left_width, 'scenes'),
                                                (right, scene.view_layers, right_width, 'layers')):
            labels = padded_names(context, items, width - (LINK_BUTTON_WIDTH if cache_key == 'scenes' and link_object else 0), cache_key)
            for item in sorted(items, key=lambda item: item.name.lower()):
                draw_browser_item(context, column, item, width, labels[item.name], link_object)
            for _ in range(row_count - len(items)):
                column.row().label(text='')

class QUICKSCENE_OT_open(bpy.types.Operator):
    bl_idname = 'quickscene.open'
    bl_label = 'QuickScene'
    bl_description = 'Open the QuickScene browser'

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def invoke(self, context, event):
        prepare_widths(context)
        prune_window_memory(context)
        window = context.window
        key = window.as_pointer()
        original = (event.mouse_x, event.mouse_y)
        scale = max(context.preferences.system.ui_scale, 0.1)
        delta = POSITION_MEMORY.get(key, (0.0, 0.0))
        anchor = (max(1, min(window.width - 2, round(original[0] - delta[0] * scale))),
                  max(1, min(window.height - 2, round(original[1] - delta[1] * scale))))
        OPEN_ANCHORS[key] = anchor
        if anchor == original:
            return open_with_keyboard(context)
        # cursor_warp updates Blender's eventstate synchronously.
        # Construct the popup at the shifted anchor and restore the pointer
        # within this invocation; no timer or intermediate redraw is needed.
        try:
            window.cursor_warp(*anchor)
            return open_with_keyboard(context)
        finally:
            window.cursor_warp(*original)

    def execute(self, context):
        prepare_widths(context)
        OPEN_ANCHORS.pop(context.window.as_pointer(), None)
        return open_with_keyboard(context)



class QUICKSCENE_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text='QuickScene 1.2.4')
        box = layout.box()
        box.label(text='功能说明')
        col = box.column(align=True)
        col.label(text='快速切换场景和视图层；两列分别自适应名称宽度。')
        col.label(text='支持重命名、新建、删除，以及菜单位置记忆。')
        col.label(text='选中活动对象时显示 Link 按钮，标识使用同一对象的场景。')
        col.label(text='Link 菜单可将目标场景中的对象、数据、材质设为单用户。')
        box = layout.box()
        box.label(text='使用方法')
        col = box.column(align=True)
        col.label(text='1. 鼠标移到编辑区域，按 V 打开菜单。')
        col.label(text='2. 点击名称切换；右侧按钮依次为重命名、新建、删除。')
        col.label(text='3. 选中活动对象，点击目标场景右侧可用的 Link 按钮。')
        col.label(text='4. 选择 Object / Object&Data / Object&Data&Materials。')
        col.label(text='5. 菜单内按 Ctrl+Z 撤销最近一步操作，列表自动刷新。')
        box = layout.box()
        box.label(text='使用提示')
        col = box.column(align=True)
        col.label(text='未选中活动对象时不显示 Link 按钮；多选时仅判断活动对象。')
        col.label(text='Link 表示同一个对象，不包括仅共用网格的不同对象。')
        col.label(text='单用户分离仅针对目标场景；库覆盖对象暂不支持。')
        col.label(text='快捷键可能与其他操作冲突，可在偏好设置的键位映射中调整。')
        layout.operator("wm.url_open", text="项目说明 / 更新记录", icon="URL").url = 'https://github.com/soooonice/blender-remote-extensions/tree/main/addons/QuickScene'

CLASSES = (QUICKSCENE_AP_preferences, QUICKSCENE_OT_select, QUICKSCENE_OT_edit, QUICKSCENE_OT_delete, QUICKSCENE_OT_new,
           QUICKSCENE_OT_new_menu, QUICKSCENE_OT_single_user, QUICKSCENE_OT_single_menu, QUICKSCENE_OT_popup_undo, QUICKSCENE_OT_undo_watch, QUICKSCENE_PT_browser, QUICKSCENE_OT_open)

def remove_keymaps():
    # Resolve fresh RNA objects: stored keymap handles can become invalid.
    config = bpy.context.window_manager.keyconfigs.addon
    if config is None:
        return
    for km in config.keymaps:
        for item in list(km.keymap_items):
            if item.idname == 'quickscene.open' or (
                    item.idname == 'wm.call_panel' and
                    getattr(item.properties, 'name', '') == 'QUICKSCENE_PT_browser'):
                km.keymap_items.remove(item)


def unregister():
    for timer in tuple(_WATCH_TIMERS.values()):
        bpy.context.window_manager.event_timer_remove(timer)
    _WATCH_TIMERS.clear()
    global _REFRESH_QUEUED
    _REFRESH_QUEUED = False
    _POPUP_REGIONS.clear()
    _CHILD_MENU.clear()
    _POPUP_WATCH.clear()
    _POPUP_BOUNDS.clear()
    _PADDING_CACHE.clear()
    POSITION_MEMORY.clear()
    OPEN_ANCHORS.clear()
    for callback in tuple(PENDING_TIMERS):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    PENDING_TIMERS.clear()
    remove_keymaps()
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    if bpy.app.driver_namespace.get(KEY) is unregister:
        bpy.app.driver_namespace.pop(KEY, None)


def register():
    previous = bpy.app.driver_namespace.get(KEY)
    if callable(previous) and previous is not unregister:
        try:
            previous()
        except (ReferenceError, RuntimeError, UnicodeError) as error:
            print('QuickScene: recovering previous registration:', repr(error))
    unregister()
    for cls in reversed(CLASSES):
        old = getattr(bpy.types, cls.__name__, None)
        if old is not None:
            bpy.utils.unregister_class(old)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    # Installed extensions use the add-on keyconfig, merged by Blender.
    config = bpy.context.window_manager.keyconfigs.addon
    if config is not None:
        for name, space in (('Window', 'EMPTY'), ('3D View', 'VIEW_3D')):
            km = config.keymaps.new(name=name, space_type=space, region_type='WINDOW')
            km.keymap_items.new('quickscene.open', 'V', 'PRESS', head=True)
    bpy.app.driver_namespace[KEY] = unregister


if __name__ == '__main__':
    register()
