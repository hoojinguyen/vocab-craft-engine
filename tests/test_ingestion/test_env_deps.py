"""Verify that all required Phase 1 libraries and dependencies are importable."""

def test_required_dependencies_importable():
    import orjson
    import nltk
    import pyarrow
    import duckdb
    import polars

    assert orjson is not None
    assert nltk is not None
    assert pyarrow is not None
    assert duckdb is not None
    assert polars is not None
