# GTAVSidecar

GTA5 辅助后台工具集 — 通过视觉识别（4K RGBA 透明覆盖图匹配）检测游戏画面 UI 元素，自动执行鼠标点击、键盘操作或进程操作。

## 目录结构

```
GTAVSidecar/
├── main.py              # 事件循环 + TUI + anti_afk 管理
├── config.json          # 配置文件（热重载 + 持久化）
├── core/                # 共享核心模块
│   ├── __init__.py      # 统一导出 + _INJECT_SYMBOLS 组装
│   ├── i18n.py          # 翻译引擎
│   ├── log_buffer.py    # 日志缓冲 + 文件持久化
│   ├── config.py        # 配置管理 + Steam 语言检测 + 模块加载
│   ├── windows_api.py   # Win32 API 封装（窗口/截图/输入/进程）
│   ├── resource_monitor.py # CPU/内存采样 + 游戏状态检测
│   ├── task_base.py     # BaseTask + OverlayMatcher
│   ├── task_runner.py   # TaskRunner 状态机
│   ├── task_registry.py # 任务自动扫描注册
│   ├── game_lifecycle.py # 游戏进程生命周期管理
│   └── renderer.py      # TUI 面板构建 + 颜色常量
├── locales/             # UI 翻译（zh_CN.json / zh_TW.json / en_US.json）
└── tasks/               # 任务目录，每个自包含
    ├── bunker_fast_track_research/     # 覆盖图匹配 + 点击
    ├── close_game_at_results/          # 覆盖图匹配 + 进程终止
    ├── hack_solver_connect_host/        # OCR + BFS寻路（连接主机）
    ├── hack_solver_voltlab/            # OCR + 排列求解（电压连线）
    ├── hack_solver_bruteforce/         # 坐标采样 + 红色像素检测（暴力破解）
    ├── create_invite_only/             # 纯按键序列
    ├── join_online/                    # PID 追踪 + 鼠标移动 + 回车
    ├── anti_afk/                       # 防挂机定时按键
    └── show_performance/               # 性能显示开关
```

## 架构

### 任务基类

```python
class Task(BaseTask):
    group = None                    # 分组标识（如 "hack_solver"）
    start_trigger = {}              # 开始触发器配置，{} 表示无触发直接执行
    steps = []                      # 步骤序列
    step_timeout_ms = 30000         # 步骤超时
    run_once = False                # True = 执行后自动禁用
    default_config = {}             # 自定义配置默认值，首次运行时自动合并到 config.json
```

**三种任务模式**：

| 模式 | `start_trigger` | `steps` | 说明 |
|------|----------------|---------|------|
| 按键序列 | `{}` | `[{"delay": N, "key": "x"}]` | 执行一次后自动禁用（如创建邀请战局） |
| 触发+步骤 | `{"overlay": "trigger"}` | `[{"overlay": "step1"}]` | 检测触发→按序执行→循环（如地堡加速） |
| 触发+hack | `{"overlay": "trigger", "click": False}` | `[{"overlay": "hack", "action": "hack"}]` | 覆写 `execute_step` 调用自定义 solver |

**`run_once` 机制**：任务执行完成后自动将 `enabled` 设为 `False` 并停止。开启后持续扫描直到检测到 trigger 并完成执行后才停用，首次扫描无 trigger 不会提前失败。`run_once = False` 时任务循环运行，完成后回到扫描等待阶段。

**`default_config` 机制**：Task 类定义 `default_config` 字典，`TaskRegistry.build_config()` 自动合并。新任务添加自定义配置项时只需在 Task 类定义 `default_config`，无需修改 config.py。

**符号注入**：`task.py` 可直接使用 `BaseTask`、`OverlayMatcher`、`send_key`、`capture_window`、`focus_game_window`、`clip_cursor_to_window`、`unclip_cursor`、`get_client_offset`、`move_cursor_to`、`_find_pid_by_name`、`C_RED`、`C_GREEN`、`C_YELLOW`、`C_RESET`、`C_HIGHLIGHT`、`translate`、`_log_buffer` 等符号（由 `core/__init__.py` 注入），标准库和第三方库仍需显式 import。

### TaskRunner 状态机

双频检测：等待阶段低频（全局 `scan_ms`），执行阶段高频（`task.scan_ms`）。检测到 `start_trigger` → 执行步骤序列 → 全部完成后回到等待阶段。游戏未运行时暂停，等待 `GameLifecycleManager` 唤醒。

**状态重置**：`_reset_state()` 提取为共用方法，重置 `_sequence_started`、`_current_step`、`_timeout_count`、`_last_confidence`。`stop()`（外部调用）和 `_disable_and_stop_in_config()`（工作线程内部）均调用此方法。

**工作线程内停止**：`_disable_and_stop_in_config()` 直接设置 `_running=False` + `_status="stopped"` + `_reset_state()`，不可调用 `stop()`（后者会 `join` 当前线程导致 `RuntimeError`）。

### 覆盖图匹配

基于 4K RGBA 透明 PNG，不透明像素定义匹配目标，`cv2.absdiff` + mask 加权计算置信度（阈值 0.95）。支持固定位置和水平扫描两种模式。

**坐标采样替代方案**：当覆盖图仅用于定位固定位置的 UI 元素（如 bruteforce 的 8 个方框），可在 `load()` 阶段从 `OverlayMatcher.bbox` 提取坐标缓存，运行时直接采样像素检测，避免每帧执行 absdiff。适合高频扫描场景（如 50ms 间隔）。

### 键盘输入

使用**硬件扫描码** + `KEYEVENTF_SCANCODE`（RAGE 引擎/DirectInput 不响应虚拟键码）。`send_key()` 内部 `w/a/s/d` 映射为方向键扫描码。

### 配置管理

**配置文件**：`config.json`，通过 mtime 检测变更，`TaskRunner` 每轮循环检查并 `reload()`。

**配置结构**：

```json
{
    "lang": "auto",
    "scan_ms": 2000,
    "anti_afk": {"enabled": false, "key": "enter", "interval_min": 10},
    "create_invite_only": {"enabled": false, "scan_ms": 500},
    "hack_solver": {
        "voltlab": {"enabled": false, "scan_ms": 500},
        "connect_host": {"enabled": false, "scan_ms": 500, "auto_enter": false},
        "bruteforce": {"enabled": false, "scan_ms": 50}
    }
}
```

- 分组任务的 `group` 在 `task.py` 类属性中定义，组键作为 `config.json` 的一级键，子任务为二级键
- 任务顺序由 `TaskRegistry` 的 `order` 字段自动排序

**TaskRegistry**：启动时一次性扫描 `tasks/` 目录（< 10ms），自动发现注册任务元数据。提供 `build_config()`（合并 `default_config` 生成配置）、`get_task_info()`、`is_task_group()`、`extract_sub_name()` 等方法。使用 `_get_registry()` 懒加载缓存单例避免重复扫描。

### 日志系统

`log_buffer` 模块管理内存日志缓冲（200 行上限），同时实时写入 `logs/session_*.log` 纯文本文件（剥离 ANSI 颜色码），保留最近 5 个文件自动轮替。

**API**：`add()`、`replace_at()`、`recent()`、`set_log_dir()` 通过模块级代理函数暴露。task 文件中使用 `_log_buffer.add()` / `_log_buffer.replace_at()`。

### 颜色常量

所有 ANSI 颜色码集中定义在 `renderer.py`：

| 常量 | 用途 |
|------|------|
| `C_RED` | 错误/失败回显 |
| `C_GREEN` | 成功回显 |
| `C_YELLOW` | 游戏开始/重试回显 |
| `C_BLUE` | 信息回显 |
| `C_HIGHLIGHT` | 网格单元格高亮反色背景 |
| `C_RESET` | 重置颜色 |

通过 `_INJECT_SYMBOLS` 注入到 task 模块全局符号表，task.py 中可直接使用无需 import。

### 游戏生命周期

`GameLifecycleManager` 统一管理游戏进程生命周期：每 5 秒查询 1 次进程，使用 `threading.Event` 实现 `wait_for_state`，游戏退出后所有 runner 阻塞等待唤醒，游戏启动时广播 RUNNING 事件。避免 N 个任务各自每 2 秒独立轮询。

**anti_afk 后台计时器**：通过 `GetForegroundWindow()` 检测游戏是否在前台。追踪 `_last_hwnd`，当 hwnd 变化（游戏重启）或变为 `None`（窗口消失）时重置计时器，确保只统计最近一次切到后台后的时长。

## 黑客求解器

### 暴力破解 (bruteforce)

8 个方框按顺序激活（激活方框有竖线+横线，未激活只有横线），红色字母在活跃方框内滑动。**坐标采样**检测活跃方框（从覆盖图 bbox 提取坐标，采样左右边缘 1px 竖线亮度 > 100 的像素占比 > 5%），**红色像素检测**判断何时按回车（R > 80 且 R > G × 2，占比 > 2%）。不识别字符。

- 方框过渡期间 `_find_active_cell` 返回 None，通过 trigger 匹配区分"等待过渡"和"游戏完成"
- `capture_fails` 仅对连续截图失败计数，正常等待不递增
- 扫描间隔 50ms，按回车后 0.2s 等待切换
- 误按 2 次即失败，所有方框消失时按回车重置

### 连接主机 (connect_host)

8×10 网格，在网格中找 4 位目标序列，BFS 最短路径导航。逐步执行 + 周期性重读屏幕追踪网格滚动。自动检测失败界面并重置。`scan_ms` 通过 `_speed_ratio` 比例因子应用到破解全过程（按键间隔、动画等待、重读间隔），下限保护 `max(scan_ms, 50)`。

### 电压连线 (voltlab)

3 个数字 × 3 个乘数符号 = 目标值。排列求解（6 种），Enter + 上下键 + Enter 逐位配对。

**光标落点规则**（关键）：
- 第 1 个数字 Enter → 光标必在槽位 1
- 第 2 个数字 Enter → 光标优先落槽位 2 → 槽位 3 → 槽位 1（跳过已占）
- 第 3 个数字 → 只剩 1 个空槽，光标必落那里
- 导航用 `up`/`down`，已选符号自动跳过。第 1 位按上到第 3 位，第 3 位按下到第 1 位

## 关键设计约定

- **任务目录名 = config.json 键名**，以英文命名
- **覆盖图必须 3840x2160 RGBA 透明 PNG**，所有语言版本目标 UI 元素位置一致
- **用户可见文本必须走 `translate()`**，禁止硬编码
- **翻译键命名**：`task.{task_name}` 用于任务显示名，`hack.{task_name}.{status}` 用于 hack 任务状态，按任务独立注册不跨任务共用
- **菜单启用/禁用**用 🗹/☐ 表示，分组标题用 ☒ 前缀
- **`run_once`** 任务执行后自动将 `enabled` 设为 `False` 并停止
- **新增 hack solver**：只需创建 `tasks/{name}/` 目录 + `task.py`，TaskRegistry 自动发现注册，无需修改 config.py 或 locale 文件外的任何核心模块
- **日志回显**：使用 `_log_buffer.add()` 新增行、`_log_buffer.replace_at()` 原地刷新行，格式 `[{display_name}] {message}`

## 新增任务步骤

1. 在 `tasks/` 下创建目录（英文名）
2. 创建 `task.py`，定义 `Task(BaseTask)` 子类
3. 创建语言子目录（`global/`、`zh_CN/` 等），放入覆盖图 PNG
4. 在各语言 locale 添加 `task.{key}` 翻译键
5. 如需分组，设置 `group = "..."` 并添加 `group.{key}` 翻译键
6. 如需自定义行为，覆写 `execute_step()` 或 `load()`

## 已知限制

- PrintWindow 对全屏独占模式可能返回黑屏，需要窗口化或无边框窗口
- SendInput 要求窗口在前台
- 覆盖图硬编码 4K 3840x2160，不支持多分辨率自适应
- 黑客破解的网格坐标基于 4K 硬编码，游戏更新字体后需重新校准
- `bring_to_foreground` 可能因 Windows 前台锁定策略失败
- 覆盖图匹配计算量大（absdiff 全图），高频扫描场景应优先考虑坐标采样方案
- 日志批量写入（每 1 秒 flush），异常退出时可能丢失最近 1 秒内未 flush 的日志