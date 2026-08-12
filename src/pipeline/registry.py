"""Checkpoint read/write for stage-level resume."""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CheckpointRegistry:
    """Reads/writes stage completion checkpoints."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def is_done(self, stage_name: str) -> bool:
        cp = self._read(stage_name)
        return cp is not None and cp.get("completed", False)

    def mark_done(self, stage_name: str, metadata: Optional[Dict[str, Any]] = None):
        data = {
            "completed": True,
            "timestamp": time.time(),
            **(metadata or {}),
        }
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        logger.info("[Checkpoint] Stage '%s' marked complete.", stage_name)

    def clear(self, stage_name: str):
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        path.unlink(missing_ok=True)

    def clear_all(self):
        for path in self.checkpoint_dir.glob("checkpoint_*.json"):
            path.unlink()

    def _read(self, stage_name: str) -> Optional[Dict[str, Any]]:
        path = self.checkpoint_dir / f"checkpoint_{stage_name}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
