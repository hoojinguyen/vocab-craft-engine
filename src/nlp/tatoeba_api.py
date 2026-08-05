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
            "lang": "eng", "trans:lang": "vie", "q": word, "limit": limit, "sort": "relevance",
        })
        url = f"{API_BASE}?{params}"
        try:
            with self._open(urllib.request.Request(url)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("Tatoeba API call failed for '%s': %s", word, e)
            return []

        rows = []
        for item in data.get("data", []):
            text_en = (item.get("text") or "").strip()
            if not text_en:
                continue
            translations = item.get("translations") or []
            text_vi = ""
            preferred = next((t for t in translations if t.get("lang") == "vie" and t.get("text")), None)
            fallback = next((t for t in translations if t.get("text")), None)
            if preferred is not None:
                text_vi = preferred["text"].strip()
            elif fallback is not None:
                text_vi = fallback["text"].strip()
            if text_en and text_vi:
                rows.append({"text_en": text_en, "text_vi": text_vi, "source": "Tatoeba"})
        self.cache[word] = rows
        return rows
