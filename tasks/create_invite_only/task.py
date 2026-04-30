class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = [
        {"delay": 1000, "key": "esc"},
        {"delay": 1000, "key": "right"},
        {"delay": 1000, "key": "enter"},
        {"delay": 1000, "key": "up",   "repeat": 5},
        {"delay": 1000, "key": "enter"},
        {"delay": 1000, "key": "down"},
        {"delay": 1000, "key": "enter", "repeat": 2},
    ]
