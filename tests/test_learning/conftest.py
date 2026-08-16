from pathlib import Path

import pytest

from src.learning.catalog import SourceCatalog
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.store import LearningGraphStore


@pytest.fixture
def graph_catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    catalog = SourceCatalog(store)
    catalog.register_source(
        SourceAssetInput(
            asset_id="human-authored-a0",
            title="Human-authored A0 pilot content",
            locator="https://example.test/a0",
            asset_version="2026-08",
            sha256="a" * 64,
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Vocab Craft editorial team",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    return catalog
