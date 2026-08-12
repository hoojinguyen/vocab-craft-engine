"""
Phonetic and IPA Mapper for English Dataset System Engine.
Maps IPA transcriptions from dictionary lookups and uses G2P (Grapheme-to-Phoneme) as fallback.
"""

import logging
from typing import Optional, List, Dict
import g2p_en

logger = logging.getLogger(__name__)


class IPAMapper:
    """Provides IPA phonetic transcriptions for English words."""

    # Simple ARPAbet to approximate IPA symbol mapping for G2P fallback
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
        "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ"
    }

    def __init__(self):
        self._g2p = None

    def _get_g2p(self):
        if self._g2p is None:
            self._g2p = g2p_en.G2p()
        return self._g2p

    def get_ipa(self, word: str, existing_ipa: Optional[str] = None, fast_only: bool = False) -> Optional[str]:
        """
        Returns existing IPA if valid.
        If missing, uses G2P conversion unless fast_only is True.
        """
        if existing_ipa and existing_ipa.strip():
            return existing_ipa.strip()

        if fast_only:
            return None

        word_clean = word.strip().lower()
        try:
            g2p = self._get_g2p()
            phonemes = g2p(word_clean)
            ipa_symbols = []
            for p in phonemes:
                if p.strip():
                    symbol = self.ARPABET_TO_IPA.get(p.upper(), p)
                    ipa_symbols.append(symbol)
            return "".join(ipa_symbols)
        except Exception as e:
            logger.warning("G2P conversion failed for word '%s': %s", word, e)
            return f"/{word_clean}/"
