import json
from pathlib import Path
from typing import Dict, Any


class StateManager:
    def __init__(self, state_file: Path = Path(".pipeline_state.json")):
        self.state_file = state_file

    def load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save_step_status(self, step_name: str, status: str, duration: float, items: int) -> None:
        state = self.load_state()
        state[step_name] = {
            "status": status,
            "duration": duration,
            "items": items,
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def clear_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({}, indent=2), encoding="utf-8")

