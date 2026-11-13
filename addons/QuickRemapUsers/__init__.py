# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import EnumProperty

# ============================================================
# Batch Remap Users - Blender 5.3
# Outliner > Blender File (LIBRARIES) > R
# ============================================================

OP_ID = "outliner.quick_batch_remap"
CLASS_NAME = "OUTLINER_OT_quick_batch_remap"

# 临时会话数据：只在弹窗打开期间使用
_SESSION = {
    "sources": [],
    "targets": [],
    "items": [],
    "id_type": "",
}


def clear_session():
    _SESSION["sources"] = []
    _SESSION["targets"] = []
    _SESSION["items"] = []
    _SESSION["id_type"] = ""


def target_items(self, context):
    # 动态 EnumProperty 的字符串必须保持有效引用
    return _SESSION["items"]


class OUTLINER_OT_quick_batch_remap(bpy.types.Operator):
    bl_idname = OP_ID
    bl_label = "Batch Remap Users"
    bl_description = "Remap selected IDs to one target"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="Remap To",
        description="Choose the destination data-block",
        items=target_items,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'OUTLINER'
            and context.space_data is not None
            and context.space_data.display_mode == 'LIBRARIES'
        )

    def invoke(self, context, event):
        clear_session()

        # 获取 Blender File 模式下选中的 ID
        try:
            selected = list(context.selected_ids)
        except (AttributeError, TypeError):
            selected = []

        # 去重，并过滤非 ID 项
        sources = []
        seen = set()

        for item in selected:
            if not isinstance(item, bpy.types.ID):
                continue

            ptr = item.as_pointer()

            if ptr not in seen:
                seen.add(ptr)
                sources.append(item)

        if not sources:
            self.report(
                {'WARNING'},
                "No data-blocks selected in Outliner"
            )
            return {'CANCELLED'}

        # 必须为同一种 ID 类型
        id_type = sources[0].bl_rna.identifier

        if any(
            item.bl_rna.identifier != id_type
            for item in sources
        ):
            self.report(
                {'ERROR'},
                "Select data-blocks of the same type"
            )
            return {'CANCELLED'}

        # 在 bpy.data 中查找同类型目标
        targets = []
        seen_targets = set()

        for prop in bpy.data.bl_rna.properties:
            name = prop.identifier

            if name == "rna_type":
                continue

            try:
                collection = getattr(bpy.data, name)
            except (AttributeError, TypeError):
                continue

            if not isinstance(
                collection,
                bpy.types.bpy_prop_collection
            ):
                continue

            try:
                candidates = list(collection)
            except (TypeError, RuntimeError):
                continue

            for item in candidates:
                if not isinstance(item, bpy.types.ID):
                    continue

                if item.bl_rna.identifier != id_type:
                    continue

                ptr = item.as_pointer()

                if ptr in seen_targets:
                    continue

                seen_targets.add(ptr)
                targets.append(item)

        # 按名称排序
        targets.sort(key=lambda x: x.name.casefold())

        if not targets:
            self.report(
                {'WARNING'},
                "No compatible target data-blocks found"
            )
            return {'CANCELLED'}

        # 保存会话
        _SESSION["sources"] = sources
        _SESSION["targets"] = targets
        _SESSION["id_type"] = id_type

        # Enum 的 identifier 使用索引，
        # 避免中文名称或重名造成标识问题
        items = []

        for i, item in enumerate(targets):
            items.append((
                str(i),
                item.name,
                f"{id_type}: {item.name}",
                i
            ))

        _SESSION["items"] = items

        # 默认目标：优先选择未包含在源列表中的数据块
        source_ptrs = {
            item.as_pointer() for item in sources
        }

        default_index = 0

        for i, item in enumerate(targets):
            if item.as_pointer() not in source_ptrs:
                default_index = i
                break

        self.target = str(default_index)

        return context.window_manager.invoke_props_dialog(
            self,
            width=180,
            title="Remap Users",
            confirm_text="Remap"
        )

    def draw(self, context):
        layout = self.layout
        sources = _SESSION["sources"]

        # 外框标题：位于框外左上角
        layout.label(
            text=f"Selected Sources ({len(sources)})"
        )

        # 源数据块列表外框
        box = layout.box()
        col = box.column(align=True)

        # 名称居中、紧凑排列
        for item in sources[:10]:
            row = col.row(align=True)
            row.alignment = 'CENTER'
            row.label(text=item.name)

        if len(sources) > 10:
            row = col.row(align=True)
            row.alignment = 'CENTER'
            row.label(
                text=f"... and {len(sources) - 10} more"
            )

        # 目标数据块下拉框
        layout.separator(factor=0.5)

        layout.prop(
            self,
            "target",
            text="Remap To"
        )

    def execute(self, context):
        sources = list(_SESSION["sources"])
        targets = _SESSION["targets"]

        try:
            index = int(self.target)
        except (ValueError, TypeError, AttributeError):
            self.report(
                {'ERROR'},
                "Invalid target selection"
            )
            clear_session()
            return {'CANCELLED'}

        if not (0 <= index < len(targets)):
            self.report(
                {'ERROR'},
                "Target is no longer available"
            )
            clear_session()
            return {'CANCELLED'}

        target = targets[index]

        # 预先检查，防止不同类型重映射
        if any(
            source.bl_rna.identifier
            != target.bl_rna.identifier
            for source in sources
        ):
            self.report(
                {'ERROR'},
                "Source and target types do not match"
            )
            clear_session()
            return {'CANCELLED'}

        count = 0
        skipped = 0

        for source in sources:
            # 不对自身重映射
            if source == target:
                skipped += 1
                continue

            try:
                source.user_remap(target)
                count += 1

            except (RuntimeError, TypeError, ValueError) as exc:
                print(
                    f"[Batch Remap] Failed: "
                    f"{source.name}: {exc}"
                )
                skipped += 1

        clear_session()

        self.report(
            {'INFO'},
            f"Remapped {count} data-blocks; "
            f"skipped {skipped}"
        )

        return {'FINISHED'}

    def cancel(self, context):
        clear_session()


# ============================================================
# Registration
# ============================================================


class QUICKREMAPUSERS_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text='QuickRemapUsers 1.0.1')
        box = layout.box()
        box.label(text='功能说明')
        col = box.column(align=True)
        col.label(text='将选中的多个同类型数据块的使用者，统一重映射到一个目标。')
        col.label(text='支持从当前文件中选择同类型目标；不会自动删除源数据块。')
        box = layout.box()
        box.label(text='使用方法')
        col = box.column(align=True)
        col.label(text='1. 将 Outliner（大纲视图）的显示模式切换为 Blender File。')
        col.label(text='2. 选择一个或多个同类型数据块，鼠标留在 Outliner 中。')
        col.label(text='3. 按 R 打开 Remap Users。')
        col.label(text='4. 在 Remap To 中选择目标，点击 Remap 执行。')
        col.label(text='5. 按 Ctrl+Z 撤销。')
        box = layout.box()
        box.label(text='使用提示')
        col = box.column(align=True)
        col.label(text='源数据块必须属于同一类型；目标本身被选中时会自动跳过。')
        col.label(text='重映射影响整个文件内对源数据块的引用，不限于当前场景。')
        col.label(text='执行前请确认目标；此工具不同于仅替换选中对象的材质槽。')
        layout.operator("wm.url_open", text="项目说明 / 更新记录", icon="URL").url = 'https://github.com/soooonice/blender-remote-extensions/tree/main/addons/QuickRemapUsers'

def unregister():
    if QUICKREMAPUSERS_AP_preferences.is_registered:
        bpy.utils.unregister_class(QUICKREMAPUSERS_AP_preferences)
    clear_session()
    wm = bpy.context.window_manager

    if wm and wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.get("Outliner")

        if km:
            for kmi in tuple(km.keymap_items):
                if kmi.idname == OP_ID:
                    km.keymap_items.remove(kmi)

    old = bpy.types.Operator.bl_rna_get_subclass_py(
        CLASS_NAME,
        None
    )

    if old:
        bpy.utils.unregister_class(old)


def register():
    unregister()
    bpy.utils.register_class(QUICKREMAPUSERS_AP_preferences)

    bpy.utils.register_class(
        OUTLINER_OT_quick_batch_remap
    )

    kc = bpy.context.window_manager.keyconfigs.addon

    if kc:
        km = kc.keymaps.new(
            name="Outliner",
            space_type='OUTLINER'
        )

        km.keymap_items.new(
            OP_ID,
            type='R',
            value='PRESS'
        )

    print("[Batch Remap] Registered")
    print("[Batch Remap] Press R in Blender File Outliner")


if __name__ == "__main__":
    register()

