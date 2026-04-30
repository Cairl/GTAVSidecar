# GTAVSidecar 技术报告

**日期**: 2026-04-26
**阶段**: 防止游戏挂机检测功能 (Anti-AFK)

***

## 项目概述

GTAVSidecar 是一个辅助 GTA5 操作的后台工具集。通过视觉识别（透明覆盖图匹配）检测游戏画面中的 UI 元素，自动执行鼠标点击序列、键盘操作或进程操作。所有识图基于 4K RGBA 透明 PNG 覆盖图，不透明像素定义匹配目标。支持固定位置逐像素比对和水平行扫描匹配两种模式。

**任务类型演进**:
- 第一任务（地堡加速）: 覆盖图匹配 + 鼠标点击
- 第二任务（任务结束退出）: 覆盖图匹配 + 进程终止
- 第三任务（网络地址）: OCR 数字识别 + 上下左右箭头键路径规划
- 第四任务（电压连线）: OCR 数字识别 + 符号识别 + 排列求解 + 上下箭头键导航
- 第五任务（仅限邀请战局）: 纯按键序列 + 延迟，无覆盖图匹配

***

## 目录结构

```
GTAVSidecar/
├── main.py              # 框架入口 (i18n + vision + BaseTask + TaskRunner + TUI)
├── config.json          # 配置文件 (支持热重载 + 持久化)
├── .gitignore
├── locales/             # UI 翻译文件 + 任务显示名
│   ├── zh_CN.json       # 简体中文
│   ├── zh_TW.json       # 繁體中文
│   └── en_US.json       # English
├── tasks/               # 任务目录 (每个任务自包含)
│   ├── bunker_fast_track_research/
│   │   ├── task.py      # Task(BaseTask) 类定义
│   │   ├── zh_CN/       # 簡體中文覆蓋圖資源
│   │   │   ├── trigger.png
│   │   │   ├── confirm.png
│   │   │   └── complete.png
│   │   ├── zh_TW/       # 繁體中文覆蓋圖資源
│   │   │   ├── trigger.png
│   │   │   ├── confirm.png
│   │   │   └── complete.png
│   │   └── en_US/       # English overlay resources
│   │       ├── trigger.png
│   │       ├── confirm.png
│   │       └── complete.png
│   ├── close_game_at_results/
│   │   ├── task.py      # Task(BaseTask) 类定义
│   │   └── global/      # 全语言通用覆盖图 (纯图标)
│   │       ├── trigger.png
│   │       └── exit.png
│   ├── hack_solver_ip_crack/
│   │   ├── task.py      # Task(BaseTask) + HackingSolver 类定义
│   │   ├── global/      # 黑客游戏开始触发图标
│   │   │   └── trigger.png
│   │   ├── zh_CN/       # 简中数字模板 + 网格配置 + 失败界面
│   │   │   ├── 0.png ~ 9.png
│   │   │   ├── fail.png
│   │   │   └── grid.json
│   │   ├── en_US/       # 英文数字模板 + 网格配置 + 失败界面
│   │   │   ├── 0.png ~ 9.png
│   │   │   ├── fail.png
│   │   │   └── grid.json
│   │   └── zh_TW/       # 繁中数字模板 + 网格配置 + 失败界面
│   │       ├── 0.png ~ 9.png
│   │       ├── fail.png
│   │       └── grid.json
│   └── hack_solver_voltlab/
│       ├── task.py      # Task(BaseTask) + BreachSolver 类定义
│       └── global/      # 全语言通用资源 (数字模板 + 符号模板 + 网格配置)
│           ├── trigger.png
│           ├── 0.png ~ 9.png
│           ├── x1.png, x2.png, x10.png
│           └── grid.json
│   └── anti_afk/
│       └── task.py      # Task(BaseTask) 防挂机定时按键
│   └── create_invite_only/
│       └── task.py      # Task(BaseTask) 仅限邀请战局按键序列
└── .agents_logs/
```

**重要**: 任务目录名必须与 `config.json` 中的任务键名完全一致（包括空格和特殊字符）。任务文件夹命名以英文为准。

***

## 核心模块详解

### 窗口捕获 (PrintWindow)

```python
capture_window(hwnd) -> np.ndarray | None
```

- 使用 `PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)` 捕获游戏窗口画面
- 返回 BGR 格式 numpy 数组，即使窗口被其他窗口遮挡也能正常获取
- 不依赖 `PIL.ImageGrab`，不需要窗口在前台

### 游戏窗口查找

```python
find_game_window(process_name="GTA5_Enhanced.exe") -> int | None
```

- 通过 `CreateToolhelp32Snapshot` + `Process32FirstW/NextW` 遍历进程列表查找 PID
- 通过 `EnumWindows` + `GetWindowThreadProcessId` 查找对应可见窗口句柄
- 返回窗口句柄 (HWND)，未找到返回 None

### 覆盖图匹配 (OverlayMatcher)

```python
OverlayMatcher(overlay_path, alpha_threshold=128)
matcher.match_from_image(image, threshold=0.95, offset=(0,0)) -> (bool, float)
matcher.match_from_image_scan(image, threshold=0.95, offset=(0,0)) -> (bool, float, tuple|None)
```

**固定位置匹配** (`match_from_image`):

1. 加载 4K RGBA 透明 PNG，提取 Alpha 通道，二值化为掩码
2. `cv2.boundingRect` 定位不透明像素的边界框，裁剪出模板和掩码
3. 截取屏幕/窗口图像对应区域，`cv2.absdiff` 逐像素比对
4. 以掩码为权重计算归一化相似度: `confidence = 1 - weighted_diff / total_weight`

**水平扫描匹配** (`match_from_image_scan`):

1. 从覆盖图提取模板、掩码和 Y 坐标（行位置）
2. 创建 `_template_scan`：将模板透明像素填充为不透明像素均值（解决 `TM_CCOEFF_NORMED` 无掩码支持问题）
3. 截取屏幕图像对应行区域（含 20px 垂直容差），全宽水平条带
4. **第一阶段**：`cv2.matchTemplate(TM_CCOEFF_NORMED)` 快速定位候选位置（使用均值填充模板）
5. **第二阶段**：在候选位置用 `cv2.absdiff` + mask 精确验证，计算与固定位置匹配一致的置信度
6. 返回 `(found, confidence, center)`，center 为匹配中心在覆盖图坐标系中的位置
7. 适用于图标在同一行不同水平位置出现的场景

**坐标体系**:

- `bbox` 和 `center` 是相对于覆盖图左上角的像素坐标
- `match_from_image` 的 `offset` 参数是客户区相对于窗口左上角的偏移
- 点击时需要: `screen_origin + matcher.center` 得到屏幕坐标
- 扫描匹配返回的 center 同样是覆盖图坐标系，可直接用于点击

### 鼠标点击 (SendInput)

```python
click_at(screen_x, screen_y)
```

- 通过 `_make_mouse_input(flags)` 辅助函数构造 `_INPUT` 结构体
- LEFTDOWN 和 LEFTUP 分开发送，中间间隔 80ms
- SetCursorPos 后等待 100ms

### 键盘输入 (SendInput)

```python
send_key(key)          # key: "w"/"a"/"s"/"d"/"enter"/"up"/"down"/"left"/"right"
clip_cursor_to_window(hwnd)  # 锁定鼠标到窗口
unclip_cursor()              # 解锁鼠标
```

- 使用**硬件扫描码**（Scan Code）+ `KEYEVENTF_SCANCODE` 标志，而非虚拟键码（VK）
- RAGE 引擎使用 DirectInput 读取键盘，不响应虚拟键码的 SendInput
- 扫描码映射: `W=0x11, A=0x1E, S=0x1F, D=0x20, Esc=0x01, Enter=0x1C, Up=0x48, Down=0x50, Left=0x4B, Right=0x4D`
- 为统一操作方式，代码层面使用 `w/a/s/d` 作为方向键别名，`send_key` 内部自动映射为上下左右箭头键扫描码
- KEYDOWN 和 KEYUP 分开发送，中间间隔 80ms
- `clip_cursor_to_window` 使用 `ClipCursor` 将鼠标限制在游戏窗口内，防止干扰键盘操作

### 后台键盘输入 (PostMessage)

```python
send_key_background(hwnd, key)  # key: "enter"/"space"/"w"/"f1" 等
```

- 使用 `PostMessageW` 向指定窗口发送 `WM_KEYDOWN`/`WM_KEYUP` 消息
- **无需窗口在前台**，游戏窗口可在后台或被其他窗口遮挡
- 通过 `MapVirtualKeyW` 获取扫描码，构造标准 lParam（含扫描码、扩展键标志、重复计数）
- 扩展键（方向键、Insert、Delete 等）自动设置 bit 24 扩展键标志
- KEYDOWN 和 KEYUP 间隔 50ms
- 支持命名键（`enter`/`space`/`tab`/`esc`/`up`/`down`/`f1`~`f12` 等）、单字母（`w`/`a`/`s`/`d`）、单数字（`1`~`9`）
- **限制**: RAGE 引擎使用 DirectInput 读取键盘，PostMessage 发送的 WM_KEYDOWN 不会被游戏作为操作输入处理（与踩坑 #28 同理）

### 防止游戏挂机检测 (Anti-AFK)

**位置**: `tasks/anti_afk/task.py`

```python
class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = []
```

- 独立后台线程，仅在游戏窗口处于后台时计时，累计时间达到 `interval_min` 后将游戏切至前台发送按键
- 发送按键通过 `key` 配置项控制（默认 `enter`），支持字母键（如 `w`）、数字键（如 `1`）、功能键（如 `f1`、`space`、`tab`）等
- 使用 `SendInput` + 扫描码（`send_key`）实现，将游戏切至前台发送按键后**不切回**原窗口
- 游戏未运行时自动跳过，不发送按键
- 游戏在前台时计时器归零，不触发按键
- 支持配置热重载：修改 `interval_min` 或 `key` 后下一周期自动生效
- TUI 任务面板末行显示"防止游戏挂机检测"条目，可通过回车键切换启停
- 日志中按键名以黄色方括号显示，如 `发送按键 [W]`
- 配置项位于 `config.json` 的 `anti_afk` 节

### 任务基类 (BaseTask)

```python
class BaseTask:
    start_trigger: dict = {}      # 类属性: 开始触发器配置
    steps: list[dict] = []        # 类属性: 步骤序列配置
    group: str | None = None      # 类属性: 任务分组标识

    def __init__(self, task_name, task_cfg, global_cfg)
    def load() -> bool
    def match_start_trigger(image, offset, threshold) -> (bool, float, tuple|None)
    def execute_start_trigger(hwnd, confidence, scan_center)
    def match_step(step_index, image, offset, threshold) -> (bool, float, tuple|None)
    def execute_step(step_index, hwnd, confidence, scan_center) -> bool
    def reload(task_cfg, global_cfg)
    def read_timing() -> (idle, active, threshold, click_delay, step_timeout)
```

**职责划分**:

- `BaseTask` 负责任务的**资源加载**（覆盖图匹配器）、**匹配检测**（图像比对）、**动作执行**（点击/终止进程/黑客破解）、**日志记录**（步骤执行日志）
- `TaskRunner` 负责状态机调度（等待/执行/超时/重置）、游戏窗口检测、配置热重载

**符号注入机制**:

`_load_task_module()` 通过 `_INJECT_SYMBOLS` 字典将 main.py 中的符号注入到 task.py 模块命名空间，task.py 可直接使用 `BaseTask`、`OverlayMatcher`、`click_at` 等符号，无需 import 语句。标准库和第三方库（`os`、`json`、`cv2`、`np` 等）仍需在 task.py 中显式导入。

**子类化模式**:

简单任务只需声明类属性，无需覆写任何方法：

```python
class Task(BaseTask):
    group = None
    start_trigger = {"overlay": "trigger", "lang": "auto"}
    steps = [
        {"overlay": "confirm", "lang": "auto"},
        {"overlay": "complete", "lang": "auto"},
    ]
```

需要自定义 action 的任务覆写 `execute_step()`：

```python
class Task(BaseTask):
    group = "hack_solver"
    start_trigger = {"overlay": "trigger", "lang": "global", "click": False}
    steps = [{"overlay": "hack", "lang": "auto", "action": "hack"}]

    def __init__(self, task_name, task_cfg, global_cfg):
        super().__init__(task_name, task_cfg, global_cfg)
        self._hacking_solver = None

    def load(self):
        if not super().load():
            return False
        solver = HackingSolver(self._task_name, self._global_cfg)
        if not solver.load():
            return False
        self._hacking_solver = solver
        return True

    def execute_step(self, step_index, hwnd, confidence, scan_center):
        if self._step_actions[step_index] == "hack":
            return self._hacking_solver.run(hwnd)
        return super().execute_step(step_index, hwnd, confidence, scan_center)
```

### 黑客破解求解器 (HackingSolver)

**位置**: `tasks/hack_solver_ip_crack/task.py`（从 main.py 迁移至任务模块）

```python
solver = HackingSolver(task_name, global_cfg)
solver.load() -> bool
solver.run(hwnd) -> bool
```

**游戏规则** (2026-04-19 修正):

- 顶部显示目标 Host 地址（4 组两位数，红色大号字体）
- 下方 8×10 网格显示两位数数组，上下左右箭头键控制光标（4 组连续选择）
- **光标初始位置**：第 4 行第 4-7 位（数组索引 33-36，即位置 33）
- **网格滚动机制（蛇形滚动）**：
  - 整个网格每隔一段时间向左移动一位
  - 每行最左侧的数组会移动到上一行的最右侧
  - 第 1 行（最上行）最左侧的数组会移动到第 8 行（最下行）的最右侧
  - 这是一个连续的循环蛇形运动
- **关键特性**：网格滚动时，玩家的框选光标不会移动（光标固定在屏幕位置）
- **光标移动规则（蛇形换行）**：
  - 按 右键 向右移动，到达行末（第 10 列）后跳到下一行的第 1 列
  - 按 左键 向左移动，到达行首（第 1 列）后跳到上一行的第 10 列
  - 按 上键 向上移动一行，列位置不变；第 1 行按 上键 跳到第 8 行
  - 按 下键 向下移动一行，列位置不变；第 8 行按 下键 跳到第 1 行
  - 光标不循环同行，而是跨行换行
- 时间限制 1 分钟，5 次选错机会，按 Enter 确认

**实现策略**:

1. **初始扫描**：一次性读取全部 80 个数组，建立初始网格状态
2. **实时重读**：每执行 3 步按键后，重新截屏并完整 OCR 读取网格和光标位置
3. **目标追踪**：重读后在当前网格中重新查找目标位置，若位置变化则重新规划路径
4. **路径规划**：基于光标实际位置计算到目标的上下左右箭头键路径（BFS 最短路径）
5. **即时显示**：每次重读后立即更新 TUI 面板，光标和目标位置独立显示

**OCR 识别**:

- 每种语言有独立的数字模板（`0.png` \~ `9.png`）和网格配置（`grid.json`）
- 不同语言的数字字体、尺寸、位置不同，必须按语言区分
- **红色/非红色分区 OCR**: 先检测每个连通组件的红色属性，将网格数字分为红色（光标行）和非红色两组
- **红色数字识别**: 光标行的数字为红色高亮，使用形状轮廓匹配（颜色无关）
- **非红色数字识别**: 普通行为白色/灰色，优先使用 absdiff 彩色匹配，低置信度时回退到形状匹配
- **目标 Host 读取**: 连通组件检测 → 缩放到模板尺寸 → 形状匹配识别每个数字
- **网格读取**: 连通组件检测 → 按行分组 → 红色检测分区 → 配对为两位数单元格 → 逐位识别

**光标位置检测**:

- 通过 OCR 识别红色高亮数字来视觉定位光标位置
- 收集所有行中标记为红色的单元格位置到 `red_positions` 集合（不做行级门控）
- 通过蛇形左邻判断定位光标起始：红色序列的第一个格子，其蛇形左邻居（col>0 时为同行 col-1，col=0 时为上一行末列）一定不是红色
- 支持光标跨行场景：当 4 格选区跨越两行时（如行末 2 格 + 下一行行首 2 格），两行都有红色数字，蛇形左邻判断能正确定位起始行
- 不假设固定初始位置，每次从屏幕实际检测

**寻路算法**:

- 将 8×10 网格视为二维坐标 (row, col)，row∈[0,7]，col∈[0,9]
- 行移动: 上键 = row-1（row=0 时跳到 row=7），下键 = row+1（row=7 时跳到 row=0）
- 列移动（蛇形换行）: 右键 = col+1（col=9 时跳到下一行 col=0），左键 = col-1（col=0 时跳到上一行 col=9）
- 行列分别选最短方向（行循环距离 + 列线性距离或换行距离）

**执行流程**:

```
1. 前台切换 + 鼠标锁定
2. 截屏 → OCR 读取目标 Host（4 组两位数，日志中红色显示）
3. 截屏 → OCR 读取网格（80 个两位数）+ 检测光标位置（仅 TUI 面板显示）
4. 在网格中查找目标序列位置
5. 计算从光标位置到目标位置的最短上下左右箭头键路径
6. 逐步执行按键，每 3 步重新截屏读取网格状态
7. 若目标位置变化（网格滚动），重新规划路径
8. 触发图标消失 → 检查失败界面 → 失败则重置游戏，成功则游戏结束
9. 解锁鼠标
```

**游戏失败重置机制**:

网络地址破解游戏有时间限制和错误次数限制，超时或错误过多会出现失败界面。失败界面通过 `fail.png` 覆盖图检测（按语言分目录），检测到后按 Enter 重置游戏并重新开始破解。

```python
_check_fail(hwnd, offset) -> bool   # 截屏检测失败界面
```

- `fail.png` 为 4K RGBA 透明 PNG，不透明区域为失败界面的特征文字
- `load()` 时从语言目录加载 `fail.png`（可选，不存在则跳过）
- `_attempt_hack` 返回 `"reset"` 表示需要重置游戏
- `run()` 循环处理：`"reset"` → 输出"重置游戏" → 按 Enter → 等待 1 秒 → 重新尝试

**触发重置的条件**:

| 条件 | 位置 | 说明 |
|------|------|------|
| 目标未在网格中找到 | 初始扫描 + 重读后 | 网格数据异常（全零行），直接返回 `"reset"` |
| trigger 消失 + 失败界面存在 | 对位重读 + 周期重读 | 先 `_check_fail`，失败则 `"reset"`，否则游戏成功结束 |
| 目标 Host 读取失败 + 失败界面存在 | 初始扫描 | 先 `_check_fail`，失败则 `"reset"` |

**关键设计**: trigger 消失有两种含义——游戏成功完成或游戏失败。必须先检查失败界面再判定游戏结束，否则会将失败误判为成功。

**grid.json 配置**:

```json
{
    "grid": {
        "origin_x": 935,     "origin_y": 818,
        "col_spacing": 192,   "row_spacing": 122,
        "rows": 8,            "cols": 10,
        "d2_offset_x": 66
    },
    "target_host": {
        "y": 455,             "h": 104,
        "x_start": 1527,     "digit_h_scale": 0.84
    }
}
```

### 电压连线求解器 (BreachSolver)

**位置**: `tasks/hack_solver_voltlab/task.py`

```python
solver = BreachSolver(task_name, global_cfg)
solver.load() -> bool
solver.run(hwnd) -> bool
```

**游戏规则**:

- 3 个左侧数字，3 个右侧乘数符号（位置随机，可重复，值域 {x1, x2, x10}）
- 一一配对：每个数字分配一个符号位置，每个位置只用一次
- 目标：所有配对的乘积之和 = 正上方红色 TARGET 数值
- 右侧符号含义：≠ = x1，中 = x2，X = x10

**操作流程**:

1. 光标起始位于左侧第 1 个数字
2. 按 Enter 选择 → 光标移至右侧第 i 个符号位置（跳过已选符号）
3. 上下键在可用符号间导航（已选符号被跳过） → Enter 确认
4. 动画间隔 (1-2 秒) → 光标回到左侧次位
5. 重复直至 3 个数字全部配对

**求解算法**:

1. 截屏 → OCR 读取 TARGET（红色大字，连通组件 + 形状匹配）
2. 截屏 → OCR 读取 3 个左侧数字（连通组件 + 形状匹配）
3. 截屏 → 模板匹配识别 3 个右侧符号（absdiff 匹配 x1/x2/x10 模板）
4. 遍历 3! = 6 种排列，找到 n[i]*m[p[i]] 之和 = TARGET 的分配
5. 计算按键序列：每个数字 = Enter + N 个 Up/Down（在可用符号间导航） + Enter
6. 执行按键序列，每步后截屏重读 TARGET 验证实际结果

**符号导航规则**:

- 选择左侧第 i 个数字（0-indexed）后，光标默认出现在右侧第 i 个符号位置
- 若该位置已被选择，自动跳到下一个可用符号（向下循环）
- 使用 `up`/`down` 键在**未选符号**之间导航，已选符号被自动跳过
- 只剩一个未选符号时，光标自动出现在该位置，无需导航键

**实时结果验证**:

- 每步执行后（动画延迟结束），重新截屏并读取 TARGET 区域
- 若游戏显示剩余值（小于原始 TARGET），则 `current_sum = target - actual_target`
- 若 TARGET 未变化，回退到计算值 `current_sum = expected_sum`
- 日志中的累计和始终反映游戏实际状态

**边框盒回显**:

游戏开始后，在日志区域内嵌显示 7 行边框盒，实时展示配对进度：

```
╭─────────────╮
│ 5 ×    =     │
│ 7 ×    =     │
│ 3 ×    =     │
│─────────────│
│     000/078 │
╰─────────────╯
```

- **预计算固定宽度**: 所有宽度在创建盒前一次性计算，`inner_w = max(content_w, sum_visible) + 2`（含两侧 1 字符安全边距）
- **初始状态**: 数字 + 空乘号位（`N ×    =    `），乘数值和乘积位置留空
- **配对完成**: 乘数值黄色闪烁 3 次后保持，乘积无颜色
- **累计和**: 右对齐，未达标黄色，达标绿色；配对确认后立即启动后台线程逐帧递增动画（30ms/帧），与乘数闪烁并行执行
- **游戏结束**: 绿色文本输出，等待动画线程完成后继续后续逻辑
- **移除内容**: 可用符号行、`breach_target_detected` 日志行

**示例**（假设 3 个符号位置索引 0,1,2 从上到下）：

| 步骤 | 已选符号 | 光标起始位置 | 可用符号列表 | 若目标为索引 2 |
|------|----------|--------------|--------------|----------------|
| 第 1 个数字 (i=0) | 无 | 0 | [0,1,2] | down, down |
| 第 2 个数字 (i=1) | {2} | 1 | [0,1] | up |
| 第 3 个数字 (i=2) | {1,2} | 0 (2已选→跳到0) | [0] | 无需按键 |

**grid.json 配置**:

```json
{
    "target": {
        "y": 220,             "h": 180,
        "x_start": 1690
    },
    "numbers": [
        {"x": 900, "y": 490, "w": 300, "h": 250},
        {"x": 930, "y": 980, "w": 220, "h": 210},
        {"x": 930, "y": 1450, "w": 220, "h": 210}
    ],
    "symbols": [
        {"x": 2600, "y": 480, "w": 360, "h": 320},
        {"x": 2600, "y": 885, "w": 360, "h": 335},
        {"x": 2600, "y": 1351, "w": 360, "h": 370}
    ],
    "animation_delay_ms": 1500
}
```

**与网络地址的差异**:

| 特性 | 网络地址 | 电压连线 |
|------|----------|--------|
| 游戏类型 | 网络地址 | 电压连线 |
| 输入方式 | 上下左右箭头键 + Enter | Enter + 上下箭头键 + Enter |
| 资源语言 | 按语言分目录 | 全部 global/ |
| 读取策略 | 逐步执行+动态追踪 | 一次性读取+计算+执行 |
| 符号识别 | 无 | 模板匹配 x1/x2/x10 |
| 显示方式 | `_hack_display` 全局状态 + TUI 网格面板 | `_log_buffer` 日志区域内嵌边框盒 |
| 实时动画 | 网格面板增量更新 | 闪烁 + 后台线程累计数递增 |

### 进程终止

```python
kill_game_process(process_name) -> bool
```

- 通过 `_find_pid_by_name` 查找进程 PID
- 使用 `OpenProcess(PROCESS_TERMINATE)` + `TerminateProcess` 终止进程
- 返回是否成功终止
- 用于 `action: "kill_process"` 步骤，无需前台窗口

### 前台切换

```python
bring_to_foreground(hwnd) -> bool
```

- 循环重试最多 10 次，每次通过 `AttachThreadInput` + `SetForegroundWindow` 尝试
- 返回是否成功切换到前台
- 点击前必须确保窗口在前台，SendInput 只对前台窗口有效

### TaskRunner 状态机

每个任务在独立线程中运行，采用**双频检测**架构。TaskRunner 委托 BaseTask 处理匹配和执行逻辑，自身仅负责状态机调度:

```
等待阶段 (低频 idle_check_interval_ms):
  task.match_start_trigger() 检测
  ├── 匹配成功 → task.execute_start_trigger() → 进入执行阶段
  └── 匹配失败 → 等待 idle 间隔后继续

执行阶段 (高频 active_check_interval_ms):
  task.match_step() 检测
  ├── 匹配成功 → task.execute_step() → 下一步 / 失败处理
  ├── 超时 → 重试当前步骤 / 累计3次超时后重置到等待阶段
  └── 全部完成 → 回到等待阶段
```

游戏未运行 → 暂停检测，每 2 秒检查一次

**匹配模式**:

- 默认: 固定位置匹配 (`match_from_image`)，覆盖图 bbox 坐标处逐像素比对
- `scan: "horizontal"`: 水平扫描匹配 (`match_from_image_scan`)，在覆盖图 Y 坐标对应行全宽滑动匹配
- 扫描模式适用于图标可能出现在同一行不同水平位置的场景

**关键设计**:

- `start_trigger` 是开始特征图，检测到才进入高频执行模式
- 无 `start_trigger` 时，任务直接执行 `steps` 序列
- 序列完成后自动回到低频等待，节省资源

**前台切换延迟**: 当检测到 start\_trigger 且需要将游戏从后台切回前台时，`BaseTask._click_matcher()` 会等待 3 秒让游戏画面稳定后再执行点击，避免首次点击失败。

**超时重试机制**:

- `step_timeout_ms` 默认 30 秒（从 5 秒延长）
- 步骤超时后累计超时计数
- 1-2 次超时：重置到当前序列开头重试
- 3 次超时：强制重置到 `start_trigger` 等待阶段
- 点击成功后重置超时计数

### 配置热重载

- `load_config()` 通过文件修改时间 (`mtime`) 检测变更
- TaskRunner 后台线程每轮循环检查 `_config_cache["mtime"]`
- 变更时通过 `task.reload()` 重新加载配置和资源
- `game_language` 变更时同时重新加载 i18n 翻译

### TUI 渲染

**布局结构** (自上而下):

```
任务面板 (顶部)
日志区域 (中间)
网格面板 (底部，仅黑客破解任务)
```

**任务面板**:

- 圆角边框面板风格 (`╭─ ╮ ╰ ╯ │ ─`)
- 面板宽度自适应内容，不拉满控制台
- 内置安全边距 (PAD=2)
- **选中行整行高亮背景色** `#585B70` (亮灰)，通过上下箭头键移动选择
- **任务状态指示**: `🗹` 表示运行中，`☐` 表示已停止
- **交互方式**: 上下箭头键选择任务，回车键切换运行/停止状态
- **任务分组树状结构**: 支持通过 `group` 字段将任务归类，分组标题独立显示，子项使用树状连接符缩进
- 分组标题不可选中，导航时自动跳过

**日志区域**:

- 无包裹，自然滚动
- 增量渲染: 只更新变化的行
- 日志显示本地化任务名
- 步骤名称黄色高亮 (trigger/confirm/complete 等)

**网格面板** (`_build_grid_panel`):

- 仅在黑客破解任务运行时显示，由 `_hack_display` 全局状态驱动
- 8 行网格数据，每行 10 个两位数，目标位置绿色高亮，光标位置下划线标记
- 目标与光标重叠时显示绿色下划线
- 无 header 行（目标 Host 已在日志区红色显示）
- 游戏结束时追加 footer 行 `[任务名] 游戏结束`，网格冻结在最后一刻状态
- 破解失败时面板清除，成功时面板保持冻结直到下次破解开始

**配色方案** (Catppuccin Mocha):

- 红: `#F38BA8` - 错误/警告
- 绿: `#A6E3A1` - 成功/执行次数
- 黄: `#F9E2AF` - 步骤名称/数字键
- 蓝: `#89B4FA` - 边框
- 高亮背景: `#585B70` - 选中行

### i18n 国际化

```python
i18n_init(lang, base_dir)  # 加载翻译文件
translate(key, **kwargs)    # 获取翻译，支持模板参数
```

- `game_language` 配置同时控制: 视觉资源目录选择 + UI 翻译
- `lang: "auto"` 的步骤优先查找对应语言目录，回退到 `global/` → `en_US/`
- 语言标识统一为 `zh_CN`、`zh_TW`、`en_US`
- **任务显示名**: 通过 `task.{key}` 翻译键映射，如 `task.[disruption_logistics] fast-track` → `地堡 - 加速研究` / `Bunker - Fast-track Research`
- **分组标题**: 通过 `group.{group_key}` 翻译键映射，如 `group.hack_solver` → `黑客游戏自动破解`

**新增翻译键**:

```json
{
    "step_timeout": "监控超时，重新监控",
    "step_timeout_reset": "监控超时，结束监控",
    "detected": "检测到 {name} ({confidence})",
    "process_killed": "已终止游戏进程 ({confidence})",
    "process_kill_failed": "终止游戏进程失败",
    "hack_capture_failed": "截屏失败",
    "hack_target_read_failed": "目标 Host 读取失败",
    "hack_target_not_found": "未在网格中找到目标",
    "hack_target_detected": "目标 Host: {target}",
    "hack_target_found": "目标位于位置 {pos}",
    "hack_executing": "执行按键: {keys}",
    "hack_completed": "破解完成",
    "hack_game_over": "游戏结束",
    "hack_resetting": "重置游戏",
    "breach_target_detected": "目标值: {target}",
    "breach_number_read_failed": "第{index}个数字读取失败",
    "breach_numbers_detected": "数字: {numbers}",
    "breach_symbol_read_failed": "第{index}个符号识别失败",
    "breach_symbols_detected": "符号: {symbols}",
    "breach_no_solution": "未找到有效配对方案"
}
```

***

## 命名哲学

### 核心原则

所有命名以**简体中文**为基准，遵循以下本地化策略：

| 语言                | 翻译策略                   | 示例                            |
| ----------------- | ---------------------- | ----------------------------- |
| **简体中文 (zh\_CN)** | 基准语言，直接使用游戏内术语         | "地堡"、"网络地址"、"黑客"                |
| **繁体中文 (zh\_TW)** | 基于 zh\_CN 本地化，符合台湾语法习惯 | "地堡"→"地堡"、"网络地址"→"網路地址"、"黑客"→"駭客" |
| **英语 (en\_US)**   | 使用 GTA5 原版游戏内存在的词汇     | "地堡"→"Bunker"、"任务"→"Mission"  |

### 英语命名准则

**必须基于 GTA5 原版游戏内实际存在的英文词汇**，而非直译：

| ❌ 避免 (直译)             | ✅ 使用 (游戏原版)             | 说明               |
| --------------------- | ----------------------- | ---------------- |
| Fortress              | **Bunker**              | 游戏内实际使用 "Bunker" |
| Research Acceleration | **Fast-track Research** | 使用游戏内按钮原文        |
| Decrypt / Crack       | **Hack** / **IP Crack** | 黑客小游戏使用 "Hack"   |
| Task / Quest          | **Mission** / **Job**   | 任务系统使用 "Mission" |
| Settlement            | **Results Screen**      | 结算界面使用 "Results" |
| Exit Game             | **Quit** / **Leave**    | 退出使用游戏内用词        |

### 命名优先级

```
1. 准确性 > 简洁性 > 一致性
2. 优先使用游戏 UI 中出现的原文
3. 次优先使用游戏内 NPC 对话/提示中的用词
4. 最后参考 Rockstar 官方文档/更新日志
```

### 本地化示例

**任务名称**：

- zh\_CN: `地堡点击加速研究`
- zh\_TW: `地堡點擊加速研究`
- en\_US: `Bunker - Fast-track Research`

**分组标题**：

- zh\_CN: `黑客游戏自动破译`
- zh\_TW: `駭客遊戲自動破譯`
- en\_US: `Hack Solver`

**UI 元素**：

- zh\_CN: `任务结束退出游戏`
- zh\_TW: `任務結束退出遊戲`
- en\_US: `Close Game at Results Screen`

### 变量命名例外

代码中的变量、函数、类名使用 **snake\_case / PascalCase** 英语命名，但应反映简体中文概念：

```python
# ✅ 正确: 使用英语，但反映中文概念
bunker_fast_track_research  # 地堡点击加速研究
hack_solver_ip_crack        # 网络地址
mission_results_quit        # 任务结果退出

# ❌ 避免: 直译或脱离游戏语境
fortress_research_accel     # 错误词汇
decrypt_ip_address          # 非游戏用词
```

### 回显设计原则

日志回显应当**直观、自然、符合人类语言习惯**，避免机械化的技术术语暴露给用户。

#### ❌ 避免机械化提示

```
[任务结束退出游戏] 检测到 trigger (95.0%)
[任务结束退出游戏] 点击 exit (95.0%)
```

#### ✅ 使用自然语言

```
[任务结束退出游戏] 发现任务结束界面 (95.0%)
[任务结束退出游戏] 正在退出游戏 (95.0%)
```

### 实现方式

通过 `step.{overlay_name}.{task_name}` 翻译键为每个任务的每个步骤定义自然语言描述：

```json
{
    "step.trigger.bunker_fast_track_research": "研究界面",
    "step.confirm.bunker_fast_track_research": "已点击加速",
    "step.complete.bunker_fast_track_research": "研究完成",
    
    "step.trigger.force_close_game_after_mission_results": "任务结束界面",
    "step.exit.force_close_game_after_mission_results": "正在退出游戏",
    
    "step.trigger.hacker_game_ip_crack": "黑客小游戏",
    "step.hack.hacker_game_ip_crack": "正在破解"
}
```

### 设计准则

| 场景       | 准则             | 示例                                |
| -------- | -------------- | --------------------------------- |
| **触发检测** | 使用"发现"而非"检测到"  | `发现任务结束界面`                        |
| **执行动作** | 使用进行时表示正在发生的动作 | `正在退出游戏`、`已点击加速`                  |
| **完成状态** | 使用完成时表示结束      | `研究完成`、`破解完成`                     |
| **错误提示** | 简洁明了，避免技术细节    | `退出游戏失败` 而非 `TerminateProcess 失败` |

### 语言适配

- **简体中文**: 简洁直接，`发现`、`正在`、`已`、`完成`
- **繁体中文**: 符合台湾用语习惯，`發現`、`正在`、`已`、`完成`
- **英语**: 使用游戏内原词，`Found`、`Closing`、`Complete`

***

## 命名规范

| 类别     | 规范                               | 示例                                                            |
| ------ | -------------------------------- | ------------------------------------------------------------- |
| 真常量    | `UPPER_SNAKE_CASE`               | `CONFIG_FILE`, `BASE_DIR`, `INPUT_MOUSE`                      |
| 可变全局状态 | `_lower_snake_case`              | `_config_cache`, `_log_buffer`, `_translations`               |
| 内部类    | `_PascalCase`                    | `_LogBuffer`, `_RECT`, `_INPUT`                               |
| 公开类    | `PascalCase`                     | `OverlayMatcher`, `TaskRunner`, `HackingSolver`               |
| 公开函数   | `snake_case`                     | `find_game_window`, `capture_window`, `translate`, `send_key` |
| 内部函数   | `_snake_case`                    | `_find_pid_by_name`, `_make_mouse_input`, `_make_key_input`   |
| 方法     | `snake_case`                     | `_load_overlay`, `_click_matcher`, `_read_timing`             |
| 属性     | `snake_case`                     | `center`, `bbox`, `is_running`                                |
| 语言标识   | `xx_XX` (ISO 639-1 + ISO 3166-1) | `zh_CN`, `zh_TW`, `en_US`                                     |

***

## 踩坑记录

### 1. SendInput 点击失败

**现象**: 鼠标移动到目标位置但没有点击效果。

**原因链**:

- Windows UIPI: 非管理员进程无法向管理员进程发送 SendInput
- LEFTDOWN + LEFTUP 放在同一个 SendInput 调用中，部分游戏引擎无法识别

**解决**:

- 分开发送: LEFTDOWN 和 LEFTUP 各自独立调用 `SendInput`，中间间隔 80ms
- SetCursorPos 后等待 100ms

### 2. PostMessage 对 GTA5 无效

**现象**: PostMessage WM\_LBUTTONDOWN/UP 发送成功但游戏无反应。

**原因**: RAGE 引擎使用 DirectInput/Raw Input 读取鼠标状态，不处理 WM\_LBUTTONDOWN 消息。

**结论**: 只保留 SendInput 一种点击方式。

### 3. 识图误匹配

**现象**: trigger 置信度 80.8% 时误触发点击，confirm 自然超时。

**原因**: `match_threshold` 设为 0.8 过低，游戏画面中某些区域颜色接近导致误匹配。

**解决**: 提高阈值到 0.95。

### 4. 任务目录名不匹配

**现象**: `IndexError: list index out of range` 或 `No such file or directory`。

**原因**: 任务目录名与 `config.json` 中的键名不一致。

**解决**: 统一任务键名与目录名（包括空格和特殊字符）。

### 5. 覆盖图资源不一致导致点击偏移

**现象**: 英文版 trigger.png 点击偏移到右上方。

**原因**: 不同语言版本的覆盖图尺寸/Alpha 通道不一致。OverlayMatcher 的 center 基于不透明区域的边界框计算，如果英文版的不透明区域范围与简中版不同，点击坐标就会偏移。

**解决**: 所有语言版本的覆盖图必须使用相同的画布尺寸 (3840x2160)，且目标 UI 元素的位置必须一致。只替换文字部分，不改变按钮位置。

### 6. 前台切换后首次点击失败

**现象**: 当程序检测到 start\_trigger 且需要将游戏从后台切回前台时，首次点击没有生效。

**原因**: 游戏从后台切回前台时会卡顿，画面尚未稳定就执行了点击。

**解决**: 在 `_click_matcher` 中检测窗口是否已在后台，若从后台切回则等待 3 秒让游戏画面稳定后再点击。

### 7. 步骤超时导致任务流混乱

**现象**: complete 步骤超时后，任务回到 confirm 重试，连续失败多次才完成。

**原因**:

- 超时时间 5 秒过短
- 超时后只重置 step\_index，未重置 sequence\_started，导致在 steps 内循环

**解决**:

- 延长 `step_timeout_ms` 默认值为 30 秒
- 添加 `_timeout_count` 计数器
- 1-2 次超时：重置到序列开头重试
- 3 次超时：设置 `sequence_started = False`，强制回到 `start_trigger` 等待阶段

### 8. 水平扫描匹配在真实游戏画面中失效

**现象**: `match_from_image_scan` 在测试代码中能工作，但在真实 GTA5 画面中无法找到图标。

**原因**:

- 模板中 21.5% 的透明像素保留了覆盖图 PNG 的原始 BGR 值
- `TM_CCOEFF_NORMED` 无掩码时，这些像素参与相关计算
- 真实游戏画面中，透明区域是游戏背景而非模板值，导致相关系数极低 (0.08)

**解决**:

- 在 `_load_overlay` 中创建 `_template_scan`：将透明像素填充为不透明像素均值
- `TM_CCOEFF_NORMED` 的零均值化自动消除均值填充像素的影响
- 第二阶段 absdiff 仍使用原始 `_template` + mask 做精确验证
- 阈值从 0.7 降低到 0.5，提高检测灵敏度

### 9. TUI 日志延迟显示

**现象**: 检测到 trigger 的日志没有立即显示，而是和后续日志一起刷新。

**原因**: `click_delay` 期间使用单次 `time.sleep(0.5)`，TUI 主线程虽然继续渲染，但日志刷新有延迟。

**解决**: 将 `time.sleep(click_delay)` 拆分为 100ms 小段循环，让 TUI 有更多机会刷新显示。

### 10. SendInput 键盘虚拟键码对 GTA5 无效

**现象**: `send_key` 使用虚拟键码（VK\_W=0x57 等）发送按键，游戏无任何反应，光标不移动。

**原因**: RAGE 引擎使用 DirectInput/Raw Input 读取键盘状态，不处理虚拟键码的 SendInput。与踩坑 #2（PostMessage 对 GTA5 无效）同一根因。

**解决**:

- 改用硬件扫描码（Scan Code）+ `KEYEVENTF_SCANCODE` 标志
- 扫描码映射: W=0x11, A=0x1E, S=0x1F, D=0x20, Enter=0x1C
- 设置 `ki.wVk = 0`，`ki.wScan = scan_code`，`ki.dwFlags = flags | KEYEVENTF_SCANCODE`
- KEYDOWN 和 KEYUP 分开发送，间隔 80ms

### 11. 黑客破解光标位置假设导致路径错误

**现象**: 网格在滚动，且之前失败的按键可能改变了光标位置，但代码假设光标始终在初始位置 34，导致路径计算错误。

**原因**: 光标位置受网格滚动和之前的按键影响，不能假设固定位置。

**解决**:

- `_read_grid` 返回 `(grid, cursor_pos)` 元组，而非仅返回 grid
- 新增 `_detect_cursor_row` 方法：采样数字像素，检测 R > G×2 的红色像素占比 > 30% 判定为光标行
- 寻路使用检测到的实际光标位置

### 12. 黑客破解红色高亮数字无法识别

**现象**: 光标行的数字是红色高亮的，absdiff 彩色匹配与模板（白色/灰色）颜色差异大，置信度极低。

**原因**: 普通数字 BGR≈(220,220,220)，红色高亮数字 BGR≈(0,0,227)，absdiff 差异巨大。

**解决**:

- 双层匹配策略：先用 absdiff 彩色匹配（置信度 > 0.7 直接返回），失败后回退到形状轮廓匹配
- 形状轮廓匹配：取 max(R,G,B) 通道二值化，比较掩码区域内的前景/背景一致性，颜色无关

### 13. TUI 边框右侧无法闭合

**现象**: 任务列表面板的右侧边框 `│` 与顶部 `╮` 不对齐，少一个字符宽度。

**原因**:

- `☐` (U+2610) 和 `🗹` (U+1F5F9) 等 Unicode 符号的显示宽度在不同终端中不一致
- 某些终端中这些符号占1列，而 `unicodedata.east_asian_width()` 返回 "N" (Neutral)
- `_visible_len()` 函数原本错误地将这些符号计算为2列宽度

**解决**:

- 移除对 `☐` 和 `🗹` 的特殊宽度处理
- 依赖 `unicodedata.east_asian_width()` 的标准返回值（这些符号返回 "N"，按1列计算）
- 同时移除了 `cycle_count` 执行次数统计功能，简化了界面

### 14. 模板 PNG 的 alpha 通道全为 255 导致 OCR 失败

**现象**: 数字/符号识别全部失败，所有模板匹配返回置信度 1.0 但识别为错误数字（如 8→0）。

**原因**:

- 检查模板 PNG 发现所有像素的 alpha 值都是 255（完全不透明）
- 原本使用 alpha > 128 生成掩码，导致掩码覆盖整个图像区域
- 形状匹配比较的是整个区域而非仅数字笔画，使 8 和 0 在彼此掩码内几乎一致

**解决**:

- 改用**亮度阈值**生成掩码：`np.max(bgr, axis=2) > 30`
- 数字笔画像素 BGR≈(205,205,205)，背景像素 BGR≈(12,12,12)
- 30 的阈值能可靠分离前景/背景

### 15. Union mask 形状匹配解决相似数字混淆

**现象**: 使用模板 mask 做形状匹配时，8 被识别为 0（conf=1.0），9 被识别为 7（conf=0.92）。

**原因**:

- 仅使用模板 mask 时，8 的中间横杠在 0 的 mask 之外被忽略
- 比较区域只包含 0 的圆形部分，8 的额外笔画不影响匹配分数

**解决**:

- 改用 **Union mask**：`union_mask = region_mask | template_mask`
- 比较区域包含模板和图像中所有前景像素
- 8 的中间横杠现在被计入，与 0 的差异得以体现

### 16. Per-template 定位解决窄字符偏移

**现象**: 数字 "1"（38px 宽）被识别为 "0"（89px 宽），即使 shape matching 也失败。

**原因**:

- 使用参考尺寸（最大模板 0 的 89px）计算 `x_start = cx - ref_w // 2`
- 对于 "1"，这个偏移量导致提取的 patch 偏向左侧，只包含数字的左半部分

**解决**:

- 每个模板使用自己的宽高计算偏移：`x_start = cx - tw // 2`
- 确保窄字符的 patch 中心与组件中心对齐

### 17. 符号尺寸过滤防止误匹配

**现象**: x2（157px 高）被识别为 x1（79px 高），因为 x1 模板匹配了 x2 的上半部分。

**原因**:

- 符号高度差异大（x1=79px, x2=157px, x10=150px）
- 小模板可以匹配大符号的局部区域，给出较高置信度

**解决**:

- 添加 CC 组件高度与模板高度的比值过滤：`0.6 <= cc_h / th <= 1.6`
- 尺寸差异过大的模板直接跳过，避免局部匹配

### 18. 滚动监控线程误判光标移动为网格滚动

**现象**: 程序操作光标移动时，`_ScrollMonitor` 后台线程将光标高亮区域的变化误判为网格滚动，导致网格状态被错误偏移，路径计算完全错误。

**原因**:

- `_ScrollMonitor` 通过帧差法检测水平位移，无法区分"网格整体滚动"和"光标高亮移动"
- 程序发送上下左右箭头键按键后，光标行的红色高亮会移动到新位置，帧差法检测到变化后误报为滚动
- 滚动计数被错误累加，`_apply_scroll` 将网格偏移到错误状态

**解决**:

- 移除 `_ScrollMonitor` 线程、`_apply_scroll`、`_extract_grid_area`、`_detect_cursor_row_only` 等滚动推断相关代码
- 改为实时重读策略：每执行 8 步按键后，重新截屏并完整 OCR 读取当前网格和光标位置
- 不做任何变化检测推断，每次重读都从屏幕获取最新真实状态
- 目标位置变化时自动重新规划路径

### 19. 光标蛇形换行与同行循环导致路径错误

**现象**: 光标到达行末按 D 后应跳到下一行行首，但代码将列视为同行循环（col+1 mod 10），导致光标回到同行行首而非换行，路径计算完全错误。

**原因**:

- `_move` 方法使用 `col = (col + 1) % GRID_COLS` 实现列移动，这是同行循环
- `_plan_path` 使用 `col_diff = (g_col - s_col) % GRID_COLS` 计算列距离，也是同行循环距离
- 实际游戏中光标是蛇形换行：D 到行末跳到下一行行首，A 到行首跳到上一行行末
- 同行循环和蛇形换行在多数情况下结果不同，尤其当目标在光标的跨行方向时

**解决**:

- 重写 `_move` 方法实现蛇形换行：D 在 col=9 时跳到 (row+1, 0)，A 在 col=0 时跳到 (row-1, 9)
- 重写 `_plan_path` 考虑蛇形换行的路径代价
- 重写网格读取逻辑，用红色 OCR 视觉定位光标行和列，替代算法推断

### 20. 目标序列跨行时查找失败

**现象**: 当目标 4 个连续数字跨越两行（如行末 2 个 + 下一行行首 2 个）时，`_find_target_in_grid` 返回 None，提示"未在网格中找到目标"。

**原因**:

- `_find_target_in_grid` 使用 `(col + k) % GRID_COLS` 计算连续位置，这是同行循环（到行末回到同行行首）
- 实际游戏光标是蛇形换行（到行末跳到下一行行首）
- 当目标跨行时，同行循环无法匹配到正确的连续位置

**解决**:

- 改用 `_move(pos, "right")` 追踪连续 4 个位置
- `_move` 已正确实现蛇形换行逻辑，天然支持跨行目标查找

### 21. 光标跨行时位置检测间歇性失败

**现象**: 光标 4 格选区跨越两行时，光标位置检测不稳定，有时正确有时错误，表现为光标短暂"失焦"后重新锁定。

**原因**:

- `_read_grid` 使用 `is_cursor_row` 门控（`red_in_row / len(row_digits) > 0.2`）决定是否收集该行红色位置
- 光标跨行时，每行只有 2 个红色数字 / 10 个总数 = 0.2，**不满足** `> 0.2`
- OCR 漏检的随机性导致某行偶尔少于 10 个数字（如 8 个，2/8=0.25>0.2 通过），造成间歇性
- 门控失败的行不收集红色位置，蛇形左邻判断缺少数据，导致光标位置错误

**解决**:

- 移除 `is_cursor_row` 行级门控，始终收集所有红色位置到 `red_positions` 集合
- `_is_component_red` 已有 30% 红色像素阈值过滤噪声，行级门控是多余的
- 蛇形左邻判断在完整的红色位置集合上工作，跨行场景稳定可靠

### 22. 重读后光标与目标在 TUI 中捆绑移动

**现象**: 光标到达目标后，TUI 面板中光标（下划线）和目标（绿色）重叠显示。重读后网格滚动导致目标位移，但光标和目标仍然重叠显示，直到下一次按键才分开。

**原因**:

- `_attempt_hack` 的两个重读点（对位重读 + 周期重读）在更新 `current_pos` 和 `current_target_pos` 后，没有调用 `_update_display`
- 旧显示状态（光标=目标）一直保留到下一次按键时才刷新
- 视觉上表现为光标和目标"捆绑移动"，而非独立显示各自位置

**解决**:

- 在两个重读点之后都立即调用 `_update_display`，传入最新的光标位置和目标位置
- TUI 面板即时反映两者的独立位置，用户可清晰看到光标追踪目标的过程

### 23. 黑客破解日志与 TUI 面板信息冗余与布局错位

**现象**:

1. 游戏开始时日志区输出完整网格数据（8 行缩进 + 光标位置），与 TUI 网格面板内容重复
2. TUI 网格面板有 "目标: XX.XX.XX.XX" header 行，与日志区 "目标 Host: XX.XX.XX.XX" 重复
3. "游戏结束" 消息写入日志区，出现在网格面板上方而非下方，视觉上像是旧日志
4. 游戏结束时 TUI 网格面板立即清除，无法看到最终网格状态

**原因**:

- 初始网格数据同时输出到日志和 TUI 面板，信息冗余
- `_build_grid_panel` 生成 header 行显示目标 IP，而日志区已有相同信息
- "游戏结束" 通过 `_log_buffer.add()` 写入日志区，而 TUI 布局为 `任务面板 → 日志区 → 网格面板`，日志区在网格面板上方
- 游戏结束时调用 `_hack_display_clear()` 清除面板，网格数据丢失

**解决**:

- 移除 `_attempt_hack` 中初始网格日志输出（"网格:" + 缩进行 + "低置信:" + "光标:"），网格数据仅通过 TUI 面板显示
- 移除 `_build_grid_panel` 的 "目标:" header 行，目标 Host 已在日志区红色显示
- "游戏结束" 改为通过 `_hack_display_update(game_over=True)` 写入网格面板状态，`_build_grid_panel` 在网格行下方追加 footer 行
- 游戏结束时不再调用 `_hack_display_clear()`，面板冻结在最后一刻；仅在破解失败时清除
- 目标 Host 日志行中的数字使用 `C_RED` 颜色高亮，与游戏内红色目标 Host 视觉一致
- 移除 iti（inter-trigger interval）功能，序列完成时不再追加间隔时间统计

### 24. 游戏失败时 trigger 消失被误判为游戏成功结束

**现象**: 光标移动过程中游戏失败（超时或错误过多），出现失败界面，但日志显示"游戏结束"而非"重置游戏"，TUI 面板网格冻结在全零行状态。

**原因**:

- 游戏失败时 trigger 图标也会消失，与游戏成功完成表现一致
- 代码在 trigger 消失时直接判定为游戏成功结束，未区分两种情况
- 失败界面的网格区域无数字（全零行），`_find_target_in_grid` 返回 None，但此时返回 None 会触发 TaskRunner 的超时重试循环

**解决**:

- 在 trigger 消失的判定点（对位重读 + 周期重读），先调用 `_check_fail` 检测失败界面
- 失败界面存在 → 返回 `"reset"`，按 Enter 重置游戏
- 失败界面不存在 → 才判定为游戏成功结束
- 目标未在网格中找到时，直接返回 `"reset"` 而非输出错误信息，避免刷屏

### 25. 电压连线符号导航键错误与光标起始位置假设错误

**现象**: 电压连线任务中，数字和符号都能准确识别，但执行时符号选择顺序错误，导致配对失败（如目标76实际得到94）。

**原因**:

- 代码使用 `right`/`left` 键在符号间导航，实际游戏使用 `up`/`down` 键
- 代码假设光标默认出现在第一个可用符号（从上到下），实际光标出现在第 i 个符号位置（i 为当前操作的数字索引，0-indexed）
- 若第 i 个符号位置已被选择，光标自动跳到下一个可用符号（向下循环）

**解决**:

- 将符号导航从 `right`/`left` 改为 `up`/`down`
- 光标起始位置改为 `cursor_pos = i`，若已选则 `cursor_pos = (cursor_pos + 1) % NUM_COUNT` 循环跳过
- 导航步数基于光标在可用列表中的位置与目标在可用列表中的位置之差
- 每步执行后截屏重读 TARGET 验证实际结果，而非根据推断计算

### 26. 电压连线日志乘号格式不统一

**现象**: 日志中乘号与数字之间缺少空格，如 `5 ×10 = 50`，不符合标准数学公式表达习惯。

**原因**:

- 符号字符串替换逻辑为 `s.replace("x", "×")`，仅将字母 x 替换为乘号，未在乘号后添加空格
- 导致 `×10` 被当作一个整体符号显示，视觉上与 `× 10` 的规范写法不一致

**解决**:

- 将替换逻辑改为 `s.replace("x", "× ")`，在乘号后追加一个空格
- 日志输出从 `5 ×10 = 50` 变为 `5 × 10 = 50`，符合标准公式格式
- 同步调整 `sym_w` 宽度计算，确保对齐不受空格影响

### 27. 代码中残留硬编码中文/英文文本

**现象**: 扫描整个代码库发现多处用户可见的硬编码字符串未走 `translate()` 国际化，包括：

1. `main.py` 异常信息：`无法加载覆盖图`、`覆盖图必须为带 Alpha 通道的 RGBA 图像`、`覆盖图中没有不透明像素`
2. `main.py` 崩溃提示：`FATAL: {e}`、`Press Enter to exit...`
3. `hack_solver_ip_crack/task.py` 状态提示：`准备寻路...`、`已对位目标 (第X次)，等待重读...`、`重读: 光标R{x}C{y} 目标R{x}C{y}`

**原因**:

- 早期开发时直接写入中文/英文硬编码字符串，后续国际化时遗漏
- 异常信息和调试状态提示未被纳入翻译体系

**解决**:

- 新增翻译键并同步到 `zh_CN` / `zh_TW` / `en_US`：
  - `overlay_load_error` / `overlay_format_error` / `overlay_empty_error`
  - `fatal_error` / `press_enter_to_exit`
  - `hack_planning_path` / `hack_target_aligned` / `hack_reread_status`
- 将所有硬编码字符串改为 `translate(key, **kwargs)` 调用
- 建立规则：**任何用户可见文本必须通过 `translate()`，禁止硬编码**

### 28. PostMessage 后台键盘输入对 GTA5 游戏操作无效

**现象**: 使用 `PostMessageW` 发送 `WM_KEYDOWN`/`WM_KEYUP` 消息到 GTA5 窗口，游戏无任何反应，角色不移动、菜单不响应。

**原因**:

- 与踩坑 #2（PostMessage 鼠标消息对 GTA5 无效）和踩坑 #10（SendInput 虚拟键码对 GTA5 无效）同一根因
- RAGE 引擎使用 DirectInput/Raw Input 读取键盘状态，不处理 Windows 消息队列中的 `WM_KEYDOWN` 消息
- `PostMessageW` 将消息投递到窗口的消息队列，但游戏不从此队列读取键盘输入

**解决**:

- 防挂机功能改用 `SendInput` + 硬件扫描码（`send_key`），将游戏短暂切至前台发送按键
- 切前台后不切回原窗口，让游戏保持前台
- 仅在游戏处于后台时计时，游戏在前台时计时器归零，避免不必要的切换

### 29. 电压连线回显扁平日志改为边框盒 + 动画并行

**现象**: 电压连线任务的回显使用扁平日志行（可用符号行 + 配对行 + 分隔线 + 累计和），无视觉包裹感，乘数出现缓慢，累计数无过渡动画。

**原因**:

- 原实现使用 `_log_buffer.replace_at()` 原地替换扁平文本行，无边框包裹
- 乘数确认后直接 `sleep(delay)` 等待动画延迟，期间无视觉反馈
- 累计数直接跳变到目标值，无递增过渡
- 累计数动画在主线程阻塞执行，导致下一步操作延迟

**解决**:

- 改用 7 行边框盒（`╭─╮│╰╯─`）包裹配对行 + 分隔线 + 累计和，预计算固定宽度
- 乘数确认后立即显示并启动黄色闪烁动画（3 次，0.15s 间隔），闪烁期间等待动画延迟
- 累计数使用后台 `daemon` 线程逐帧递增（30ms/帧），与闪烁动画并行执行
- 游戏结束后先输出绿色"游戏结束"文本，再 `join()` 等待动画线程完成
- 移除可用符号行和 `breach_target_detected` 日志行（目标值已在框内累计和行显示）
- 注入 `C_BORDER`、`C_BLUE` 颜色常量到 task.py

## 配置说明 (config.json)

```json
{
    "game_language": "en_US",
    "game_process_name": "GTA5_Enhanced.exe",
    "anti_afk": {
        "enabled": true,
        "key": "enter",
        "interval_min": 10
    },
    "vision": {
        "match_threshold": 0.95,
        "alpha_threshold": 128
    },
    "tasks": {
        "bunker_fast_track_research": {
            "match_threshold": 0.95,
            "idle_check_interval_ms": 2000,
            "active_check_interval_ms": 500,
            "click_delay_ms": 500,
            "step_timeout_ms": 30000
        },
        "close_game_at_results": {
            "match_threshold": 0.95,
            "idle_check_interval_ms": 2000,
            "active_check_interval_ms": 500,
            "click_delay_ms": 500,
            "step_timeout_ms": 30000
        },
        "hack_solver_ip_crack": {
            "match_threshold": 0.95,
            "idle_check_interval_ms": 2000,
            "active_check_interval_ms": 500,
            "click_delay_ms": 500,
            "step_timeout_ms": 60000
        },
        "hack_solver_voltlab": {
            "match_threshold": 0.95,
            "idle_check_interval_ms": 2000,
            "active_check_interval_ms": 500,
            "click_delay_ms": 500,
            "step_timeout_ms": 60000
        }
    }
}
```

| 字段                                     | 说明                                                                             |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| `game_language`                        | 游戏语言，影响视觉资源目录和 UI 翻译，统一格式 `zh_CN` / `zh_TW` / `en_US`                          |
| `game_process_name`                    | 游戏进程名                                                                          |
| `anti_afk.enabled`                     | 防挂机功能开关                                                                       |
| `anti_afk.key`                         | 防挂机发送的按键 (默认 `enter`)，支持字母键、数字键、功能键等                                  |
| `anti_afk.interval_min`                | 防挂机按键间隔 (默认 10 分钟)                                                          |
| `vision.match_threshold`               | 全局匹配置信度阈值 (默认 0.95)                                                            |
| `vision.alpha_threshold`               | Alpha 通道不透明判定阈值                                                                |
| `tasks.<key>.match_threshold`          | 任务级阈值，覆盖全局                                                                     |
| `tasks.<key>.idle_check_interval_ms`   | 等待阶段检测间隔 (默认 2000ms)                                                           |
| `tasks.<key>.active_check_interval_ms` | 执行阶段检测间隔 (默认 500ms)                                                            |
| `tasks.<key>.click_delay_ms`           | 点击后等待时间                                                                        |
| `tasks.<key>.step_timeout_ms`          | 非首步超时时间 (默认 30000ms)                                                           |

**配置职责分离**: `start_trigger`、`steps`、`group` 等任务结构定义在 `task.py` 的 `Task(BaseTask)` 类属性中；`config.json` 仅存储时序参数（检测间隔、超时、阈值等），支持热重载。

**分组配置**: 任务的 `group` 在 `task.py` 的 `Task` 类属性中定义（如 `group = "hack_solver"`），对应 locale 翻译键 `group.hack_solver`。

```json
    "group.hack_solver": "黑客游戏自动破解",
    "task.hack_solver_ip_crack": "网络地址"
}
```

TUI 渲染效果:

```
  ☐  地堡点击加速研究
  ☐  结算界面结束游戏
  黑客游戏自动破解
    └─ ☐  电压连线
    └─ ☐  网络地址
  ☐  防止游戏挂机检测
```

***

## 新增任务指南

1. 在 `tasks/` 下创建任务目录 (如 `my_task/`)，**目录名将成为 config.json 中的键名**，命名以英文为准
2. 在任务目录下创建 `task.py`，定义 `Task(BaseTask)` 子类，声明 `start_trigger`、`steps`、`group` 类属性
3. 在任务目录下创建语言子目录: `global/`, `zh_CN/`, `zh_TW/`, `en_US/`
4. 将覆盖图 PNG 放入对应目录，**必须为 3840x2160 RGBA 透明 PNG**
5. 命名语义化 (如 `trigger.png`, `confirm.png`)
6. **所有语言版本的目标 UI 元素位置必须一致**，仅文字不同
7. 在 `config.json` 的 `tasks` 中添加条目，**键名必须与目录名完全一致**
8. 每个步骤的 `lang` 字段: `"global"` 表示通用，`"auto"` 表示跟随 `game_language` 配置
9. 在各语言 locale 文件中添加 `task.{key}` 翻译键和 `step.{overlay}.{key}` 翻译键
10. 如需分组显示，在 Task 类中设置 `group = "group_key"`，并在 locale 中添加 `group.group_key` 翻译键
11. 如需自定义 action，覆写 `execute_step()` 方法（参考 `hack_solver_ip_crack/task.py`）
12. task.py 中可直接使用 `BaseTask`、`OverlayMatcher`、`click_at` 等注入符号，标准库和第三方库需显式 import

***

## 已知限制

- `PrintWindow` 对某些全屏独占模式可能返回黑屏，需要窗口化或无边框窗口模式
- SendInput 要求窗口在前台，点击时会打断用户操作
- 覆盖图固定位置匹配不支持多分辨率自适应 (当前硬编码 4K 3840x2160)；水平扫描模式仅在同一行内滑动，不支持跨行搜索
- `bring_to_foreground` 在某些情况下可能失败 (Windows 前台锁定策略)
- 任务键名必须与目录名完全一致（包括空格和特殊字符）
- 黑客破解的网格坐标基于 4K 分辨率硬编码（grid.json），不同分辨率需重新校准
- 黑客破解的 OCR 依赖数字模板匹配，游戏更新字体后需重新截取模板

***

## 变更记录

### 26w18d (2026-04-30)

**修改范围**: `main.py` — BaseTask 扩展 `execute_key_sequence`、TaskRunner 新增按键序列分支、`_KEY_MAP` 补充 esc、TUI 菜单优化、全局顺序控制 `_TASK_ORDER`、组标题灰色显示、光标触底反弹、去掉菜单空行；`tasks/create_invite_only/task.py` — 新建；`locales/*.json` — 新增任务名

**修改原因**: 新增"创建仅限邀请战局"功能；TUI 菜单视觉和交互优化

**修改内容**:

- `main.py`: `_KEY_MAP` 新增 `"esc": 0x01`
- `main.py`: BaseTask 新增 `_is_key_sequence`、`_key_steps` 属性，`load()` 支持纯按键序列任务，新增 `execute_key_sequence()` 方法，`has_start_trigger` 和 `step_count` 兼容按键序列模式
- `main.py`: TaskRunner._run() 新增按键序列执行分支（聚焦+点击窗口中心+按键+自动关闭），hwnd=None 时快速失败
- `main.py`: 新增模块级常量 `_TASK_ORDER` 统一控制菜单显示顺序和配置生成顺序
- `main.py`: `_build_default_config()` 按 `_TASK_ORDER` 顺序生成配置
- `main.py`: 菜单导航支持触底反弹（顶部按上跳到底部，底部按下跳回顶部）
- `main.py`: 去掉菜单标题下方和列表下方的空白行
- `main.py`: 分组标题（黑客游戏自动破译）使用灰色弱化显示
- `main.py`: `execute_key_sequence` 日志改为"开始创建战局"/"战局创建完成"（黄色）
- `tasks/create_invite_only/task.py`: 新建，8步按键序列
- `locales/zh_CN.json` + `en_US.json`: 新增 `task.create_invite_only` 翻译键

**修改前后行为差异**:

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 创建仅限邀请战局 | 无此功能 | 菜单新增条目，启用后自动执行按键序列，完成后自动关闭 |
| 按键序列任务 | 不支持 | BaseTask + TaskRunner 框架原生支持 |
| 菜单任务顺序 | 按目录扫描顺序 | 按 `_TASK_ORDER` 固定顺序 |
| 菜单导航 | 顶部卡住/底部卡住 | 触底反弹，循环滚动 |
| 分组标题 | 白色 | 灰色弱化 |
| 菜单空白行 | 标题下方和列表下方有空行 | 无空行 |

**对系统影响范围**: 新建任务模块，扩展框架支持新任务类型；TUI 视觉和交互调整不影响任务执行逻辑

### 26w18c (2026-04-30)

**修改范围**: `main.py` — 标题边框颜色统一、性能显示安全边距；`tasks/hack_solver_ip_crack/task.py` — IP→Host 术语替换；`tasks/hack_solver_ip_crack/*/grid.json` — `target_ip`→`target_host`；`locales/*.json` — 翻译文本更新

**修改原因**: 游戏内实际显示为"Host"而非"IP"，术语不一致导致用户困惑。超时回显包含多余的动作名称和次数信息，不够简洁。标题行边框颜色存在混搭，性能信息紧贴边框缺少安全边距。

**修改内容**:

- `task.py`: `_read_target_ip` 重命名为 `_read_target_host`，所有相关变量名同步更新
- `grid.json`（三语言）: `target_ip` 键名改为 `target_host`
- `locales/*.json`: `hack_target_read_failed` 改为"目标 Host 读取失败"，`hack_target_detected` 改为"目标 Host: {target}"
- `locales/zh_CN.json` + `zh_TW.json`: `step_timeout` 改为"监控超时，重新监控"，`step_timeout_reset` 改为"监控超时，结束监控"
- `locales/en_US.json`: `step_timeout` 改为"Monitor timeout, restarting"，`step_timeout_reset` 改为"Monitor timeout, ending monitor"
- `main.py`: 标题行 `C_RESET` 后的空格前插入 `border_color`，统一边框颜色
- `main.py`: 性能显示从 `_rpad_to_width(" " + status_text + " ", inner_w)` 改为 `" " + _rpad_to_width(status_text, inner_w - 2) + " "`，确保左右各至少 1 字符安全边距

**修改前后行为差异**:

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 目标读取失败 | "目标 IP 读取失败" | "目标 Host 读取失败" |
| 目标检测成功 | "目标 IP: XX.XX.XX.XX" | "目标 Host: XX.XX.XX.XX" |
| 超时重试 | "正在|破解 超时，重新监控" | "监控超时，重新监控" |
| 超时结束 | "正在|破解 超时 3 次，重置任务流" | "监控超时，结束监控" |
| 标题行边框 | 空格处颜色为默认终端色 | 空格处颜色与边框统一 |
| 性能信息 | 紧贴右侧边框 | 左右各保留 1 字符安全边距 |

**对系统影响范围**: 仅影响显示文本和 TUI 布局，不改变任何任务检测或执行逻辑

### 26w18b (2026-04-29)

**修改范围**: `main.py` — 新增状态显示器；`locales/*.json` — 新增翻译键

**修改原因**: 游戏更新后原有识别功能失效，用户无法直观判断程序是否正常连接游戏。需要在界面顶部增加状态显示器，显示游戏连接状态和程序资源占用，方便排查问题。

**修改内容**:

- 新增 `_FILETIME`、`_PROCESS_MEMORY_COUNTERS` 结构体，用于 Windows API 调用
- 新增 `_get_process_cpu_percent()`：通过 `GetProcessTimes` 两次采样计算 CPU 占用率
- 新增 `_get_process_memory_mb()`：通过 `GetProcessMemoryInfo` 获取工作集内存
- 新增 `_get_game_status()`：三态判定游戏进程状态（未运行/无窗口/已连接）
- 修改 `_build_task_panel()`：在标题行下方插入状态行和分隔线，显示游戏连接状态、CPU、内存、线程数
- 修改 `main()` 主循环：每 3 秒检测游戏状态，每轮更新 CPU 采样
- 新增 6 个 i18n 翻译键（`status_connected`/`status_not_running`/`status_no_window`/`status_cpu`/`status_memory`/`status_threads`）

**修改前后行为差异**:

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 任务面板 | 仅显示任务列表 | 标题下方新增状态行，显示游戏连接和资源信息 |
| 游戏未运行 | 无直观提示 | 红色圆圈 + "未运行" |
| 游戏运行中 | 无直观提示 | 绿色圆点 + "已连接" |

**对系统影响范围**: 仅影响 TUI 显示层，不改变任何任务检测或执行逻辑

### 26w18a (2026-04-27)

**修改范围**: `main.py` — `load_config()` 及新增 `_build_default_config()`

**修改原因**: 首次运行或 `config.json` 被删除后，`load_config()` 返回空字典，导致 `_flatten_task_configs()` 无任务可解析，菜单仅显示硬编码的 `anti_afk` 一项，其余任务不可见。

**修改内容**:

- 新增 `_build_default_config()` 函数：自动扫描 `tasks/` 目录，逐个加载 `task.py` 模块读取 `group` 类属性，生成包含所有任务的默认配置（全部默认关闭）
- 修改 `load_config()`：当 `config.json` 不存在时，调用 `_build_default_config()` 生成默认配置并通过 `save_config()` 写入文件，而非返回空字典

**修改前后行为差异**:

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| `config.json` 不存在 | 菜单仅显示"防止游戏挂机检测" | 自动生成配置，菜单显示全部任务 |
| `config.json` 不存在 | 用户需手动创建配置文件 | 程序自动创建并写入默认配置 |

**对系统影响范围**: 仅影响 `config.json` 不存在时的首次启动行为，已有配置文件的用户不受影响

