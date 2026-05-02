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
│   ├── log_buffer.py    # 日志缓冲 + hack 显示状态
│   ├── config.py        # 配置管理 + Steam 语言检测 + 模块加载
│   ├── windows_api.py   # Win32 API 封装（窗口/截图/输入/进程）
│   ├── resource_monitor.py # CPU/内存采样 + 游戏状态检测
│   ├── task_base.py     # BaseTask + OverlayMatcher
│   ├── task_runner.py   # TaskRunner 状态机
│   └── renderer.py      # TUI 面板构建
├── locales/             # UI 翻译（zh_CN.json / zh_TW.json / en_US.json）
└── tasks/               # 任务目录，每个自包含
    ├── bunker_fast_track_research/     # 覆盖图匹配 + 点击
    ├── close_game_at_results/          # 覆盖图匹配 + 进程终止
    ├── hack_solver_ip_crack/           # OCR + BFS寻路（网络地址）
    ├── hack_solver_voltlab/            # OCR + 排列求解（电压连线）
    ├── create_invite_only/             # 纯按键序列
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
```

**三种任务模式**：

| 模式 | `start_trigger` | `steps` | 说明 |
|------|----------------|---------|------|
| 按键序列 | `{}` | `[{"delay": N, "key": "x"}]` | 执行一次后自动禁用（如创建邀请战局） |
| 触发+步骤 | `{"overlay": "trigger"}` | `[{"overlay": "step1"}]` | 检测触发→按序执行→循环（如地堡加速） |
| 触发+hack | `{"overlay": "trigger", "click": False}` | `[{"overlay": "hack", "action": "hack"}]` | 覆写 `execute_step` 调用自定义 solver |

**符号注入**：`task.py` 可直接使用 `BaseTask`、`OverlayMatcher`、`send_key` 等符号（由 `core/__init__.py` 注入），标准库和第三方库仍需显式 import。

### TaskRunner 状态机

双频检测：等待阶段低频（`scan_ms`），执行阶段高频（`task.scan_ms`）。检测到 `start_trigger` → 执行步骤序列 → 全部完成后回到等待阶段。游戏未运行时暂停，每 2 秒检查一次。

### 覆盖图匹配

基于 4K RGBA 透明 PNG，不透明像素定义匹配目标，`cv2.absdiff` + mask 加权计算置信度（阈值 0.95）。支持固定位置和水平扫描两种模式。

### 键盘输入

使用**硬件扫描码** + `KEYEVENTF_SCANCODE`（RAGE 引擎/DirectInput 不响应虚拟键码）。`send_key()` 内部 `w/a/s/d` 映射为方向键扫描码。

### 配置热重载

`config.json` 通过 mtime 检测变更，`TaskRunner` 每轮循环检查并 `reload()`。

### 配置结构

```json
{
    "lang": "auto",
    "scan_ms": 2000,
    "anti_afk": {"enabled": false, "key": "enter", "interval_min": 10},
    "create_invite_only": {"enabled": false, "scan_ms": 500},
    "hack_solver": {
        "voltlab": {"enabled": false, "scan_ms": 500},
        "ip_crack": {"enabled": false, "scan_ms": 500}
    }
}
```

- 分组任务的 `group` 在 `task.py` 类属性中定义，组键作为 `config.json` 的一级键，子任务为二级键
- 任务顺序由 `core/config.py` 的 `_TASK_ORDER` 控制

## 黑客求解器

### 网络地址 (ip_crack)

8×10 网格，在网格中找 4 位目标序列，BFS 最短路径导航。逐步执行 + 周期性重读屏幕追踪网格滚动。自动检测失败界面并重置。

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
- **菜单启用/禁用**用 🗹/☐ 表示
- **`run_once`** 任务执行后自动将 `enabled` 设为 `False` 并停止

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

---

## 26w18f

### 修改范围
- `tasks/hack_solver_voltlab/task.py` — 光标落点逻辑 + 动画延迟
- `tasks/hack_solver_voltlab/global/grid.json` — animation_delay_ms 2000→3000
- `core/task_base.py` — BaseTask 新增 `run_once` 类属性
- `core/task_runner.py` — TaskRunner 新增 `_disable_and_stop_in_config()`、run_once 执行后自动禁用、首次扫描无 trigger 时快速失败
- `tasks/hack_solver_ip_crack/task.py` — 设置 `run_once = True`
- `core/renderer.py` — 复选框符号 ☑→🗹
- `locales/*.json` — 新增 `trigger_not_found` 翻译键
- `config.json` — hack_solver 子任务默认 enabled: false
- `AGENTS.md` — 精简去冗余（1453→129 行）

### 原因与背景
1. 电压连线光标落点逻辑错误：代码假设第 i 个数字 Enter 后光标必在槽位 i，但游戏实际规则是第 2 个数字 Enter 后光标优先落槽位 2→3→1（跳过已占），导致日志回显的配对方案与游戏实际执行不一致
2. 黑客游戏任务始终循环扫描，启用后无法自动停止，需要改为"启用即执行、执行后即停用"的一次性模式
3. 启用状态下若画面无 trigger 覆盖图，任务无限等待无反馈，需要快速失败并提示用户

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 电压连线第 2 数字配对 | 盲目假设光标在槽位 i | 按优先级 2→3→1 跳到首个未占槽位 |
| 动画等待 | 2000ms | 3000ms |
| 黑客任务启用后 | 始终循环扫描，需手动关闭 | 执行一次后自动禁用 |
| 启用后画面无 trigger | 无限期等待检测 | 立即回显"尚未发现游戏"并自动禁用 |
| 菜单启用标记 | ☑ | 🗹 |

### 系统影响
- `run_once` 机制与按键序列任务的自动禁用逻辑并列，不影响现有循环任务
- 黑客任务默认配置从 enabled: true 改为 false，需用户手动启用

### 关键问题
- 电压连线不稳定根因是代码对游戏光标落点规则的假设错误，而非 OCR 识别问题
- 动画延迟过短（2000ms）导致 Enter 在动画期间被吞掉，后续导航键在错误状态下执行，产生"平行连"结果
- `C_RED` 常量通过 `_INJECT_SYMBOLS` 仅对 task.py 模块注入，`task_runner.py` 使用会 NameError，改用原始 ANSI 转义码
