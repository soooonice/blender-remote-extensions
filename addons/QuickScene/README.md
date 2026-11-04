# QuickScene

**QuickScene — Blender 场景与视图层快速切换工具**

一款轻量级 Blender 插件，通过全局快捷键快速切换场景（Scene）和视图层（View Layer），减少在不同编辑器之间切换和查找场景选择器的操作。

## 主要功能

- **快速切换场景**：自动列出当前 Blender 文件中的全部场景，点击即可切换。
- **快速切换视图层**：列出当前场景中的所有视图层，支持直接切换。
- **全局快捷键**：默认使用 `V` 键呼出菜单，适用于 3D 视图、视频序列编辑器（VSE）等编辑区域。
- **双列菜单**：左侧显示 Scenes，右侧显示 View Layers，方便查看和选择。
- **当前项标识**：使用选中状态图标标记当前场景和视图层。
- **轻量化设计**：不添加额外的 N 面板，不占用工作空间。

## 安装方法

### 方式一：本地安装

1. 打开 Blender。
2. 进入 `Edit → Preferences → Get Extensions`。
3. 选择 `Install from Disk`。
4. 选择 QuickScene 的 ZIP 安装包。
5. 完成安装并启用插件。

### 方式二：远程仓库安装

1. 进入 `Edit → Preferences → Get Extensions`。
2. 在 Repositories 中添加包含 QuickScene 的远程扩展仓库地址。
3. 同步远程仓库。
4. 搜索 `QuickScene` 并安装。

## 使用方法

将鼠标移动到 Blender 编辑区域，按下 `V` 键。

弹出菜单包含两列：

| Scenes | View Layers |
|---|---|
| 当前文件中的所有场景 | 当前场景中的所有视图层 |
| 点击场景名称进行切换 | 点击视图层名称进行切换 |
| 标识当前活动场景 | 标识当前活动视图层 |

菜单内容会根据当前 Blender 文件动态更新，无需手动刷新。

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `V` | 打开 QuickScene 切换菜单 |
| `Esc` | 关闭菜单 |

默认快捷键可能与其他插件或 Blender 内置操作发生冲突，可通过 Blender 的 Keymap 设置进行调整。

## 兼容性

- **Blender 版本**：5.2 及以上
- **操作系统**：Windows / macOS / Linux（使用 Blender 标准 Python API）
- **插件类型**：Blender Extension

## 注意事项

1. 切换视图层时，仅显示当前活动场景所属的视图层。
2. 切换场景后，重新打开菜单即可查看新场景的视图层。
3. 快捷键作用范围受 Blender 当前编辑器和模态操作影响。
4. 禁用插件后，其注册的快捷键会被移除。

## 版本与更新

当前版本：**1.0.0**

详细更新记录请查看 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

GPL-3.0-or-later