# QuickScene 1.2.0 — SPDX-License-Identifier: GPL-3.0-or-later
# Press V in a Blender editor to open the scene/view-layer browser.
import bpy
from bpy.props import StringProperty

KEY = '_quickscene_cleanup'

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
                    bpy.ops.wm.call_panel('INVOKE_DEFAULT', name='QUICKSCENE_PT_browser', keep_open=True)
        except (ReferenceError, RuntimeError):
            pass
        return None
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
        return context.window_manager.invoke_props_dialog(self, width=180)
    def draw(self, context):
        self.layout.prop(self, 'name', text='Name')
    def execute(self, context):
        scene = bpy.data.scenes.get(self.scene)
        target = scene.view_layers.get(self.layer) if scene and self.layer else scene
        if target is None or not self.name.strip():
            return {'CANCELLED'}
        target.name = self.name.strip()
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
        return context.window_manager.invoke_props_dialog(self, width=180)
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
            if source is None or self.mode not in {'NEW', 'COPY', 'EMPTY'}:
                return {'CANCELLED'}
            context.window.view_layer = source
            with context.temp_override(scene=scene, view_layer=source):
                result = bpy.ops.scene.view_layer_add(type=self.mode)
        else:
            if self.mode not in {'NEW', 'EMPTY', 'LINK_COPY', 'FULL_COPY'}:
                return {'CANCELLED'}
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
            width = 120
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

def draw_browser_item(context, layout, item):
    is_scene = isinstance(item, bpy.types.Scene)
    scene = item if is_scene else context.window.scene
    layer = '' if is_scene else item.name
    active = (context.window.scene == item if is_scene else context.window.view_layer == item)
    # Fixed cells prevent per-name text measurements from changing the
    # minimum width of a column when the filtered item set changes.
    row = layout.split(factor=0.64, align=True)
    name_button = row.row(align=True)
    name_button.ui_units_x = 5.8
    name_button.active_default = active
    op = name_button.template_popup_confirm('quickscene.select', text=item.name, icon='SCENE_DATA' if is_scene else 'RENDERLAYERS', cancel_text='', cancel_default=True)
    op.scene, op.layer = scene.name, layer
    actions = row.row(align=True)
    actions.ui_units_x = 3.0
    for identifier, icon_name in [('quickscene.edit', 'GREASEPENCIL'), ('quickscene.new_menu', 'ADD'), ('quickscene.delete', 'TRASH')]:
        button = actions.row(align=True)
        button.ui_units_x = 1.0
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
    bl_ui_units_x = 20

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 20
        scene = context.window.scene
        columns = layout.grid_flow(row_major=True, columns=2,
                                   even_columns=True, even_rows=False, align=True)
        left, right = columns.box().column(align=True), columns.box().column(align=True)
        row_count = max(1, len(bpy.data.scenes), len(scene.view_layers))
        # Use Blender's own alphabetical-order helper, with no UIList footer.
        for column, items in ((left, bpy.data.scenes), (right, scene.view_layers)):
            order = bpy.types.UI_UL_list.sort_items_by_name(items, 'name')
            indexes = sorted(range(len(items)), key=lambda i: order[i])
            for index in indexes:
                draw_browser_item(context, column, items[index])
            for _ in range(row_count - len(items)):
                column.row().label(text='')

CLASSES = (QUICKSCENE_OT_select, QUICKSCENE_OT_edit, QUICKSCENE_OT_delete, QUICKSCENE_OT_new,
           QUICKSCENE_OT_new_menu, QUICKSCENE_PT_browser)
KEYMAPS = []

def unregister():
    for km, item in KEYMAPS:
        try: km.keymap_items.remove(item)
        except (ReferenceError, RuntimeError): pass
    KEYMAPS.clear()
    for prop in ('sv53_scene_index', 'sv53_layer_index'):
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    bpy.app.driver_namespace.pop(KEY, None)

def register():
    # Text Editor execution and loading another .blend can invalidate Python
    # globals/driver_namespace. Resolve registered classes by RNA name instead.
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for km in kc.keymaps:
            for item in list(km.keymap_items):
                if item.idname == 'wm.call_panel' and getattr(item.properties, 'name', '') == 'QUICKSCENE_PT_browser':
                    km.keymap_items.remove(item)
    KEYMAPS.clear()
    for cls in reversed(CLASSES):
        old = getattr(bpy.types, cls.__name__, None)
        if old is not None:
            bpy.utils.unregister_class(old)
    for prop in ('sv53_scene_index', 'sv53_layer_index'):
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Window', space_type='EMPTY', region_type='WINDOW')
        item = km.keymap_items.new('wm.call_panel', 'V', 'PRESS', head=True)
        item.properties.name = 'QUICKSCENE_PT_browser'
        item.properties.keep_open = True
        KEYMAPS.append((km, item))
    bpy.app.driver_namespace[KEY] = unregister

if __name__ == '__main__':
    register()
