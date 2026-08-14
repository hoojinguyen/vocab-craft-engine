from pathlib import Path
from config.settings import load_pipeline_config, PIPELINE_CONFIG_PATH


def test_pipeline_config_loads_defaults():
    config = load_pipeline_config()
    assert "concurrency" in config
    assert config["concurrency"]["max_workers"] >= 1
    assert "staging" in config
    assert "export" in config
    assert config["export"]["journal_mode"] == "WAL"
    assert "steps" in config


def test_pipeline_config_loads_custom_path(tmp_path: Path):
    custom_yaml = tmp_path / "custom.yaml"
    custom_yaml.write_text("concurrency:\n  max_workers: 8\n", encoding="utf-8")

    config = load_pipeline_config(custom_yaml)
    assert config["concurrency"]["max_workers"] == 8
