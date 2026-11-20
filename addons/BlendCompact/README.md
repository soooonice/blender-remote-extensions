# BlendCompact

**Blender 工程无损压缩副本工具**

在文件菜单选择 **保存无损压缩副本**。若工程有编辑，会先保存当前工程，再在后台压缩。完成提示中可查看体积和路径。新工程请先命名保存。

## 文件与校验

- 副本与原工程在同一目录，使用 `_compact.blend` 后缀。同名副本已存在时自动编号。
- 支持普通、Gzip 和 Blender 可寻址 Zstandard 工程。输出使用可寻址 Zstandard 格式，能直接在 Blender 中打开。
- 使用最多四个工作线程，按原顺序写入数据块。完成后从磁盘读回副本，逐块解压并校验 SHA-256。
- 原文件在压缩期间被重新保存时会提示重试。退出 Blender 或禁用插件后，已启动的独立任务可继续完成，完成提示随界面关闭。
- 需要 Blender 5.3 或更高版本。使用 Blender 自带的 Python 运行；Python 3.13 使用 `zstandard`，提供 `compression.zstd` 的新版 Python 优先使用标准库。
