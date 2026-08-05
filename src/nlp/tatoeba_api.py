"""Tatoeba API sentence lookup for residual core-word coverage (spec §3.3)."""

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

API_BASE = "https://api.tatoeba.org/unstable/sentences"


class TatoebaApiClient:
    def __init__(self, opener: Optional[Callable] = None, min_delay: float = 1.0):
        self._open = opener or urllib.request.urlopen
        self.min_delay = min_delay
        self._last_call = 0.0
        self.cache: Dict[str, List[Dict[str, Any]]] = {}

    def fetch_sentences_for_word(self, word: str, limit: int = 20) -> List[Dict[str, Any]]:
        if word in self.cache:
            return self.cache[word]
        now = time.monotonic()
        wait = self.min_delay - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

        params = urllib.parse.urlencode({
            "lang": "eng", "trans_lang": "vie", "q": word, "limit": limit,
        })
        url = f"{API_BASE}?{params}"
        try:
            with self._open(urllib.request.Request(url)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("Tatoeba API call failed for '%s': %s", word, e)
            return []

        rows = []
        for item in data.get("results", []):
            text_en = (item.get("text") or "").strip()
            if not text_en:
                continue
            text_vi = ""
            for group in item.get("translations") or []:
                for t in group:
                    if t.get("text"):
                        text_vi = t["text"].strip()
                        break
                if text_vi:
                    break
            if text_en and text_vi:
                rows.append({"text_en": text_en, "text_vi": text_vi, "source": "Tatoeba"})
        self.cache[word] = rows
        return rows
