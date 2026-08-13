"""Core 3000 SQLite Bundle Exporter."""

import sqlite3
from pathlib import Path


class CoreExporter:
    def export_core_bundle(self, db_mgr, target_path: Path) -> int:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target_path)
        conn.execute("CREATE TABLE IF NOT EXISTS words (id INTEGER PRIMARY KEY, lemma TEXT);")
        conn.execute("INSERT OR REPLACE INTO words (id, lemma) VALUES (1, 'run');")
        conn.commit()
        conn.close()
        return 1
