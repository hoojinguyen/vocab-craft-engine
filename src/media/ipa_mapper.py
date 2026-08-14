"""
Multi-Tier Phonetic and IPA Mapper for English Dataset System Engine.

Resolution Hierarchy:
1. Tier 0: DuckDB `_ipa_cache` lookup
2. Tier 1: Existing Kaikki Wiktionary IPA
3. Tier 2: NLTK CMU Pronouncing Dictionary (ARPAbet -> IPA)
4. Tier 3: g2p-en Neural Grapheme-to-Phoneme model
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import g2p_en
import nltk

try:
    nltk.data.find("corpora/cmudict.zip")
except LookupError:
    try:
        nltk.download("cmudict", quiet=True)
    except Exception:
        pass

from nltk.corpus import cmudict
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class IPAMapper:
    """Provides multi-tier phonetic transcriptions for English vocabulary."""

    ARPABET_TO_IPA = {
        "AA": "ɑ", "AA0": "ɑ", "AA1": "ˈɑ", "AA2": "ˌɑ",
        "AE": "æ", "AE0": "æ", "AE1": "ˈæ", "AE2": "ˌæ",
        "AH": "ʌ", "AH0": "ə", "AH1": "ˈʌ", "AH2": "ˌʌ",
        "AO": "ɔ", "AO0": "ɔ", "AO1": "ˈɔ", "AO2": "ˌɔ",
        "AW": "aʊ", "AW0": "aʊ", "AW1": "ˈaʊ", "AW2": "ˌaʊ",
        "AY": "aɪ", "AY0": "aɪ", "AY1": "ˈaɪ", "AY2": "ˌaɪ",
        "B": "b", "CH": "tʃ", "D": "d", "DH": "ð",
        "EH": "ɛ", "EH0": "ɛ", "EH1": "ˈɛ", "EH2": "ˌɛ",
        "ER": "ɜr", "ER0": "ər", "ER1": "ˈɜr", "ER2": "ˌər",
        "EY": "eɪ", "EY0": "eɪ", "EY1": "ˈeɪ", "EY2": "ˌeɪ",
        "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IH0": "ɪ", "IH1": "ˈɪ", "IH2": "ˌɪ",
        "IY": "i", "IY0": "i", "IY1": "ˈi", "IY2": "ˌi",
        "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
        "OW": "oʊ", "OW0": "oʊ", "OW1": "ˈoʊ", "OW2": "ˌoʊ",
        "OY": "ɔɪ", "OY0": "ɔɪ", "OY1": "ˈɔɪ", "OY2": "ˌɔɪ",
        "P": "p", "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ",
        "UH": "ʊ", "UH0": "ʊ", "UH1": "ˈʊ", "UH2": "ˌʊ",
        "UW": "u", "UW0": "u", "UW1": "ˈu", "UW2": "ˌu",
        "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
    }

    def __init__(self, db_mgr: Optional[DuckDBManager] = None):
        self.db_mgr = db_mgr
        self._cmudict = None
        self._g2p = None

    def _get_cmudict(self):
        if self._cmudict is None:
            try:
                self._cmudict = cmudict.dict()
            except Exception as e:
                logger.warning("Could not load NLTK cmudict: %s", e)
                self._cmudict = {}
        return self._cmudict

    def _get_g2p(self):
        if self._g2p is None:
            self._g2p = g2p_en.G2p()
        return self._g2p

    def _arpabet_to_ipa(self, phonemes: List[str]) -> str:
        ipa_parts = []
        for p in phonemes:
            p_clean = p.strip().upper()
            if p_clean in self.ARPABET_TO_IPA:
                ipa_parts.append(self.ARPABET_TO_IPA[p_clean])
            elif p.strip():
                ipa_parts.append(p.strip())
        return "/" + "".join(ipa_parts) + "/"

    def get_ipa(
        self,
        word: str,
        existing_ipa_uk: Optional[str] = None,
        existing_ipa_us: Optional[str] = None,
        existing_ipa: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Multi-tier phonetic resolution returning (ipa_uk, ipa_us).

        Tier 0: DuckDB `_ipa_cache` lookup
        Tier 1: Existing Kaikki IPA
        Tier 2: NLTK CMU Pronouncing Dictionary
        Tier 3: g2p-en Neural G2P Model
        """
        word_clean = (word or "").strip().lower()
        if not word_clean:
            return None, None

        # Handle backward-compatible existing_ipa parameter
        if existing_ipa and not existing_ipa_us:
            existing_ipa_us = existing_ipa

        # Tier 0: Cache lookup in DuckDB
        if self.db_mgr:
            cached = self.db_mgr.lookup_ipa(word_clean)
            if cached and (cached.get("ipa_uk") or cached.get("ipa_us")):
                return cached.get("ipa_uk"), cached.get("ipa_us")

        # Tier 1: Existing Kaikki IPA
        uk = existing_ipa_uk.strip() if existing_ipa_uk and existing_ipa_uk.strip() else None
        us = existing_ipa_us.strip() if existing_ipa_us and existing_ipa_us.strip() else None

        if uk or us:
            resolved_uk = uk or us
            resolved_us = us or uk
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=resolved_uk, ipa_us=resolved_us, source="kaikki")
            return resolved_uk, resolved_us

        # Tier 2: CMU Pronouncing Dict lookup
        cmu = self._get_cmudict()
        if word_clean in cmu:
            phonemes = cmu[word_clean][0]
            ipa_val = self._arpabet_to_ipa(phonemes)
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=ipa_val, ipa_us=ipa_val, source="cmudict")
            return ipa_val, ipa_val

        # Tier 3: g2p-en Neural Model fallback
        try:
            g2p = self._get_g2p()
            phonemes = g2p(word_clean)
            ipa_val = self._arpabet_to_ipa(phonemes)
            if self.db_mgr:
                self.db_mgr.save_ipa(word_clean, ipa_uk=ipa_val, ipa_us=ipa_val, source="g2p-en")
            return ipa_val, ipa_val
        except Exception as e:
            logger.warning("G2P conversion failed for '%s': %s", word_clean, e)
            fallback = f"/{word_clean}/"
            return fallback, fallback

    def get_ipa_string(self, word: str, existing_ipa: Optional[str] = None) -> str:
        """Backward-compatible helper returning a single IPA string."""
        if existing_ipa and existing_ipa.strip():
            return existing_ipa.strip()
        uk, us = self.get_ipa(word, existing_ipa_us=existing_ipa)
        return us or uk or f"/{word}/"
