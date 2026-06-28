# -*- coding: utf-8 -*-
import os, json

# --- Fallback rules (comprehensive) nếu không có deinflect.json ---
# Longer suffixes listed first within each group to prevent partial over-stripping.
FALLBACK_RULES = [
    # ── Polite masu-form ──────────────────────────────────────────────────
    ("ませんでした","る"), ("ませんでしょう","る"),
    ("ましょう","る"), ("ました","る"), ("ません","る"), ("ます","る"),

    # ── i-adjective (形容詞) ──────────────────────────────────────────────
    ("くなかったです","い"), ("くないです","い"), ("かったです","い"),
    ("くなかった","い"), ("くなった","い"), ("くなる","い"),
    ("くない","い"), ("かった","い"),
    ("くて","い"), ("く","い"),      # adverb / te-form

    # ── na-adjective / copula (だ/です stripped) ──────────────────────────
    ("ではなかった",""),  ("じゃなかった",""),
    ("ではない",""),     ("じゃない",""),
    ("でした",""),       ("でしょう",""),
    ("だった",""),       ("だろう",""),

    # ── する (suru) verbs — full paradigm ────────────────────────────────
    ("されませんでした","する"), ("させられました","する"), ("させられる","する"),
    ("されました","する"), ("されます","する"), ("されていた","する"),
    ("させました","する"), ("させます","する"),
    ("させられた","する"), ("させられて","する"),
    ("されている","する"), ("させている","する"),
    ("された","する"),   ("される","する"),
    ("させた","する"),   ("させる","する"),
    ("しました","する"), ("しません","する"), ("しています","する"),
    ("している","する"), ("していた","する"),
    ("してみた","する"), ("してみる","する"),
    ("してしまった","する"), ("してしまう","する"),
    ("して","する"),     ("した","する"),
    ("しない","する"),   ("しなかった","する"),
    ("しよう","する"),   ("できる","する"),   ("できた","する"),

    # ── Passive / potential / causative (ichidan & godan common) ─────────
    ("られませんでした","る"), ("られました","る"), ("られます","る"),
    ("られている","る"), ("られていた","る"),
    ("られなかった","る"), ("られない","る"),
    ("られた","る"), ("られて","る"), ("られる","る"),

    # ── Godan -く verbs ──────────────────────────────────────────────────
    ("かなかった","く"), ("かない","く"),
    ("かせる","く"), ("かせた","く"),
    ("ける","く"),   # potential: 書ける → 書く
    ("けば","く"),   # conditional
    ("こう","く"),   # volitional
    ("いた","く"), ("いて","く"),

    # ── Godan -ぐ verbs ──────────────────────────────────────────────────
    ("がなかった","ぐ"), ("がない","ぐ"),
    ("げる","ぐ"),   # potential
    ("げば","ぐ"),   # conditional
    ("ごう","ぐ"),   # volitional
    ("いだ","ぐ"), ("いで","ぐ"),

    # ── Godan -す verbs ──────────────────────────────────────────────────
    ("さなかった","す"), ("さない","す"),
    ("せる","す"),   # potential
    ("せば","す"),   # conditional
    ("そう","す"),   # volitional
    ("します","す"), ("しません","す"),
    ("して","す"), ("した","す"),

    # ── Godan -つ verbs ──────────────────────────────────────────────────
    ("たなかった","つ"), ("たない","つ"),
    ("てる","つ"),   # potential
    ("てば","つ"),   # conditional
    ("とう","つ"),   # volitional
    ("った","つ"), ("って","つ"),    # note: also covers -う godan below

    # ── Godan -ぬ verbs (rare) ───────────────────────────────────────────
    ("なない","ぬ"), ("ねる","ぬ"), ("ねば","ぬ"), ("のう","ぬ"),
    ("んだ","ぬ"), ("んで","ぬ"),

    # ── Godan -ぶ verbs ──────────────────────────────────────────────────
    ("ばなかった","ぶ"), ("ばない","ぶ"),
    ("べる","ぶ"), ("べば","ぶ"), ("ぼう","ぶ"),
    ("んだ","ぶ"), ("んで","ぶ"),

    # ── Godan -む verbs ──────────────────────────────────────────────────
    ("まなかった","む"), ("まない","む"),
    ("める","む"), ("めば","む"), ("もう","む"),
    ("んだ","む"), ("んで","む"),

    # ── Godan -る (godan) verbs ──────────────────────────────────────────
    ("らなかった","る"), ("らない","る"),
    ("れる","る"),   # potential (godan): 走れる → 走る
    ("れば","る"),   # conditional
    ("ろう","る"),   # volitional
    ("った","う"),   # -う godan past (重複 with -つ; BFS handles ambiguity)

    # ── Godan -う verbs ──────────────────────────────────────────────────
    ("わなかった","う"), ("わない","う"),
    ("える","う"),   # potential: 言える → 言う
    ("えば","う"),   # conditional: 言えば → 言う
    ("おう","う"),   # volitional: 言おう → 言う
    ("って","う"),

    # ── Ichidan (ru-verbs) — generic forms ───────────────────────────────
    ("させられなかった","る"), ("させられなかった","る"),
    ("ていなかった","る"), ("ていない","る"),
    ("てほしい","る"), ("てください","る"),
    ("てしまった","て"), ("てしまう","て"),  # chain: て → る (depth 2)
    ("でしまった","で"), ("でしまう","で"),
    ("てみなかった","て"), ("てみた","て"), ("てみる","て"),
    ("ておいた","て"), ("ておく","て"),
    ("てから","て"),
    ("ながら","る"),
    ("ている","る"), ("ていた","る"), ("ています","る"),
    ("なかった","る"), ("ない","る"),   # ichidan negative
    ("よう","る"),   # volitional: 食べよう → 食べる
    ("たい","る"), ("たくない","る"), ("たかった","る"),
    ("た","る"), ("て","る"),          # past / te-form (ichidan)
    ("ば","る"),     # conditional: 食べれば strip → but handled above per-class

    # ── -chau / -chimau (colloquial ~てしまう) ────────────────────────────
    # Past/te forms → direct base (longer first)
    ("ちゃった","る"),  # 食べちゃった → 食べる
    ("ちまった","る"),  # 食べちまった → 食べる
    ("いちゃった","く"), ("しちゃった","す"), ("っちゃった","う"), ("っちゃった","つ"),
    ("っちゃった","る"), ("んじゃった","ぶ"), ("んじゃった","む"),
    ("ちゃう","る"),
    ("いじゃう","ぐ"), ("いちゃう","く"), ("しちゃう","す"),
    ("っちゃう","う"), ("っちゃう","く"), ("っちゃう","つ"), ("っちゃう","る"),
    ("んじゃう","ぬ"), ("んじゃう","ぶ"), ("んじゃう","む"),
    ("ちまう","る"),
    ("いじまう","ぐ"), ("いちまう","く"), ("しちまう","す"),
    ("っちまう","う"), ("っちまう","く"), ("っちまう","つ"), ("っちまう","る"),
    ("んじまう","ぬ"), ("んじまう","ぶ"), ("んじまう","む"),

    # ── -nasai (polite imperative) ────────────────────────────────────────
    ("なさい","る"),
    ("いなさい","う"), ("きなさい","く"), ("ぎなさい","ぐ"), ("しなさい","す"),
    ("ちなさい","つ"), ("になさい","ぬ"), ("びなさい","ぶ"), ("みなさい","む"),
    ("りなさい","る"),

    # ── -sou (looks like / seems) ─────────────────────────────────────────
    ("そう","い"),   # adj: 嬉しそう → 嬉しい
    ("いそう","う"), ("きそう","く"), ("ぎそう","ぐ"), ("しそう","す"),
    ("ちそう","つ"), ("にそう","ぬ"), ("びそう","ぶ"), ("みそう","む"),
    ("りそう","る"),

    # ── -sugiru (too much) ────────────────────────────────────────────────
    ("すぎる","い"),   # adj: 大きすぎる → 大きい
    ("すぎる","る"),   # ichidan
    ("いすぎる","う"), ("きすぎる","く"), ("ぎすぎる","ぐ"), ("しすぎる","す"),
    ("ちすぎる","つ"), ("にすぎる","ぬ"), ("びすぎる","ぶ"), ("みすぎる","む"),
    ("りすぎる","る"),

    # ── -tara / -tari (conditional / concurrent) ─────────────────────────
    ("かったら","い"),
    ("たら","る"),
    ("いたら","く"), ("いだら","ぐ"), ("したら","す"),
    ("ったら","う"), ("ったら","つ"), ("ったら","る"),
    ("んだら","ぬ"), ("んだら","ぶ"), ("んだら","む"),
    ("かったり","い"),
    ("たり","る"),
    ("いたり","く"), ("いだり","ぐ"), ("したり","す"),
    ("ったり","う"), ("ったり","つ"), ("ったり","る"),
    ("んだり","ぬ"), ("んだり","ぶ"), ("んだり","む"),

    # ── -zu / -nu (archaic / classical negative) ──────────────────────────
    ("かず","く"), ("がず","ぐ"), ("さず","す"), ("たず","つ"),
    ("ばず","ぶ"), ("まず","む"), ("らず","る"), ("わず","う"),
    ("かぬ","く"), ("がぬ","ぐ"), ("さぬ","す"), ("たぬ","つ"),
    ("ばぬ","ぶ"), ("まぬ","む"), ("らぬ","る"), ("わぬ","う"),

    # ── Causative godan (specific per row) ───────────────────────────────
    ("かせる","く"), ("がせる","ぐ"), ("たせる","つ"),
    ("なせる","ぬ"), ("ばせる","ぶ"), ("ませる","む"), ("らせる","る"),
    ("わせる","う"),

    # ── Imperative ────────────────────────────────────────────────────────
    ("ろ","る"), ("よ","る"),   # ichidan imperative
    ("え","う"), ("け","く"), ("げ","ぐ"), ("せ","す"),
    ("て","つ"), ("ね","ぬ"), ("べ","ぶ"), ("め","む"), ("れ","る"),

    # ── Continuative / potential stems (Yomitan custom regex rules) ──────
    ("け","ける"), ("げ","げる"), ("じ","じる"), ("せ","せる"),
    ("ぜ","ぜる"), ("ち","ちる"), ("て","てる"), ("で","でる"),
    ("に","にる"), ("ね","ねる"), ("ひ","ひる"), ("び","びる"),
    ("へ","へる"), ("べ","べる"), ("み","みる"), ("め","める"),
    ("り","りる"), ("れ","れる"),

    # ── -ki / noun form ───────────────────────────────────────────────────
    ("さ","い"),     # 大きさ → 大きい (noun from adj)
]

_RULES_PATH = os.path.join(os.path.dirname(__file__), "deinflect.json")
_CACHE = {"mtime": -1, "pairs": None}

def _parse_pairs(obj):
    """
    Hỗ trợ vài dạng phổ biến:
    - Dạng Yomichan giản lược: {"rules":[{"from":"った","to":"う"}, ...]}
    - Dạng list đôi: [["った","う"], ["して","する"], ...]
    - Dạng list object: [{"from":"った","to":"う"}, ...]
    Bỏ qua mọi metadata khác.
    """
    pairs = []
    try:
        if isinstance(obj, dict) and "rules" in obj and isinstance(obj["rules"], list):
            it = obj["rules"]
        elif isinstance(obj, list):
            it = obj
        else:
            return []

        for r in it:
            if isinstance(r, (list, tuple)) and len(r) >= 2 and all(isinstance(x, str) for x in r[:2]):
                pairs.append((r[0], r[1]))
            elif isinstance(r, dict):
                f = r.get("from"); t = r.get("to")
                if isinstance(f, str) and isinstance(t, str):
                    pairs.append((f, t))
    except Exception:
        return []
    return pairs

def _load_rules_from_file():
    try:
        with open(_RULES_PATH, "r", encoding="utf-8") as f:
            obj = json.loads(f.read())
        pairs = _parse_pairs(obj)
        return pairs if pairs else None
    except Exception:
        return None

def _get_pairs():
    """Đọc deinflect.json nếu có & đổi, cache theo mtime; fallback về FALLBACK_RULES."""
    try:
        m = os.path.getmtime(_RULES_PATH)
    except Exception:
        m = -1

    if _CACHE["pairs"] is not None and _CACHE["mtime"] == m:
        return _CACHE["pairs"]

    pairs = _load_rules_from_file() if m != -1 else None
    if not pairs:
        pairs = FALLBACK_RULES

    _CACHE["pairs"] = pairs
    _CACHE["mtime"] = m
    return pairs

def reload_rules():
    """Gọi khi bạn thay file deinflect.json để nạp lại ngay."""
    _CACHE["mtime"] = -2  # ép _get_pairs() nạp lại

def candidates(surface: str, max_depth: int = 3, cap: int = 120):
    # BFS đơn giản dựa trên cặp (suffix -> baseSuffix)
    rules = _get_pairs()
    s0 = (surface or "").strip()
    out = []
    seen = set()
    frontier = [(s0, 0)]
    def add(x):
        if x and x not in seen:
            out.append(x)
            seen.add(x)
            return True
        return False
    add(s0)
    while frontier and len(out) < cap:
        s, d = frontier.pop(0)
        if d >= max_depth:
            continue
        for suf, base in rules:
            if s.endswith(suf) and len(s) > len(suf):
                cand = s[:-len(suf)] + base
                if add(cand):
                    frontier.append((cand, d+1))
    return out

def keep_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3040 <= cp <= 0x30FF or   # hiragana + katakana
        0xFF65 <= cp <= 0xFF9F or   # half-width katakana
        0x4E00 <= cp <= 0x9FFF or   # CJK Unified (common kanji)
        0x3400 <= cp <= 0x4DBF or   # CJK Extension-A
        0x20000 <= cp <= 0x2A6DF or # CJK Extension-B
        cp == 0x30FC or             # ー (katakana prolonged)
        cp == 0x3005 or             # 々 (ideographic iteration)
        cp == 0x309E or             # ゞ (hiragana voiced iteration)
        cp == 0x30FE                # ヾ (katakana voiced iteration)
    )
