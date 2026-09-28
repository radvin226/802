# -*- coding: utf-8 -*-
"""Multilingual profanity moderation helper.

Uses SafeText's bundled multilingual moderation dictionaries instead of
embedding explicit terms directly in the bot source.
"""
from functools import lru_cache

from safetext import SafeText

SUPPORTED_LANGUAGES = (
    "fa", "en", "ar", "az", "de", "es", "fr", "hi",
    "ja", "pt", "ru", "tr", "zh",
)

@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _guard(language: str) -> SafeText:
    return SafeText(language=language)


def contains_profanity(text: str) -> bool:
    if not text or not text.strip():
        return False

    # Auto-detect first; if it detects one of the supported languages,
    # use that dictionary. Then check Persian/English as common fallbacks.
    try:
        auto = SafeText(language=None)
        auto.set_language_from_text(text)
        detected = getattr(auto, "language", None)
        if detected in SUPPORTED_LANGUAGES:
            if _guard(detected).check_profanity(text=text):
                return True
    except Exception:
        pass

    for language in ("fa", "en", "ar"):
        try:
            if _guard(language).check_profanity(text=text):
                return True
        except Exception:
            continue

    return False
