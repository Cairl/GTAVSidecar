class Task(BaseTask):
    group = None
    start_trigger = {}
    steps = [
        {"delay": 70, "key": "esc"},
        {"delay": 70, "key": "right"},
        {"delay": 300, "key": "enter"},
        {"delay": 70, "key": "up",   "repeat": 5},
        {"delay": 70, "key": "enter"},
        {"delay": 70, "key": "down"},
        {"delay": 70, "key": "enter", "repeat": 2},
    ]
