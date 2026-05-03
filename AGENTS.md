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
    ├── hack_solver_connect_host/        # OCR + BFS寻路（连接主机）
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
        "connect_host": {"enabled": false, "scan_ms": 500}
    }
}
```

- 分组任务的 `group` 在 `task.py` 类属性中定义，组键作为 `config.json` 的一级键，子任务为二级键
- 任务顺序由 `core/config.py` 的 `_TASK_ORDER` 控制

## 黑客求解器

### 连接主机 (connect_host)

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
- `tasks/hack_solver_connect_host/task.py` — 设置 `run_once = True`
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

---

## 26w18g

### 修改范围
- `locales/*.json` — 重构 hack 翻译键体系，删除 17 个旧通用键，新增 14 个按任务独立注册的新键
- `locales/en_US.json` — "Create Invite-Only Session" 去连字符、"Voltlab"→"VOLTlab"、"Memory"→"Mem"、step 文本去 `|` 分隔符
- `tasks/hack_solver_voltlab/task.py` — 6 处翻译键引用更新为 `hack.<task_name>.<status>` 格式
- `tasks/hack_solver_connect_host/task.py` — 10 处翻译键引用更新
- `core/renderer.py` — 内存显示自动缩放单位（<1024 MB 显示 MB，≥1024 MB 显示 GB）
- `core/resource_monitor.py` — 采样间隔 2.0s→1.0s

### 原因与背景
1. hack 相关翻译键（`hack_target_read_failed`、`hack_capture_failed` 等）被 voltlab 和 connect_host 共用，但语义不同：voltlab 表示目标数字 OCR 失败，connect_host 表示目标格识别失败。混用导致回显不准确、排查困难
2. 性能面板内存刷新 2 秒过慢，且超出 1024 MB 时仍显示小数不便阅读
3. "Memory" 标签长度与 "CPU" 不一致，排版不紧凑
4. step 文本中的 `|` 分隔符原用于两色渲染（action 白色 + detail 黄色），去掉后整段显示黄色，视觉更统一

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 翻译键注册 | 通用 `hack_*`/`breach_*` 跨任务共用 | `hack.<task_name>.<status>` 按任务独立注册 |
| 电压连线读取失败回显 | "Failed to read target Host" | "Failed to read target number" |
| connect_host 读取失败回显 | "Failed to read target Host" | "Failed to detect target" |
| step 文本渲染 | `\|` 分割两色 | 整段黄色 |
| 内存显示 | 始终 `X.X MB` | <1024: `X.X MB` / ≥1024: `X.XX GB` |
| "Memory" 标签 | Memory | Mem |
| 性能刷新间隔 | 2.0s | 1.0s |

### 系统影响
- 新增任务按 `hack.<task_name>.<status>` 命名独立注册翻译键，不再复用通用键
- 闲置键（`breach_target_detected` 等 9 个）已从三个 locale 文件清除
- `_color_step()` 中的 `|` 分割逻辑保留但不再被触发，向后兼容无影响

### 关键问题
- 重构涉及三个语言文件同步修改（17 旧键删除 + 14 新键添加 + 6 处文本调整），逐个对齐避免遗漏
- 翻译键命名与已有 `step.<阶段>.<task_name>` 模式对齐为 `hack.<task_name>.<status>`，保持一致性

---

## 26w18h

### 修改范围
- `tasks/hack_solver_ip_crack/` → `tasks/hack_solver_connect_host/` — 目录重命名
- `core/config.py` — `_TASK_ORDER` 更新为新键名，新增 `_migrate_config()` 自动迁移旧配置
- `locales/en_US.json` — 10 个翻译键 `hack_solver_ip_crack` → `hack_solver_connect_host`，显示名 "IP Crack" → "CONNECTING TO THE HOST"
- `locales/zh_CN.json` — 10 个翻译键同步重命名，显示名 "网络地址" → "连接主机"
- `locales/zh_TW.json` — 10 个翻译键同步重命名，显示名 "網路地址" → "連接主機"
- `config.json` — 用户配置键 `ip_crack` → `connect_host`

### 原因与背景
任务显示名从 "IP Crack"（网络地址/網路地址）统一改为 "CONNECTING TO THE HOST"（连接主机/連接主機），涵盖目录名、内部键名、翻译键和配置文件键的全量重命名。

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 英文任务名 | IP Crack | CONNECTING TO THE HOST |
| 简体中文任务名 | 网络地址 | 连接主机 |
| 繁体中文任务名 | 網路地址 | 連接主機 |
| 配置键名 | `hack_solver.ip_crack` | `hack_solver.connect_host` |

### 系统影响
- `load_config()` 内置 `_migrate_config()` 自动将旧 `ip_crack` 配置迁移为 `connect_host`，旧用户升级无感
- 翻译键 `hack.hack_solver_ip_crack.*` → `hack.hack_solver_connect_host.*`，task.py 内通过 `self._task_name` 动态拼接无需改动

### 关键问题
- 目录重命名使用 `git mv` 保留版本历史
- 翻译键在所有三种语言文件中严格对齐，避免键名不同步导致回退到键名原文

---

## 26w18j

### 修改范围
- `main.py` — 主循环帧间隔从 0.15s 降至 0.02s，终端尺寸单次调用即缓存，渲染写入合并为单次批量输出
- `core/renderer.py` — `_visible_len()` 添加 `@lru_cache(maxsize=512)` 缓存

### 原因与背景
菜单操作存在明显顿挫感。根因是主循环每帧固定 `time.sleep(0.15)`，导致按键到视觉反馈最多延迟 150ms。同时每帧存在多次不必要的系统调用（终端尺寸查询两次、逐行独立 ANSI 写入、重复的 Unicode 宽度扫描）。

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 菜单按键响应延迟 | 最多 ~150ms | 最多 ~20ms |
| 终端尺寸获取 | 每帧调用 `shutil.get_terminal_size()` 两次 | 每帧调用一次 |
| 渲染输出 | 逐行独立 `sys.stdout.write()` + 多次 ANSI 定位 | 合并为单个字符串后单次 `sys.stdout.write()` |
| `_visible_len` 计算 | 每次重新扫描字符级 Unicode 宽度 | 最近 512 个结果缓存命中 |

### 系统影响
- 帧率从约 6.6fps 提升至约 50fps，CPU 占用相应增加但被批量写入和缓存优化所抵消
- `shutil.get_terminal_size()` 减少一半调用量
- 渲染仅在一次系统调用中完成，减少终端闪烁

### 关键问题
- 帧间隔不宜降至 0（忙等待），0.02s 在流畅度与 CPU 占用之间取得平衡

---

## 26w18k

### 修改范围
- `tasks/hack_solver_connect_host/task.py` — `_find_target_in_grid` 方向键修复（`"right"`→`"d"`）；新增 `_set_status_line` 单行原地刷新 + `_clear_display` 方法；`HackingSolver.__init__` 新增 `_status_line_idx`；Task 类新增 `default_config`
- `tasks/close_game_at_results/task.py` — 新增 `default_config = {"wait_ms": 2000}`
- `core/task_base.py` — `BaseTask` 新增 `default_config: dict = {}` 类属性
- `core/config.py` — `_build_default_config` + `_flatten_task_configs` 合并 `default_config`
- `core/log_buffer.py` — 移除 `_hack_display`、`_hack_display_lock`、`_hack_display_update()`、`_hack_display_clear()`
- `core/__init__.py` — 移除 `_hack_display_update`、`_hack_display_clear` 注入符号
- `core/renderer.py` — 移除 `build_grid_panel()` 函数
- `main.py` — 移除 `build_grid_panel()` 调用及 `grid_panel_h` / `log_avail` 相关计算
- `config.json` — connect_host 新增 `auto_enter: true`；close_game_at_results 新增 `wait_ms: 2000`

### 原因与背景
1. 连接主机始终在"目标 Host → 重置游戏"间循环：`_find_target_in_grid` 中 `self._move(current, "right")` 调用 `_move` 方法，但 `_move` 仅处理 `"w"/"a"/"s"/"d"` 四个 WASD 键，`"right"` 不匹配任何分支成为 no-op，导致第 2-4 个目标数字始终与同一格比较，目标永远找不到
2. 连接主机原有的 `_hack_display_update` → `build_grid_panel` 使用独立面板渲染 8×10 网格，与日志行分离，用户要求改为电压连线那样的 log-line + `replace_at` 原地刷新方式
3. 配置文件缺少 `auto_enter` 选项，且首次运行时仅生成 `enabled` + `scan_ms`，其他任务自定义配置项需要手动补全，缺少自动生成机制

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 连接主机寻目标 | 始终找不到目标，循环重置 | 正确匹配 4 位目标序列并执行路径导航 |
| 连接主机破解回显 | 独立网格面板渲染 | 单行日志 `add()` + `replace_at()` 原地刷新 |
| `auto_enter` 配置 | 不存在，代码硬编码默认 True | config.json 生成时自动包含，可修改 |
| 首次运行 config.json 生成 | 仅 `enabled` + `scan_ms` | 合并 Task 类的 `default_config`，包含所有自定义选项 |
| `build_grid_panel` | 存在且仅被 connect_host 消费 | 完全移除 |

### 系统影响
- `_hack_display` 基础设施因 connect_host 是唯一消费者，已从 4 个文件中完全移除
- `default_config` 机制向后兼容：不定义 `default_config` 的 Task 类行为不变
- 新任务添加自定义配置项时只需在 Task 类定义 `default_config`，无需修改 `_build_default_config`

### 关键问题
- `_move` 在 `_find_target_in_grid` 中的 `"right"` 与 `_plan_path` 中的 `"d"` 不一致，属代码编写疏忽
- `replace_at` 仅替换消息体，需在 msg 中包含 `[display_name]` 前缀以保持日志行格式一致

---

## 26w18i

### 修改范围
- `core/renderer.py` — 分组标题行新增 ☒ 复选框符号，颜色恢复为默认色，子任务缩进减半

### 原因与背景
分组标题 "Hack Solver" 需要视觉上与普通任务区分，添加 ☒ 标记标识其为分组；子任务缩进 4 空格过深，影响菜单阅读的层次感。

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 分组标题前缀 | 无复选框 | ☒ 复选框（对齐父任务） |
| 分组标题颜色 | C_GRAY | 默认终端色（与其他任务名一致） |
| 子任务缩进 | PAD + 4 空格 | PAD + 2 空格 |

### 系统影响
- 仅影响 TUI 菜单渲染视觉，无逻辑或配置变更

### 关键问题
- ☒ 与 ☐ 缩进需在同一列对齐，分组标题前缀与父任务完全一致（`PAD + 符号 + 2 空格`）
- 子任务缩进保留 2 空格差异，确保层次可辨识同时不过深

---

## 26w18l

### 修改范围
- `tasks/hack_solver_connect_host/task.py` — 新增 `_init_display`、`_render_grid_row`、`_render_grid_rows` 三个方法；`_set_status_line` 替换为 `_set_display_status`；创建 8 行网格占位符 + 1 行状态行显示架构；后续又完全移除状态行，改为纯网格显示；`_clear_display` 增加清空旧显式行内容避免重试时残留；移除 `_attempt_hack` 入口的提前 `_clear_display()`
- `core/__init__.py` — `_INJECT_SYMBOLS` 新增 `C_HIGHLIGHT` 注入
- `core/log_buffer.py` — 新增 `set_log_dir()`、`_ensure_log_file()`、`_rotate_logs()` 方法；`add()` 内同步写入纯文本日志文件；`_ANSI_RE` 正则剥离颜色码；`_max_log_files = 5` 自动轮替
- `core/task_runner.py` — 移除 `run_once` 任务首次未检测到 trigger 就停用的提前失败逻辑，删除 `_run_once_checked` 变量及相关引用
- `main.py` — 新增 `signal.signal(signal.SIGINT, signal.SIG_IGN)` 阻止 Ctrl+C 退出；`getwch()` 中显式吞掉 `\x1b`（Esc 键）；调用 `log_buffer._log_buffer.set_log_dir()` 初始化日志目录
- `locales/zh_CN.json` — 新增 `hack.hack_solver_connect_host.game_start`、`game_over` 翻译键
- `locales/en_US.json` — 同上
- `locales/zh_TW.json` — 同上
- `.gitignore` — 新增 `logs/`

### 原因与背景
1. 连接主机破解回显仅有一行状态文本（"准备寻路…"→"R1C3→R1C2 w→…"），用户看不到完整 8×10 网格，无法直观了解破解进度。需要类似电压连线的多行面板实时刷新方式
2. `run_once = True` 的任务在首次扫描未发现 trigger 时立即停用，导致用户必须在游戏内出现黑客图标后才能去菜单开启任务。正确行为应为：开启任务→持续扫描→检测到图标→执行→完成→停用
3. 用户可能误按 Ctrl+C 或 Esc 导致程序退出，需要防护
4. 日志仅在内存中，程序退出后无法回溯排查问题

### 行为差异

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 连接主机破解回显 | 单行状态文本原地刷新 | 游戏开始→目标 Host→8 行网格（光标高亮实时刷新）→游戏结束，网格始终可见 |
| 连接主机光标高亮 | 无高亮 | 光标覆盖的 4 个单元格 `C_HIGHLIGHT` 反色背景 |
| 连接主机状态行 | 持续显示"已对位目标 (第N次)"、"R1C1→R2C3 w→(3/5)"等 | 已移除，仅保留网格 |
| 连接主机重试时旧显示 | 残留空行（仅时间戳） | `_clear_display` 清空旧显示行内容，避免重试时残留 |
| 连接主机新一轮触发时 | 立即清空上次显示（可能在识别失败后只看到空行） | 等 `_init_display` 创建新显示时才清旧，失败时保持上次成功结果 |
| `run_once` 任务开启后 | 首次扫描无 trigger 即停用 | 持续扫描直到检测到 trigger 并完成执行后才停用 |
| 日志持久化 | 内存中，退出即丢失 | 实时写入 `logs/session_*.log`，剥离 ANSI 颜色码为纯文本，保留最近 5 个文件 |
| Ctrl+C / Esc | 退出程序 | 被忽略，无法退出 |

### 系统影响
- 连接主机回显从 1 行变为 10 行（2 固定行 + 8 网格行），占用更多日志缓冲空间，但在 `_log_buffer` 200 行上限内有余量
- `C_HIGHLIGHT` 注入到所有 task.py 模块，现有任务无影响，新任务可直接使用
- `_run_once_checked` 已从 `TaskRunner.__init__`、`start()`、`reload()` 三处移除
- 日志文件 `logs/` 已加入 `.gitignore`，不影响版本控制
- `signal.SIG_IGN` 在主线程注册，全局生效，任务线程不受影响

### 关键问题
- 增量刷新初版使用 XOR 计算高亮行变化，仅更新"高亮状态改变"的行。但光标同行内移动时高亮行集合不变（XOR 为空），网格不更新。修复为 union（`|`），始终刷新所有高亮行
- `C_HIGHLIGHT` 定义在 `core/renderer.py` 但未注入到 task 模块全局符号表，直接使用会 `NameError`。已补入 `_INJECT_SYMBOLS`
- `_attempt_hack` 入口调用 `_clear_display()` 在新一轮触发时立即清空上次成功破解的回显，若新一轮识别失败则只留空行。修复为移除此调用，`_init_display` 创建新显示时自行清旧
- `_init_display` 内 `_log_buffer.add(target_detected)` 与旧代码中独立的 `_log_buffer.add(target_detected)` 导致目标 Host 行重复出现。已移除独立调用
