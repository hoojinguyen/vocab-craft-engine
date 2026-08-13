import subprocess
import sys
import pytest

def test_pipeline_dry_run_cli(tmp_path):
    db_path = tmp_path / "sqlite_export.db"
    state_path = tmp_path / ".pipeline_state.json"
    script = (
        "import sys, pathlib; sys.argv=['main.py', '--dry-run']; "
        "from unittest.mock import patch; "
        "patch('main.download_all_raw_data').start(); "
        "import config.settings; "
        f"config.settings.EXPORT_SQLITE_PATH = pathlib.Path({repr(str(db_path))}); "
        "import main; "
        f"main.EXPORT_SQLITE_PATH = pathlib.Path({repr(str(db_path))}); "
        "main.main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "[DRY-RUN] Would run 'schema_init'" in result.stdout or "[DRY-RUN] Would run 'schema_init'" in result.stderr
    assert not db_path.exists() or db_path.stat().st_size == 0
    assert not state_path.exists()



