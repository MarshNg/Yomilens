# -*- coding: utf-8 -*-
"""
English deinflect (lightweight lemmatizer)
- Fallback rules (built in)
- Optional JSON rules: deinflect/en_rules.json
- Exposes:
    pick_word(text) -> str
    candidates(token) -> list[str]
    reload_rules() -> None
"""

import os, json, re

# ---- token picking (giữ nguyên API cũ) ----
WORD_RE_PHRASE = re.compile(r"[A-Za-z][A-Za-z\-']*(?:\s+[A-Za-z][A-Za-z\-']*)*")

def pick_word(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    m = WORD_RE_PHRASE.search(s)
    if not m:
        return ""
    phrase = m.group(0)
    # cắt gọn dấu câu hai đầu
    phrase = phrase.strip(".,;:!?()[]{}\"“”‘’")
    return phrase

# ---- fallback irregulars & helpers ----
# Một nhóm irregular phổ biến (đủ thực dụng). Có thể mở rộng qua JSON.
IRREGULAR = {
    # be/have/do
    "am":"be","is":"be","are":"be","was":"be","were":"be","been":"be","being":"be",
    "has":"have","had":"have","having":"have","does":"do","did":"do","done":"do","doing":"do",

    # frequent verbs
    "went":"go","gone":"go","goes":"go","going":"go",
    "came":"come","comes":"come","coming":"come",
    "got":"get","gets":"get","getting":"get",
    "took":"take","taken":"take","takes":"take","taking":"take",
    "made":"make","makes":"make","making":"make",
    "said":"say","says":"say","saying":"say",
    "saw":"see","seen":"see","sees":"see","seeing":"see",
    "ran":"run","run":"run","runs":"run","running":"run",
    "won":"win","wins":"win","winning":"win",
    "wrote":"write","written":"write","writes":"write","writing":"write",
    "drove":"drive","driven":"drive","drives":"drive","driving":"drive",
    "bought":"buy","buys":"buy","buying":"buy",
    "brought":"bring","brings":"bring","bringing":"bring",
    "thought":"think","thinks":"think","thinking":"think",
    "taught":"teach","teaches":"teach","teaching":"teach",
    "told":"tell","tells":"tell","telling":"tell",
    "left":"leave","leaves":"leave","leaving":"leave",
    "kept":"keep","keeps":"keep","keeping":"keep",
    "held":"hold","holds":"hold","holding":"hold",
    "found":"find","finds":"find","finding":"find",
    "sent":"send","sends":"send","sending":"send",
    "paid":"pay","pays":"pay","paying":"pay",
    "put":"put","puts":"put","putting":"put",
    "set":"set","sets":"set","setting":"set",
    "built":"build","builds":"build","building":"build",
    "felt":"feel","feels":"feel","feeling":"feel",
    "heard":"hear","hears":"hear","hearing":"hear",
    "slept":"sleep","sleeps":"sleep","sleeping":"sleep",
    "sat":"sit","sits":"sit","sitting":"sit",
    "stood":"stand","stands":"stand","standing":"stand",

    # adjectives/adverbs common
    "better":"good","best":"good",
    "worse":"bad","worst":"bad",
}

# Nouns ending with -ves (knife->knives, leaf->leaves...)
VES_SPECIAL = {
    "knives":"knife","leaves":"leaf","wolves":"wolf","wives":"wife","shelves":"shelf",
    "calves":"calf","halves":"half","lives":"life"
}

_PATH = os.path.join(os.path.dirname(__file__), "en_rules.json")
_CACHE = {"mtime": -1, "pairs": None}

# Load irregular-verbs.json from language folder if present (1000+ mappings)
_LANG_IRREGULAR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "language", "languages", "en", "irregular-verbs.json"
)
_LANG_IRREGULAR: dict = {}

def _load_lang_irregular():
    global _LANG_IRREGULAR
    if _LANG_IRREGULAR:
        return
    try:
        with open(_LANG_IRREGULAR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # format: {infinitive: [[past, participle], ...]}
        m = {}
        for base, forms in data.items():
            for pair in forms:
                if len(pair) >= 2:
                    for form in pair:
                        if isinstance(form, str) and form != base:
                            m.setdefault(form, base)
        _LANG_IRREGULAR = m
    except Exception:
        pass

_load_lang_irregular()

def _load_pairs_from_json():
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        pairs = []
        # Hỗ trợ 2 dạng:
        # 1) {"rules":[{"from":"went","to":"go"}, ...], "map":{"children":"child",...}}
        # 2) [["went","go"], ["worse","bad"], ...]
        if isinstance(data, dict):
            if isinstance(data.get("map"), dict):
                for f,t in data["map"].items():
                    if isinstance(f,str) and isinstance(t,str):
                        pairs.append((f, t))
            if isinstance(data.get("rules"), list):
                for r in data["rules"]:
                    if isinstance(r, (list,tuple)) and len(r)>=2:
                        f,t = r[0], r[1]
                        if isinstance(f,str) and isinstance(t,str):
                            pairs.append((f,t))
                    elif isinstance(r, dict):
                        f, t = r.get("from"), r.get("to")
                        if isinstance(f,str) and isinstance(t,str):
                            pairs.append((f,t))
        elif isinstance(data, list):
            for r in data:
                if isinstance(r, (list,tuple)) and len(r)>=2 and all(isinstance(x,str) for x in r[:2]):
                    pairs.append((r[0], r[1]))
        return pairs
    except Exception:
        return None

def _get_json_pairs():
    try:
        m = os.path.getmtime(_PATH)
    except Exception:
        m = -1
    if _CACHE["pairs"] is not None and _CACHE["mtime"] == m:
        return _CACHE["pairs"]
    pairs = _load_pairs_from_json() if m != -1 else None
    _CACHE["pairs"] = pairs or []
    _CACHE["mtime"] = m
    return _CACHE["pairs"]

def reload_rules():
    _CACHE["mtime"] = -2  # ép nạp lại

# ----- core transforms -----
def _strip_possessive(s: str):
    if s.endswith("'s") and len(s) > 2: return s[:-2]
    if s.endswith("’s") and len(s) > 2: return s[:-2]
    if s.endswith("s'") and len(s) > 2: return s[:-2]
    return s

def _plural_noun_variants(s: str):
    out = set()
    if s in VES_SPECIAL:
        out.add(VES_SPECIAL[s])
    if s.endswith("ies") and len(s) > 3:
        out.add(s[:-3] + "y")
    if s.endswith("ves") and len(s) > 3:
        out.add(s[:-3] + "f")   # knife->knif(e) mơ hồ; dữ liệu JSON có thể bù thêm
        out.add(s[:-3] + "fe")
    if s.endswith("es") and len(s) > 2:
        # boxes->box, watches->watch, heroes->hero...
        out.add(s[:-2])
    if s.endswith("s") and len(s) > 3:
        out.add(s[:-1])
    return out

def _verb_3rd_variants(s: str):
    out = set()
    if s.endswith("ies") and len(s) > 3: out.add(s[:-3]+"y")   # tries->try
    if s.endswith("es") and len(s) > 2:  out.add(s[:-2])       # goes->go
    if s.endswith("s") and len(s) > 3:   out.add(s[:-1])       # runs->run
    return out

def _past_variants(s: str):
    out = set()
    if s.endswith("ied") and len(s) > 3: out.add(s[:-3]+"y")   # studied->study
    if s.endswith("ed") and len(s) > 2:
        base = s[:-2]
        out.add(base)
        # consonant-doubling: stopped->stopp->stop
        # Bug fix: was `base.endswith(base[-1]*1)` which is always True.
        # Correct check: last two chars are the same non-vowel consonant.
        if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in "aeiou":
            out.add(base[:-1])             # stopped->stop, planned->plan
        if not base.endswith("e"):
            out.add(base+"e")              # hoped->hope, liked->like
    # -t forms (kept, built, etc.) covered by IRREGULAR / en_rules.json
    return out

def _gerund_variants(s: str):
    out = set()
    if s.endswith("ing") and len(s) > 3:
        stem = s[:-3]
        out.add(stem)                      # running->runn (sẽ có rule giảm đôi phụ âm ở dưới)
        out.add(stem+"e")                  # making->make
        if len(stem)>=2 and stem[-1] == stem[-2]:  # running->run
            out.add(stem[:-1])
        if stem.endswith("y"):
            out.add(stem)                  # staying->stay (giữ nguyên)
    return out

def _adj_comp_sup_variants(s: str):
    out = set()
    if s.endswith("est") and len(s) > 4:
        out.add(s[:-3])            # biggest->big
        if s[:-3].endswith("i"):   # happiest->happy
            out.add(s[:-4]+"y")
    if s.endswith("er") and len(s) > 3:
        out.add(s[:-2])            # bigger->big
        if s[:-2].endswith("i"):
            out.add(s[:-3]+"y")
    return out

def candidates(token: str):
    t0 = (token or "").strip()
    if not t0:
        return []
    # normalize nhẹ
    t = t0.strip(".,;:!?()[]{}\"“”‘’").replace("’","'").lower()
    t = _strip_possessive(t)

    # Dùng list + set để giữ thứ tự ưu tiên (surface trước)
    seen = set()
    out_list = []
    def add(x):
        if x and x not in seen:
            out_list.append(x); seen.add(x)

    add(t)

    json_pairs = _get_json_pairs()

    # Nếu surface có trong irregular/map -> thêm lemma ngay sau surface
    if t in IRREGULAR:
        add(IRREGULAR[t])
    if t in _LANG_IRREGULAR:
        add(_LANG_IRREGULAR[t])
    for f, base in json_pairs:
        if t == f:
            add(base)

    # Sinh biến thể “có thể là lemma”
    vars_set = set()
    vars_set |= _plural_noun_variants(t)
    vars_set |= _verb_3rd_variants(t)
    vars_set |= _past_variants(t)
    vars_set |= _gerund_variants(t)
    vars_set |= _adj_comp_sup_variants(t)

    # Thêm các biến thể + map ngược nếu có
    for v in list(vars_set):
        add(v)
        if v in IRREGULAR:
            add(IRREGULAR[v])
        if v in _LANG_IRREGULAR:
            add(_LANG_IRREGULAR[v])
        for f, base in json_pairs:
            if v == f:
                add(base)

    return out_list
