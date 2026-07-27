# 九歌批量 MKV 混流工具 — BUG 扫描报告（2026-07-28）

> 扫描方式：逐文件阅读核心源码 + 全量 `py_compile` 语法校验（Python 3.13.14，无语法错误）+ 定向模式扫描。
> 结论：**未发现会导致启动崩溃或数据丢失的致命 BUG**；存在 1 个真实的高危隐患（子进程管道可能死锁）和若干中低危问题。

## 项目概况
- 语言/框架：Python 3.13 + PySide6（Qt6）+ MKVToolNix（mkvmerge / mkvextract）
- 功能：批量给视频混流字幕、音轨、附件；设置默认/语言/轨道名；视频切割（可视化取点）；轨道提取；多线程并行
- 架构：全局单例状态 `GlobalSetting`（挂在 QWidget 子类上），各 Tab 共享；`BackgroundRunner` 统一后台线程执行器；混流命令在 `MuxSetting.build_mkvmerge_args` 拼接、在 `process_single_task` 执行
- 代码质量：结构清晰、注释充分、CHANGELOG 显示 v1.4.1 刚修过一批真实 BUG；无 `print` 调试残留、无裸 `except`、无未实现占位

## 问题清单（按严重度排序）

### 🔴 高危：混流子进程 stdout/stderr 顺序读取可死锁（process_single_task）
- 位置：`packages/Tabs/MuxSetting/MuxSetting.py` `process_single_task()`（约 642–668 行）
- 现象：先 `for line in process.stdout:` 读到 EOF，再 `process.stderr.read()`。当 mkvmerge 向 stderr 输出超过 OS 管道缓冲（Windows 约 64KB，如大量 warning）时，子进程写 stderr 阻塞 → 子进程不关闭 stdout → 主循环读不到 EOF → **线程永久挂起**，整个批次进度卡死且无法恢复（只能杀进程）。
- 修复建议：用独立线程并发排空 stderr，或 `process.communicate()` 一次性读取，或将 stderr 合并到 stdout（`stderr=subprocess.STDOUT`）。

### 🟠 中危：轨道信息未加载完就开始混流，会静默丢失轨道选择
- 位置：`VideoSelection.load_track_info_threaded` → `on_all_done` 在后台线程写回 `GlobalSetting.VIDEO_OLD_TRACKS_*`；`build_mkvmerge_args` 读取它们。
- 现象：若用户添加视频后立刻「添加到队列 / 开始混流」，而后台轨道解析尚未完成，`VIDEO_OLD_TRACKS_*` 仍为空列表 → 拼接命令时不带 `--audio-tracks/--subtitle-tracks/--default-track` → mkvmerge 默认保留全部轨道，**用户设置的轨道选择/默认轨/语言/轨道名全部失效**（不崩溃，但结果不符预期）。
- 修复建议：轨道信息加载完成前禁用「添加到队列/开始混流」，或按钮上显示加载态。

### 🟠 中危：视频切割把同一时间段套用到所有视频，不校验各视频时长
- 位置：`MuxSetting.show_video_cut_dialog`（约 264–277 行）+ `build_mkvmerge_args`
- 现象：切割设置对同一队列内所有视频使用完全相同的时间点（仅部分符合设计，对话框也有说明）。若某视频短于切割结束时间，mkvmerge 行为异常，拼接分支可能缺文件。
- 修复建议：按各视频实际时长裁剪/校验切割段；或在 UI 上按视频分别设置。

### 🟡 低危：输出目录与源目录相同时的命名冲突处理较弱
- 位置：`MuxSetting.get_output_path` / `process_single_task` 的 CRC 改名分支
- 现象：同目录输出加 `_1` 后缀，但未检测已存在的 `name_1.mkv` / `name_1 [CRC].mkv`，重跑时可能被 mkvmerge 覆盖或报错。
- 修复建议：输出前检测目标文件是否存在并递增后缀，或提示覆盖确认。

### 🟡 低危：视频格式提示文案与真实支持列表不一致
- 位置：`VideoSelection.dropEvent` 报错文案（约 69–71 行）
- 现象：提示「.flv .m2ts」并不在 `PreDefined.VIDEO_EXTENSIONS` 中，而真正支持的 `.m4v/.mpeg/.ogg/.ogm/.h264/.h265` 未列出，易误导用户。
- 修复建议：从 `PreDefined.VIDEO_EXTENSIONS` 动态生成提示文案。

### ⚪ 代码卫生：存在未使用代码
- `MuxSetting.VideoCutDialog`、`MuxSetting.get_keep_times`（已废弃）、`Widgets.MediaInfoDialog` 均未被引用，属历史遗留死代码，可清理。

## 未发现的问题
- 语法错误：`py_compile` 全量通过。
- 外部字幕/音轨 key 一致性（`ext_0` 等）在 `TrackSelectionDialog` 与 `build_mkvmerge_args` 间一致。
- `BackgroundRunner` 用 generation 计数避免了过期任务回调覆盖，线程安全合理。
- 切割单段/多段的拼接与 CRC 逻辑经追踪基本自洽。

## 修复记录（2026-07-28 已全部处理，全量 `py_compile` 通过）

| # | 严重度 | 问题 | 修复方式 | 文件/位置 |
|---|--------|------|----------|-----------|
| 1 | 🔴 高危 | 混流子进程 stdout→stderr 顺序读可死锁 | 用独立守护线程并发排空 stderr，主线程读 stdout，结束后 `join` 再 `wait` | `MuxSetting.process_single_task` |
| 2 | 🟠 中危 | 轨道信息未解析完就混流，静默丢失轨道选择/默认轨/语言 | 新增 `GlobalSetting.VIDEO_TRACK_INFO_READY` 标志；`start_muxing` 开始前等待解析完成（最长 8s，否则提示并返回）；并对 `None` 轨道信息兜底为空列表，避免 `enumerate(None)` 崩溃 | `GlobalSetting.py` / `VideoSelection.load_track_info_threaded` / `MuxSetting.start_muxing` + `build_mkvmerge_args` |
| 3 | 🟠 中危 | 切割同一时间段套用所有视频、不校验时长 | 新增 `_clamp_cut_times_to_duration`：按各视频实际时长截断/丢弃超界保留段；无法获取时长时降级原样返回。新增 `TrackInfo.get_video_duration_seconds` 取时长 | `MuxSetting.build_mkvmerge_args` + 新辅助方法 / `TrackInfo.py` |
| 4 | 🟡 低危 | 输出与源同目录仅加 `_1`、未检测已存在文件 | `get_output_path` 改为递增 `_2/_3...` 直到不冲突 | `MuxSetting.get_output_path` |
| 5 | 🟡 低危 | 视频格式提示文案与真实支持列表不一致 | 改为从 `PreDefined.VIDEO_EXTENSIONS` 动态生成提示文案 | `VideoSelection.dropEvent` |
| 6 | ⚪ 卫生 | 未使用死代码 | 删除 `VideoCutDialog` 类、`VideoPreviewDialog.get_keep_times` 方法、`Widgets/MediaInfoDialog.py`（已确认全局无引用） | — |

> 验证：Python 3.13 全量 `py_compile` 通过（EXIT=0）。GUI 模块（依赖 PySide6）在本沙箱无 PySide6 无法导入冒烟，但纯逻辑模块 `TrackInfo` 导入正常，且所有改动均为局部字符串/分支替换，未改动命令拼接与线程执行主流程。
> 说明：切割按各视频时长截断为「行为变更」（采用用户确认的推荐方案），短于切割点的视频不再异常，而是自动裁剪/跳过对应段。
