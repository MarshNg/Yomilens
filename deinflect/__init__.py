# -*- coding: utf-8 -*-
import re

from . import ja, en, ko, fr, de, es, ru, yomitan_js

# ── All supported languages ────────────────────────────────────────────────
# fmt: (code, display_label, script_family)
ALL_LANGS = [
    ("zh", "Chinese (中文)",              "cjk"),
    ("ja", "Japanese (日本語)",            "cjk"),
    ("ko", "Korean (한국어)",              "hangul"),
    ("en", "English",                     "latin"),
    ("eo", "Esperanto",                   "latin"),
    ("fr", "French (Français)",           "latin"),
    ("de", "German (Deutsch)",            "latin"),
    ("es", "Spanish (Español)",           "latin"),
    ("eu", "Basque (Euskara)",            "latin"),
    ("ga", "Irish (Gaeilge)",             "latin"),
    ("sq", "Albanian (Shqip)",            "latin"),
    ("pt", "Portuguese (Português)",      "latin"),
    ("it", "Italian (Italiano)",          "latin"),
    ("id", "Indonesian (Bahasa)",         "latin"),
    ("vi", "Vietnamese (Tiếng Việt)",     "latin"),
    ("ar", "Arabic (العربية)",            "arabic"),
    ("la", "Latin",                       "latin"),
    ("pl", "Polish (Polski)",             "latin"),
    ("sga", "Old Irish",                  "latin"),
    ("sh", "Serbo-Croatian",              "latin"),
    ("tl", "Tagalog",                     "latin"),
    ("ru", "Russian (Русский)",           "cyrillic"),
    ("el", "Greek (Ελληνικά)",            "greek"),
    ("grc", "Ancient Greek",              "greek"),
    ("ka", "Georgian (ქართული)",          "georgian"),
    ("aii", "Assyrian Neo-Aramaic",        "syriac"),
    ("yi", "Yiddish (יידיש)",             "hebrew"),
    ("th", "Thai (ภาษาไทย)",             "thai"),
]
ALL_LANG_CODES = {c for c, *_ in ALL_LANGS}
INFLECTED_LANGS = {
    "ja", "en", "ko", "fr", "de", "es", "ru", "sq",
    "ar", "eo", "eu", "ga", "grc", "ka", "la", "sga", "tl", "yi",
}

# Latin-script langs (share same character set, auto-detect can't distinguish)
LATIN_LANGS = {
    "en", "eo", "fr", "de", "es", "eu", "ga", "sq", "pt", "it", "id",
    "vi", "la", "pl", "sga", "sh", "tl",
}
SPACE_WORD_LANGS = set(LATIN_LANGS) | {"en", "ru", "ar", "aii", "yi"}

_WORD_RE = {
    "ar": re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]+"),
    "aii": re.compile(r"[\u0700-\u074F]+"),
    "yi": re.compile(r"[\u0590-\u05FF]+"),
    "ru": re.compile(r"[\u0400-\u04FF]+"),
}


def _pick_script_word(lang: str, text: str) -> str:
    rx = _WORD_RE.get(lang)
    if not rx:
        return ""
    words = [m.group(0) for m in rx.finditer(text or "")]
    if not words:
        return ""
    # If a user accidentally selects a phrase, prefer the longest real token.
    return max(words, key=len)

# candidates(lang, surface) -> list[str]
def candidates(lang: str, surface: str):
    if not surface:
        return []
    base = None
    if lang == "ja":
        base = ja.candidates(surface)
    elif lang == "en":
        base = en.candidates(surface)
    elif lang == "ko":
        base = ko.candidates(surface)
    elif lang == "fr":
        base = fr.candidates(surface)
    elif lang == "de":
        base = de.candidates(surface)
    elif lang == "es":
        base = es.candidates(surface)
    elif lang == "ru":
        base = ru.candidates(surface)
    else:
        base = [surface]
    if lang == "en":
        return base
    return yomitan_js.enrich(lang, surface, base)

# keep_char(lang, ch) -> bool
def keep_char(lang: str, ch: str) -> bool:
    if lang == "ja":
        return ja.keep_char(ch)
    if lang == "ko":
        return ko.keep_char(ch)
    if lang == "ru":
        return ru.keep_char(ch)
    if lang == "ar":
        cp = ord(ch)
        return (0x0600 <= cp <= 0x06FF or
                0xFB50 <= cp <= 0xFDFF or
                0xFE70 <= cp <= 0xFEFF)
    if lang == "th":
        return 0x0E00 <= ord(ch) <= 0x0E7F
    if lang == "el":
        cp = ord(ch)
        return 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF
    if lang == "grc":
        cp = ord(ch)
        return 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF
    if lang == "ka":
        cp = ord(ch)
        return 0x10A0 <= cp <= 0x10FF or 0x1C90 <= cp <= 0x1CBF
    if lang == "aii":
        return 0x0700 <= ord(ch) <= 0x074F
    if lang == "yi":
        return 0x0590 <= ord(ch) <= 0x05FF
    if lang in LATIN_LANGS:
        return ch.isalpha() and (ch.isascii() or ord(ch) < 0x0300)
    # zh default: CJK BMP + Extensions
    cp = ord(ch)
    return (
        (0x3400 <= cp <= 0x9FFF) or
        (0x20000 <= cp <= 0x2EBEF) or
        (0x30000 <= cp <= 0x3134F)
    )

def pick_seed(lang: str, text: str) -> str:
    text = text or ""
    if lang == "en" or lang in LATIN_LANGS:
        return en.pick_word(text)
    if lang in _WORD_RE:
        return _pick_script_word(lang, text)
    seed = "".join(c for c in text if keep_char(lang, c))
    if not seed and lang == "ja":
        seed = "".join(c for c in text if keep_char("zh", c))
    return seed
