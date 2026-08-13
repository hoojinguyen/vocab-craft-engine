import json
import logging
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from src.pipeline.core.result import PipelineSummary

logger = logging.getLogger(__name__)


class RunLogger:
    def __init__(self, log_dir: Path = Path("logs"), run_id: Optional[str] = None):
        self.log_dir = Path(log_dir)
        self.runs_dir = self.log_dir / "runs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        self.now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id or f"run_{self.now_str}"
        self.log_file_path = self.log_dir / f"pipeline_{self.now_str}.log"
        self._setup_file_logging()

    def _setup_file_logging(self) -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(self.log_file_path.resolve()):
                return

        file_handler = logging.FileHandler(self.log_file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    def save_run_summary(self, summary: PipelineSummary, is_resumed: bool = False) -> Path:
        json_file_path = self.runs_dir / f"{self.run_id}.json"

        total_items = sum(r.items_processed for r in summary.results)
        throughput = round(total_items / summary.total_time_seconds, 2) if summary.total_time_seconds > 0 else 0.0

        run_data = {
            "run_id": self.run_id,
            "started_at": self.now_str,
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_runtime_seconds": summary.total_time_seconds,
            "status": "FAILED" if summary.has_failures else "SUCCESS",
            "is_resumed_run": is_resumed,
            "system_info": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform()
            },
            "summary_metrics": {
                "total_steps": len(summary.results),
                "successful_steps": sum(1 for r in summary.results if r.status.value == "SUCCESS"),
                "failed_steps": sum(1 for r in summary.results if r.status.value == "FAILED"),
                "skipped_steps": sum(1 for r in summary.results if r.status.value == "SKIPPED"),
                "total_items_processed": total_items,
                "overall_throughput_items_per_sec": throughput
            },
            "steps": [
                {
                    "step_name": r.step_name,
                    "status": r.status.value,
                    "execution_time_seconds": r.execution_time_seconds,
                    "items_processed": r.items_processed,
                    "retry_count": r.retry_count,
                    "message": r.message,
                    "data_metrics": r.data_metrics,
                    "error_details": {
                        "error_message": str(r.error) if r.error else None,
                        "stacktrace": r.error_traceback
                    } if r.error_traceback or r.error else None
                }
                for r in summary.results
            ]
        }

        json_file_path.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")

        latest_path = self.log_dir / "latest_run.json"
        latest_path.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("Saved structured run report to %s", json_file_path)
        return json_file_path
