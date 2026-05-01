class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = [
        {"delay": 100, "key": "esc"},
        {"delay": 100, "key": "right"},
        {"delay": 300, "key": "enter"},
        {"delay": 100, "key": "up",   "repeat": 5},
        {"delay": 100, "key": "enter"},
        {"delay": 100, "key": "down"},
        {"delay": 100, "key": "enter", "repeat": 2},
    ]
