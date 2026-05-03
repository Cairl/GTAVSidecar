# Connect Host Reset Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs in HackingSolver: (1) unwanted Enter press at game start from premature reset, (2) cannot restart task after game-over due to stale state and no retry on read failures.

**Architecture:** Three changes to `tasks/hack_solver_connect_host/task.py` in the `HackingSolver` class: add `_reset_solver_state()`, add `None` retry loop in `run()`, and relax the `target_not_found` branch from immediate reset to retry.

**Tech Stack:** Python 3.12, existing codebase patterns (no new dependencies)

---

### Task 1: Add `_reset_solver_state()` and call at `run()` start

**Files:**
- Modify: `tasks/hack_solver_connect_host/task.py`

- [ ] **Step 1: Add `_reset_solver_state()` method after `_clear_display()`**

Insert after line 489 (`_clear_display` method end):

```python
    def _reset_solver_state(self):
        self._clear_display()
```

- [ ] **Step 2: Call `_reset_solver_state()` at start of `run()`**

At line 709 (`focus_game_window(hwnd)`), insert before it:

```python
    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        self._reset_solver_state()

        focus_game_window(hwnd)
        clip_cursor_to_window(hwnd)
```

Full `run()` after change:

```python
    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        self._reset_solver_state()

        focus_game_window(hwnd)
        clip_cursor_to_window(hwnd)

        try:
            while True:
                result = self._attempt_hack(hwnd, display_name)
                if result == "reset":
                    self._clear_display()
                    _log_buffer.add(f"[{display_name}] {C_YELLOW}{translate('hack.' + self._task_name + '.resetting')}{C_RESET}")
                    send_key("enter")
                    time.sleep(1.0 / self._speed_ratio)
                    continue
                if result is not True:
                    self._clear_display()
                return result is True
        finally:
            unclip_cursor()
```

- [ ] **Step 3: Commit**

```bash
git add tasks/hack_solver_connect_host/task.py
git commit -m "feat: add _reset_solver_state() and call at run() start"
```

---

### Task 2: Add `None` retry loop in `run()`

**Files:**
- Modify: `tasks/hack_solver_connect_host/task.py`

- [ ] **Step 1: Rewrite `run()` to retry on `None` with `MAX_ATTEMPTS` limit**

Replace the entire `run()` method (lines 706-725) with:

```python
    def run(self, hwnd):
        display_name = translate("task." + self._task_name)

        self._reset_solver_state()

        focus_game_window(hwnd)
        clip_cursor_to_window(hwnd)

        try:
            attempts = 0
            while True:
                result = self._attempt_hack(hwnd, display_name)
                if result == "reset":
                    attempts = 0
                    self._clear_display()
                    _log_buffer.add(f"[{display_name}] {C_YELLOW}{translate('hack.' + self._task_name + '.resetting')}{C_RESET}")
                    send_key("enter")
                    time.sleep(1.0 / self._speed_ratio)
                    continue
                if result is True:
                    return True
                attempts += 1
                if attempts >= self.MAX_ATTEMPTS:
                    self._clear_display()
                    return False
                time.sleep(0.3 / self._speed_ratio)
        finally:
            unclip_cursor()
```

Key changes:
- `attempts` counter tracks consecutive `None` results
- `"reset"` resets counter to 0 (game state refreshed, worth retrying)
- `True` returns immediately (success)
- `None` increments counter; if >= `MAX_ATTEMPTS` (5), gives up and returns False
- Brief sleep between retries to let the game render the next frame

- [ ] **Step 2: Commit**

```bash
git add tasks/hack_solver_connect_host/task.py
git commit -m "fix: add None retry loop in run() with MAX_ATTEMPTS limit"
```

---

### Task 3: Change `target_not_found` from `"reset"` to `None`

**Files:**
- Modify: `tasks/hack_solver_connect_host/task.py`

- [ ] **Step 1: Change the return value at line 599**

In `_attempt_hack()`, change line 599 from `return "reset"` to `return None`:

```python
        target_pos = self._find_target_in_grid(target[:self.CURSOR_LEN], grid)
        if target_pos is None:
            self._init_display(display_name, target_str)
            for r in range(self.GRID_ROWS):
                row_vals = grid[r * self.GRID_COLS:(r + 1) * self.GRID_COLS]
                row_str = " ".join(f"{v:02d}" for v in row_vals)
                _log_buffer.replace_at(
                    self._grid_line_indices[r],
                    f"[{display_name}] {C_GRAY}{row_str}{C_RESET}"
                )
            _log_buffer.add(
                f"[{display_name}] {C_RED}{translate('hack.' + self._task_name + '.target_not_found', target=target_str)}{C_RESET}"
            )
            return None
```

The log message and grid display are preserved — the user still sees what happened. But instead of sending Enter to reset the game, `run()` will now re-capture and retry.

- [ ] **Step 2: Commit**

```bash
git add tasks/hack_solver_connect_host/task.py
git commit -m "fix: return None instead of reset on target_not_found"
```

---

### Task 4: Verify all changes are consistent

- [ ] **Step 1: Read the final file to verify correctness**

```bash
# Read the run() method and _attempt_hack() entry to verify
```

Check that:
1. `_reset_solver_state()` exists and delegates to `_clear_display()`
2. `run()` calls `_reset_solver_state()` at start, has `attempts` counter, retries on `None`
3. `_attempt_hack()` line ~599 returns `None` not `"reset"`

- [ ] **Step 2: Commit any final adjustments**

```bash
git add tasks/hack_solver_connect_host/task.py
git commit -m "chore: final review of connect_host reset fixes"
```
