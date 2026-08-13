import subprocess
import sys
import pytest

def test_pipeline_dry_run_cli():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.argv=['main.py', '--dry-run']; from unittest.mock import patch; patch('main.download_all_raw_data').start(); import main; main.main()"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "[DRY-RUN] Would run 'schema_init'" in result.stdout or "[DRY-RUN] Would run 'schema_init'" in result.stderr

