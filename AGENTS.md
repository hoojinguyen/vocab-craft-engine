# Repository Guidelines

## Project Structure & Module Organization

`src/` contains the pipeline by responsibility: `ingestion/` reads source corpora, `db/` manages DuckDB staging, `transform/` and `enrichment/` refine lexical data, and `export/` produces SQLite and JSON artifacts. The DAG runner and CLI live in `src/pipeline/`; terminal UI code is in `src/monitoring/`. Keep configuration in `config/`, automation scripts in `scripts/`, and tests in the matching `tests/` area (for example, `src/export/` and `tests/test_export/`). Raw inputs, staging data, and generated deliverables belong under `data/`.

## Build, Test, and Development Commands

- `make setup` creates `.venv`, installs development dependencies, and downloads required spaCy and NLTK resources.
- `make test` runs the full pytest suite; run a focused area with `.venv/bin/pytest tests/test_pipeline/ -v`.
- `make run` starts the headless pipeline; `make run-tui` enables the Textual monitor.
- `make dry-run` shows the resolved DAG without changing data, while `make status` reports checkpoint state.

Use `make download-data` before an end-to-end run when source data is absent. `make clean-db` and `make clean` delete generated artifacts; inspect their targets before using them.

## Coding Style & Naming Conventions

Write Python with four-space indentation, type hints where practical, and small focused modules. Use `snake_case` for functions, variables, modules, and pytest files; use `PascalCase` for classes. Format changed Python with `black src tests` and lint with `ruff check src tests`. Keep pipeline step names lowercase and underscore-separated, such as `export_core3000`.

## Testing Guidelines

Pytest discovers `test_*.py` files under `tests/`; async tests run automatically. Add or update a focused test for behavior changes and keep tests adjacent to the responsible subsystem. Prefer deterministic fixtures over real downloads, APIs, or audio generation. Run the narrowest relevant test first, then `make test` before submitting.

## Commit & Pull Request Guidelines

Follow the existing Conventional Commit pattern: `feat(pipeline): ...`, `fix(ingestion): ...`, `docs(plan): ...`, or `chore: ...`. Keep commits single-purpose. PRs should state the pipeline impact, list verification commands, link relevant issues or design documents, and include TUI screenshots when visual behavior changes. Do not commit source datasets, generated databases, audio, credentials, or local environment files.
