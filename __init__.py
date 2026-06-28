# -*- coding: utf-8 -*-
# Anki 2.1.49 – Hanzi Popup via localhost (deck-safe) + Native Yomichan/Yomitan dictionaries
from aqt import mw, gui_hooks
from aqt.utils import tooltip
from aqt.qt import QAction, QFileDialog, QDesktopServices, QUrl, Qt, QFrame, QWidget, QLineEdit
import sqlite3, hashlib, time
from aqt.qt import QDialog, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QVBoxLayout, QLabel, QMessageBox, QProgressDialog, QApplication

from .deinflect import candidates as df_candidates, keep_char as df_keep_char, pick_seed as df_pick_seed
from .deinflect import ALL_LANGS as DEINFLECT_ALL_LANGS, ALL_LANG_CODES as DEINFLECT_LANG_CODES, INFLECTED_LANGS as DEINFLECT_INFLECTED_LANGS, LATIN_LANGS as DEINFLECT_LATIN_LANGS
from .deinflect import SPACE_WORD_LANGS as DEINFLECT_SPACE_WORD_LANGS
import os, re, json, zipfile, threading, urllib.parse, http.server, socketserver, unicodedata, io, mimetypes

ADDON_DIR       = os.path.dirname(__file__)
INJECT_JS_PATH  = os.path.join(ADDON_DIR, "inject.js")
# đầu file (gần các hằng số khác)
POPUP_TPL_PATH = os.path.join(ADDON_DIR, "popup_iframe.html")

DB_PATH   = os.path.join(ADDON_DIR, "yomi_index.db")
DB        = None          # sqlite3.Connection hoặc None
DB_MODE   = False         # True nếu đang dùng DB để tra
DB_SIG    = None          # detects external DB/WAL changes while Anki is running

CONFIG_PATH  = os.path.join(ADDON_DIR, "yomi_config.json")
LANG_PROFILE = "auto"
HANZI_WRITER = False
POPUP_LANGS = ["zh", "ja", "en"]
POPUP_TRIGGER_MOD = "none"
POPUP_SUBLOOKUP_MODE = "reuse"
DISMISS_REBUILD_NOTICE = False

_TPL_CACHE = {"text": None, "mtime": 0}
NORM_TERM_VERSION = "3"

# === API: decomposition ===
DECOMP_PATH = os.path.join(ADDON_DIR, "decomp_cc.txt")
_DECOMP_CACHE = {'mtime': None, 'data': {}}

_ARABIC_DIACRITIC_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_CJK_KANA_HANGUL_RE = re.compile(
    r"[\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]"
)

def _lookup_norm_term(text):
    """Normalize lookup keys for scripts where dictionary headwords may contain optional marks."""
    s = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not s:
        return ""
    s = s.replace("\u0640", "")  # tatweel
    s = _ARABIC_DIACRITIC_RE.sub("", s)
    s = s.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
        "ؤ": "و", "ئ": "ي", "ى": "ي",
    }))
    s = re.sub(r"ة$", "ه", s)
    # Do not strip marks from CJK/kana/hangul terms: dakuten/kana distinctions matter.
    if _CJK_KANA_HANGUL_RE.search(s):
        return s
    return unicodedata.normalize("NFC", "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    ))

def _open_yomitan_zip(path):
    """Open a Yomitan zip, unwrapping one nested zip if the outer file is only a wrapper."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    has_yomitan_files = any(
        n.lower().endswith(".json") and (
            os.path.basename(n).lower() == "index.json" or
            "term_bank" in n.lower() or
            "kanji_bank" in n.lower()
        )
        for n in names
    )
    inner_zips = [n for n in names if n.lower().endswith(".zip")]
    if not has_yomitan_files and len(inner_zips) == 1:
        data = z.read(inner_zips[0])
        z.close()
        buf = io.BytesIO(data)
        inner = zipfile.ZipFile(buf)
        inner._yomilens_buffer = buf
        return inner
    return z

def _load_decomp_map():
    try:
        m = os.path.getmtime(DECOMP_PATH)
    except Exception:
        return {}
    global _DECOMP_CACHE
    if _DECOMP_CACHE.get('mtime') != m:
        data = {}
        try:
            with open(DECOMP_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(None, 1)  # "字  ⿰氵步"
                    if len(parts) == 2 and len(parts[0]) == 1:
                        data[parts[0]] = parts[1].strip()
        except Exception:
            data = {}
        _DECOMP_CACHE['mtime'] = m
        _DECOMP_CACHE['data'] = data
    return _DECOMP_CACHE.get('data') or {}
def _load_config():
    global LANG_PROFILE, HANZI_WRITER, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE, DISMISS_REBUILD_NOTICE
    try:
        cfg = json.loads(_read_text(CONFIG_PATH))
        LANG_PROFILE = cfg.get('lang_profile', 'auto')
        HANZI_WRITER = bool(cfg.get('hanzi_writer', False))
        POPUP_TRIGGER_MOD = cfg.get('popup_trigger_mod', 'none')
        if POPUP_TRIGGER_MOD not in ("none", "alt", "ctrl", "shift", "meta"):
            POPUP_TRIGGER_MOD = "none"
        POPUP_SUBLOOKUP_MODE = cfg.get('popup_sublookup_mode', 'reuse')
        if POPUP_SUBLOOKUP_MODE not in ("reuse", "nested"):
            POPUP_SUBLOOKUP_MODE = "reuse"
        DISMISS_REBUILD_NOTICE = bool(cfg.get('dismiss_rebuild_notice', False))
        langs = cfg.get('popup_langs')
        if isinstance(langs, list):
            POPUP_LANGS = [x for x in langs if x in DEINFLECT_LANG_CODES] or ["zh", "ja", "en"]
        else:
            POPUP_LANGS = ["zh", "ja", "en"] if LANG_PROFILE == "auto" else [LANG_PROFILE]
    except Exception:
        LANG_PROFILE = 'auto'
        POPUP_LANGS = ["zh", "ja", "en"]
        POPUP_TRIGGER_MOD = "none"
        POPUP_SUBLOOKUP_MODE = "reuse"
        DISMISS_REBUILD_NOTICE = False

def _save_config():
    try:
        data = {
            'lang_profile': LANG_PROFILE,
            'popup_langs': POPUP_LANGS,
            'popup_trigger_mod': POPUP_TRIGGER_MOD,
            'popup_sublookup_mode': POPUP_SUBLOOKUP_MODE,
            'hanzi_writer': bool(HANZI_WRITER),
            'dismiss_rebuild_notice': bool(DISMISS_REBUILD_NOTICE),
        }
        _write_text(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass

def _guess_lang_from_sources():
    titles = []
    try:
        if DB_MODE and DB:
            cur = DB.execute("SELECT title FROM source WHERE enabled=1")
            titles = [r[0] for r in cur.fetchall()]
    except Exception:
        pass
    s = " ".join(map(str, titles))
    if any(k in s for k in ("日本", "和英", "国語", "Japanese", "JMdict", "JP")):
        return "ja"
    return "zh"

def _lang_profile_from_popup_langs():
    # primary lang = first non-auto lang; "auto" if multiple or ambiguous
    langs = [x for x in POPUP_LANGS if x in DEINFLECT_LANG_CODES]
    return langs[0] if len(langs) == 1 else "auto"


def _get_popup_tpl():
    """Đọc popup_iframe.html, cache theo mtime, fallback về DEFAULT_TPL nếu thiếu."""
    try:
        m = os.path.getmtime(POPUP_TPL_PATH)
        if _TPL_CACHE["text"] is None or _TPL_CACHE["mtime"] != m:
            with open(POPUP_TPL_PATH, "r", encoding="utf-8") as f:
                _TPL_CACHE["text"] = f.read()
            _TPL_CACHE["mtime"] = m
    except Exception:
        _TPL_CACHE["text"] = DEFAULT_TPL
        _TPL_CACHE["mtime"] = 0
    return _TPL_CACHE["text"]
DEFAULT_TPL = (
    "<!doctype html><meta charset='utf-8'>"
    "<style>"
    ":root{ --term-size:26px; --text-size:16px }"
    "body{margin:0;background:#fff8ee;font:var(--text-size) system-ui,sans-serif;line-height:1.4}"
    ".wrap{padding:12px 14px;max-width:620px}"
    ".term{margin:10px 0 14px;border-left:3px solid #e0c8a7;padding-left:10px}"
    ".t{font-weight:700;font-size:var(--term-size);margin-bottom:6px}"
    ".src{font-size:12px;opacity:.8;margin:4px 0 4px}"
    ".def{margin:3px 0;display:flex;align-items:flex-start}"
    ".def .r{flex-shrink:0;min-width:9em;opacity:.9;font-size:var(--text-size);padding-top:2px}"
    ".def .g{display:block;flex:1;font-size:var(--text-size);line-height:1.6}"
    ".empty{opacity:.7}"
    "</style>"
    "<div class='wrap'>{{ROWS}}</div>"
)


# Lưu danh sách từ điển (đã thêm) để tự nạp lại khi mở Anki
SOURCES_PATH    = os.path.join(ADDON_DIR, "yomi_sources.json")

# URL manifest JSON chứa danh sách dictionary có thể download
# Trỏ đến raw.githubusercontent.com/<user>/<repo>/main/manifest.json
DICT_MANIFEST_URL = "https://raw.githubusercontent.com/MarshNg/yomilens-dictionaries/main/manifest.json"

# Server cục bộ
PORT = 8777

# ====== State cho từ điển Yomichan ======
# sources: [{"type":"zip"|"folder","path":"...","title":"..."}]
SOURCES = []

# TERM_INDEX: term -> list of entries
# entry = {"reading": str, "glosses": [str], "source": str}
TERM_INDEX = {}

# Độ dài tối đa của từ (để match nhanh)
MAX_TERM_LEN = 10

HANZI_RE = re.compile(
    r"[\u3400-\u9FFF"          # BMP: CJK Unified Ideographs + Ext-A
    r"\U00020000-\U0002EBEF"   # Ext-B..F (khoảng gộp an toàn tới 2EBEF)
    r"\U00030000-\U0003134F"   # Ext-G..H
    r"]"
)

# --------------------------------------------------------------------------------------
# Utils
# --------------------------------------------------------------------------------------

def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def _is_cjk(c): 
    return bool(HANZI_RE.fullmatch(c))

def _esc(s):
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _attr(s):
    return _esc(str(s or "")).replace('"', "&quot;")
    
def _html_txt(s):
    return _esc(s).replace("\n", "<br>")

def _render_gloss_line(line):
    line = (line or "").strip()
    if not line:
        return ""
    if line.startswith("@@"):
        parts = line.split("\t")
        kind = parts[0]
        if kind == "@@html" and len(parts) >= 2:
            return f"<div class='structured-gloss'>{parts[1]}</div>"
        if kind == "@@entrymeta":
            return ""
        if kind == "@@tags":
            tags = "".join(f"<span class='pos-tag'>{_esc(x)}</span>" for x in parts[1:] if x)
            return f"<div class='gloss-tags'>{tags}</div>"
        if kind == "@@sense" and len(parts) >= 3:
            return f"<div class='sense-line'><span class='sense-num'>{_esc(parts[1])}</span><span>{_html_txt(parts[2])}</span></div>"
        if kind == "@@sense-cont" and len(parts) >= 2:
            return f"<div class='sense-cont'>{_html_txt(parts[1])}</div>"
        if kind == "@@note" and len(parts) >= 2:
            return f"<div class='gloss-note'><span class='gloss-label'>Note</span>{_html_txt(parts[1])}</div>"
        if kind == "@@xref" and len(parts) >= 2:
            return f"<div class='gloss-xref'><span class='gloss-label'>See also</span>{_html_txt(parts[1])}</div>"
        if kind == "@@example-ja" and len(parts) >= 2:
            return f"<div class='gloss-example ja-example'>{_html_txt(parts[1])}</div>"
        if kind == "@@example-en" and len(parts) >= 2:
            return f"<div class='gloss-example en-example'>{_html_txt(parts[1])}</div>"
    return _html_txt(line)


# --------------------------------------------------------------------------------------
# Cleanup / Inject (giữ Deck an toàn)
# --------------------------------------------------------------------------------------

def _nuke(wv):
    if not wv:
        return
    # gỡ iframe popup + cleanup của JS trong reviewer
    wv.eval(r"""(function(){
      var e = document.getElementById('hanzi-mini-iframe'); if(e) e.remove();
      if (window.__hanziMiniCleanup) { try { __hanziMiniCleanup(); } catch(_){} }
    })();""")

def _inject():
    rv = getattr(mw, "reviewer", None)
    if not rv or not rv.web:
        return
    _nuke(rv.web)
    # truyền profile cho inject.js
    rv.web.eval(
        f"window.__hanziLang = {json.dumps(LANG_PROFILE)}; "
        f"window.__hanziLangs = {json.dumps(POPUP_LANGS)}; "
        f"window.__yomiPopupModifier = {json.dumps(POPUP_TRIGGER_MOD)}; "
        f"window.__yomiSublookupMode = {json.dumps(POPUP_SUBLOOKUP_MODE)};"
    )
    rv.web.eval(_read_text(INJECT_JS_PATH))


def _on_q(_): _inject()
def _on_a(_): _inject()

def _on_state_change(state, *_):
    if state != "review":
        rv = getattr(mw, "reviewer", None)
        if rv and rv.web:
            _nuke(rv.web)
        _nuke(mw.web)  # dọn bên Deck/Overview

# --------------------------------------------------------------------------------------
# Quản lý nguồn từ điển (Yomichan/Yomitan)
# --------------------------------------------------------------------------------------

def _load_sources():
    global SOURCES
    if os.path.exists(SOURCES_PATH):
        try:
            SOURCES = json.loads(_read_text(SOURCES_PATH))
            if not isinstance(SOURCES, list):
                SOURCES = []
        except Exception:
            SOURCES = []
    else:
        SOURCES = []

def _save_sources():
    _write_text(SOURCES_PATH, json.dumps(SOURCES, ensure_ascii=False, indent=2))

def _structured_text(node):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        return "".join(_structured_text(x) for x in node)
    if isinstance(node, dict):
        if node.get("tag") == "rt":
            return ""
        data = node.get("data")
        if isinstance(data, dict) and data.get("content") == "attribution":
            return ""
        if isinstance(data, dict) and data.get("content") == "attribution-footnote":
            return ""
        return _structured_text(node.get("content"))
    return str(node)

def _structured_kind(node):
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            return data.get("content")
    return None

def _structured_children(node):
    if isinstance(node, dict):
        content = node.get("content")
        return content if isinstance(content, list) else [content]
    if isinstance(node, list):
        return node
    return []

def _find_structured(node, kind):
    out = []
    if isinstance(node, list):
        for x in node:
            out.extend(_find_structured(x, kind))
        return out
    if not isinstance(node, dict):
        return out
    if _structured_kind(node) == kind:
        out.append(node)
    for child in _structured_children(node):
        out.extend(_find_structured(child, kind))
    return out

def _has_lisaan_data(node):
    if isinstance(node, list):
        return any(_has_lisaan_data(x) for x in node)
    if not isinstance(node, dict):
        return False
    data = node.get("data")
    if isinstance(data, dict) and "lisaan" in data:
        return True
    return _has_lisaan_data(node.get("content"))

_STRUCTURED_TAGS = {
    "a", "br", "div", "span", "table", "tbody", "tr", "td", "th",
    "ul", "ol", "li", "details", "summary", "ruby", "rt", "rp", "b", "i", "strong", "em", "img",
}

def _structured_class(data):
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in ("lisaan", "content"):
        val = data.get(key)
        if val:
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(val)).strip("-").lower()
            if slug:
                parts.append(f"yomi-{slug}")
    return " ".join(parts)

def _render_structured_html(node):
    if node is None:
        return ""
    if isinstance(node, str):
        return _esc(node)
    if isinstance(node, (int, float)):
        return _esc(str(node))
    if isinstance(node, list):
        return "".join(_render_structured_html(x) for x in node)
    if not isinstance(node, dict):
        return _esc(str(node))

    tag = str(node.get("tag") or "span").lower()
    if tag not in _STRUCTURED_TAGS:
        tag = "span"
    data = node.get("data")
    cls = _structured_class(data)
    attrs = []
    if cls:
        attrs.append(f'class="{_attr(cls)}"')
    lang = node.get("lang")
    if lang:
        attrs.append(f'lang="{_attr(lang)}"')
        if str(lang).lower().startswith("ar"):
            attrs.append('dir="rtl"')
    if tag == "a":
        href = str(node.get("href") or "")
        if href.startswith(("http://", "https://")):
            attrs.append(f'href="{_attr(href)}"')
            attrs.append('target="_blank"')
            attrs.append('rel="noreferrer"')
        elif href.startswith("?query="):
            attrs.append(f'href="{_attr(href)}"')
    if tag in ("td", "th"):
        for source_key, html_key in (("rowSpan", "rowspan"), ("colSpan", "colspan")):
            val = node.get(source_key)
            if isinstance(val, int) and val > 1:
                attrs.append(f'{html_key}="{val}"')
    if tag == "img":
        path = str(node.get("path") or "").strip()
        if path:
            attrs.append(f'src="__YOMI_RESOURCE__{urllib.parse.quote(path, safe="")}__"')
        attrs.append('loading="lazy"')
        attrs.append('class="yomi-img"')
        width = node.get("width")
        height = node.get("height")
        units = str(node.get("sizeUnits") or "").lower()
        styles = []
        if isinstance(width, (int, float)) and width > 0:
            styles.append(f"width:{width}{'em' if units == 'em' else 'px'}")
        if isinstance(height, (int, float)) and height > 0:
            styles.append(f"height:{height}{'em' if units == 'em' else 'px'}")
        if styles:
            attrs.append(f'style="{_attr(";".join(styles))}"')
    if tag == "details" and node.get("open") is True:
        attrs.append("open")
    attr_text = (" " + " ".join(attrs)) if attrs else ""
    if tag == "br":
        return "<br>"
    if tag == "img":
        return f"<img{attr_text}>"
    inner = _render_structured_html(node.get("content"))
    return f"<{tag}{attr_text}>{inner}</{tag}>"

_CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

def _sense_number(node, idx):
    style = node.get("style") if isinstance(node, dict) else None
    marker = ""
    if isinstance(style, dict):
        marker = str(style.get("listStyleType") or "").strip().strip('"').strip("'")
    if not marker:
        marker = _CIRCLED_NUMS[idx - 1] if 1 <= idx <= len(_CIRCLED_NUMS) else f"{idx}."
    return marker

def _collect_structured_glossary(node):
    out = []
    for gnode in _find_structured(node, "glossary"):
        content = gnode.get("content") if isinstance(gnode, dict) else None
        items = content if isinstance(content, list) else [content]
        for item in items:
            text = _structured_text(item).strip()
            if text:
                out.append(text)
    return out

def _collect_structured_note(node):
    out = []
    for kind in ("sense-note-content", "notes"):
        for n in _find_structured(node, kind):
            text = _structured_text(n).strip()
            if text:
                out.append(text)
    return out

def _collect_structured_xrefs(node):
    out = []
    for xref in _find_structured(node, "xref"):
        label = " ".join(_structured_text(x).strip() for x in _find_structured(xref, "xref-content") if _structured_text(x).strip())
        gloss = " ".join(_structured_text(x).strip() for x in _find_structured(xref, "xref-glossary") if _structured_text(x).strip())
        label = re.sub(r"^See also\s*", "", label).strip()
        text = " ".join(x for x in (label, gloss) if x)
        if text:
            out.append(text)
    return out

def _collect_structured_examples(node):
    out = []
    for ex in _find_structured(node, "example-sentence"):
        ja = " ".join(_structured_text(x).strip() for x in _find_structured(ex, "example-sentence-a") if _structured_text(x).strip())
        en = " ".join(_structured_text(x).strip() for x in _find_structured(ex, "example-sentence-b") if _structured_text(x).strip())
        if ja:
            out.append(("ja", ja))
        if en:
            out.append(("en", en))
    return out

def _collect_structured_sense_groups(node):
    blocks = []
    for group in _find_structured(node, "sense-group"):
        lines = []
        tags = []
        for t in _find_structured(group, "part-of-speech-info"):
            text = _structured_text(t).strip()
            if text and text not in tags:
                tags.append(text)
        if tags:
            lines.append("@@tags\t" + "\t".join(tags))

        senses = _find_structured(group, "sense")
        for idx, sense in enumerate(senses, start=1):
            glosses = _collect_structured_glossary(sense)
            if glosses:
                marker = _sense_number(sense, idx)
                lines.append(f"@@sense\t{marker}\t{glosses[0]}")
                for g in glosses[1:]:
                    lines.append(f"@@sense-cont\t{g}")
            for note in _collect_structured_note(sense):
                lines.append(f"@@note\t{note}")
            for xref in _collect_structured_xrefs(sense):
                lines.append(f"@@xref\t{xref}")
            for lang, text in _collect_structured_examples(sense):
                lines.append(f"@@example-{lang}\t{text}")

        if lines:
            blocks.append("\n".join(lines))
    return blocks

def _collect_structured_glosses(node):
    grouped = _collect_structured_sense_groups(node)
    if grouped:
        return grouped
    out = []
    if isinstance(node, list):
        for x in node:
            out.extend(_collect_structured_glosses(x))
        return out
    if not isinstance(node, dict):
        return out

    data = node.get("data")
    if isinstance(data, dict) and data.get("content") == "glossary":
        content = node.get("content")
        items = content if isinstance(content, list) else [content]
        for item in items:
            text = _structured_text(item).strip()
            if text:
                out.append(text)
        return out

    out.extend(_collect_structured_glosses(node.get("content")))
    return out

def _clean_glosses(g):
    # Yomitan dictionaries may store glossary as plain text, {"glossary": ...},
    # or structured-content (Jitendex/JMdict).
    if isinstance(g, str):
        return [g.strip()] if g.strip() else []
    if isinstance(g, dict):
        if "glossary" in g:
            text = str(g.get("glossary") or "").strip()
            return [text] if text else []
        if g.get("type") == "structured-content":
            content = g.get("content")
            if _has_lisaan_data(content):
                html = _render_structured_html(content).strip()
                return [f"@@html\t{html}"] if html else []
            glosses = [x for x in _collect_structured_glosses(content) if x]
            if glosses:
                return glosses
            html = _render_structured_html(content).strip()
            if html:
                return [f"@@html\t{html}"]
            text = _structured_text(content).strip()
            return [text] if text else []
        glosses = _collect_structured_glosses(g)
        if glosses:
            return glosses
        text = _structured_text(g).strip()
        return [text] if text else []
    text = str(g).strip()
    return [text] if text else []

def _parse_term_bank_payload(text, sink_add):
    """Đọc 1 file term_bank (array JSON lớn hoặc NDJSON) và đẩy vào sink_add(term, reading, glosses)."""
    data = None
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
            data = data["entries"]
    except Exception:
        # NDJSON fallback
        data = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                data.append(json.loads(ln))
            except Exception:
                pass

    if not isinstance(data, list):
        return

    for ent in data:
        if not isinstance(ent, list) or not ent:
            continue
        term = str(ent[0]) if len(ent) >= 1 else ""
        reading = str(ent[1]) if len(ent) >= 2 and isinstance(ent[1], str) else ""
        if not term:
            continue

        glosses = []
        entry_meta = []
        if len(ent) > 2 and isinstance(ent[2], str) and ent[2].strip():
            entry_meta.append(ent[2].strip())
        if len(ent) > 3 and isinstance(ent[3], str) and ent[3].strip():
            entry_meta.append(ent[3].strip())
        if len(ent) > 7 and isinstance(ent[7], str) and ent[7].strip():
            entry_meta.append(ent[7].strip())

        # Ưu tiên tuyệt đối: cột 6 (index 5) theo format Yomichan
        if len(ent) > 5 and isinstance(ent[5], list):
            cand = ent[5]
            for g in cand:
                glosses.extend(_clean_glosses(g))

        # Fallback: nếu bộ nào “lạ” không để ở index 5, quét các list còn lại
        if not glosses:
            for x in ent[2:]:
                if isinstance(x, list):
                    for g in x:
                        glosses.extend(_clean_glosses(g))
                    if glosses:
                        break

        if glosses:
            if entry_meta:
                glosses = ["@@entrymeta\t" + "\t".join(entry_meta)] + glosses
            sink_add(term, reading, glosses)

def _action_setup_language():
    global LANG_PROFILE, HANZI_WRITER, POPUP_LANGS
    dlg = QDialog(mw); dlg.setWindowTitle('Yomi – Popup Languages')
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel('Open popup for selected languages:'))
    from aqt.qt import QCheckBox
    cb_zh = QCheckBox('Chinese (zh)')
    cb_ja = QCheckBox('Japanese (ja)')
    cb_en = QCheckBox('English (en)')
    cb_zh.setChecked('zh' in POPUP_LANGS)
    cb_ja.setChecked('ja' in POPUP_LANGS)
    cb_en.setChecked('en' in POPUP_LANGS)
    for lang_cb in (cb_zh, cb_ja, cb_en):
        v.addWidget(lang_cb)
    cb = QCheckBox('Enable Hanzi Writer tab')
    cb.setChecked(bool(HANZI_WRITER))
    v.addWidget(cb)
    hb = QHBoxLayout(); v.addLayout(hb)
    ok = QPushButton('OK'); cancel = QPushButton('Cancel')
    hb.addWidget(ok); hb.addWidget(cancel)
    def on_ok():
        global LANG_PROFILE, HANZI_WRITER, POPUP_LANGS
        POPUP_LANGS = []
        if cb_zh.isChecked(): POPUP_LANGS.append('zh')
        if cb_ja.isChecked(): POPUP_LANGS.append('ja')
        if cb_en.isChecked(): POPUP_LANGS.append('en')
        if not POPUP_LANGS:
            POPUP_LANGS = ['zh']
        LANG_PROFILE = _lang_profile_from_popup_langs()
        HANZI_WRITER = bool(cb.isChecked())
        _save_config()
        dlg.accept()
        tooltip(f'Popup languages: {", ".join(POPUP_LANGS)} | HanziWriter: {"ON" if HANZI_WRITER else "OFF"}', period=1600)
    ok.clicked.connect(on_ok); cancel.clicked.connect(dlg.reject)
    dlg.exec()
    _inject()

def _db_file_signature():
    sig = []
    for p in (DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"):
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except Exception:
            sig.append((p, 0, 0))
    return tuple(sig)

def _db_open():
    global DB, DB_MODE, DB_SIG
    if DB:
        try: DB.close()
        except Exception: pass
    DB = sqlite3.connect(DB_PATH, check_same_thread=False)
    DB.create_function("yomi_norm", 1, _lookup_norm_term)
    DB.execute("PRAGMA journal_mode=WAL")
    DB.execute("PRAGMA synchronous=NORMAL")
    DB.execute("PRAGMA temp_store=MEMORY")
    DB.execute("PRAGMA foreign_keys=ON")
    DB.execute("""
        CREATE TABLE IF NOT EXISTS source(
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          type  TEXT NOT NULL,   -- zip | folder
          path  TEXT NOT NULL,
          hash  TEXT,
          enabled INTEGER DEFAULT 1,
          added_at REAL
        )
    """)
    DB.execute("""
        CREATE TABLE IF NOT EXISTS term(
          term TEXT NOT NULL,
          norm_term TEXT,
          reading TEXT,
          norm_reading TEXT,
          gloss TEXT,
          source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE
        )
    """)
    DB.execute("""
        CREATE TABLE IF NOT EXISTS kanji(
          character TEXT NOT NULL,
          onyomi TEXT,
          kunyomi TEXT,
          tags TEXT,
          meanings TEXT,
          stats TEXT,
          source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE
        )
    """)
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_term ON term(term)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_len ON term(term, length(term))")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_kanji_char ON kanji(character)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_source ON term(source_id)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_kanji_source ON kanji(source_id)")
    DB.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    # --- MIGRATION: thêm cột priority nếu thiếu ---
    cols = [r[1] for r in DB.execute("PRAGMA table_info(source)")]
    if "priority" not in cols:
        DB.execute("ALTER TABLE source ADD COLUMN priority INTEGER DEFAULT 1000")
        # init theo id để có thứ tự xác định
        DB.execute("UPDATE source SET priority = id")
    term_cols = [r[1] for r in DB.execute("PRAGMA table_info(term)")]
    if "norm_term" not in term_cols:
        DB.execute("ALTER TABLE term ADD COLUMN norm_term TEXT")
    if "norm_reading" not in term_cols:
        DB.execute("ALTER TABLE term ADD COLUMN norm_reading TEXT")
    if _db_get_meta("norm_term_version") != NORM_TERM_VERSION:
        DB.execute("UPDATE term SET norm_term=yomi_norm(term), norm_reading=yomi_norm(reading)")
        _db_set_meta("norm_term_version", NORM_TERM_VERSION)
    else:
        DB.execute("UPDATE term SET norm_term=yomi_norm(term) WHERE norm_term IS NULL OR norm_term=''")
        DB.execute("UPDATE term SET norm_reading=yomi_norm(reading) WHERE norm_reading IS NULL OR norm_reading=''")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_norm ON term(norm_term)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_reading ON term(reading)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_norm_reading ON term(norm_reading)")
    DB.commit()
    _db_backfill_kanji_sources()
    DB_MODE = (
        DB.execute("SELECT COUNT(*) FROM term").fetchone()[0] > 0 or
        DB.execute("SELECT COUNT(*) FROM kanji").fetchone()[0] > 0
    )
    DB_SIG = _db_file_signature()


def _db_close():
    global DB, DB_MODE, DB_SIG
    if DB:
        try: DB.close()
        except: pass
    DB = None
    DB_MODE = False
    DB_SIG = None

def _db_refresh_if_changed():
    if DB is None:
        _db_open()
        return
    sig = _db_file_signature()
    if DB_SIG is not None and sig != DB_SIG:
        _db_open()

def _db_set_meta(key, val):
    DB.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(val)))

def _db_get_meta(key, default=None):
    cur = DB.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default

def _db_recalc_max_len():
    cur = DB.execute("SELECT MAX(LENGTH(term)) FROM term")
    maxlen = cur.fetchone()[0] or 1
    _db_set_meta("max_len", maxlen)
    DB.commit()

def _db_get_max_len():
    v = _db_get_meta("max_len", None)
    return int(v) if v else 10

def _db_content_counts(enabled_only=True):
    """Return counts for deciding whether lookup is unconfigured or just no-hit."""
    if DB is None:
        return {"sources": 0, "terms": 0, "kanji": 0}
    source_where = "WHERE enabled=1" if enabled_only else ""
    join_enabled = "JOIN source s ON s.id=t.source_id AND s.enabled=1" if enabled_only else ""
    kanji_join_enabled = "JOIN source s ON s.id=k.source_id AND s.enabled=1" if enabled_only else ""
    try:
        sources = DB.execute(f"SELECT COUNT(*) FROM source {source_where}").fetchone()[0]
        terms = DB.execute(f"SELECT COUNT(*) FROM term t {join_enabled}").fetchone()[0]
        kanji = DB.execute(f"SELECT COUNT(*) FROM kanji k {kanji_join_enabled}").fetchone()[0]
        return {"sources": int(sources or 0), "terms": int(terms or 0), "kanji": int(kanji or 0)}
    except Exception:
        return {"sources": 0, "terms": 0, "kanji": 0}

def _progress_step(progress, value, label):
    if progress:
        progress.setValue(value)
        progress.setLabelText(label)
        QApplication.processEvents()

def _db_compact_after_delete(progress=None):
    global DB_MODE
    _progress_step(progress, 3, "Recalculating lookup metadata...")
    _db_recalc_max_len()

    _progress_step(progress, 4, "Flushing SQLite WAL...")
    try:
        DB.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        DB.execute("PRAGMA wal_checkpoint(FULL)")

    _progress_step(progress, 5, "Compacting database file...")
    DB.execute("VACUUM")

    _progress_step(progress, 6, "Finalizing compacted database...")
    try:
        DB.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    DB.commit()
    DB_MODE = (
        DB.execute("SELECT COUNT(*) FROM term").fetchone()[0] > 0 or
        DB.execute("SELECT COUNT(*) FROM kanji").fetchone()[0] > 0
    )

def _db_finalize_after_delete(progress=None):
    global DB_MODE
    _progress_step(progress, 2, "Recalculating lookup metadata...")
    _db_recalc_max_len()

    _progress_step(progress, 3, "Flushing SQLite WAL...")
    try:
        DB.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        try:
            DB.execute("PRAGMA wal_checkpoint(FULL)")
        except Exception:
            pass
    DB.commit()
    DB_MODE = (
        DB.execute("SELECT COUNT(*) FROM term").fetchone()[0] > 0 or
        DB.execute("SELECT COUNT(*) FROM kanji").fetchone()[0] > 0
    )

def _db_ensure_delete_indexes(progress=None):
    _progress_step(progress, 1, "Preparing delete indexes...")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_term_source ON term(source_id)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_kanji_source ON kanji(source_id)")
    DB.commit()

def _hash_file(path, chunk=65536):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()
def _db_add_source(title, typ, path, hsh=None):
    now = time.time()
    prio = DB.execute("SELECT COALESCE(MAX(priority),0)+1 FROM source").fetchone()[0]
    cur = DB.execute(
        "INSERT INTO source(title,type,path,hash,enabled,added_at,priority) VALUES(?,?,?,?,1,?,?)",
        (title, typ, path, hsh or "", now, prio)
    )
    return cur.lastrowid


def _db_bulk_terms(rows):
    # rows: list[(term, reading, gloss, source_id)]
    rows2 = [(term, _lookup_norm_term(term), reading, _lookup_norm_term(reading), gloss, source_id)
             for term, reading, gloss, source_id in rows]
    DB.executemany(
        "INSERT INTO term(term,norm_term,reading,norm_reading,gloss,source_id) VALUES(?,?,?,?,?,?)",
        rows2,
    )

def _db_bulk_kanji(rows):
    DB.executemany(
        "INSERT INTO kanji(character,onyomi,kunyomi,tags,meanings,stats,source_id) VALUES(?,?,?,?,?,?,?)",
        rows,
    )

def _parse_kanji_bank_payload(text, sink_add):
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
            data = data["entries"]
    except Exception:
        data = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                data.append(json.loads(ln))
            except Exception:
                pass
    if not isinstance(data, list):
        return
    for ent in data:
        if not isinstance(ent, list) or not ent:
            continue
        ch = str(ent[0] or "").strip()
        if not ch:
            continue
        onyomi = str(ent[1] or "").strip() if len(ent) > 1 else ""
        kunyomi = str(ent[2] or "").strip() if len(ent) > 2 else ""
        tags = str(ent[3] or "").strip() if len(ent) > 3 else ""
        meanings = ent[4] if len(ent) > 4 and isinstance(ent[4], list) else []
        stats = ent[5] if len(ent) > 5 and isinstance(ent[5], dict) else {}
        sink_add(ch, onyomi, kunyomi, tags, meanings, stats)

def _db_backfill_kanji_sources():
    try:
        cur = DB.execute("SELECT id,path FROM source WHERE type='zip'")
        rows = cur.fetchall()
    except Exception:
        return
    changed = False
    for sid, path in rows:
        try:
            if DB.execute("SELECT 1 FROM kanji WHERE source_id=? LIMIT 1", (sid,)).fetchone():
                continue
            if not path or not os.path.exists(path):
                continue
            kanji_batch = []
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.lower().endswith(".json") and "kanji_bank" in n.lower()]
                if not names:
                    continue
                def sink_add_kanji(ch, onyomi, kunyomi, tags, meanings, stats):
                    kanji_batch.append((
                        ch, onyomi, kunyomi, tags,
                        json.dumps(meanings, ensure_ascii=False),
                        json.dumps(stats, ensure_ascii=False),
                        sid,
                    ))
                    if len(kanji_batch) >= 1000:
                        _db_bulk_kanji(kanji_batch); kanji_batch.clear()
                for name in names:
                    with z.open(name) as fh:
                        text = fh.read().decode("utf-8", errors="ignore")
                    _parse_kanji_bank_payload(text, sink_add_kanji)
            if kanji_batch:
                _db_bulk_kanji(kanji_batch)
            changed = True
        except Exception:
            continue
    if changed:
        DB.commit()

def import_yomichan_zip_to_db(path: str, title_override: str = None, progress_cb=None):
    def report(pct, msg):
        if progress_cb:
            try:
                progress_cb(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    report(0, "Preparing dictionary...")
    with _open_yomitan_zip(path) as z:
        title = os.path.splitext(os.path.basename(path))[0]
        # lấy title đẹp từ index.json nếu có
        try:
            with z.open("index.json") as fh:
                idx = json.loads(fh.read().decode("utf-8", errors="ignore"))
                if isinstance(idx, dict):
                    if "title" in idx:
                        title = idx.get("title") or title
                    elif "dictionary" in idx and isinstance(idx["dictionary"], dict):
                        title = idx["dictionary"].get("title") or title
        except Exception: pass

        # Manifest title takes priority so _is_in_db() can match consistently
        if title_override:
            title = title_override

        report(3, f"Registering '{title}'...")
        sid = _db_add_source(str(title), "zip", path, _hash_file(path))
        batch = []
        kanji_batch = []
        cnt = 0

        def sink_add(term, reading, glosses):
            nonlocal cnt, batch
            for g in glosses:
                batch.append((term, reading, g, sid))
                cnt += 1
                if len(batch) >= 2000:
                    _db_bulk_terms(batch); batch.clear()

        def sink_add_kanji(ch, onyomi, kunyomi, tags, meanings, stats):
            nonlocal cnt, kanji_batch
            kanji_batch.append((
                ch, onyomi, kunyomi, tags,
                json.dumps(meanings, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
                sid,
            ))
            cnt += 1
            if len(kanji_batch) >= 1000:
                _db_bulk_kanji(kanji_batch); kanji_batch.clear()

        # duyệt term_bank_*.json + kanji_bank_*.json
        bank_names = []
        for name in z.namelist():
            low = name.lower()
            if not low.endswith(".json"):
                continue
            if "term_bank" in low or "kanji_bank" in low:
                bank_names.append(name)
        total_banks = max(1, len(bank_names))
        report(5, f"Found {len(bank_names)} bank file(s).")

        for i, name in enumerate(bank_names, 1):
            low = name.lower()
            is_term_bank = "term_bank" in low
            is_kanji_bank = "kanji_bank" in low
            try:
                report(5 + int((i - 1) * 85 / total_banks), f"Importing {i}/{total_banks}: {os.path.basename(name)}")
                with z.open(name) as fh:
                    text = fh.read().decode("utf-8", errors="ignore")
                if is_term_bank:
                    _parse_term_bank_payload(text, sink_add)
                else:
                    _parse_kanji_bank_payload(text, sink_add_kanji)
            except Exception: continue

        report(92, "Writing remaining entries...")
        if batch: _db_bulk_terms(batch)
        if kanji_batch: _db_bulk_kanji(kanji_batch)
        report(96, "Rebuilding lookup metadata...")
        _db_recalc_max_len()
        report(99, "Saving database...")
        DB.commit()
        report(100, f"Installed {cnt} entries.")
        return cnt

def import_yomichan_folder_to_db(folder: str):
    title = os.path.basename(folder.rstrip("/\\")) or "FolderDict"
    # title đẹp từ index.json nếu có
    idx_path = os.path.join(folder, "index.json")
    if os.path.exists(idx_path):
        try:
            idx = json.loads(_read_text(idx_path))
            if isinstance(idx, dict):
                if "title" in idx: title = idx.get("title") or title
                elif "dictionary" in idx and isinstance(idx["dictionary"], dict):
                    title = idx["dictionary"].get("title") or title
        except Exception: pass

    sid = _db_add_source(str(title), "folder", folder, None)
    batch = []
    cnt = 0

    def sink_add(term, reading, glosses):
        nonlocal cnt, batch
        for g in glosses:
            batch.append((term, reading, g, sid))
            cnt += 1
            if len(batch) >= 2000:
                _db_bulk_terms(batch); batch.clear()

    for root, _, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".json"): continue
            if "term_bank" not in fn.lower(): continue
            p = os.path.join(root, fn)
            try:
                text = _read_text(p)
                _parse_term_bank_payload(text, sink_add)
            except Exception: continue

    if batch: _db_bulk_terms(batch)
    _db_recalc_max_len()
    DB.commit()
    return cnt
def _db_first_existing_any(forms):
    for f in forms:
        nf = _lookup_norm_term(f)
        cur = DB.execute("""
            SELECT t.term
            FROM term t JOIN source s ON s.id=t.source_id
            WHERE (t.term=? OR t.norm_term=? OR t.reading=? OR t.norm_reading=?) AND s.enabled=1
            ORDER BY CASE
                WHEN t.term=? THEN 0
                WHEN t.reading=? THEN 1
                WHEN t.norm_term=? THEN 2
                ELSE 3
            END, s.priority ASC, s.id ASC, t.rowid ASC
            LIMIT 1
        """, (f, nf, f, nf, f, f, nf))
        row = cur.fetchone()
        if row:
            return row[0]
    return None

def _db_existing_in_order(forms, limit=None):
    form_seen, out_seen, out = set(), set(), []
    for f in forms:
        if f in form_seen: continue
        form_seen.add(f)
        nf = _lookup_norm_term(f)
        row_limit = max(1, (limit or 1) - len(out))
        cur = DB.execute("""
            SELECT t.term
            FROM term t JOIN source s ON s.id=t.source_id
            WHERE (t.term=? OR t.norm_term=? OR t.reading=? OR t.norm_reading=?) AND s.enabled=1
            GROUP BY t.term
            ORDER BY CASE
                WHEN t.term=? THEN 0
                WHEN t.reading=? THEN 1
                WHEN t.norm_term=? THEN 2
                ELSE 3
            END, s.priority ASC, s.id ASC, MIN(t.rowid) ASC
            LIMIT ?
        """, (f, nf, f, nf, f, f, nf, row_limit))
        for row in cur.fetchall():
            if row and row[0] not in out_seen:
                out.append(row[0]); out_seen.add(row[0])
                if limit and len(out) >= limit: break
        if limit and len(out) >= limit: break
    return out


def _detect_lookup_lang(text):
    """Auto-detect language from script, then fall back to POPUP_LANGS config."""
    s = text or ""
    if re.search(r"[\u0041-\u0041]", s): pass  # dummy
    # Script-unique languages
    if re.search(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]", s):
        return "ko"
    if re.search(r"[\u0400-\u04FF]", s):
        return "ru"
    if re.search(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]", s):
        return "ar"
    if re.search(r"[\u0E00-\u0E7F]", s):
        return "th"
    if re.search(r"[\u3040-\u30FF\uFF65-\uFF9F]", s):
        return "ja"
    if re.search(r"[\u4E00-\u9FFF\u3400-\u4DBF]", s):
        return LANG_PROFILE if LANG_PROFILE in ("zh", "ja") else "zh"
    # Latin-script: pick first configured Latin lang
    if re.search(r"[A-Za-z\u00C0-\u024F]", s):
        for lang in POPUP_LANGS:
            if lang in DEINFLECT_LATIN_LANGS:
                return lang
        return "en"
    return LANG_PROFILE if LANG_PROFILE in DEINFLECT_LANG_CODES else "zh"



def db_longest_matches(text):
    lang = _detect_lookup_lang(text)

    # Space-separated/tokenized langs: pick one word then deinflect.
    # Arabic uses spaces/punctuation; longest-match over characters splits words badly.
    if lang in DEINFLECT_SPACE_WORD_LANGS:
        word = df_pick_seed(lang, text)
        if not word:
            return []
        forms = df_candidates(lang, word)
        exist = _db_existing_in_order(forms, limit=5)
        return exist

    # No-space script langs (zh, ja, ko, th): longest-match over seed
    s = df_pick_seed(lang, text)
    if not s:
        return []

    max_len = _db_get_max_len()
    out, i, n = [], 0, len(s)
    while i < n:
        found = []
        found_len = 0
        Lmax = min(max_len, n - i)
        for L in range(Lmax, 0, -1):
            seg = s[i:i+L]
            forms = df_candidates(lang, seg)
            terms = _db_existing_in_order(forms, limit=5)
            if terms:
                found = terms
                found_len = L
                break
        if found:
            out.extend(found)
            i += found_len
        else:
            i += 1

    # unique theo thứ tự
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            uniq.append(w); seen.add(w)
    return uniq


def db_entries_for_term(term):
    norm = _lookup_norm_term(term)
    exact = DB.execute("""
        SELECT 1
        FROM term t JOIN source s ON s.id=t.source_id
        WHERE t.term=? AND s.enabled=1
        LIMIT 1
    """, (term,)).fetchone()
    if exact:
        cur = DB.execute("""
            SELECT s.id, s.title, t.term, t.reading, t.gloss, t.rowid
            FROM term t
            JOIN source s ON s.id=t.source_id
            WHERE t.term=? AND s.enabled=1
            ORDER BY s.priority ASC, s.id ASC, t.rowid ASC
            LIMIT 200
        """, (term,))
    else:
        cur = DB.execute("""
            SELECT s.id, s.title, t.term, t.reading, t.gloss, t.rowid
            FROM term t
            JOIN source s ON s.id=t.source_id
            WHERE (t.term=? OR t.norm_term=? OR t.reading=? OR t.norm_reading=?) AND s.enabled=1
            ORDER BY CASE
                WHEN t.term=? THEN 0
                WHEN t.reading=? THEN 1
                WHEN t.norm_term=? THEN 2
                ELSE 3
            END, s.priority ASC, s.id ASC, t.rowid ASC
            LIMIT 200
        """, (term, norm, term, norm, term, term, norm))
    entries = []
    current = None
    current_key = None
    for source_id, title, headword, reading, gloss, _rowid in cur.fetchall():
        key = (title, headword, reading)
        text = gloss or ""
        if text.startswith("@@entrymeta"):
            meta = [x for x in text.split("\t")[1:] if x]
            current = {"source_id": source_id, "source": title, "term": headword, "reading": reading, "meta": meta, "glosses": []}
            entries.append(current)
            current_key = key
            continue
        if current is not None and current_key == key:
            current["glosses"].append(text)
        else:
            current = {"source_id": source_id, "source": title, "term": headword, "reading": reading, "meta": [], "glosses": [text]}
            entries.append(current)
            current_key = key
    entries = [e for e in entries if e.get("glosses")]
    return entries

def _kanji_chars_from_text(text):
    chars, seen = [], set()
    for ch in text or "":
        if re.match(r"[\u3400-\u9fff]", ch) and ch not in seen:
            chars.append(ch)
            seen.add(ch)
    return chars

def db_kanji_for_text(text):
    if DB is None:
        _db_open()
    out = []
    for ch in _kanji_chars_from_text(text):
        cur = DB.execute("""
            SELECT k.character,k.onyomi,k.kunyomi,k.tags,k.meanings,k.stats,s.title
            FROM kanji k JOIN source s ON s.id=k.source_id
            WHERE k.character=? AND s.enabled=1
            ORDER BY s.priority ASC, s.id ASC
            LIMIT 3
        """, (ch,))
        for character, onyomi, kunyomi, tags, meanings, stats, source in cur.fetchall():
            try:
                meanings_val = json.loads(meanings or "[]")
            except Exception:
                meanings_val = []
            try:
                stats_val = json.loads(stats or "{}")
            except Exception:
                stats_val = {}
            out.append({
                "character": character,
                "onyomi": onyomi or "",
                "kunyomi": kunyomi or "",
                "tags": tags or "",
                "meanings": meanings_val,
                "stats": stats_val,
                "source": source or "",
            })
    return out

def db_has_kanji_for_text(text):
    return bool(db_kanji_for_text(text))


def _load_yomi_zip(path):
    # Trả về {"title": "...", "count": N}
    title = os.path.splitext(os.path.basename(path))[0]
    count_added = 0

    def sink_add(term, reading, glosses):
        nonlocal count_added
        ent = {"reading": reading, "glosses": glosses, "source": title}
        TERM_INDEX.setdefault(term, []).append(ent)
        count_added += 1

    try:
        with _open_yomitan_zip(path) as z:
            # Tên bộ từ điển trong index.json (nếu có)
            try:
                with z.open("index.json") as fh:
                    idx = json.loads(fh.read().decode("utf-8", errors="ignore"))
                    # 'title' có thể nằm ở metadata/ngược lại… xử lý nhẹ
                    if isinstance(idx, dict):
                        if "title" in idx:
                            title = str(idx.get("title") or title)
                        elif "dictionary" in idx and isinstance(idx["dictionary"], dict):
                            title = str(idx["dictionary"].get("title") or title)
            except Exception:
                pass

            # Duyệt mọi file term_bank_*.json
            for name in z.namelist():
                if not name.lower().endswith(".json"):
                    continue
                if "term_bank" not in name.lower():
                    continue
                try:
                    with z.open(name) as fh:
                        text = fh.read().decode("utf-8", errors="ignore")
                    _parse_term_bank_payload(text, sink_add)
                except Exception:
                    continue
    except Exception as e:
        raise e

    return {"title": title, "count": count_added}

def _load_yomi_folder(folder):
    # Trả về {"title": "...", "count": N}
    title = os.path.basename(folder.rstrip("/\\")) or "FolderDict"
    count_added = 0

    def sink_add(term, reading, glosses):
        nonlocal count_added
        ent = {"reading": reading, "glosses": glosses, "source": title}
        TERM_INDEX.setdefault(term, []).append(ent)
        count_added += 1

    # Đọc index.json nếu có để lấy title
    idx_path = os.path.join(folder, "index.json")
    if os.path.exists(idx_path):
        try:
            idx = json.loads(_read_text(idx_path))
            if isinstance(idx, dict):
                if "title" in idx:
                    title = str(idx.get("title") or title)
                elif "dictionary" in idx and isinstance(idx["dictionary"], dict):
                    title = str(idx["dictionary"].get("title") or title)
        except Exception:
            pass

    # Duyệt term_bank_*.json
    for root, _, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".json"):
                continue
            if "term_bank" not in fn.lower():
                continue
            p = os.path.join(root, fn)
            try:
                text = _read_text(p)
                _parse_term_bank_payload(text, sink_add)
            except Exception:
                continue

    return {"title": title, "count": count_added}

def _rebuild_max_len():
    global MAX_TERM_LEN
    MAX_TERM_LEN = 10
    for term in TERM_INDEX.keys():
        if len(term) > MAX_TERM_LEN:
            MAX_TERM_LEN = len(term)

def _reload_all_sources():
    # Xây TERM_INDEX từ SOURCES
    TERM_INDEX.clear()
    for s in SOURCES:
        t = s.get("type")
        p = s.get("path")
        if not p:
            continue
        try:
            if t == "zip" and os.path.exists(p):
                _load_yomi_zip(p)
            elif t == "folder" and os.path.isdir(p):
                _load_yomi_folder(p)
        except Exception:
            # bỏ qua lỗi từng nguồn
            pass
    _rebuild_max_len()

# --------------------------------------------------------------------------------------
# Tra cứu: longest match + gom kết quả
# --------------------------------------------------------------------------------------

def longest_matches(text):
    s = "".join([c for c in text if _is_cjk(c)])
    if not s:
        return []
    # Nếu toàn chuỗi là 1 mục
    if s in TERM_INDEX:
        return [s]
    out = []
    i, n = 0, len(s)
    while i < n:
        if not _is_cjk(s[i]):
            i += 1
            continue
        found = None
        max_len = min(MAX_TERM_LEN, n - i)
        for L in range(max_len, 0, -1):
            seg = s[i:i+L]
            if seg in TERM_INDEX:
                found = seg
                break
        if found:
            out.append(found)
            i += len(found)
        else:
            if s[i] in TERM_INDEX:
                out.append(s[i])
            i += 1

    # unique theo thứ tự
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            uniq.append(w)
            seen.add(w)
    return uniq

# --------------------------------------------------------------------------------------
# HTTP server: /lookup?q=...
# --------------------------------------------------------------------------------------

class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # tránh keep-alive
    BROKEN = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)

    def log_message(self, *a, **kw):
        return  # im lặng

    # ===== tiện ích JSON an toàn =====
    def _safe_send_headers(self, code, length, ctype="text/html; charset=utf-8"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            # --- CORS ---
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return True
        except self.BROKEN:
            return False

    def do_OPTIONS(self):
        # Preflight cho fetch JSON (Content-Type: application/json)
        self._safe_send_headers(204, 0)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        if self._safe_send_headers(code, len(data), "application/json; charset=utf-8"):
            try: self.wfile.write(data)
            except self.BROKEN: pass

    def _safe_write(self, data: bytes):
        try:
            self.wfile.write(data)
        except self.BROKEN:
            pass

    def _serve_resource(self, qs):
        try:
            sid = int((qs.get("sid") or ["0"])[0] or 0)
            rel = urllib.parse.unquote((qs.get("path") or [""])[0] or "")
            rel = rel.lstrip("/\\")
            if not sid or not rel or ".." in rel.replace("\\", "/").split("/"):
                self._safe_send_headers(404, 0)
                return
            row = DB.execute("SELECT path FROM source WHERE id=?", (sid,)).fetchone()
            if not row or not row[0] or not os.path.exists(row[0]):
                self._safe_send_headers(404, 0)
                return
            with zipfile.ZipFile(row[0]) as z:
                data = z.read(rel)
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            if self._safe_send_headers(200, len(data), ctype):
                self._safe_write(data)
        except Exception:
            self._safe_send_headers(404, 0)

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/resource":
                _db_refresh_if_changed()
                self._serve_resource(urllib.parse.parse_qs(parsed.query or ""))
                return
            # --- API: danh sách dictionaries trong DB ---
            if parsed.path == "/api/sources":
                _db_refresh_if_changed()
                rows = []
                cur = DB.execute("SELECT id,title,enabled,priority FROM source ORDER BY priority ASC, id ASC")
                for sid, title, en, pr in cur.fetchall():
                    rows.append({"id": sid, "title": title, "enabled": int(en), "priority": int(pr)})
                self._json({"ok": True, "sources": rows})
                return
            
            # --- API: KANJIDIC / kanji_bank data ---
            if parsed.path == "/api/kanji":
                _db_refresh_if_changed()
                try:
                    qs = urllib.parse.parse_qs(parsed.query or "")
                except Exception:
                    qs = {}
                q = (qs.get("q", [""])[0] or "").strip()
                self._json({"ok": True, "items": db_kanji_for_text(q)})
                return

            # --- trang tra cứu như cũ ---
            if parsed.path not in ("/lookup", "/", "/q"):
                body = b"<!doctype html><title>404</title>Not Found"
                if self._safe_send_headers(404, len(body)):
                    self._safe_write(body)
                return
            



            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            _db_refresh_if_changed()

            if DB_MODE and DB:
                terms = db_longest_matches(q)
                blocks = []
                for term in terms:
                    entries = db_entries_for_term(term)
                    blocks.append((term, entries))
            else:
                terms = longest_matches(q)
                blocks = []
                for term in terms:
                    entries = TERM_INDEX.get(term, [])
                    blocks.append((term, entries))

            html = self._render(blocks, q)
            enc = html.encode("utf-8")
            if self._safe_send_headers(200, len(enc)):
                self._safe_write(enc)

        except self.BROKEN:
            return
        except Exception as e:
            msg = ("<!doctype html><meta charset='utf-8'>"
                   "<style>body{font:14px system-ui;margin:8px}</style>"
                   f"<b>Error:</b> {_esc(str(e))}").encode("utf-8")
            if self._safe_send_headers(200, len(msg)):
                self._safe_write(msg)

    # ====== NEW: nhận dữ liệu thêm mục ======
    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/add":
                self._json({"ok": False, "error": "Not Found"}, code=404)
                return

            ln = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(ln).decode("utf-8", errors="ignore") if ln > 0 else "{}"
            data = json.loads(raw or "{}")

            term = (data.get("term") or "").strip()
            reading = (data.get("reading") or "").strip()
            gloss = (data.get("gloss") or "").strip()
            sid = data.get("source_id")
            new_title = (data.get("new_source_title") or "").strip()

            if not term:
                self._json({"ok": False, "error": "Empty term"})
                return

            _db_refresh_if_changed()

            # tạo source mới nếu cần
            if (not sid) and new_title:
                sid = _db_add_source(new_title, "manual", ":manual", None)

            if not sid:
                self._json({"ok": False, "error": "No source selected"})
                return

            # chèn các dòng gloss (mỗi dòng 1 mục)
            rows = []
            for line in (gloss.splitlines() or [""]):
                g = line.strip()
                if g:
                    rows.append((term, reading, g, sid))
            if rows:
                _db_bulk_terms(rows)
                _db_recalc_max_len()
                DB.commit()

            self._json({"ok": True, "inserted": len(rows), "source_id": sid})

        except self.BROKEN:
            return
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, code=200)


    # ---------------- renderer giữ nguyên ----------------
    def _render(self, blocks, q):
        rows = []
        if blocks:
            for (term, entries) in blocks:
                # nhóm theo source
                per_src = {}
                for e in entries:
                    per_src.setdefault(e["source"], []).append(e)

                term_class = "t en-term" if re.search(r"[A-Za-z]", term or "") else "t"
                term_html = [f"<div class='term'><div class='{term_class}'>{_esc(term)}</div>"]
                for src, items in per_src.items():
                    term_html.append(f"<div class='src'>{_esc(src)}</div>")
                    visible_items = items[:8]
                    show_entry_nums = len(visible_items) > 1
                    for idx, e in enumerate(visible_items, start=1):
                        rd = _esc(e.get("reading",""))
                        meta = e.get("meta") or []
                        meta_html = "".join(
                            f"<span class='entry-tag'>{_esc(x)}</span>"
                            for x in meta if x
                        )
                        num_cls = "entry-num" if show_entry_nums else "entry-num entry-num-hidden"
                        head_html = (
                            f"<div class='entry-head'><span class='{num_cls}'>{idx}.</span>{meta_html}</div>"
                            if (show_entry_nums or meta_html) else ""
                        )
                        # Flatten: each gloss may itself contain \n-joined sub-defs
                        lines = []
                        has_structured_lines = False
                        resource_base = f"http://127.0.0.1:{PORT}/api/resource?sid={int(e.get('source_id') or 0)}&path="
                        for g in e.get("glosses", []):
                            if g:
                                for sub in g.split("\n"):
                                    sub = sub.strip()
                                    if sub:
                                        if sub.startswith("@@"):
                                            has_structured_lines = True
                                        rendered = _render_gloss_line(sub)
                                        if "__YOMI_RESOURCE__" in rendered:
                                            rendered = re.sub(
                                                r"__YOMI_RESOURCE__(.*?)__",
                                                lambda m: resource_base + m.group(1),
                                                rendered,
                                            )
                                        lines.append(rendered)
                        gloss = "".join(lines) if has_structured_lines else "<br>".join(lines)
                        term_html.append(
                            f"<div class='def'><span class='r'>{rd}</span>"
                            f"<div class='g'>{head_html}{gloss}</div></div>"
                        )
                term_html.append("</div>")
                rows.append("".join(term_html))
        else:
            counts = _db_content_counts() if DB_MODE and DB else {"sources": 0, "terms": 0, "kanji": 0}
            if counts["terms"] <= 0 and counts["kanji"] <= 0:
                rows.append(
                    "<div class='setup-empty'>"
                    "<b>No dictionaries installed yet.</b>"
                    "Open <code>Tools → YomiLens Settings</code>, then go to "
                    "<code>Dictionaries</code> to download or import a dictionary."
                    "<div class='hint'>After installing a dictionary, select a word again to open the popup.</div>"
                    "</div>"
                )
            else:
                rows.append(f"<div class='empty'>Not found: {_esc(q)}</div>")

        tpl = _get_popup_tpl()
        kanji_enabled = "1" if (DB_MODE and DB and db_has_kanji_for_text(q)) else "0"
        html = (
            tpl.replace("{{ROWS}}", "".join(rows))
            .replace("{{QUERY}}", _esc(q))
            .replace("{{HW_ENABLED}}", "1" if HANZI_WRITER else "0")
            .replace("{{KANJI_ENABLED}}", kanji_enabled)
        )
        return html



_server = None
def _start_server():
    global _server
    try:
        _server = _ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
        t = threading.Thread(target=_server.serve_forever, daemon=True)
        t.start()
    except OSError:
        # nếu port bận, bỏ qua; iframe sẽ báo lỗi, nhưng không ảnh hưởng Anki
        pass

# --------------------------------------------------------------------------------------
# Menu: Thêm / Quản lý từ điển Yomichan
# --------------------------------------------------------------------------------------
def _action_db_import_zip():
    path, _ = QFileDialog.getOpenFileName(mw, "Select Yomichan ZIP", "", "ZIP (*.zip)")
    if not path: return
    progress = QProgressDialog("Preparing dictionary...", None, 0, 100, mw)
    progress.setWindowTitle("Install Dictionary")
    progress.setMinimumDuration(0)
    progress.setAutoClose(True)
    progress.setAutoReset(True)
    progress.setValue(0)
    def set_import_progress(pct, msg):
        progress.setValue(pct)
        progress.setLabelText(msg)
        QApplication.processEvents()
    try:
        if DB is None: _db_open()
        n = import_yomichan_zip_to_db(path, progress_cb=set_import_progress)
        global DB_MODE; DB_MODE = True
        progress.setValue(100)
        tooltip(f"Imported {n} entries to DB")
    except Exception as e:
        tooltip(f"DB ZIP error: {e}", period=2000)
    finally:
        progress.close()

def _action_db_import_folder():
    folder = QFileDialog.getExistingDirectory(mw, "Select Yomichan folder")
    if not folder: return
    try:
        if DB is None: _db_open()
        n = import_yomichan_folder_to_db(folder)
        global DB_MODE; DB_MODE = True
        tooltip(f"Imported {n} entries to DB")
    except Exception as e:
        tooltip(f"DB folder error: {e}", period=2000)

def _action_db_clear():
    try:
        _db_close()
        if os.path.exists(DB_PATH): os.remove(DB_PATH)
        tooltip("yomi_index.db deleted")
    except Exception as e:
        tooltip(f"Error deleting DB: {e}", period=2000)

def _action_db_stats():
    try:
        if DB is None: _db_open()
        c1 = DB.execute("SELECT COUNT(*) FROM source").fetchone()[0]
        c2 = DB.execute("SELECT COUNT(*) FROM term").fetchone()[0]
        c3 = DB.execute("SELECT COUNT(*) FROM kanji").fetchone()[0]
        ml = _db_get_max_len()
        tooltip(f"DB: {c1} source(s), {c2} entries, {c3} kanji, max_len={ml}", period=2500)
    except Exception as e:
        tooltip(f"Stats error: {e}", period=2000)

def _db_stats_text():
    try:
        if DB is None: _db_open()
        c1 = DB.execute("SELECT COUNT(*) FROM source").fetchone()[0]
        c2 = DB.execute("SELECT COUNT(*) FROM term").fetchone()[0]
        c3 = DB.execute("SELECT COUNT(*) FROM kanji").fetchone()[0]
        ml = _db_get_max_len()
        return f"DB: {c1} source(s), {c2} entries, {c3} kanji, max_len={ml}"
    except Exception as e:
        return f"Stats error: {e}"

class _DbManageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Yomi – Manage DB Dictionaries")
        self.resize(600, 420)

        self.list = QListWidget(self)
        self.hint = QLabel("↑/↓ to reorder priority · Enable/Disable to toggle · Delete to remove from DB", self)
        self.hint.setStyleSheet("color:#666;margin:4px 0 8px")

        btnUp = QPushButton("↑ Up", self)
        btnDown = QPushButton("↓ Down", self)
        btnToggle = QPushButton("Enable / Disable", self)
        btnDelete = QPushButton("Delete", self)
        btnClose = QPushButton("Save & Close", self)

        btnUp.clicked.connect(self.on_up)
        btnDown.clicked.connect(self.on_down)
        btnToggle.clicked.connect(self.on_toggle)
        btnDelete.clicked.connect(self.on_delete)
        btnClose.clicked.connect(self.on_save_close)

        hl = QHBoxLayout()
        for b in (btnUp, btnDown, btnToggle, btnDelete, btnClose):
            hl.addWidget(b)

        vl = QVBoxLayout(self)
        vl.addWidget(self.hint)
        vl.addWidget(self.list, 1)
        vl.addLayout(hl)
        self.setLayout(vl)

        self.rows = []  # [{id,title,type,path,enabled,priority}]
        self.reload()

    def reload(self):
        self.rows = []
        self.list.clear()
        if DB is None:
            _db_open()
        cur = DB.execute("SELECT id,title,type,path,enabled,priority FROM source ORDER BY priority ASC, id ASC")
        for (sid, title, typ, path, en, pr) in cur.fetchall():
            row = {"id":sid, "title":title, "type":typ, "path":path, "enabled":bool(en), "priority":pr}
            self.rows.append(row)
            self._add_item(row)

    def _add_item(self, row):
        mark = "✓" if row["enabled"] else "×"
        base = os.path.basename(row["path"])
        txt = f"[{mark}]  {row['title']}   —  {row['type']}   —  {base}"
        item = QListWidgetItem(txt)
        item.setData(32, row)  # Qt.UserRole = 32
        self.list.addItem(item)

    def _refresh_list(self):
        self.list.clear()
        for r in self.rows:
            self._add_item(r)
        if self.rows:
            self.list.setCurrentRow(0)

    def current_index(self):
        return self.list.currentRow()

    def on_up(self):
        i = self.current_index()
        if i <= 0: return
        self.rows[i-1], self.rows[i] = self.rows[i], self.rows[i-1]
        self._refresh_list()
        self.list.setCurrentRow(i-1)

    def on_down(self):
        i = self.current_index()
        if i < 0 or i >= len(self.rows)-1: return
        self.rows[i], self.rows[i+1] = self.rows[i+1], self.rows[i]
        self._refresh_list()
        self.list.setCurrentRow(i+1)

    def on_toggle(self):
        i = self.current_index()
        if i < 0: return
        self.rows[i]["enabled"] = not self.rows[i]["enabled"]
        self._refresh_list()
        self.list.setCurrentRow(i)

    def on_delete(self):
        i = self.current_index()
        if i < 0: return
        row = self.rows[i]
        _Yes = QMessageBox.StandardButton.Yes
        _No  = QMessageBox.StandardButton.No
        ok = QMessageBox.question(self, "Delete Dictionary",
                                  f"Remove '{row['title']}' from DB?\n(This cannot be undone.)",
                                  _Yes | _No, _No)
        if ok != _Yes: return
        progress = QProgressDialog("Deleting dictionary...", None, 0, 7, self)
        progress.setWindowTitle("Delete Dictionary")
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.setValue(0)
        QApplication.processEvents()
        try:
            _db_ensure_delete_indexes(progress)
            _progress_step(progress, 2, f"Removing '{row['title']}' entries...")
            DB.execute("DELETE FROM term WHERE source_id=?", (row["id"],))
            DB.execute("DELETE FROM kanji WHERE source_id=?", (row["id"],))
            DB.execute("DELETE FROM source WHERE id=?", (row["id"],))
            DB.commit()
            _db_compact_after_delete(progress)
            _progress_step(progress, 7, "Done.")
            del self.rows[i]
            self._refresh_list()
            tooltip("Dictionary removed and database compacted", period=1800)
        except Exception as e:
            try:
                DB.rollback()
            except Exception:
                pass
            QMessageBox.critical(self, "Error", f"Could not delete: {e}")
        finally:
            progress.close()

    def on_save_close(self):
        # ghi lại priority tuần tự & enabled
        try:
            for pr, r in enumerate(self.rows, start=1):
                DB.execute("UPDATE source SET enabled=?, priority=? WHERE id=?",
                           (1 if r["enabled"] else 0, pr, r["id"]))
            _db_recalc_max_len()
            DB.commit()
            tooltip("Order and state saved", period=1500)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save: {e}")
        self.accept()

def _action_db_manage():
    if DB is None: _db_open()
    dlg = _DbManageDialog(mw)
    dlg.exec()

class _YomiSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("YomiLens Settings")
        self.resize(780, 600)

        from aqt.qt import QTabWidget, QCheckBox

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        root.addWidget(tabs, 1)

        tabs.addTab(self._build_general_tab(QCheckBox), "General")
        tabs.addTab(self._build_database_tab(), "Dictionaries")
        tabs.addTab(self._build_about_tab(), "☕ Support")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _build_general_tab(self, QCheckBox):
        from aqt.qt import QScrollArea, QGridLayout, QComboBox
        global LANG_PROFILE, HANZI_WRITER, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Open popup for selected languages:"))

        # Scrollable grid of checkboxes — 2 columns
        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(4)
        scroll.setWidget(inner)
        v.addWidget(scroll)

        lang_cbs = {}   # code -> QCheckBox
        for i, (code, label, _script) in enumerate(DEINFLECT_ALL_LANGS):
            mode = "inflection" if code in DEINFLECT_INFLECTED_LANGS else "exact match"
            cb_l = QCheckBox(f"{label} · {mode}", inner)
            cb_l.setToolTip(
                "Popup can deinflect common word forms for this language."
                if code in DEINFLECT_INFLECTED_LANGS
                else "Popup can open for this script, but lookup is exact-match only."
            )
            cb_l.setChecked(code in POPUP_LANGS)
            grid.addWidget(cb_l, i // 2, i % 2)
            lang_cbs[code] = cb_l

        cb_hw = QCheckBox("Enable Hanzi Writer tab", w)
        cb_hw.setChecked(bool(HANZI_WRITER))
        v.addWidget(cb_hw)

        trigger_row = QHBoxLayout()
        trigger_row.addWidget(QLabel("Open popup trigger:", w))
        trigger_combo = QComboBox(w)
        trigger_options = [
            ("No key", "none"),
            ("Opt", "alt"),
            ("Ctrl", "ctrl"),
            ("Shift", "shift"),
            ("Cmd", "meta"),
        ]
        for label, value in trigger_options:
            trigger_combo.addItem(label, value)
        current_idx = next((i for i, (_label, value) in enumerate(trigger_options) if value == POPUP_TRIGGER_MOD), 0)
        trigger_combo.setCurrentIndex(current_idx)
        trigger_combo.setToolTip(
            "No key opens after selecting text. Modifier options require holding that key while selecting, "
            "or pressing it after selecting text."
        )
        trigger_row.addWidget(trigger_combo, 1)
        v.addLayout(trigger_row)

        sublookup_row = QHBoxLayout()
        sublookup_row.addWidget(QLabel("Popup lookup behavior:", w))
        sublookup_combo = QComboBox(w)
        sublookup_options = [
            ("Reuse current popup", "reuse"),
            ("Open nested popup", "nested"),
        ]
        for label, value in sublookup_options:
            sublookup_combo.addItem(label, value)
        sublookup_idx = next((i for i, (_label, value) in enumerate(sublookup_options) if value == POPUP_SUBLOOKUP_MODE), 0)
        sublookup_combo.setCurrentIndex(sublookup_idx)
        sublookup_combo.setToolTip(
            "Controls what happens when you look up text from inside an existing popup."
        )
        sublookup_row.addWidget(sublookup_combo, 1)
        v.addLayout(sublookup_row)

        save = QPushButton("Save Language Settings", w)
        v.addWidget(save)
        apply_note = QLabel(
            "Saved settings are applied to the current review screen immediately when possible. "
            "For the most reliable result, restart Anki after saving.",
            w,
        )
        apply_note.setWordWrap(True)
        apply_note.setStyleSheet("color:#666;font-size:12px")
        v.addWidget(apply_note)
        v.addStretch(1)

        def on_save():
            global LANG_PROFILE, HANZI_WRITER, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE
            POPUP_LANGS = [code for code, cb_l in lang_cbs.items() if cb_l.isChecked()]
            if not POPUP_LANGS:
                POPUP_LANGS = ["zh"]
            LANG_PROFILE = _lang_profile_from_popup_langs()
            HANZI_WRITER = bool(cb_hw.isChecked())
            POPUP_TRIGGER_MOD = str(trigger_combo.currentData() or "none")
            POPUP_SUBLOOKUP_MODE = str(sublookup_combo.currentData() or "reuse")
            _save_config()
            _inject()
            tooltip(
                f'Popup languages: {", ".join(POPUP_LANGS)} | Trigger: {trigger_combo.currentText()} | '
                f'Lookup: {sublookup_combo.currentText()} | '
                f'HanziWriter: {"ON" if HANZI_WRITER else "OFF"}',
                period=1600,
            )
        save.clicked.connect(on_save)
        return w

    def _build_about_tab(self):
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.setSpacing(16)
        v.setContentsMargins(24, 24, 24, 24)
        v.addStretch(1)

        title = QLabel("YomiLens Popup Dictionary", w)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#333")
        v.addWidget(title)

        desc = QLabel(
            "A quick lookup lens for Anki — hover any word to look it up.\n"
            "Supports Chinese, Japanese, English, and more.", w
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("font-size:13px;color:#666;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        sep = QFrame(w)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#eee;margin:4px 40px")
        v.addWidget(sep)

        coffee_btn = QPushButton("☕  Support on Ko-fi", w)
        coffee_btn.setMinimumHeight(40)
        coffee_btn.setStyleSheet(
            "QPushButton{background:#ffdd00;color:#333;font-size:14px;font-weight:bold;"
            "border:none;border-radius:10px;padding:0 24px}"
            "QPushButton:hover{background:#ffd000}"
        )
        coffee_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ko-fi.com/marshnguyen"))
        )
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(coffee_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        github_lbl = QLabel(
            '<a href="https://github.com/MarshNg/yomilens-dictionaries" '
            'style="color:#555;font-size:12px">GitHub: MarshNg/yomilens-dictionaries</a>', w
        )
        github_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_lbl.setOpenExternalLinks(True)
        v.addWidget(github_lbl)

        credits = QLabel(
            '<div style="font-size:11px;color:#666;line-height:1.45;text-align:left;">'
            '<b>Dictionary credits</b><br>'
            'Chinese EN/VI/FR data from LingLook / Phong Phan: '
            'CC-CEDICT by MDBG (CC BY-SA 4.0), CVDICT by Phong Phan '
            '(CC BY-SA 4.0), and CFDICT by Chine Informations '
            '(CC BY-SA 3.0).<br>'
            'Japanese data from <a href="https://www.edrdg.org/">EDRDG</a>; '
            'Yomitan-ready JMdict/JMnedict/KANJIDIC builds by '
            '<a href="https://github.com/yomidevs/jmdict-yomitan">Yomidevs</a> '
            'using <a href="https://github.com/yomidevs/yomitan-import">Yomitan Import</a>; '
            'Jitendex from <a href="https://jitendex.org">Jitendex.org</a> / '
            '<a href="https://github.com/Jitendex/Jitendex">Jitendex</a>.<br>'
            'Language detection and deinflection logic adapted from '
            '<a href="https://github.com/yomidevs/yomitan">Yomitan</a> by '
            '<a href="https://github.com/yomidevs/yomitan?tab=readme-ov-file#contributing">'
            'the Yomitan contributors</a>.<br>'
            'English EN→EN data: Open English WordNet (CC BY 4.0), '
            'MongoDB english-words-definitions (Apache 2.0), ipa-dict (MIT). '
            'EN→VI data: Free Vietnamese Dictionary Project / Hồ Ngọc Đức '
            '(GPL v2 or later).'
            '</div>', w
        )
        credits.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        credits.setWordWrap(True)
        credits.setOpenExternalLinks(True)
        v.addWidget(credits)

        v.addStretch(2)
        return w

    def _build_database_tab(self):
        from aqt.qt import (QScrollArea, QFrame, QProgressBar,
                            QSizePolicy, QFont)
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        # ── DB stats + management buttons ─────────────────────────────────
        self.stats_label = QLabel(_db_stats_text(), w)
        self.stats_label.setStyleSheet("color:#666;font-size:12px;margin-bottom:4px")
        v.addWidget(self.stats_label)

        if not DISMISS_REBUILD_NOTICE:
            notice_box = QFrame(w)
            notice_box.setStyleSheet(
                "QFrame{background:#fff4d8;border:1px solid #e0c887;border-radius:6px}"
                "QLabel{background:transparent;border:none;color:#5a4630;font-size:12px}"
                "QPushButton{padding:3px 8px;font-size:11px}"
            )
            notice_row = QHBoxLayout(notice_box)
            notice_row.setContentsMargins(9, 7, 9, 7)
            notice_row.setSpacing(8)
            rebuild_notice = QLabel(
                "<b>Update note:</b> If a dictionary was imported with an older YomiLens version "
                "and results look missing or broken, remove that dictionary and import/download it again "
                "so the index can be rebuilt with the latest parser.",
                notice_box,
            )
            rebuild_notice.setWordWrap(True)
            dismiss_notice = QPushButton("Don’t show again", notice_box)
            dismiss_notice.setFixedWidth(120)
            notice_row.addWidget(rebuild_notice, 1)
            notice_row.addWidget(dismiss_notice, 0)
            def hide_rebuild_notice():
                global DISMISS_REBUILD_NOTICE
                DISMISS_REBUILD_NOTICE = True
                _save_config()
                notice_box.hide()
            dismiss_notice.clicked.connect(hide_rebuild_notice)
            v.addWidget(notice_box)

        manage     = QPushButton("Manage Dictionaries", w)
        edit       = QPushButton("Edit Entries", w)
        import_zip = QPushButton("Import ZIP", w)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        for btn in (manage, edit, import_zip):
            btn.setMinimumHeight(32)
            btn_row.addWidget(btn, 1)   # stretch=1 → equal width
        v.addLayout(btn_row)

        def refresh_stats():
            self.stats_label.setText(_db_stats_text())
        def run_and_refresh(fn):
            fn(); refresh_stats()
        manage.clicked.connect(lambda: run_and_refresh(_action_db_manage))
        edit.clicked.connect(_action_db_edit_entries)
        import_zip.clicked.connect(lambda: run_and_refresh(_action_db_import_zip))

        export_btn = QPushButton("Export Yomichan.zip", w)
        export_btn.setMinimumHeight(32)
        export_btn.clicked.connect(_action_export_yomichan)
        v.addWidget(export_btn)

        # ── separator ─────────────────────────────────────────────────────
        sep = QFrame(w); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#ddd;margin-top:4px;margin-bottom:4px")
        v.addWidget(sep)

        # ── Download header row ───────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_lbl = QLabel("Download Dictionaries", w)
        hdr_font = QFont(); hdr_font.setBold(True); hdr_font.setPointSize(13)
        hdr_lbl.setFont(hdr_font)
        btn_refresh = QPushButton("↻ Refresh", w)
        btn_refresh.setFixedWidth(100)
        btn_refresh.setMinimumHeight(30)
        hdr_row.addWidget(hdr_lbl); hdr_row.addStretch(1); hdr_row.addWidget(btn_refresh)
        v.addLayout(hdr_row)

        # ── status label ──────────────────────────────────────────────────
        self._dl_status = QLabel("", w)
        self._dl_status.setWordWrap(True)
        self._dl_status.setStyleSheet("color:#444;font-size:12px")
        v.addWidget(self._dl_status)

        # ── scroll area for dictionary cards ─────────────────────────────
        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_inner = QWidget()
        self._dl_cards_layout = QVBoxLayout(scroll_inner)
        self._dl_cards_layout.setSpacing(8)
        self._dl_cards_layout.setContentsMargins(2, 4, 6, 4)
        self._dl_cards_layout.addStretch(1)
        scroll.setWidget(scroll_inner)
        v.addWidget(scroll, 1)

        # ── language display names ─────────────────────────────────────────
        LANG_LABELS = {
            "zh": "Chinese (中文)",
            "en": "English",
            "ja": "Japanese (日本語)",
            "ko": "Korean (한국어)",
            "fr": "French (Français)",
            "de": "German (Deutsch)",
            "vi": "Vietnamese (Tiếng Việt)",
        }

        self._dl_manifest = []

        def set_status(msg, color="#444"):
            self._dl_status.setText(msg)
            self._dl_status.setStyleSheet(f"color:{color};font-size:11px")

        def _clear_cards():
            layout = self._dl_cards_layout
            while layout.count() > 1:           # keep the trailing stretch
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        def _add_lang_header(lang):
            lbl = QLabel(LANG_LABELS.get(lang, lang.upper()), scroll_inner)
            font = QFont(); font.setBold(True); font.setPointSize(12)
            lbl.setFont(font)
            lbl.setStyleSheet("color:#333;margin-top:10px;margin-bottom:4px;padding-left:2px")
            self._dl_cards_layout.insertWidget(
                self._dl_cards_layout.count() - 1, lbl)

        def _is_in_db(title):
            try:
                if DB is None: _db_open()
                return DB.execute(
                    "SELECT 1 FROM source WHERE title=?", (title,)
                ).fetchone() is not None
            except Exception:
                return False

        def _add_card(entry):
            title   = entry.get("title", entry.get("id", "?"))
            desc    = entry.get("description", "")
            size_mb = entry.get("size_mb", "?")
            url     = entry.get("url", "")
            already = _is_in_db(title)

            card = QFrame(scroll_inner)
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setObjectName("dictCard")
            card.setStyleSheet(
                "QFrame#dictCard{border:1px solid #ddd;border-radius:6px;background:#fafafa}"
                "QFrame#dictCard QLabel{border:none;background:transparent}"
            )
            h = QHBoxLayout(card)
            h.setContentsMargins(14, 12, 14, 12)
            h.setSpacing(14)

            # left: text
            txt = QVBoxLayout()
            txt.setSpacing(4)
            title_lbl = QLabel(f"<b style='font-size:13px'>{title}</b>"
                               f"&nbsp;&nbsp;<span style='color:#999;font-size:12px'>"
                               f"{size_mb} MB</span>", card)
            title_lbl.setTextFormat(Qt.TextFormat.RichText)
            desc_lbl = QLabel(desc, card)
            desc_lbl.setStyleSheet("color:#666;font-size:12px;border:none")
            desc_lbl.setWordWrap(True)
            txt.addWidget(title_lbl)
            if desc:
                txt.addWidget(desc_lbl)
            h.addLayout(txt, 1)

            # right: stack (download btn | progress) + optional re-download link
            from aqt.qt import QStackedWidget
            stack = QStackedWidget(card)
            stack.setFixedWidth(130)
            stack.setFixedHeight(34)

            btn = QPushButton("⬇ Download", card)
            btn.setFixedHeight(34)

            prog_w = QWidget(card)
            prog_vl = QVBoxLayout(prog_w)
            prog_vl.setContentsMargins(0, 0, 0, 0); prog_vl.setSpacing(2)
            prog_pct = QLabel("0%", prog_w)
            prog_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prog_pct.setStyleSheet("font-size:11px;color:#555;border:none;background:transparent")
            prog = QProgressBar(prog_w)
            prog.setRange(0, 100); prog.setValue(0)
            prog.setTextVisible(False); prog.setFixedHeight(8)
            prog.setStyleSheet(
                "QProgressBar{border:1px solid #bbb;border-radius:4px;background:#eee}"
                "QProgressBar::chunk{background:#4a90d9;border-radius:4px}")
            prog_vl.addWidget(prog_pct); prog_vl.addWidget(prog); prog_vl.addStretch(1)

            stack.addWidget(btn)       # 0 = idle / installed
            stack.addWidget(prog_w)    # 1 = downloading
            stack.setCurrentIndex(0)

            # re-download link (hidden until installed)
            redl_btn = QPushButton("↺ Re-download", card)
            redl_btn.setFlat(True)
            redl_btn.setStyleSheet(
                "QPushButton{color:#888;font-size:11px;border:none;background:transparent;"
                "text-decoration:underline;padding:0}"
                "QPushButton:hover{color:#4a90d9}")
            redl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            redl_btn.setVisible(False)

            right = QVBoxLayout()
            right.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            right.setSpacing(4)
            right.addWidget(stack)
            right.addWidget(redl_btn, 0, Qt.AlignmentFlag.AlignHCenter)
            h.addLayout(right)

            self._dl_cards_layout.insertWidget(
                self._dl_cards_layout.count() - 1, card)

            # ── helpers ───────────────────────────────────────────────────
            _INSTALLED_SS = (
                "QPushButton{color:#080;font-weight:bold;"
                "border:1px solid #6c6;border-radius:4px;background:#f0fff0}"
            )

            def _set_installed():
                btn.setText("✓ Installed")
                btn.setEnabled(False)
                btn.setStyleSheet(_INSTALLED_SS)
                redl_btn.setVisible(True)

            def _set_idle():
                btn.setText("⬇ Download")
                btn.setEnabled(True)
                btn.setStyleSheet("")
                redl_btn.setVisible(False)

            if already:
                _set_installed()

            # ── download logic ────────────────────────────────────────────
            def _do_download():
                if not url:
                    set_status("No URL.", "#c00"); return
                stack.setCurrentIndex(1)
                prog.setValue(0); prog_pct.setText("0%")
                redl_btn.setVisible(False)
                set_status(f"Downloading {title}…", "#444")

                import urllib.request, tempfile

                def do_dl():
                    try:
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                        tmp_path = tmp.name; tmp.close()
                        with urllib.request.urlopen(url, timeout=60) as r:
                            total = int(r.headers.get("Content-Length") or 0)
                            done  = 0
                            with open(tmp_path, "wb") as f:
                                while True:
                                    buf = r.read(65536)
                                    if not buf: break
                                    f.write(buf); done += len(buf)
                                    if total > 0:
                                        pct = int(done * 50 / total)
                                        mw.taskman.run_on_main(
                                            lambda p=pct: (prog.setValue(p),
                                                           prog_pct.setText(f"{p}%")))
                        mw.taskman.run_on_main(lambda: (prog.setValue(50), prog_pct.setText("50%")))
                        return tmp_path, None
                    except Exception as e:
                        return None, str(e)

                def on_done(future):
                    try:
                        tmp_path, err = future.result()
                    except Exception as e:
                        tmp_path, err = None, str(e)
                    if err:
                        stack.setCurrentIndex(0)
                        _set_idle()
                        set_status(f"Download failed: {err}", "#c00"); return
                    try:
                        if DB is None: _db_open()
                        prog.setValue(50)
                        prog_pct.setText("50%")
                        set_status(f"Installing {title}…", "#444")
                        QApplication.processEvents()
                        def set_import_progress(pct, msg):
                            p = 50 + int(pct * 50 / 100)
                            prog.setValue(p)
                            prog_pct.setText(f"{p}%")
                            set_status(msg, "#444")
                            QApplication.processEvents()
                        import_yomichan_zip_to_db(tmp_path, title_override=title, progress_cb=set_import_progress)
                        try: os.remove(tmp_path)
                        except Exception: pass
                        stack.setCurrentIndex(0)
                        _set_installed()
                        set_status(f"✓ '{title}' installed!", "#080")
                        refresh_stats()
                        tooltip(f"Dictionary '{title}' installed!", period=2000)
                    except Exception as e:
                        stack.setCurrentIndex(0)
                        _set_idle()
                        set_status(f"Import failed: {e}", "#c00")

                mw.taskman.run_in_background(do_dl, on_done)

            btn.clicked.connect(lambda: _do_download())
            redl_btn.clicked.connect(lambda: _do_download())

        def on_refresh():
            btn_refresh.setEnabled(False)
            set_status("Fetching manifest…", "#888")
            _clear_cards()
            self._dl_manifest = []

            def fetch():
                import urllib.request
                try:
                    with urllib.request.urlopen(DICT_MANIFEST_URL, timeout=10) as r:
                        data = json.loads(r.read().decode())
                    return data, None
                except Exception as e:
                    return None, str(e)

            def on_done(future):
                try:
                    data, err = future.result()
                except Exception as e:
                    data, err = None, str(e)
                btn_refresh.setEnabled(True)
                if err:
                    set_status(f"Error: {err}", "#c00"); return
                self._dl_manifest = data or []
                if not self._dl_manifest:
                    set_status("No dictionaries found.", "#888"); return

                # group by lang
                groups = {}
                order  = []
                for entry in self._dl_manifest:
                    lang = entry.get("lang", "other")
                    if lang not in groups:
                        groups[lang] = []; order.append(lang)
                    groups[lang].append(entry)

                for lang in order:
                    _add_lang_header(lang)
                    for entry in groups[lang]:
                        _add_card(entry)

                n = len(self._dl_manifest)
                set_status(f"{n} {'dictionary' if n==1 else 'dictionaries'} available.", "#080")

            mw.taskman.run_in_background(fetch, on_done)

        btn_refresh.clicked.connect(on_refresh)
        on_refresh()   # auto-fetch khi mở tab
        return w

    def _build_download_tab_UNUSED(self):
        """REMOVED — download UI merged into Database tab."""
        from aqt.qt import QWidget, QProgressBar, QTextEdit, QScrollArea
        w = QWidget(self)
        v = QVBoxLayout(w)

        # --- header ---
        lbl = QLabel("Download dictionaries from the cloud.\nClick 'Refresh' to load the list.", w)
        lbl.setStyleSheet("color:#555;margin-bottom:4px")
        v.addWidget(lbl)

        # --- list widget ---
        self._dl_list = QListWidget(w)
        self._dl_list.setMinimumHeight(140)
        v.addWidget(self._dl_list, 1)

        # --- status label ---
        self._dl_status = QLabel("", w)
        self._dl_status.setWordWrap(True)
        self._dl_status.setStyleSheet("color:#444;font-size:11px;margin-top:4px")
        v.addWidget(self._dl_status)

        # --- progress bar ---
        self._dl_progress = QProgressBar(w)
        self._dl_progress.setRange(0, 100)
        self._dl_progress.setValue(0)
        self._dl_progress.setVisible(False)
        v.addWidget(self._dl_progress)

        # --- buttons ---
        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("↻ Refresh List", w)
        btn_download = QPushButton("⬇ Download & Install", w)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_download)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        # state
        self._dl_manifest = []   # list of dict from manifest JSON

        def set_status(msg, color="#444"):
            self._dl_status.setText(msg)
            self._dl_status.setStyleSheet(f"color:{color};font-size:11px;margin-top:4px")

        def on_refresh():
            btn_refresh.setEnabled(False)
            set_status("Fetching manifest…", "#888")
            self._dl_list.clear()
            self._dl_manifest = []

            def fetch():
                import urllib.request
                try:
                    with urllib.request.urlopen(DICT_MANIFEST_URL, timeout=10) as r:
                        data = json.loads(r.read().decode())
                    return data, None
                except Exception as e:
                    return None, str(e)

            def on_done(future):
                try:
                    data, err = future.result()
                except Exception as e:
                    data, err = None, str(e)
                btn_refresh.setEnabled(True)
                if err:
                    set_status(f"Error: {err}", "#c00")
                    return
                self._dl_manifest = data or []
                if not self._dl_manifest:
                    set_status("No dictionaries found in manifest.", "#888")
                    return
                for entry in self._dl_manifest:
                    title = entry.get("title", entry.get("id", "?"))
                    desc  = entry.get("description", "")
                    size  = entry.get("size_mb", "?")
                    item  = QListWidgetItem(f"{title}  ({size} MB)\n{desc}")
                    item.setData(32, entry)
                    self._dl_list.addItem(item)
                set_status(f"{len(self._dl_manifest)} dictionary/dictionaries available.", "#080")

            mw.taskman.run_in_background(fetch, on_done)

        def on_download():
            sel = self._dl_list.currentItem()
            if not sel:
                set_status("Select a dictionary first.", "#c60")
                return
            entry = sel.data(32)
            url   = entry.get("url", "")
            title = entry.get("title", entry.get("id", "dict"))
            if not url:
                set_status("No URL in manifest entry.", "#c00")
                return

            btn_download.setEnabled(False)
            btn_refresh.setEnabled(False)
            self._dl_progress.setVisible(True)
            self._dl_progress.setValue(0)
            set_status(f"Downloading {title}…", "#444")

            import urllib.request, tempfile

            def do_download():
                try:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                    tmp_path = tmp.name
                    tmp.close()

                    # stream download với progress
                    with urllib.request.urlopen(url, timeout=60) as r:
                        total = int(r.headers.get("Content-Length") or 0)
                        downloaded = 0
                        chunk = 65536
                        with open(tmp_path, "wb") as f:
                            while True:
                                buf = r.read(chunk)
                                if not buf:
                                    break
                                f.write(buf)
                                downloaded += len(buf)
                                if total > 0:
                                    pct = int(downloaded * 100 / total)
                                    mw.taskman.run_on_main(lambda p=pct: self._dl_progress.setValue(p))
                    return tmp_path, None
                except Exception as e:
                    return None, str(e)

            def on_dl_done(future):
                try:
                    tmp_path, err = future.result()
                except Exception as e:
                    tmp_path, err = None, str(e)
                btn_download.setEnabled(True)
                btn_refresh.setEnabled(True)
                self._dl_progress.setVisible(False)
                if err:
                    set_status(f"Download failed: {err}", "#c00")
                    return
                # import vào DB
                try:
                    if DB is None:
                        _db_open()
                    import_yomichan_zip_to_db(tmp_path)
                    try: os.remove(tmp_path)
                    except Exception: pass
                    set_status(f"✓ '{title}' installed successfully!", "#080")
                    tooltip(f"Dictionary '{title}' installed!", period=2000)
                    if hasattr(self, 'stats_label'):
                        self.stats_label.setText(_db_stats_text())
                except Exception as e:
                    set_status(f"Import failed: {e}", "#c00")

            mw.taskman.run_in_background(do_download, on_dl_done)

        btn_refresh.clicked.connect(on_refresh)
        btn_download.clicked.connect(on_download)

        # auto-fetch khi mở tab
        on_refresh()
        return w

    def _build_export_tab(self):
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Export the current DB sources as a Yomichan/Yomitan ZIP."))
        export_btn = QPushButton("Export Yomichan.zip", w)
        export_btn.clicked.connect(_action_export_yomichan)
        v.addWidget(export_btn)
        v.addStretch(1)
        return w

def _action_yomi_settings():
    dlg = _YomiSettingsDialog(mw)
    dlg.exec()

# --- Tools > YomiLens Settings ---
def build_yomi_menu():
    if getattr(mw, "_yomi_menu_built", False):
        return
    a = QAction("YomiLens Settings…", mw)
    a.triggered.connect(_action_yomi_settings)
    mw.form.menuTools.addAction(a)

    mw._yomi_menu_built = True





# --------------------------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------------------------

def on_profile_opened():
    _load_config()  # đọc yomi_config.json

    # Mở DB sớm để có DB_MODE & đoán 'auto'
    try:
        _db_open()
    except Exception:
        pass

    if LANG_PROFILE == "auto":
        try:
            lang = _guess_lang_from_sources()
            if lang:
                globals()["LANG_PROFILE"] = lang
        except Exception:
            pass

    # (tùy chọn) chỉ build RAM khi KHÔNG có DB
    if not DB_MODE:
        _load_sources()
        _reload_all_sources()

    _start_server()
    _nuke(mw.web)
    build_yomi_menu()

    gui_hooks.reviewer_did_show_question.append(_on_q)
    gui_hooks.reviewer_did_show_answer.append(_on_a)
    gui_hooks.state_did_change.append(_on_state_change)



# ✅ NEW: đảm bảo chạy trên luồng chính (fix cho Anki >= 25.09.02)
from aqt import mw

def _run_on_profile_opened():
    mw.taskman.run_on_main(on_profile_opened)

gui_hooks.profile_did_open.append(_run_on_profile_opened)



# === Yomichan Export ===
def _action_export_yomichan():
    try:
        if DB is None:
            _db_open()
        # fetch sources
        cur = DB.execute("SELECT title, enabled FROM source ORDER BY title ASC")
        sources = [(r[0], r[1]) for r in cur.fetchall()]
    except Exception as e:
        tooltip(f"Error reading sources from DB: {e}", period=3000)
        return

    # Simple selection dialog
    from aqt.qt import QAbstractItemView
    dlg = QDialog(mw); dlg.setWindowTitle("Export: Yomichan.zip")
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel("Select sources to export (default: enabled sources only)."))
    lst = QListWidget(dlg); lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
    for title, enabled in sources:
        it = QListWidgetItem(title); lst.addItem(it)
        if enabled: it.setSelected(True)
    v.addWidget(lst)

    from aqt.qt import QSpinBox, QLineEdit
    hb = QHBoxLayout(); v.addLayout(hb)
    hb.addWidget(QLabel("Chunk size (entries/file):"))
    sp = QSpinBox(dlg); sp.setMinimum(1000); sp.setMaximum(200000); sp.setSingleStep(1000); sp.setValue(20000)
    hb.addWidget(sp)
    hb2 = QHBoxLayout(); v.addLayout(hb2)
    hb2.addWidget(QLabel("Title:"))
    title_edit = QLineEdit(dlg); title_edit.setPlaceholderText("Exported Dictionary")
    hb2.addWidget(title_edit)

    btns = QHBoxLayout(); v.addLayout(btns)
    ok = QPushButton("Choose save location…", dlg); btns.addWidget(ok)
    cancel = QPushButton("Cancel", dlg); btns.addWidget(cancel)

    def on_cancel(): dlg.reject()
    cancel.clicked.connect(on_cancel)

    def on_ok():
        from aqt.qt import QFileDialog
        path, _ = QFileDialog.getSaveFileName(dlg, "Save Yomichan ZIP", "", "ZIP Files (*.zip)")
        if not path: return
        selected = [i.text() for i in lst.selectedItems()]
        chunk_size = sp.value()
        title_val = title_edit.text().strip() or None
        try:
            from . import yomi_export
            out_path, n = yomi_export.write_yomichan_zip(path, ADDON_DIR, selected_titles=selected, chunk_size=chunk_size, title=title_val, author="Anki Export", description=None)
            tooltip(f"Exported {n} entries → {out_path}", period=3000)
        except Exception as e:
            tooltip(f"Export error: {e}", period=4000)
        dlg.accept()
    ok.clicked.connect(on_ok)
    dlg.exec()



# === DB Editor: search & edit entries ===
from aqt.qt import (
    QWidget, QLineEdit, QTextEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHBoxLayout, QVBoxLayout, QSplitter, QSizePolicy,
    QDialog, Qt, QAbstractItemView   # ⬅️ thêm QDialog và Qt ở đây
)

_QSIZE_EXPANDING = getattr(getattr(QSizePolicy, "Policy", QSizePolicy), "Expanding")
_NO_EDIT_TRIGGERS = getattr(
    getattr(QAbstractItemView, "EditTrigger", QAbstractItemView),
    "NoEditTriggers",
)
_QT_GRAY = getattr(getattr(Qt, "GlobalColor", Qt), "gray")
_QT_DARK_BLUE = getattr(getattr(Qt, "GlobalColor", Qt), "darkBlue")

class _DbEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Yomi – Edit Dictionary Entries")
        self.resize(900, 560)

        # State
        self.rows = []              # list of dict rows from DB
        self.row_index_by_id = {}   # rowid -> row index
        self.changes = {}           # rowid -> {"term","reading","gloss","source_id"}
        self.deletions = set()      # rowid pending delete

        # Top controls
        top = QHBoxLayout()
        self.q = QLineEdit(self); self.q.setPlaceholderText("Search keyword (term / reading / gloss)…")
        self.src = QComboBox(self); self._load_sources_combo()
        self.btnSearch = QPushButton("Search", self)
        self.btnSearch.clicked.connect(self._on_search)
        top.addWidget(QLabel("Keyword:")); top.addWidget(self.q, 5)
        top.addWidget(QLabel("Dictionary:")); top.addWidget(self.src, 2)
        top.addWidget(self.btnSearch)

        # Splitter
        split = QSplitter(self); split.setSizePolicy(_QSIZE_EXPANDING, _QSIZE_EXPANDING)

        # Left: table
        leftw = QWidget(self); left = QVBoxLayout(leftw)
        self.tbl = QTableWidget(self); self.tbl.setColumnCount(4)
        self.tbl.setHorizontalHeaderLabels(["Dictionary", "Term", "Reading", "Gloss"])
        self.tbl.setEditTriggers(_NO_EDIT_TRIGGERS)
        self.tbl.itemSelectionChanged.connect(self._on_pick_row)
        left.addWidget(self.tbl)

        # Buttons under table
        bb = QHBoxLayout()
        self.btnUpdate = QPushButton("Update", self); self.btnUpdate.clicked.connect(self._on_update_clicked)
        self.btnDelete = QPushButton("Delete", self); self.btnDelete.clicked.connect(self._on_delete_clicked)
        self.btnUndo = QPushButton("Undo", self); self.btnUndo.clicked.connect(self._on_undo_clicked)
        self.btnSaveAll = QPushButton("Save", self); self.btnSaveAll.clicked.connect(self._on_save_clicked)
        bb.addWidget(self.btnUpdate); bb.addWidget(self.btnDelete); bb.addWidget(self.btnUndo); bb.addStretch(1); bb.addWidget(self.btnSaveAll)
        left.addLayout(bb)

        # Right: editor
        rightw = QWidget(self); right = QVBoxLayout(rightw)
        self.eSrc = QComboBox(self); self._load_sources_combo_editor()
        self.eTerm = QLineEdit(self)
        self.eReading = QLineEdit(self)
        self.eGloss = QTextEdit(self); self.eGloss.setAcceptRichText(False)
        right.addWidget(QLabel("Dictionary:")); right.addWidget(self.eSrc, 2)
        right.addWidget(QLabel("Term:")); right.addWidget(self.eTerm)
        right.addWidget(QLabel("Reading:")); right.addWidget(self.eReading)
        right.addWidget(QLabel("Gloss:")); right.addWidget(self.eGloss, 2)
        right.addStretch(1)

        split.addWidget(leftw); split.addWidget(rightw); split.setStretchFactor(0, 2); split.setStretchFactor(1, 3)

        # Main layout
        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(split)

        # Initial
        self._on_search()

    def _load_sources_combo(self, target=None):
        if DB is None: _db_open()
        try:
            cur = DB.execute("SELECT id, title FROM source ORDER BY title ASC")
            items = cur.fetchall()
        except Exception as e:
            items = []
        combo = target or self.src
        combo.clear()
        combo.addItem("All sources", 0)
        for sid, title in items:
            combo.addItem(title, sid)
            
    def _load_sources_combo_editor(self):
        """Load dictionaries cho combobox EDITOR (không có 'All sources')."""
        if DB is None: _db_open()
        try:
            cur = DB.execute("SELECT id, title FROM source ORDER BY priority ASC, id ASC")
            items = cur.fetchall()
        except Exception:
            items = []
        self.eSrc.clear()
        for sid, title in items:
            self.eSrc.addItem(str(title), int(sid))
            
    def _on_search(self):
        kw = (self.q.text() or "").strip()
        src_id = self.src.currentData()
        if DB is None: _db_open()
        sql = """SELECT t.rowid, s.title, t.term, t.reading, t.gloss, t.source_id
                 FROM term t JOIN source s ON s.id=t.source_id
                 WHERE 1=1 """
        args = []
        if kw:
            sql += " AND (t.term LIKE ? OR IFNULL(t.reading,'') LIKE ? OR IFNULL(t.gloss,'') LIKE ?)"
            like = f"%{kw}%"
            args += [like, like, like]
        if src_id:
            sql += " AND t.source_id=?"
            args.append(src_id)
        sql += " ORDER BY s.title, t.term LIMIT 1000"
        cur = DB.execute(sql, args)
        self.rows = [{"rowid":r[0],"source":r[1],"term":r[2] or "","reading":r[3] or "","gloss":r[4] or "","source_id":r[5]} for r in cur.fetchall()]
        self.row_index_by_id = {r["rowid"]: i for i,r in enumerate(self.rows)}
        self._fill_table()

    def _fill_table(self):
        self.tbl.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            ch = self.changes.get(r["rowid"])
            is_del = r["rowid"] in self.deletions
            vals = [
                r["source"],
                r["term"],
                r["reading"],
                (r["gloss"][:120] + ("…" if len(r["gloss"]) > 120 else "")),
            ]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                from aqt.qt import QColor
                if is_del:
                    it.setForeground(_QT_GRAY)
                    it.setBackground(QColor(255, 230, 230))  # light red
                elif ch:
                    it.setForeground(_QT_DARK_BLUE)
                    it.setBackground(QColor(255, 255, 200))  # light yellow
                self.tbl.setItem(i, c, it)


    def _on_pick_row(self):
        items = self.tbl.selectedItems()
        if not items:
            return
        row = items[0].row()
        r = self.rows[row]
        # Lấy giá trị đang pending nếu có, ngược lại lấy từ self.rows
        cur = self.changes.get(r["rowid"], r)

        # Đặt dropdown Dictionary theo source_id hiện tại
        idx = self._combo_index_by_data(self.eSrc, cur.get("source_id"))
        if idx >= 0:
            self.eSrc.setCurrentIndex(idx)

        # Đổ các field còn lại
        self.eTerm.setText(cur.get("term", "") or "")
        self.eReading.setText(cur.get("reading", "") or "")
        self.eGloss.setPlainText(cur.get("gloss", "") or "")


    def _combo_index_by_data(self, combo, data):
        """Tìm index theo itemData, ép kiểu int để tránh lệch kiểu."""
        try:
            want = int(data) if data is not None else None
        except Exception:
            want = data
        for i in range(combo.count()):
            d = combo.itemData(i)
            try:
                d = int(d) if d is not None else None
            except Exception:
                pass
            if d == want:
                return i
        return -1

    def _current_selected_rowid(self):
        items = self.tbl.selectedItems()
        if not items: return None
        row = items[0].row()
        return self.rows[row]["rowid"]

    def _on_update_clicked(self):
        rid = self._current_selected_rowid()
        if not rid:
            return
        # Lấy source_id từ dropdown; nếu None thì giữ nguyên của dòng gốc
        new_src_id = self.eSrc.currentData()
        if new_src_id is None:
            new_src_id = self.rows[self.row_index_by_id[rid]]["source_id"]

        # Lưu vào bộ nhớ pending changes (chưa ghi DB)
        self.changes[rid] = {
            "term": self.eTerm.text().strip(),
            "reading": self.eReading.text().strip(),
            "gloss": self.eGloss.toPlainText().strip(),
            "source_id": int(new_src_id),
        }
        # Vẽ lại bảng để tô màu dòng pending
        self._fill_table()
        tooltip("Updated (pending). Click Save to write to DB.", period=1500)


    def _on_delete_clicked(self):
        rid = self._current_selected_rowid()
        if not rid:
            return
        if rid in self.deletions:
            self.deletions.remove(rid)
            tooltip("Unmarked delete.", period=1000)
        else:
            self.deletions.add(rid)
            # Nếu đã đánh dấu xóa, bỏ pending update của dòng đó (nếu có)
            self.changes.pop(rid, None)
            tooltip("Marked for delete (pending). Click Save to apply.", period=1600)
        self._fill_table()


    def _on_undo_clicked(self):
        rid = self._current_selected_rowid()
        if not rid:
            return
        # Bỏ pending change và pending delete của dòng này
        self.changes.pop(rid, None)
        if rid in self.deletions:
            self.deletions.remove(rid)

        # Tải lại giá trị gốc từ self.rows (hoặc DB nếu bạn muốn)
        # Ở đây dùng self.rows vì chưa Save thì DB chưa thay đổi.
        r = self.rows[self.row_index_by_id[rid]]
        idx = self._combo_index_by_data(self.eSrc, r["source_id"])
        if idx >= 0:
            self.eSrc.setCurrentIndex(idx)
        self.eTerm.setText(r["term"])
        self.eReading.setText(r["reading"])
        self.eGloss.setPlainText(r["gloss"])

        self._fill_table()
        # Re-select row
        self.tbl.selectRow(self.row_index_by_id[rid])
        tooltip("Undone pending changes.", period=1000)


    def _on_save_clicked(self):
        if DB is None:
            _db_open()
        try:
            DB.execute("BEGIN")
            # Apply updates
            for rid, ch in self.changes.items():
                DB.execute(
                    "UPDATE term SET term=?, reading=?, gloss=?, source_id=? WHERE rowid=?",
                    (ch["term"], ch["reading"], ch["gloss"], ch["source_id"], rid)
                )
            # Apply deletions
            for rid in self.deletions:
                DB.execute("DELETE FROM term WHERE rowid=?", (rid,))
            DB.commit()

            # Cập nhật model nội bộ từ DB (đảm bảo đồng bộ)
            for rid in list(self.changes.keys()):
                cur = DB.execute(
                    "SELECT s.title, t.term, t.reading, t.gloss, t.source_id "
                    "FROM term t JOIN source s ON s.id=t.source_id WHERE t.rowid=?",
                    (rid,)
                ).fetchone()
                if cur:
                    i = self.row_index_by_id.get(rid)
                    if i is not None:
                        title, term, reading, gloss, src_id = cur
                        self.rows[i].update({
                            "source": title,
                            "term": term or "",
                            "reading": reading or "",
                            "gloss": gloss or "",
                            "source_id": src_id,
                        })

            # Clear pending & refresh
            self.changes.clear()
            self.deletions.clear()
            _db_recalc_max_len()
            self._fill_table()
            tooltip("Saved to DB.", period=1200)
        except Exception as e:
            DB.rollback()
            tooltip(f"Save error: {e}", period=3000)


def _action_db_edit_entries():
    if DB is None: _db_open()
    dlg = _DbEditorDialog(mw)
    dlg.exec()
