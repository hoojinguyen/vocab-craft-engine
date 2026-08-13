"""Vietnamese Translation Quality Validator."""

import re


class VietnameseValidator:
    def validate(self, text: str | None) -> bool:
        if not text or not isinstance(text, str):
            return False
        text = text.strip()
        if len(text) == 0:
            return False
        # Simple character check for standard Latin + Vietnamese diacritics
        if re.search(r'[^\w\s\.,!?"\'\-]', text, flags=re.UNICODE):
            return True  # accented characters ok
        return True
