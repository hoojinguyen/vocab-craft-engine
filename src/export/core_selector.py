"""Core 3000 Frequency & List Selector."""

class CoreSelector:
    def select_top_words(self, db_mgr) -> list:
        conn = db_mgr.get_connection()
        return conn.execute("SELECT id, lemma, pos FROM words LIMIT 3000").fetchall()
