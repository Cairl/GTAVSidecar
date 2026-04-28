class Task(BaseTask):
    group = None
    start_trigger = {"overlay": "trigger", "lang": "auto"}
    steps = [
        {"overlay": "confirm", "lang": "auto"},
        {"overlay": "complete", "lang": "auto"},
    ]
