# QuickScene 1.2.1 — SPDX-License-Identifier: GPL-3.0-or-later
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
    QUICKSCENE_PT_browser.bl_ui_units_x = math.ceil(sum(POPUP_WIDTHS))

def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()

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
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        if scene is None or context.window is None:
            return {'CANCELLED'}
        if self.layer and self.layer not in scene.view_layers:
            self.report({'WARNING'}, 'The view layer no longer exists')
            return {'CANCELLED'}
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
        self.name = self.layer or self.scene
        return context.window_manager.invoke_props_dialog(self, width=DIALOG_WIDTH)
    def draw(self, context):
        self.layout.prop(self, 'name', text='Name')
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        target = scene.view_layers.get(self.layer) if scene and self.layer else scene
        if target is None or not self.name.strip():
            return {'CANCELLED'}
        target.name = self.name.strip()
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
        redraw()
        return result

class QUICKSCENE_OT_new_menu(bpy.types.Operator):
    bl_idname = 'quickscene.new_menu'
    bl_label = 'New Options'
    scene: StringProperty()
    layer: StringProperty()
    def invoke(self, context, event):
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

def draw_browser_item(context, layout, item, column_width):
    is_scene = isinstance(item, bpy.types.Scene)
    scene = item if is_scene else context.window.scene
    layer = '' if is_scene else item.name
    active = (context.window.scene == item if is_scene else context.window.view_layer == item)
    # Fixed cells prevent per-name text measurements from changing the
    # minimum width of a column when the filtered item set changes.
    # The split operates inside the box: exclude its horizontal padding.
    inner_width = max(column_width - BOX_PADDING, ACTION_WIDTH + 1.0)
    row = layout.split(factor=1.0 - ACTION_WIDTH / inner_width, align=True)
    name_button = row.row(align=True)
    name_button.active_default = active
    op = name_button.template_popup_confirm('quickscene.select', text=item.name, cancel_text='', cancel_default=True)
    op.scene, op.layer = scene.name, layer
    actions = row.row(align=True)
    actions.ui_units_x = ACTION_WIDTH
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
        left_width, right_width = POPUP_WIDTHS
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
        for column, items, width in ((left, bpy.data.scenes, left_width),
                                     (right, scene.view_layers, right_width)):
            for item in sorted(items, key=lambda item: item.name.lower()):
                draw_browser_item(context, column, item, width)
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
        return bpy.ops.wm.call_panel('INVOKE_DEFAULT',
                                     name='QUICKSCENE_PT_browser', keep_open=True)

    def execute(self, context):
        prepare_widths(context)
        return bpy.ops.wm.call_panel('INVOKE_DEFAULT',
                                     name='QUICKSCENE_PT_browser', keep_open=True)


CLASSES = (QUICKSCENE_OT_select, QUICKSCENE_OT_edit, QUICKSCENE_OT_delete, QUICKSCENE_OT_new,
           QUICKSCENE_OT_new_menu, QUICKSCENE_PT_browser, QUICKSCENE_OT_open)

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
