# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess
import sys
import tempfile

import bpy

_job = None
_log = None


def _check_job():
    global _job, _log
    if _job.poll() is None:
        return 0.4
    ok = _job.returncode == 0
    _log.seek(0)
    lines = _log.read().decode("utf-8", errors="replace").strip().splitlines()[-2:]
    _log.close()
    _job = _log = None
    title = "BlendCompact · 副本已保存" if ok else "BlendCompact · 压缩失败"

    def draw(menu, context):
        for line in lines or ["后台任务未返回结果"]:
            menu.layout.label(text=line)

    if not bpy.app.background:
        bpy.context.window_manager.popup_menu(draw, title=title, icon='CHECKMARK' if ok else 'ERROR')
    return None


class WM_OT_blendcompact_copy(bpy.types.Operator):
    bl_idname = "wm.blendcompact_copy"
    bl_label = "保存无损压缩副本"
    bl_description = "保存当前工程，在同一目录生成经过校验的高压缩副本"

    @classmethod
    def poll(cls, context):
        if _job is not None:
            cls.poll_message_set("正在生成压缩副本")
            return False
        if not bpy.data.filepath:
            cls.poll_message_set("请先保存工程")
            return False
        return True

    def execute(self, context):
        global _job, _log
        if bpy.data.is_dirty and 'FINISHED' not in bpy.ops.wm.save_mainfile():
            self.report({'ERROR'}, "工程保存未完成")
            return {'CANCELLED'}
        try:
            _log = tempfile.TemporaryFile()
            _job = subprocess.Popen(
                [sys.executable, "-B", "-X", "utf8", str(Path(__file__).with_name("compact.py")), bpy.data.filepath],
                stdin=subprocess.DEVNULL, stdout=_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            if _log is not None:
                _log.close()
                _log = None
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        bpy.app.timers.register(_check_job, first_interval=0.4, persistent=True)
        self.report({'INFO'}, "BlendCompact 正在后台压缩，完成后将显示副本位置")
        return {'FINISHED'}


def _menu(self, context):
    self.layout.operator(WM_OT_blendcompact_copy.bl_idname, icon='FILE_VOLUME')


def register():
    bpy.utils.register_class(WM_OT_blendcompact_copy)
    bpy.types.TOPBAR_MT_file.append(_menu)


def unregister():
    global _job, _log
    bpy.types.TOPBAR_MT_file.remove(_menu)
    bpy.utils.unregister_class(WM_OT_blendcompact_copy)
    if bpy.app.timers.is_registered(_check_job):
        bpy.app.timers.unregister(_check_job)
    # A running worker owns its output and finishes verification independently.
    if _log is not None:
        _log.close()
    _job = _log = None
