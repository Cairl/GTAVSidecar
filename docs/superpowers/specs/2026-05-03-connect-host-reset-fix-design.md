# Connect Host: Fix Reset-on-Start and State-Cleanup Bugs

## Problem

### Bug 1: Unwanted Enter press at game start

At game start, `_attempt_hack()` returns `"reset"` (target not found in grid on first frame), causing `run()` to press Enter unnecessarily. The game interface is fully rendered at this point; a simple re-read would succeed.

### Bug 2: Cannot restart task after game-over

After the task completes (game over detected → `run_once` disables it), re-enabling and starting the task again shows "目标识别失败" and immediately disables. Two root causes:

1. `run()` treats `None` results as terminal — no retry loop, returns False immediately
2. `HackingSolver` state (`_target_pos`, `_grid_line_indices`, `_game_start_line_idx`) persists across `run()` calls

## Design

### Change 1: Add `_reset_solver_state()` method

New method on `HackingSolver` that clears all mutable state to initial values:

```
_reset_solver_state()
  - _target_pos = None
  - _grid_line_indices = []
  - _game_start_line_idx = None
```

Called at:
- **Start of `run()`** — ensures clean slate before each run (fixes Bug 2)
- **`return "reset"` path in `_attempt_hack()`** — clears stale display state before retry
- **`return True` path in `_attempt_hack()`** — cleans up on successful completion
- **All `return None` paths in `_attempt_hack()`** — cleans up on read failure

`_clear_display()` already sets `_grid_line_indices = []`, `_game_start_line_idx = None`, `_target_pos = None`. So `_reset_solver_state()` can just delegate to `_clear_display()`.

### Change 2: Add retry for `None` results in `run()`

Currently `run()` retries only on `"reset"`. Change to also retry on `None`, with a limit of `MAX_ATTEMPTS` (already defined as 5):

```
run():
  attempts = 0
  while True:
    attempts += 1
    result = _attempt_hack(...)
    if result == "reset":
      attempts = 0  # reset attempts counter on game reset
      send_key("enter")
      continue
    if result is True:
      return True
    # result is None
    if attempts >= MAX_ATTEMPTS:
      return False
    time.sleep(0.3 / self._speed_ratio)  # brief wait before re-read
    continue
```

### Change 3: Don't reset on first grid-search failure in `_attempt_hack()`

When `_find_target_in_grid()` returns None, instead of immediately returning `"reset"`, return `None` to let `run()` retry with a fresh capture. Only return `"reset"` after the internal retrack/retry path has exhausted:

- Remove the `return "reset"` at the `target_not_found` branch; replace with `return None`
- The log message "目标未在网格中找到" stays

### Summary of changes

All changes are in `tasks/hack_solver_connect_host/task.py`, `HackingSolver` class:

| Method | Change |
|--------|--------|
| `_reset_solver_state()` | **New** — resets `_target_pos`, `_grid_line_indices`, `_game_start_line_idx` |
| `run()` | Add `None` retry loop with `MAX_ATTEMPTS` limit; call `_reset_solver_state()` at start |
| `_attempt_hack()` | `target_not_found` returns `None` instead of `"reset"`; call `_reset_solver_state()` on exit paths |

### What stays the same

- `_clear_display()` method unchanged (already sets fields to empty/None)
- PID control (speed_ratio, scan_interval) unchanged
- Digit recognition, grid reading, path planning unchanged
- `run_once = True` and `_disable_and_stop_in_config()` behavior unchanged
- The `"reset"` path for actual failures (capture failed + fail detected, target read failed + fail detected) unchanged
