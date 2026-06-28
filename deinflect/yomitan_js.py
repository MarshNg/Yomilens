# -*- coding: utf-8 -*-
import os
import re
import unicodedata

_CACHE = {}

_CALL_RE = re.compile(
    r"\b(?P<kind>suffixInflection|prefixInflection|infixInflection|wholeWordInflection)\s*"
    r"\(\s*(?P<q1>['\"`])(?P<inf>(?:\\.|(?!\2).)*)(?P=q1)\s*,\s*"
    r"(?P<q2>['\"`])(?P<deinf>(?:\\.|(?!\4).)*)(?P=q2)",
    re.S,
)

_SEP_RE = re.compile(r"const\s+separablePrefixes\s*=\s*\[(.*?)\]", re.S)
_STR_RE = re.compile(r"(['\"])((?:\\.|(?!\1).)*)\1", re.S)
_CUSTOM_SUFFIX_RE = re.compile(
    r"['\"]?inflected['\"]?\s*:\s*/\.\*(?P<inf>(?:\\/|[^/])*)\$/\s*,\s*"
    r"['\"]?uninflect['\"]?\s*:\s*\(term\)\s*=>\s*term\.replace"
    r"\s*\(\s*/(?P=inf)\$/\s*,\s*(?P<q>['\"])(?P<deinf>(?:\\.|(?!(?P=q)).)*)(?P=q)",
    re.S,
)


def _unescape_js_string(s):
    return (
        s.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _language_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "language", "languages"))


def _new_language_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ext-js_language"))


def _grammar_path(lang):
    return os.path.join(_language_root(), lang, "grammar.js")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_static_rules(text):
    rules = []
    for m in _CALL_RE.finditer(text):
        kind = m.group("kind")
        inflected = _unescape_js_string(m.group("inf"))
        deinflected = _unescape_js_string(m.group("deinf"))
        if "${" in inflected or "${" in deinflected:
            continue
        rules.append((kind, inflected, deinflected))
    for m in _CUSTOM_SUFFIX_RE.finditer(text):
        inflected = _unescape_js_string(m.group("inf").replace("\\/", "/"))
        deinflected = _unescape_js_string(m.group("deinf"))
        rules.append(("suffixRegex", inflected, deinflected))
    return rules


def _extract_german_separable_rules(text):
    match = _SEP_RE.search(text)
    if not match:
        return []
    prefixes = [_unescape_js_string(m.group(2)) for m in _STR_RE.finditer(match.group(1))]
    rules = []
    for prefix in prefixes:
        rules.append(("separatedPrefix", prefix, prefix))
        rules.append(("prefixInflection", prefix + "zu", prefix))
    return rules


def grammar_rules(lang):
    if lang in _CACHE:
        return _CACHE[lang]
    rules = []
    path = _grammar_path(lang)
    try:
        rules.extend(_extract_static_rules(_read(path)))
    except Exception:
        pass
    new_dir = os.path.join(_new_language_root(), lang)
    if os.path.isdir(new_dir):
        for name in sorted(os.listdir(new_dir)):
            if not name.endswith(".js"):
                continue
            try:
                rules.extend(_extract_static_rules(_read(os.path.join(new_dir, name))))
            except Exception:
                pass
    if lang == "de":
        try:
            rules.extend(_extract_german_separable_rules(_read(path)))
        except Exception:
            pass
        new_path = os.path.join(new_dir, "german-transforms.js")
        try:
            rules.extend(_extract_german_separable_rules(_read(new_path)))
        except Exception:
            pass
    unique = []
    seen = set()
    for rule in rules:
        if rule not in seen:
            unique.append(rule)
            seen.add(rule)
    rules = unique
    _CACHE[lang] = rules
    return rules


def _strip_combining(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn").normalize("NFC")


_HIRAGANA_TO_KATAKANA = str.maketrans(
    {chr(cp): chr(cp + 0x60) for cp in range(0x3041, 0x3097)}
)
_KATAKANA_TO_HIRAGANA = str.maketrans(
    {chr(cp): chr(cp - 0x60) for cp in range(0x30A1, 0x30F7)}
)


def _collapse_emphatic_japanese(s):
    out = [s]
    collapsed = re.sub(r"([ぁ-んァ-ンー])\1+", r"\1", s)
    if collapsed != s:
        out.append(collapsed)
    unlonged = re.sub(r"ー+", "", collapsed)
    if unlonged != collapsed:
        out.append(unlonged)
    return out


_VI_TONE = "([\u0300\u0309\u0303\u0301\u0323])"
_VI_DIACRITICS = "\u0306\u0302\u031B"
_VI_RE1 = re.compile(f"{_VI_TONE}([aeiouy{_VI_DIACRITICS}]+)", re.I)
_VI_RE2 = re.compile(f"(?<=[{_VI_DIACRITICS}])(.){_VI_TONE}", re.I)
_VI_RE3 = re.compile(f"(?<=[ae])([iouy]){_VI_TONE}", re.I)
_VI_RE4 = re.compile(f"(?<=[oy])([iuy]){_VI_TONE}", re.I)
_VI_RE5 = re.compile(f"(?<!q)(u)([aeiou]){_VI_TONE}", re.I)
_VI_RE6 = re.compile(f"(?<!g)(i)([aeiouy]){_VI_TONE}", re.I)
_VI_RE7 = re.compile(f"(?<!q)([ou])([aeoy]){_VI_TONE}(?!\\w)", re.I)


def _normalize_vietnamese(s, old_style=False):
    result = unicodedata.normalize("NFD", s)
    result = _VI_RE1.sub(r"\2\1", result)
    result = _VI_RE2.sub(r"\2\1", result)
    result = _VI_RE3.sub(r"\2\1", result)
    result = _VI_RE4.sub(r"\2\1", result)
    result = _VI_RE5.sub(r"\1\3\2", result)
    result = _VI_RE6.sub(r"\1\3\2", result)
    if old_style:
        result = _VI_RE7.sub(r"\1\3\2", result)
    return unicodedata.normalize("NFC", result)


def transformation_candidates(lang, surface):
    s = surface or ""
    out = []
    if not s:
        return out
    if any("A" <= ch <= "Z" or "À" <= ch <= "Þ" for ch in s):
        out.extend([s.lower(), s.title()])
    nfkc = unicodedata.normalize("NFKC", s)
    if nfkc != s:
        out.append(nfkc)
    if lang == "ar":
        out.append(re.sub(r"[\u064b-\u065f\u0670]", "", s))
        out.append(s.replace("ـ", ""))
        out.append(s.replace("ا", "أ"))
        out.append(s.replace("ا", "إ"))
        out.append(re.sub(r"ى$", "ي", s))
        out.append(re.sub(r"ه$", "ة", s))
    elif lang == "aii":
        out.append(re.sub(r"[\u0300-\u036f\u0700-\u074f]", "", s))
    elif lang == "ru":
        out.append(s.replace("\u0301", ""))
        out.append(s.replace("ё", "е").replace("Ё", "Е"))
        out.append(s.replace("е", "ё").replace("Е", "Ё"))
    elif lang == "de":
        out.append(s.replace("ss", "ß"))
        out.append(s.replace("ß", "ss"))
    elif lang == "fr":
        out.append(s.replace("'", "\u2019"))
        out.append(s.replace("\u2019", "'"))
    elif lang in {"la", "id", "it", "tl", "sh", "grc", "sga"}:
        out.append(_strip_combining(s))
        if lang == "la":
            out.append(s.replace("æ", "ae").replace("Æ", "AE").replace("œ", "oe").replace("Œ", "OE"))
            out.append(s.replace("ae", "æ").replace("AE", "Æ").replace("oe", "œ").replace("OE", "Œ"))
        elif lang == "it":
            out.append(re.sub(r"(l|dell|all|dall|nell|sull|coll|un|quest|quell|c|n)['\u2019]", "", s))
    elif lang == "vi":
        out.extend([_normalize_vietnamese(s, False), _normalize_vietnamese(s, True)])
    elif lang == "ja":
        out.append(s.translate(_HIRAGANA_TO_KATAKANA))
        out.append(s.translate(_KATAKANA_TO_HIRAGANA))
        out.extend(_collapse_emphatic_japanese(s))
    elif lang == "el":
        out.append(_strip_combining(s))
    elif lang == "yi":
        out.append(re.sub(r"[\u05B0-\u05C7]", "", s))
    return [x for x in out if x and x != s]


def apply_grammar_rules(lang, surface, max_depth=3, cap=160):
    s0 = (surface or "").strip()
    if not s0:
        return []
    rules = grammar_rules(lang)
    if not rules:
        return []

    out = []
    seen = set()

    def add(x):
        if x and x not in seen:
            out.append(x)
            seen.add(x)
            return True
        return False

    frontier = [(s0, 0)]
    while frontier and len(out) < cap:
        s, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for kind, inflected, deinflected in rules:
            cand = None
            if kind == "suffixInflection":
                if s.endswith(inflected) and len(s) > len(inflected):
                    cand = s[:-len(inflected)] + deinflected
            elif kind == "suffixRegex":
                if s.endswith(inflected) and len(s) > len(inflected):
                    cand = s[:-len(inflected)] + deinflected
            elif kind == "prefixInflection":
                if s.startswith(inflected):
                    cand = deinflected + s[len(inflected):]
            elif kind == "infixInflection":
                if inflected in s:
                    cand = s.replace(inflected, deinflected, 1)
            elif kind == "wholeWordInflection":
                if s == inflected:
                    cand = deinflected
            elif kind == "separatedPrefix":
                parts = s.split()
                if len(parts) >= 3 and parts[-1] == inflected:
                    cand = parts[0] + " " + inflected
            if cand and add(cand):
                frontier.append((cand, depth + 1))

    return out[:cap]


def enrich(lang, surface, existing=(), cap=180):
    out = []
    seen = set()
    min_len = 2 if lang in {"ja", "ko", "zh"} and len(surface or "") > 1 else 1

    def add(x):
        if len(x) < min_len and x != surface:
            return
        if x and x not in seen:
            out.append(x)
            seen.add(x)

    for x in existing:
        add(x)
    for x in transformation_candidates(lang, surface):
        add(x)
    for x in apply_grammar_rules(lang, surface, cap=cap):
        add(x)
    return out[:cap]
