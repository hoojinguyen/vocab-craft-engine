"""Hybrid Vietnamese translator — Argos Translate (local) primary, Google Translate fallback."""

import logging
import threading
from typing import Optional

from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)


class HybridTranslator:
    """Translates English to Vietnamese using Argos (offline) primary, Google fallback."""

    def __init__(self, source: str = "en", target: str = "vi"):
        self.validator = VietnameseTextValidator()
        self._local = self._init_argos(source, target)
        self._fallback = self._init_google(source, target)
        self._lock = threading.Lock()

    def _init_argos(self, source: str, target: str):
        try:
            import argostranslate.package
            import argostranslate.translate

            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            pkg = next(
                (p for p in available if p.from_code == source and p.to_code == target),
                None,
            )
            if pkg and not pkg.is_installed:
                logger.info("Installing Argos Translate %s-%s...", source, target)
                argostranslate.package.install_from_path(pkg.download())

            logger.info("Argos Translate ready (offline).")
            return argostranslate.translate

        except ImportError:
            logger.info("Argos Translate not installed — using Google Translate only.")
            return None
        except Exception as e:
            logger.warning("Argos Translate init failed: %s", e)
            return None

    def _init_google(self, source: str, target: str):
        try:
            from deep_translator import GoogleTranslator
            return GoogleTranslator(source=source, target=target)
        except Exception as e:
            logger.warning("Google Translate init failed: %s", e)
            return None

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""

        clean = text.strip()

        if self._local:
            try:
                result = self._local.translate(clean, "en", "vi")
                if result and self.validator.is_vietnamese(result):
                    return result
            except Exception:
                pass

        if self._fallback:
            try:
                result = self._fallback.translate(clean)
                if result and self.validator.is_vietnamese(result):
                    return result
            except Exception:
                pass

        return ""
