# -*- coding: utf-8 -*-
"""
Korean deinflector (basic suffix stripping).
Korean dictionary form = verb/adj stem + 다.
Handles regular conjugations; irregular stems (ㅂ/ㄷ/ㅅ/르 irregulars)
are partially covered by generating multiple candidates.
"""

# (suffix_to_strip, suffix_to_add)
# Longer suffixes first to avoid partial matches
RULES = [
    # ─── 하다 verbs (most common for Sino-Korean nouns) ───
    ("했습니다",    "하다"), ("했어요",    "하다"), ("했어",    "하다"),
    ("했다",        "하다"), ("합니다",    "하다"), ("해요",    "하다"),
    ("해서",        "하다"), ("하고",      "하다"), ("하면",    "하다"),
    ("하지",        "하다"), ("하는",      "하다"), ("한다",    "하다"),
    ("하여",        "하다"), ("해",        "하다"),

    # ─── copula 이다 ───
    ("입니다",  "이다"), ("입니까",  "이다"),
    ("이에요",  "이다"), ("예요",    "이다"),
    ("이야",    "이다"), ("이어",    "이다"),

    # ─── formal polite -ㅂ/습니다 ───
    ("습니다",  "다"),  ("습니까",  "다"),
    ("ㅂ니다",  "다"),  ("ㅂ니까",  "다"),

    # ─── past + polite ───
    ("았습니다", "다"), ("었습니다", "다"),
    ("았어요",   "다"), ("었어요",   "다"), ("였어요",  "다"),
    ("았어",     "다"), ("었어",     "다"),
    ("았다",     "다"), ("었다",     "다"), ("였다",    "다"),

    # ─── informal polite -아요/-어요 ───
    ("아요",    "다"),  ("어요",    "다"),  ("여요",    "다"),

    # ─── present declarative -ㄴ다/-는다 ───
    ("는다",    "다"),  ("ㄴ다",    "다"),

    # ─── connective -고/-서/-면/-지/-기/-음 ───
    ("어서",    "다"),  ("아서",    "다"),
    ("으면",    "다"),  ("면",      "다"),
    ("지만",    "다"),  ("지",      "다"),
    ("고서",    "다"),  ("고",      "다"),
    ("기",      "다"),  ("음",      "다"),
    ("려고",    "다"),  ("러",      "다"),

    # ─── adnominal (modifier) endings ───
    ("는",      "다"),  ("은",      "다"),  ("ㄴ",     "다"),
    ("을",      "다"),  ("ㄹ",      "다"),
    ("던",      "다"),

    # ─── informal -아/-어 ───
    ("아",      "다"),  ("어",      "다"),  ("여",      "다"),
]

def candidates(surface: str, cap: int = 60):
    s = (surface or "").strip()
    if not s:
        return []
    out, seen = [], set()

    def add(x):
        if x and x not in seen:
            out.append(x); seen.add(x)

    add(s)
    # bare stem: add 다 only if surface doesn't already look like a conjugated/dict form
    if not s.endswith("다") and not s.endswith("요") and not s.endswith("다"):
        add(s + "다")

    for suffix, repl in RULES:
        if s.endswith(suffix) and len(s) >= len(suffix):
            base = s[:-len(suffix)] if len(s) > len(suffix) else ""
            add(base + repl)
            # also try bare stem (some dicts index without 다)
            add(base)
            if len(out) >= cap:
                break

    return out

def keep_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0xAC00 <= cp <= 0xD7A3 or   # Hangul syllables
        0x1100 <= cp <= 0x11FF or   # Jamo
        0x3130 <= cp <= 0x318F or   # Compat Jamo
        0xA960 <= cp <= 0xA97F or   # Jamo Extended-A
        0xD7B0 <= cp <= 0xD7FF      # Jamo Extended-B
    )
