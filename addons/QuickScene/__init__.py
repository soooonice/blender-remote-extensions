
import bpy

MENU_ID = "QUICKSCENE_MT_switcher"

addon_keymaps = []


class QUICKSCENE_OT_switch_scene(bpy.types.Operator):
    bl_idname = "quickscene.switch_scene"
    bl_label = "Switch Scene"
    bl_description = "Switch to the selected scene"
    bl_options = {'INTERNAL'}

    scene_name: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return f"Switch to scene: {properties.scene_name}"

    def execute(self, context):
        window = context.window
        scene = bpy.data.scenes.get(self.scene_name)

        if window is None or scene is None:
            return {'CANCELLED'}

        window.scene = scene
        return {'FINISHED'}


class QUICKSCENE_OT_switch_view_layer(bpy.types.Operator):
    bl_idname = "quickscene.switch_view_layer"
    bl_label = "Switch View Layer"
    bl_description = "Switch to the selected view layer"
    bl_options = {'INTERNAL'}

    layer_name: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return f"Switch to view layer: {properties.layer_name}"

    def execute(self, context):
        window = context.window

        if window is None:
            return {'CANCELLED'}

        layer = window.scene.view_layers.get(self.layer_name)

        if layer is None:
            return {'CANCELLED'}

        window.view_layer = layer
        return {'FINISHED'}


class QUICKSCENE_MT_switcher(bpy.types.Menu):
    bl_idname = MENU_ID
    bl_label = ""

    def draw(self, context):
        window = context.window

        if window is None:
            self.layout.label(text="No active window")
            return

        scene = window.scene
        active_layer = window.view_layer

        row = self.layout.row()

        # Scenes
        scene_col = row.column(align=True)
        scene_col.label(text="Scenes", icon='SCENE_DATA')
        scene_col.separator()

        for item in bpy.data.scenes:
            op = scene_col.operator(
                QUICKSCENE_OT_switch_scene.bl_idname,
                text=item.name,
                icon=(
                    'RADIOBUT_ON'
                    if item == scene
                    else 'RADIOBUT_OFF'
                )
            )
            op.scene_name = item.name

        # View Layers
        layer_col = row.column(align=True)
        layer_col.label(
            text="View Layers",
            icon='RENDERLAYERS'
        )
        layer_col.separator()

        for item in scene.view_layers:
            op = layer_col.operator(
                QUICKSCENE_OT_switch_view_layer.bl_idname,
                text=item.name,
                icon=(
                    'RADIOBUT_ON'
                    if item == active_layer
                    else 'RADIOBUT_OFF'
                )
            )
            op.layer_name = item.name


CLASSES = (
    QUICKSCENE_OT_switch_scene,
    QUICKSCENE_OT_switch_view_layer,
    QUICKSCENE_MT_switcher,
)


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if kc is None:
        return

    km = kc.keymaps.new(
        name="Window",
        space_type='EMPTY',
        region_type='WINDOW'
    )

    kmi = km.keymap_items.new(
        "wm.call_menu",
        type='V',
        value='PRESS'
    )

    kmi.properties.name = MENU_ID
    addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass

    addon_keymaps.clear()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    register_keymaps()


def unregister():
    unregister_keymaps()

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
