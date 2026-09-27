# -*- coding: utf-8 -*-
# Anki 2.1.49 – Hanzi Popup via localhost (deck-safe) + Native Yomichan/Yomitan dictionaries
from aqt import mw, gui_hooks
from .term_metadata import ensure_schema as _metadata_schema, import_bank as _metadata_import, render_metadata as _metadata_render
from aqt.utils import tooltip
from aqt.qt import QAction, QFileDialog, QDesktopServices, QUrl, Qt, QFrame, QWidget, QLineEdit, QEvent
import sqlite3, hashlib, time
from aqt.qt import QDialog, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QVBoxLayout, QLabel, QMessageBox, QProgressDialog, QApplication
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
except Exception:
    QWebEngineView = QWebEnginePage = QWebEngineProfile = QWebEngineSettings = None

from .deinflect import candidates as df_candidates, keep_char as df_keep_char, pick_seed as df_pick_seed
from .deinflect import ALL_LANGS as DEINFLECT_ALL_LANGS, ALL_LANG_CODES as DEINFLECT_LANG_CODES, INFLECTED_LANGS as DEINFLECT_INFLECTED_LANGS, LATIN_LANGS as DEINFLECT_LATIN_LANGS
from .deinflect import SPACE_WORD_LANGS as DEINFLECT_SPACE_WORD_LANGS
import os, re, json, zipfile, threading, urllib.parse, http.server, socketserver, unicodedata, io, mimetypes
from collections import OrderedDict

SCAN_CACHE = OrderedDict()
SCAN_CACHE_LOCK = threading.RLock()
SCAN_CACHE_LIMIT = 1200

ADDON_DIR       = os.path.dirname(__file__)
INJECT_JS_PATH  = os.path.join(ADDON_DIR, "inject.js")
# đầu file (gần các hằng số khác)
POPUP_TPL_PATH = os.path.join(ADDON_DIR, "popup_iframe.html")

USER_FILES_DIR = os.path.join(ADDON_DIR, "user_files")

def _ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _anki_cloze_blank(term):
    chars = [ch for ch in (term or "") if not ch.isspace()]
    letters = [ch for ch in chars if ch.isalpha()]
    is_latin = bool(chars) and (
        all(ch.isascii() for ch in chars)
        or (bool(letters) and all("LATIN" in unicodedata.name(ch, "") for ch in letters))
    )
    marker = "_" if is_latin else "＿"
    return "「" + " ".join(marker for _ in range(max(1, len(chars)))) + " 」"

def _anki_native_cloze(term):
    escaped = (
        str(term or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return "{{c1::" + escaped + "}}"

def _anki_replace_cloze(value, term, blank, remove_html=False):
    """Replace visible term text while keeping the blank unformatted."""
    value = value or ""
    if remove_html:
        return re.sub(r"<[^>]+>", "", value).replace(term, blank)
    if not term:
        return value

    void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    def is_cloze_formatting(name, raw):
        if name in {"b", "strong", "i", "em", "u"}:
            return True
        if name != "span":
            return False
        style_match = re.search(
            r"""\bstyle\s*=\s*(["'])(.*?)\1""", raw, flags=re.IGNORECASE | re.DOTALL
        )
        if not style_match:
            return False
        style = style_match.group(2)
        return bool(
            re.search(r"font-weight\s*:\s*(?:bold|[6-9]00)\b", style, re.IGNORECASE)
            or re.search(r"font-style\s*:\s*(?:italic|oblique)\b", style, re.IGNORECASE)
            or re.search(
                r"text-decoration(?:-line)?\s*:[^;]*\bunderline\b",
                style,
                re.IGNORECASE,
            )
        )

    stack = []
    output = []
    for token in re.split(r"(<[^>]+>)", value):
        if not token:
            continue
        if token.startswith("<"):
            output.append(token)
            closing = re.match(r"<\s*/\s*([\w:-]+)", token)
            if closing:
                name = closing.group(1).lower()
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] == name:
                        del stack[index:]
                        break
                continue
            opening = re.match(r"<\s*([\w:-]+)", token)
            if opening:
                name = opening.group(1).lower()
                if name not in void_tags and not token.rstrip().endswith("/>"):
                    stack.append((name, token, is_cloze_formatting(name, token)))
            continue

        format_index = next(
            (index for index, (_name, _raw, formatted) in enumerate(stack) if formatted),
            None,
        )
        if term in token and format_index is not None:
            active = stack[format_index:]
            close_markup = "".join(
                f"</{name}>" for name, _raw, _formatted in reversed(active)
            )
            reopen_markup = "".join(raw for _name, raw, _formatted in active)
            token = token.replace(term, close_markup + blank + reopen_markup)
        else:
            token = token.replace(term, blank)
        output.append(token)

    result = "".join(output)
    empty_format = r"<(b|strong|i|em|u)(?:\s[^>]*)?>\s*</\1>"
    empty_span = r"<span(?:\s[^>]*)?>\s*</span>"
    while True:
        cleaned = re.sub(empty_format, "", result, flags=re.IGNORECASE)
        cleaned = re.sub(
            empty_span,
            lambda match: "" if is_cloze_formatting("span", match.group(0)) else match.group(0),
            cleaned,
            flags=re.IGNORECASE,
        )
        if cleaned == result:
            return cleaned
        result = cleaned

def _detect_profile_folder():
    try:
        col = getattr(mw, "col", None)
        col_path = getattr(col, "path", "") if col else ""
        if col_path:
            return os.path.dirname(col_path)
    except Exception:
        pass
    try:
        base = mw.pm.profileFolder()
        if base:
            return base
    except Exception:
        pass
    try:
        anki2_dir = os.path.dirname(os.path.dirname(ADDON_DIR))
        profiles = []
        for name in os.listdir(anki2_dir):
            p = os.path.join(anki2_dir, name)
            col = os.path.join(p, "collection.anki2")
            if os.path.isdir(p) and os.path.exists(col):
                profiles.append((os.path.getmtime(col), p))
        if profiles:
            profiles.sort(reverse=True)
            return profiles[0][1]
    except Exception:
        pass
    return ""

def _profile_data_dir():
    base = _detect_profile_folder()
    path = os.path.join(base, "YomiLens") if base else USER_FILES_DIR
    _ensure_dir(path)
    return path

DATA_DIR = _profile_data_dir()

def _migrate_file_once(old_path, new_path):
    if os.path.exists(old_path) and not os.path.exists(new_path):
        _ensure_dir(os.path.dirname(new_path))
        try:
            os.replace(old_path, new_path)
            return True
        except Exception:
            try:
                import shutil
                shutil.copy2(old_path, new_path)
                return True
            except Exception:
                return False
    return False

def _migrate_db_once(old_base, new_base):
    moved = _migrate_file_once(old_base, new_base)
    for ext in ("-wal", "-shm"):
        _migrate_file_once(old_base + ext, new_base + ext)
    return moved

# Keep user data outside the add-on folder. Windows can lock SQLite files, which
# prevents Anki from renaming add-on user_files during updates.
_old_root_db_path = os.path.join(ADDON_DIR, "yomi_index.db")
_old_user_db_path = os.path.join(USER_FILES_DIR, "yomi_index.db")
_new_db_path = os.path.join(DATA_DIR, "yomi_index.db")
_migrate_db_once(_old_root_db_path, _new_db_path)
_migrate_db_once(_old_user_db_path, _new_db_path)

try:
    if os.path.isdir(USER_FILES_DIR):
        leftovers = [name for name in os.listdir(USER_FILES_DIR) if name != ".placeholder"]
        if not leftovers:
            placeholder = os.path.join(USER_FILES_DIR, ".placeholder")
            if os.path.exists(placeholder):
                try:
                    os.remove(placeholder)
                except Exception:
                    pass
            os.rmdir(USER_FILES_DIR)
except Exception:
    pass

DB_PATH   = _new_db_path
DB        = None          # sqlite3.Connection hoặc None
DB_MODE   = False         # True nếu đang dùng DB để tra
DB_SIG    = None          # detects external DB/WAL changes while Anki is running

CONFIG_PATH  = os.path.join(DATA_DIR, "yomi_config.json")
_migrate_file_once(os.path.join(ADDON_DIR, "yomi_config.json"), CONFIG_PATH)
_migrate_file_once(os.path.join(USER_FILES_DIR, "yomi_config.json"), CONFIG_PATH)
SOURCES_PATH = os.path.join(DATA_DIR, "yomi_sources.json")
_migrate_file_once(os.path.join(ADDON_DIR, "yomi_sources.json"), SOURCES_PATH)
_migrate_file_once(os.path.join(USER_FILES_DIR, "yomi_sources.json"), SOURCES_PATH)

def _refresh_data_paths():
    global DATA_DIR, DB_PATH, CONFIG_PATH, SOURCES_PATH
    new_dir = _profile_data_dir()
    if new_dir == DATA_DIR:
        return
    old_db = DB_PATH
    old_cfg = CONFIG_PATH
    old_sources = SOURCES_PATH
    DATA_DIR = new_dir
    DB_PATH = os.path.join(DATA_DIR, "yomi_index.db")
    CONFIG_PATH = os.path.join(DATA_DIR, "yomi_config.json")
    SOURCES_PATH = os.path.join(DATA_DIR, "yomi_sources.json")
    _migrate_db_once(old_db, DB_PATH)
    _migrate_file_once(old_cfg, CONFIG_PATH)
    _migrate_file_once(old_sources, SOURCES_PATH)
    _migrate_db_once(os.path.join(USER_FILES_DIR, "yomi_index.db"), DB_PATH)
    _migrate_file_once(os.path.join(USER_FILES_DIR, "yomi_config.json"), CONFIG_PATH)
    _migrate_file_once(os.path.join(USER_FILES_DIR, "yomi_sources.json"), SOURCES_PATH)

LANG_PROFILE = "auto"
HANZI_WRITER = False
PREFER_KANJI_ON_CLICK = True
POPUP_LANGS = ["zh", "ja", "en"]
POPUP_TRIGGER_MOD = "none"
POPUP_SUBLOOKUP_MODE = "reuse"
HOVER_SHIFT_MODE = False
POPUP_THEME = "default"
CUSTOM_CSS = ""
CSS_PRESETS = {}
PITCH_STYLE = "graph"
POPUP_WIDTH = 380
POPUP_HEIGHT = 350
DISMISS_REBUILD_NOTICE = False
WHATS_NEW_VERSION = "2026.09-metadata-export-css"
DISMISSED_WHATS_NEW_VERSION = ""
YOUGLISH_SOURCE_LANGS = {}
GOOGLE_SOURCE_LANGS = {}
GOOGLE_AUDIO_SOURCE_LANGS = {}
WEB_AUDIO_ENABLED = False
WEB_YG_ENABLED = False
WEB_IMG_ENABLED = False
WEB_AUTO_SPEAK_ENABLED = False
ANKI_DECK = ""
ANKI_NOTE_TYPE = ""
ANKI_FIELD_MAP = {}
ANKI_REMOVE_HTML = False
ANKI_CLOZE_TERM = False

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
YOUGLISH_LANGUAGES = [
    ("Auto (guess from dictionary)", "auto", "en"),
    ("Arabic", "arabic", "ar"),
    ("Chinese", "chinese", "zh-CN"),
    ("Dutch", "dutch", "nl"),
    ("English", "english", "en"),
    ("French", "french", "fr"),
    ("German", "german", "de"),
    ("Greek", "greek", "el"),
    ("Hebrew", "hebrew", "he"),
    ("Hindi", "hindi", "hi"),
    ("Indonesian", "indonesian", "id"),
    ("Italian", "italian", "it"),
    ("Japanese", "japanese", "ja"),
    ("Korean", "korean", "ko"),
    ("Persian", "persian", "fa"),
    ("Polish", "polish", "pl"),
    ("Portuguese", "portuguese", "pt"),
    ("Romanian", "romanian", "ro"),
    ("Russian", "russian", "ru"),
    ("Spanish", "spanish", "es"),
    ("Swedish", "swedish", "sv"),
    ("Thai", "thai", "th"),
    ("Turkish", "turkish", "tr"),
    ("Ukrainian", "ukrainian", "uk"),
    ("Vietnamese", "vietnamese", "vi"),
]
YOUGLISH_LANG_BY_SLUG = {slug: (label, google_hl) for label, slug, google_hl in YOUGLISH_LANGUAGES}
GOOGLE_LANGUAGES = [
    ("Auto (guess from dictionary)", "auto", "en"),
    ("Arabic", "ar", "ar"),
    ("Chinese (Simplified)", "zh-CN", "zh-CN"),
    ("Chinese (Traditional)", "zh-TW", "zh-TW"),
    ("Dutch", "nl", "nl"),
    ("English", "en", "en"),
    ("French", "fr", "fr"),
    ("German", "de", "de"),
    ("Greek", "el", "el"),
    ("Hebrew", "he", "he"),
    ("Hindi", "hi", "hi"),
    ("Indonesian", "id", "id"),
    ("Italian", "it", "it"),
    ("Japanese", "ja", "ja"),
    ("Korean", "ko", "ko"),
    ("Persian", "fa", "fa"),
    ("Polish", "pl", "pl"),
    ("Portuguese", "pt", "pt"),
    ("Romanian", "ro", "ro"),
    ("Russian", "ru", "ru"),
    ("Spanish", "es", "es"),
    ("Swedish", "sv", "sv"),
    ("Thai", "th", "th"),
    ("Turkish", "tr", "tr"),
    ("Ukrainian", "uk", "uk"),
    ("Vietnamese", "vi", "vi"),
    ("Cantonese", "yue", "yue"),
]
GOOGLE_LANG_BY_CODE = {code: (label, google_hl) for label, code, google_hl in GOOGLE_LANGUAGES}
GOOGLE_AUDIO_VOICES = [
    ("Auto (same as Google/IMG)", "auto"),
    ("Arabic", "ar"),
    ("Chinese Mandarin (Mainland)", "zh-CN"),
    ("Chinese Mandarin (Taiwan)", "zh-TW"),
    ("Cantonese", "yue"),
    ("Dutch", "nl"),
    ("English (US)", "en-US"),
    ("English (UK)", "en-GB"),
    ("English (Australia)", "en-AU"),
    ("English (India)", "en-IN"),
    ("French (France)", "fr-FR"),
    ("French (Canada)", "fr-CA"),
    ("German", "de-DE"),
    ("Greek", "el-GR"),
    ("Hebrew", "he"),
    ("Hindi", "hi-IN"),
    ("Indonesian", "id-ID"),
    ("Italian", "it-IT"),
    ("Japanese", "ja-JP"),
    ("Korean", "ko-KR"),
    ("Persian", "fa"),
    ("Polish", "pl-PL"),
    ("Portuguese (Brazil)", "pt-BR"),
    ("Portuguese (Portugal)", "pt-PT"),
    ("Romanian", "ro-RO"),
    ("Russian", "ru-RU"),
    ("Spanish (Spain)", "es-ES"),
    ("Spanish (Mexico)", "es-MX"),
    ("Spanish (US)", "es-US"),
    ("Swedish", "sv-SE"),
    ("Thai", "th-TH"),
    ("Turkish", "tr-TR"),
    ("Ukrainian", "uk-UA"),
    ("Vietnamese", "vi-VN"),
]
GOOGLE_AUDIO_VOICE_CODES = {code for _label, code in GOOGLE_AUDIO_VOICES}

def _load_config():
    global LANG_PROFILE, HANZI_WRITER, PREFER_KANJI_ON_CLICK, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE, HOVER_SHIFT_MODE, POPUP_THEME, POPUP_WIDTH, POPUP_HEIGHT, DISMISS_REBUILD_NOTICE, DISMISSED_WHATS_NEW_VERSION, YOUGLISH_SOURCE_LANGS, GOOGLE_SOURCE_LANGS, GOOGLE_AUDIO_SOURCE_LANGS
    global WEB_AUDIO_ENABLED, WEB_YG_ENABLED, WEB_IMG_ENABLED, WEB_AUTO_SPEAK_ENABLED
    global ANKI_DECK, ANKI_NOTE_TYPE, ANKI_FIELD_MAP, ANKI_REMOVE_HTML, ANKI_CLOZE_TERM
    _refresh_data_paths()
    try:
        cfg = json.loads(_read_text(CONFIG_PATH))
        LANG_PROFILE = cfg.get('lang_profile', 'auto')
        HANZI_WRITER = bool(cfg.get('hanzi_writer', False))
        PREFER_KANJI_ON_CLICK = bool(cfg.get('prefer_kanji_on_click', True))
        POPUP_TRIGGER_MOD = cfg.get('popup_trigger_mod', 'none')
        if POPUP_TRIGGER_MOD not in ("none", "alt", "ctrl", "shift", "meta"):
            POPUP_TRIGGER_MOD = "none"
        POPUP_SUBLOOKUP_MODE = cfg.get('popup_sublookup_mode', 'reuse')
        if POPUP_SUBLOOKUP_MODE not in ("reuse", "nested", "disabled"):
            POPUP_SUBLOOKUP_MODE = "reuse"
        HOVER_SHIFT_MODE = bool(cfg.get('hover_shift_mode', False))
        global CUSTOM_CSS, CSS_PRESETS, PITCH_STYLE
        PITCH_STYLE = cfg.get('pitch_style', 'graph')
        if PITCH_STYLE not in ('graph', 'compact'):
            PITCH_STYLE = 'graph'
        CUSTOM_CSS = str(cfg.get('custom_css', '') or '')
        raw_css_presets = cfg.get('css_presets', {})
        if isinstance(raw_css_presets, dict):
            CSS_PRESETS = {
                str(name).strip()[:80]: str(css)
                for name, css in raw_css_presets.items()
                if str(name).strip() and isinstance(css, str)
            }
        else:
            CSS_PRESETS = {}
        POPUP_THEME = cfg.get('popup_theme', 'default')
        if POPUP_THEME not in (
            "default", "aux_bluets", "emerald_spring", "showa_matcha", "sakura_city_pop",
            "sakura_night", "lotus_noir", "violet_circuit",
        ):
            POPUP_THEME = "default"
        try:
            POPUP_WIDTH = int(cfg.get('popup_width', 380))
            if POPUP_WIDTH < 200 or POPUP_WIDTH > 1200:
                POPUP_WIDTH = 380
        except Exception:
            POPUP_WIDTH = 380
        try:
            POPUP_HEIGHT = int(cfg.get('popup_height', 350))
            if POPUP_HEIGHT < 200 or POPUP_HEIGHT > 1200:
                POPUP_HEIGHT = 350
        except Exception:
            POPUP_HEIGHT = 350
        DISMISS_REBUILD_NOTICE = bool(cfg.get('dismiss_rebuild_notice', False))
        DISMISSED_WHATS_NEW_VERSION = str(cfg.get('dismissed_whats_new_version', ''))
        langs = cfg.get('popup_langs')
        if isinstance(langs, list):
            POPUP_LANGS = [x for x in langs if x in DEINFLECT_LANG_CODES] or ["zh", "ja", "en"]
        else:
            POPUP_LANGS = ["zh", "ja", "en"] if LANG_PROFILE == "auto" else [LANG_PROFILE]
        source_langs = cfg.get("youglish_source_langs")
        if isinstance(source_langs, dict):
            YOUGLISH_SOURCE_LANGS = {
                str(k): str(v)
                for k, v in source_langs.items()
                if str(v) in YOUGLISH_LANG_BY_SLUG
            }
        else:
            YOUGLISH_SOURCE_LANGS = {}
        google_source_langs = cfg.get("google_source_langs")
        if isinstance(google_source_langs, dict):
            GOOGLE_SOURCE_LANGS = {
                str(k): str(v)
                for k, v in google_source_langs.items()
                if str(v) in GOOGLE_LANG_BY_CODE
            }
        else:
            GOOGLE_SOURCE_LANGS = {
                str(k): YOUGLISH_LANG_BY_SLUG[str(v)][1]
                for k, v in YOUGLISH_SOURCE_LANGS.items()
                if str(v) in YOUGLISH_LANG_BY_SLUG and YOUGLISH_LANG_BY_SLUG[str(v)][1] in GOOGLE_LANG_BY_CODE
            }
        google_audio_source_langs = cfg.get("google_audio_source_langs")
        if isinstance(google_audio_source_langs, dict):
            GOOGLE_AUDIO_SOURCE_LANGS = {
                str(k): str(v)
                for k, v in google_audio_source_langs.items()
                if str(v) in GOOGLE_AUDIO_VOICE_CODES
            }
        else:
            GOOGLE_AUDIO_SOURCE_LANGS = {}
        WEB_AUDIO_ENABLED = bool(cfg.get("web_audio_enabled", False))
        WEB_YG_ENABLED = bool(cfg.get("web_yg_enabled", False))
        WEB_IMG_ENABLED = bool(cfg.get("web_img_enabled", False))
        WEB_AUTO_SPEAK_ENABLED = bool(cfg.get("web_auto_speak_enabled", False))
        ANKI_DECK = str(cfg.get("anki_deck", ""))
        ANKI_NOTE_TYPE = str(cfg.get("anki_note_type", ""))
        ANKI_FIELD_MAP = cfg.get("anki_field_map", {})
        if not isinstance(ANKI_FIELD_MAP, dict): ANKI_FIELD_MAP = {}
        ANKI_REMOVE_HTML = bool(cfg.get("anki_remove_html", False))
        ANKI_CLOZE_TERM = bool(cfg.get("anki_cloze_term", False))
    except Exception:
        LANG_PROFILE = 'auto'
        PREFER_KANJI_ON_CLICK = True
        POPUP_LANGS = ["zh", "ja", "en"]
        POPUP_TRIGGER_MOD = "none"
        POPUP_SUBLOOKUP_MODE = "reuse"
        HOVER_SHIFT_MODE = False
        POPUP_THEME = "default"
        CUSTOM_CSS = ""
        CSS_PRESETS = {}
        PITCH_STYLE = "graph"
        POPUP_WIDTH = 380
        POPUP_HEIGHT = 350
        DISMISS_REBUILD_NOTICE = False
        DISMISSED_WHATS_NEW_VERSION = ""
        YOUGLISH_SOURCE_LANGS = {}
        GOOGLE_SOURCE_LANGS = {}
        GOOGLE_AUDIO_SOURCE_LANGS = {}
        WEB_AUDIO_ENABLED = False
        WEB_YG_ENABLED = False
        WEB_IMG_ENABLED = False
        WEB_AUTO_SPEAK_ENABLED = False
        ANKI_DECK = ""
        ANKI_NOTE_TYPE = ""
        ANKI_FIELD_MAP = {}

def _save_config():
    _refresh_data_paths()
    try:
        data = {
            'lang_profile': LANG_PROFILE,
            'popup_langs': POPUP_LANGS,
            'popup_trigger_mod': POPUP_TRIGGER_MOD,
            'popup_sublookup_mode': POPUP_SUBLOOKUP_MODE,
            'hover_shift_mode': bool(HOVER_SHIFT_MODE),
            'popup_theme': POPUP_THEME,
            'custom_css': CUSTOM_CSS,
            'css_presets': CSS_PRESETS,
            'pitch_style': PITCH_STYLE,
            'popup_width': POPUP_WIDTH,
            'popup_height': POPUP_HEIGHT,
            'hanzi_writer': bool(HANZI_WRITER),
            'prefer_kanji_on_click': bool(PREFER_KANJI_ON_CLICK),
            'dismiss_rebuild_notice': bool(DISMISS_REBUILD_NOTICE),
            'dismissed_whats_new_version': DISMISSED_WHATS_NEW_VERSION,
            'youglish_source_langs': YOUGLISH_SOURCE_LANGS,
            'google_source_langs': GOOGLE_SOURCE_LANGS,
            'google_audio_source_langs': GOOGLE_AUDIO_SOURCE_LANGS,
            'web_audio_enabled': bool(WEB_AUDIO_ENABLED),
            'web_yg_enabled': bool(WEB_YG_ENABLED),
            'web_img_enabled': bool(WEB_IMG_ENABLED),
            'web_auto_speak_enabled': bool(WEB_AUTO_SPEAK_ENABLED),
            'anki_deck': ANKI_DECK,
            'anki_note_type': ANKI_NOTE_TYPE,
            'anki_field_map': ANKI_FIELD_MAP,
            'anki_remove_html': bool(ANKI_REMOVE_HTML),
            'anki_cloze_term': bool(ANKI_CLOZE_TERM),
        }
        _write_text(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass

def _on_yomilens_js_message(handled, message, context):
    prefix = "yomilens:set-popup-size:"
    if not isinstance(message, str) or not message.startswith(prefix):
        return handled
    try:
        width_text, height_text = message[len(prefix):].split(":", 1)
        width = max(200, min(1200, int(width_text)))
        height = max(200, min(1200, int(height_text)))
    except (TypeError, ValueError):
        return (True, None)

    global POPUP_WIDTH, POPUP_HEIGHT
    POPUP_WIDTH = width
    POPUP_HEIGHT = height
    _save_config()
    return (True, None)

gui_hooks.webview_did_receive_js_message.append(_on_yomilens_js_message)

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

def _external_lookup_lang_from_query(term):
    s = str(term or "")
    if re.search(r"[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff]", s):
        return ("arabic", "ar")
    if re.search(r"[\u3040-\u30ff]", s):
        return ("japanese", "ja")
    if re.search(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]", s):
        return ("korean", "ko")
    if re.search(r"[\u0e00-\u0e7f]", s):
        return ("thai", "th")
    if re.search(r"[\u0400-\u04ff]", s):
        return ("russian", "ru")
    if re.search(r"[\u0370-\u03ff\u1f00-\u1fff]", s):
        return ("greek", "el")
    if re.search(r"[\u0590-\u05ff]", s):
        return ("hebrew", "he")
    if re.search(r"[\u0900-\u097f]", s):
        return ("hindi", "hi")
    if re.search(r"[\u3400-\u9fff\U00020000-\U0002EBEF]", s):
        return ("chinese", "zh-CN")
    return ("english", "en")

def _guess_external_lookup_lang(source_title, term=""):
    s = str(source_title or "").lower()
    pairs = [
        (("japanese", "jmdict", "jmnedict", "jitendex", "kanjidic", "日本", "和英", "国語", "nhật", "nhat", "jp", "ja"), ("japanese", "ja")),
        (("chinese", "cc-cedict", "cedict", "cfdict", "cvdict", "中文", "汉", "漢", "trung", "zh", "cn"), ("chinese", "zh-CN")),
        (("korean", "krdict", "한국", "korean-english", "hàn", "han", "ko", "kr"), ("korean", "ko")),
        (("arabic", "lisaan", "العربية"), ("arabic", "ar")),
        (("english", "wordnet", "en->en", "en-en", "anh", "en"), ("english", "en")),
        (("french", "français", "francais"), ("french", "fr")),
        (("spanish", "español", "espanol"), ("spanish", "es")),
        (("german", "deutsch"), ("german", "de")),
        (("italian", "italiano"), ("italian", "it")),
        (("portuguese", "português", "portugues"), ("portuguese", "pt")),
        (("russian", "русский"), ("russian", "ru")),
        (("vietnamese", "tiếng việt", "tieng viet", "en->vi", "en-vi"), ("vietnamese", "vi")),
    ]
    for needles, langs in pairs:
        if any(n in s for n in needles):
            return langs
    return _external_lookup_lang_from_query(term)

def _youglish_lang_from_source(source_title, source_id=None, term=""):
    if source_id is not None:
        chosen = YOUGLISH_SOURCE_LANGS.get(str(source_id))
        if chosen and chosen != "auto" and chosen in YOUGLISH_LANG_BY_SLUG:
            return chosen
    guessed_slug, _google_hl = _guess_external_lookup_lang(source_title, term)
    return guessed_slug if guessed_slug in YOUGLISH_LANG_BY_SLUG else "english"

def _google_lang_from_source(source_title, source_id=None, term=""):
    if source_id is not None:
        chosen = GOOGLE_SOURCE_LANGS.get(str(source_id))
        if chosen and chosen != "auto" and chosen in GOOGLE_LANG_BY_CODE:
            return GOOGLE_LANG_BY_CODE[chosen][1]
    _youglish_slug, google_hl = _guess_external_lookup_lang(source_title, term)
    return google_hl if google_hl in GOOGLE_LANG_BY_CODE else "en"

def _google_audio_lang_from_source(source_title, source_id=None, term=""):
    if source_id is not None:
        chosen = GOOGLE_AUDIO_SOURCE_LANGS.get(str(source_id))
        if chosen and chosen != "auto" and chosen in GOOGLE_AUDIO_VOICE_CODES:
            return chosen
    google_hl = _google_lang_from_source(source_title, source_id, term)
    if google_hl in GOOGLE_AUDIO_VOICE_CODES:
        return google_hl
    for _label, code in GOOGLE_AUDIO_VOICES:
        if code != "auto" and code.startswith(google_hl + "-"):
            return code
    return google_hl or "en"

def _external_lookup_lang_from_source(source_title, source_id=None, term=""):
    youglish_lang = _youglish_lang_from_source(source_title, source_id, term)
    google_hl = _google_lang_from_source(source_title, source_id, term)
    return (youglish_lang, google_hl)

def _external_lookup_url(kind, q, source_title="", source_id=None):
    term = str(q or "").strip()
    if not term:
        return ""
    if kind == "youglish":
        youglish_lang = _youglish_lang_from_source(source_title, source_id, term)
        return "https://youglish.com/pronounce/{}/{}".format(
            urllib.parse.quote(term),
            urllib.parse.quote(youglish_lang),
        )
    if kind == "images":
        google_hl = _google_lang_from_source(source_title, source_id, term)
        return "https://www.google.com/search?tbm=isch&hl={}&q={}".format(
            urllib.parse.quote(google_hl),
            urllib.parse.quote(term),
        )
    return ""

def _google_audio_url(q, source_title="", source_id=None):
    term = str(q or "").strip()
    if not term:
        return ""
    google_hl = _google_audio_lang_from_source(source_title, source_id, term)
    return "https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl={}&q={}&textlen={}".format(
        urllib.parse.quote(google_hl),
        urllib.parse.quote(term),
        urllib.parse.quote(str(len(term))),
    )

def _render_term_actions(term, source_title="", source_id=0):
    term = str(term or "").strip()
    parts = []
    source_id = int(source_id or 0)
    term_q = urllib.parse.quote(term)
    src_q = urllib.parse.quote(str(source_title or ""))
    sid_q = urllib.parse.quote(str(source_id or ""))
    _youglish_lang, google_hl = _external_lookup_lang_from_source(source_title, source_id, term)
    yg_url = f"http://127.0.0.1:{PORT}/api/web-popup?kind=youglish&q={term_q}&src={src_q}&sid={sid_q}"
    img_url = f"http://127.0.0.1:{PORT}/api/web-popup?kind=images&q={term_q}&src={src_q}&sid={sid_q}"
    audio_url = _google_audio_url(term, source_title, source_id)
    parts.append(
        f"<button type='button' class='term-action term-anki' title='Add to Anki' onclick=\"addAnkiCard(this, '{_attr(term)}')\">"
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m12 3 2.78 5.63 6.22.9-4.5 4.39 1.06 6.2L12 17.2l-5.56 2.92 1.06-6.2L3 9.53l6.22-.9L12 3z'></path></svg>"
        "</button>"
    )
    if WEB_AUDIO_ENABLED:
        parts.append(
            f"<button type='button' class='term-action term-audio' title='Play Google audio' "
            f"data-audio='{_attr(audio_url)}' data-term='{_attr(term)}' data-lang='{_attr(google_hl)}' aria-label='Play audio'>"
            "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M11 5 6 9H3v6h3l5 4V5z'></path><path d='M15.5 8.5a5 5 0 0 1 0 7'></path><path d='M18.5 5.5a9 9 0 0 1 0 13'></path></svg>"
            "</button>"
        )
    if WEB_YG_ENABLED:
        parts.append(
            f"<button type='button' class='term-action term-youglish' title='Open YouGlish in Anki' onclick=\"fetch('{_attr(yg_url)}');return false\">YG</button>"
        )
    if WEB_IMG_ENABLED:
        parts.append(
            f"<button type='button' class='term-action term-images' title='Open Google Images in Anki' onclick=\"fetch('{_attr(img_url)}');return false\">IMG</button>"
        )
    return "<div class='term-actions'>" + "".join(parts) + "</div>" if parts else ""

class _YomiLensWebPopup(QDialog):
    def __init__(self, url, title):
        super().__init__(mw)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        except AttributeError:
            self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title or "YomiLens Web")
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView(self)
        profile = QWebEngineProfile("YomiLensWebPopupProfile", self.web_view)
        page = QWebEnginePage(profile, self.web_view)
        self.web_view.setPage(page)
        try:
            self.web_view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
                False,
            )
        except Exception:
            pass
        layout.addWidget(self.web_view)
        self.web_view.load(QUrl(url))

    def closeEvent(self, event):
        try:
            page = self.web_view.page()
            try:
                page.setAudioMuted(True)
            except Exception:
                pass
            try:
                page.triggerAction(QWebEnginePage.WebAction.Stop)
            except Exception:
                pass
            try:
                self.web_view.setPage(None)
            except Exception:
                pass
            try:
                page.deleteLater()
            except Exception:
                pass
            try:
                self.web_view.deleteLater()
            except Exception:
                pass
        except Exception:
            pass
        event.accept()

    def event(self, event):
        try:
            if event.type() == QEvent.Type.WindowDeactivate:
                self.close()
        except Exception:
            pass
        return super().event(event)

def _show_external_lookup_popup(kind, q, source_title="", source_id=None):
    if QWebEngineView is None:
        tooltip("Qt WebEngine is not available in this Anki build.", period=2500)
        return False
    url = _external_lookup_url(kind, q, source_title, source_id)
    if not url:
        return False
    label = "YouGlish" if kind == "youglish" else "Google Images"

    def _open():
        try:
            wins = getattr(mw, "_yomilens_web_popups", None)
            if wins is None:
                wins = []
                mw._yomilens_web_popups = wins
            w = _YomiLensWebPopup(url, f"{label}: {q}")
            wins.append(w)
            w.destroyed.connect(lambda *_: wins.remove(w) if w in wins else None)
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            tooltip(f"Could not open web popup: {e}", period=3500)

    try:
        mw.taskman.run_on_main(_open)
    except Exception:
        _open()
    return True

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
    ".wrap{padding:12px 14px}"
    ".term{margin:10px 0 14px;border-left:3px solid #e0c8a7;padding-left:10px}"
    ".term-title-row{display:flex;align-items:flex-end;gap:8px;margin-bottom:6px}"
    ".t{font-weight:700;font-size:var(--term-size);margin-bottom:0}"
    ".term-actions{display:flex;align-items:center;gap:4px;padding-bottom:8px;flex-shrink:0}"
    ".term-action{border:1px solid #e0c8a7;background:#fff8ee;color:#7a5e3a;border-radius:999px;padding:2px 7px;font:700 11px system-ui,sans-serif;line-height:1.2;cursor:pointer}"
    ".term-action svg{display:block;width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}"
    ".term-audio{padding:3px 6px}"
    ".src{font-size:12px;opacity:.8;margin:4px 0 4px}"
    ".def{margin:3px 0;display:flex;align-items:flex-start}"
    ".def .r{flex-shrink:0;min-width:9em;opacity:.9;font-size:var(--text-size);padding-top:2px}"
    ".def .g{display:block;flex:1;font-size:var(--text-size);line-height:1.6}"
    ".empty{opacity:.7}"
    "</style>"
    "<div class='wrap'>{{ROWS}}</div>"
    "<script>\n"
    "function addAnkiCard(btn, term) {\n"
    "  try {\n"
    "    var termDiv = btn.closest('.term');\n"
    "    if (!termDiv) return;\n"
    "    \n"
    "    var readingEl = termDiv.querySelector('.r');\n"
    "    var reading = readingEl ? readingEl.textContent : '';\n"
    "    \n"
    "    var defs = termDiv.querySelectorAll('.def');\n"
    "    var glossLines = [];\n"
    "    defs.forEach(function(d) {\n"
    "      var g = d.querySelector('.g');\n"
    "      if (g) glossLines.push(g.innerText || g.textContent);\n"
    "    });\n"
    "    var gloss = glossLines.join('\\n');\n"
    "    \n"
    "    var selection = window.getSelection ? window.getSelection().toString().trim() : '';\n"
    "    var origHTML = btn.innerHTML;\n"
    "    var origColor = btn.style.borderColor;\n"
    "    \n"
    "    btn.innerHTML = \"<svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='green' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'></polyline></svg>\";\n"
    "    btn.style.borderColor = 'green';\n"
    "    \n"
    "    var xhr = new XMLHttpRequest();\n"
    "    xhr.open('POST', 'http://127.0.0.1:8777/api/add-anki-card', true);\n"
    "    xhr.setRequestHeader('Content-Type', 'application/json');\n"
    "    xhr.onreadystatechange = function() {\n"
    "      if (xhr.readyState === 4) {\n"
    "        var res = {};\n"
    "        try { res = JSON.parse(xhr.responseText); } catch(e){}\n"
    "        if (!res.ok) {\n"
    "           btn.style.borderColor = 'red';\n"
    "           btn.innerHTML = \"<svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='red' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='18' y1='6' x2='6' y2='18'></line><line x1='6' y1='6' x2='18' y2='18'></line></svg>\";\n"
    "           if (res.error) alert(res.error);\n"
    "           setTimeout(function(){\n"
    "             btn.innerHTML = origHTML;\n"
    "             btn.style.borderColor = origColor;\n"
    "           }, 2500);\n"
    "        } else {\n"
    "           setTimeout(function() {\n"
    "             btn.innerHTML = origHTML;\n"
    "             btn.style.borderColor = origColor;\n"
    "           }, 2000);\n"
    "        }\n"
    "      }\n"
    "    };\n"
    "    xhr.send(JSON.stringify({\n"
    "      term: term,\n"
    "      reading: reading,\n"
    "      gloss: gloss,\n"
    "      selection: selection\n"
    "    }));\n"
    "  } catch(e) {\n"
    "    console.error(e);\n"
    "  }\n"
    "}\n"
    "</script>\n"
)


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

def _normalize_internal_lookup_href(href):
    href = str(href or "")
    if href.startswith("?query="):
        return "?q=" + href[len("?query="):]
    return href

def _normalize_internal_lookup_links(markup):
    """Normalize Yomitan's internal links without reserializing dictionary HTML."""
    return re.sub(
        r'''(\bhref\s*=\s*["'])\?query=''',
        r"\1?q=",
        str(markup or ""),
        flags=re.IGNORECASE,
    )

def _render_gloss_line(line):
    line = (line or "").strip()
    if not line:
        return ""
    if line.startswith("@@"):
        parts = line.split("\t")
        kind = parts[0]
        if kind == "@@html" and len(parts) >= 2:
            payload = _normalize_internal_lookup_links(line.split("\t", 1)[1])
            return f"<div class='structured-gloss'>{payload}</div>"
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
        f"window.__yomiSublookupMode = {json.dumps(POPUP_SUBLOOKUP_MODE)}; "
        f"window.__yomiPreferKanjiOnClick = {json.dumps(bool(PREFER_KANJI_ON_CLICK))}; "
        f"window.__yomiHoverShiftMode = {json.dumps(HOVER_SHIFT_MODE)}; "
        f"window.__yomiPopupTheme = {json.dumps(POPUP_THEME)}; "
        f"window.__yomiPopupWidth = {json.dumps(POPUP_WIDTH)}; "
        f"window.__yomiPopupHeight = {json.dumps(POPUP_HEIGHT)};"
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
    _refresh_data_paths()
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
    _refresh_data_paths()
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
        href = _normalize_internal_lookup_href(node.get("href"))
        if href.startswith(("http://", "https://")):
            attrs.append(f'href="{_attr(href)}"')
            attrs.append('target="_blank"')
            attrs.append('rel="noreferrer"')
        elif href.startswith("?q="):
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
    _refresh_data_paths()
    _ensure_dir(os.path.dirname(DB_PATH))
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
    _metadata_schema(DB)
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

def _db_after_dictionary_change(reinject=True):
    """Refresh lightweight runtime state after source/import/delete changes."""
    global DB_MODE, DB_SIG
    with SCAN_CACHE_LOCK:
        SCAN_CACHE.clear()
    try:
        if DB is None:
            _db_open()
            return
        counts = _db_content_counts(enabled_only=False)
        DB_MODE = bool(counts.get("terms") or counts.get("kanji"))
        DB_SIG = _db_file_signature()
    except Exception:
        try:
            _db_open()
        except Exception:
            pass
    if reinject:
        try:
            _inject()
        except Exception:
            pass

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

def _scan_longest_match(q):
    query = (q or "").strip()
    if not query or not DB_MODE or not DB:
        return 0
    key = (str(DB_SIG), tuple(POPUP_LANGS), query)
    with SCAN_CACHE_LOCK:
        if key in SCAN_CACHE:
            value = SCAN_CACHE.pop(key)
            SCAN_CACHE[key] = value
            return value
    lang = _detect_lookup_lang(query)
    seed = df_pick_seed(lang, query)
    match_len = 0
    if seed:
        if lang in DEINFLECT_SPACE_WORD_LANGS:
            word = df_pick_seed(lang, query)
            forms = df_candidates(lang, word) if word else []
            exist = _db_existing_in_order(forms, limit=1)
            match_len = len(exist[0]) if exist else 0
        else:
            max_len = _db_get_max_len()
            for length in range(min(max_len, len(seed)), 0, -1):
                segment = seed[:length]
                forms = df_candidates(lang, segment)
                if _db_existing_in_order(forms, limit=1):
                    match_len = length
                    break
    with SCAN_CACHE_LOCK:
        SCAN_CACHE[key] = int(match_len)
        while len(SCAN_CACHE) > SCAN_CACHE_LIMIT:
            SCAN_CACHE.popitem(last=False)
    return int(match_len)

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
            if "term_bank" in low or "kanji_bank" in low or "term_meta_bank" in low:
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
                if "term_meta_bank" in low:
                    cnt += _metadata_import(DB, text, sid)
                elif is_term_bank:
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
            if "term_bank" not in fn.lower() and "term_meta_bank" not in fn.lower(): continue
            p = os.path.join(root, fn)
            try:
                text = _read_text(p)
                if "term_meta_bank" in fn.lower():
                    cnt += _metadata_import(DB, text, sid)
                else:
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
    unique_forms = []
    for f in forms:
        if f and f not in form_seen:
            unique_forms.append(f)
            form_seen.add(f)

    def add_rows(cur):
        for row in cur.fetchall():
            if row and row[0] not in out_seen:
                out.append(row[0]); out_seen.add(row[0])
                if limit and len(out) >= limit: break
        return bool(limit and len(out) >= limit)

    # Prefer real headword matches for every deinflected candidate before
    # falling back to reading/norm matches. This preserves cases like 読め
    # returning both 読む and 読める instead of letting a reading match consume
    # the result budget first.
    for f in unique_forms:
        row_limit = max(1, (limit or 1) - len(out))
        cur = DB.execute("""
            SELECT t.term
            FROM term t JOIN source s ON s.id=t.source_id
            WHERE t.term=? AND s.enabled=1
            GROUP BY t.term
            ORDER BY s.priority ASC, s.id ASC, MIN(t.rowid) ASC
            LIMIT ?
        """, (f, row_limit))
        if add_rows(cur):
            return out

    for f in unique_forms:
        nf = _lookup_norm_term(f)
        row_limit = max(1, (limit or 1) - len(out))
        cur = DB.execute("""
            SELECT t.term
            FROM term t JOIN source s ON s.id=t.source_id
            WHERE (t.norm_term=? OR t.reading=? OR t.norm_reading=?) AND s.enabled=1
            GROUP BY t.term
            ORDER BY CASE
                WHEN t.reading=? THEN 0
                WHEN t.norm_term=? THEN 1
                ELSE 2
            END, s.priority ASC, s.id ASC, MIN(t.rowid) ASC
            LIMIT ?
        """, (nf, f, nf, f, nf, row_limit))
        if add_rows(cur):
            return out
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
    try:
        if DB is None:
            _db_open()
        out = []
        for ch in _kanji_chars_from_text(text):
            cur = DB.execute("""
                SELECT k.character,k.onyomi,k.kunyomi,k.tags,k.meanings,k.stats,s.title,s.id
                FROM kanji k JOIN source s ON s.id=k.source_id
                WHERE k.character=? AND s.enabled=1
                ORDER BY s.priority ASC, s.id ASC
                LIMIT 3
            """, (ch,))
            for character, onyomi, kunyomi, tags, meanings, stats, source, source_id in cur.fetchall():
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
                    "source_id": int(source_id or 0),
                })
        return out
    except Exception:
        return []

def db_has_kanji_for_text(text):
    try:
        return bool(db_kanji_for_text(text))
    except Exception:
        return False


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
                try:
                    _db_refresh_if_changed()
                    try:
                        qs = urllib.parse.parse_qs(parsed.query or "")
                    except Exception:
                        qs = {}
                    q = (qs.get("q", [""])[0] or "").strip()
                    self._json({"ok": True, "items": db_kanji_for_text(q)})
                except Exception:
                    self._json({"ok": True, "items": []})
                return

            if parsed.path == "/api/web-popup":
                try:
                    qs = urllib.parse.parse_qs(parsed.query or "")
                except Exception:
                    qs = {}
                kind = (qs.get("kind", [""])[0] or "").strip()
                q = (qs.get("q", [""])[0] or "").strip()
                src = (qs.get("src", [""])[0] or "").strip()
                try:
                    sid = int((qs.get("sid", ["0"])[0] or 0))
                except Exception:
                    sid = None
                ok = _show_external_lookup_popup(kind, q, src, sid)
                self._json({"ok": bool(ok)})
                return

            if parsed.path == "/api/audio":
                try:
                    qs = urllib.parse.parse_qs(parsed.query or "")
                except Exception:
                    qs = {}
                q = (qs.get("q", [""])[0] or "").strip()
                src = (qs.get("src", [""])[0] or "").strip()
                try:
                    sid = int((qs.get("sid", ["0"])[0] or 0))
                except Exception:
                    sid = None
                audio_url = _google_audio_url(q, src, sid)
                if not audio_url:
                    self._safe_send_headers(404, 0)
                    return
                try:
                    self.send_response(302)
                    self.send_header("Location", audio_url)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                except self.BROKEN:
                    pass
                return

            # --- API: scan — return longest-match length for hook mode ---
            if parsed.path == "/api/scan":
                try:
                    _db_refresh_if_changed()
                    qs = urllib.parse.parse_qs(parsed.query or "")
                    q = (qs.get("q", [""])[0] or "").strip()
                    self._json({"ok": True, "matchLen": _scan_longest_match(q)})
                except Exception:
                    self._json({"ok": True, "matchLen": 0})
                return

            # --- trang tra cứu như cũ ---
            if parsed.path not in ("/lookup", "/", "/q"):
                body = b"<!doctype html><title>404</title>Not Found"
                if self._safe_send_headers(404, len(body)):
                    self._safe_write(body)
                return
            



            params = urllib.parse.parse_qs(parsed.query)
            q = params.get("q", [""])[0]
            return_q = params.get("return_q", [""])[0].strip()
            _db_refresh_if_changed()

            def lookup_blocks(text):
                text = (text or "").strip()
                if not text:
                    return []
                lang = _detect_lookup_lang(text)
                seed = df_pick_seed(lang, text) or text
                forms = df_candidates(lang, seed) if seed else [text]
                if text not in forms:
                    forms.insert(0, text)
                if DB_MODE and DB:
                    terms = _db_existing_in_order(forms, limit=8)
                    return [(term, db_entries_for_term(term)) for term in terms]
                seen, terms = set(), []
                for term in forms:
                    if term in TERM_INDEX and term not in seen:
                        terms.append(term)
                        seen.add(term)
                return [(term, TERM_INDEX.get(term, [])) for term in terms]

            blocks = lookup_blocks(q)
            if any(entries for _term, entries in blocks):
                first_han_match = re.search(r"[\u3400-\u9fff\U00020000-\U0002A6DF]", (q or "").strip())
                first_han = first_han_match.group(0) if first_han_match else ""
                if first_han and first_han != (q or "").strip():
                    existing_terms = {term for term, _entries in blocks}
                    for term, entries in lookup_blocks(first_han):
                        if term == first_han and entries and term not in existing_terms:
                            blocks.append((term, entries))
                            break
            display_blocks = None
            display_q = None
            if (
                return_q
                and not any(entries for _term, entries in blocks)
                and DB_MODE and DB and db_has_kanji_for_text(q)
            ):
                prev_blocks = lookup_blocks(return_q)
                if any(entries for _term, entries in prev_blocks):
                    display_blocks = prev_blocks
                    display_q = return_q

            force_kanji = params.get("kanji", [""])[0] == "1"
            html = self._render(
                blocks, q, display_blocks=display_blocks, display_q=display_q,
                force_kanji=force_kanji,
            )
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

    def _handle_add_anki_card(self):
        ln = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(ln).decode("utf-8", errors="ignore") if ln > 0 else "{}"
        try:
            import json
            data = json.loads(raw or "{}")
        except:
            data = {}
            
        term = (data.get("term") or "").strip()
        reading = (data.get("reading") or "").strip()
        gloss = (data.get("gloss") or "").strip()
        selection = (data.get("selection") or "").strip()
        
        if not ANKI_DECK or not ANKI_NOTE_TYPE:
            self._json({"ok": False, "error": "Please configure Target Deck and Note Type in Yomilens Settings first."})
            return
            
        def do_add_on_main():
            from aqt import mw
            from aqt.utils import tooltip
            import re
            
            try:
                deck_id = mw.col.decks.id(ANKI_DECK)
                model = mw.col.models.by_name(ANKI_NOTE_TYPE)
                if not model:
                    tooltip("Note type not found!")
                    return
                    
                note = mw.col.new_note(model)
                
                # Fetch current review card's data if available
                current_note = None
                if getattr(mw, 'reviewer', None) and mw.reviewer.card:
                    current_note = mw.reviewer.card.note()
                
                # Helper to process {Tag} replacements
                def process_field(tmpl):
                    if not tmpl: return ""
                    res = tmpl.replace("{term}", term)
                    res = res.replace("{reading}", reading)
                    res = res.replace("{gloss}", gloss)
                    res = res.replace("{selection}", selection)
                    
                    if current_note:
                        def repl_field(match):
                            fname = match.group(1)
                            cloze_mode = ""
                            
                            if fname.lower().startswith("ankicloze:"):
                                fname = fname[10:]
                                cloze_mode = "anki"
                            elif fname.lower().startswith("cloze:"):
                                fname = fname[6:]
                                cloze_mode = "blank"
                                
                            if fname in current_note:
                                val = current_note[fname]
                                if cloze_mode and term:
                                    replacement = (
                                        _anki_native_cloze(term)
                                        if cloze_mode == "anki"
                                        else _anki_cloze_blank(term)
                                    )
                                    val = _anki_replace_cloze(
                                        val, term, replacement, remove_html=ANKI_REMOVE_HTML
                                    )
                                elif ANKI_REMOVE_HTML:
                                    val = re.sub(r'<[^>]+>', '', val)
                                return val
                            return match.group(0)
                        res = re.sub(r'\{([^}]+)\}', repl_field, res)
                    return res
                    
                for fname, tmpl in ANKI_FIELD_MAP.items():
                    if fname in note:
                        note[fname] = process_field(tmpl)
                
                mw.col.add_note(note, deck_id)
                tooltip(f"Added {term} to {ANKI_DECK}!")
                
            except Exception as e:
                tooltip(f"Error adding card: {e}")
                
        from aqt import mw
        mw.taskman.run_on_main(do_add_on_main)
        self._json({"ok": True})

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/add-anki-card":
                self._handle_add_anki_card()
                return
            if parsed.path != "/api/add":
                self._json({"ok": False, "error": "Not Found"}, code=404)
                return

            ln = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(ln).decode("utf-8", errors="ignore") if ln > 0 else "{}"
            data = json.loads(raw or "{}")

            term = (data.get("term") or "").strip()
            reading = (data.get("reading") or "").strip()
            gloss = (data.get("gloss") or "").strip()
            selection = (data.get("selection") or "").strip()
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
    def _render(self, blocks, q, display_blocks=None, display_q=None, force_kanji=False):
        render_blocks = blocks if display_blocks is None else display_blocks
        render_q = q if display_q is None else display_q
        rows = []
        if render_blocks:
            for (term, entries) in render_blocks:
                # nhóm theo source
                per_src = {}
                for e in entries:
                    per_src.setdefault(e["source"], []).append(e)

                term_class = "t en-term" if re.search(r"[A-Za-z]", term or "") else "t"
                first_src = next(iter(per_src.keys()), "")
                first_items = per_src.get(first_src) or []
                first_source_id = int((first_items[0].get("source_id") if first_items else 0) or 0)
                term_html = [
                    "<div class='term'><div class='term-title-row'>"
                    f"<div class='{term_class}'>{_esc(term)}</div>"
                    f"{_render_term_actions(term, first_src, first_source_id)}"
                    "</div>"
                ]
                for src, items in per_src.items():
                    visible_items = items[:8]
                    show_entry_nums = len(visible_items) > 1
                    reading_groups = {}
                    for idx, e in enumerate(visible_items, start=1):
                        reading = e.get('reading', '')
                        reading_groups.setdefault(reading, [])
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
                                # Structured HTML is one document, even with embedded whitespace.
                                g = g.strip()
                                gloss_lines = [g] if g.startswith("@@html\t") else g.split("\n")
                                for sub in gloss_lines:
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
                        reading_groups[reading].append(
                            "<div class='def'>"
                            f"<div class='g'>{head_html}{gloss}</div></div>"
                        )
                    for reading, definitions in reading_groups.items():
                        source_id = int((visible_items[0].get('source_id') if visible_items else 0) or 0)
                        source_attr = _attr(src)
                        frequency = _metadata_render(DB, term, [reading], only_kind='freq')
                        pitch = _metadata_render(DB, term, [reading], only_kind='pitch', pitch_style=PITCH_STYLE)
                        term_html.append(
                            f'<div class="dictionary-reading-section" data-dictionary="{source_attr}" data-source-id="{source_id}">'
                            f'<div class="dictionary-heading"><div class="src" data-dictionary="{source_attr}" '
                            f'data-source-id="{source_id}">{_esc(src)}</div>{frequency}</div>'
                            "<div class='reading-group'><div class='reading-column'>"
                            f"<span class='r'>{_esc(reading)}</span></div>"
                            f"<div class='reading-definitions'>{pitch}{''.join(definitions)}</div></div></div>"
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
                q_class = "t en-term" if re.search(r"[A-Za-z]", render_q or "") else "t"
                rows.append(
                    "<div class='term not-found-term'><div class='term-title-row'>"
                    f"<div class='{q_class}'>{_esc(render_q)}</div>"
                    f"{_render_term_actions(render_q)}"
                    "</div>"
                    f"<div class='empty'><b>Not found: {_esc(render_q)}</b><br>"
                    "No matching term entry was found. If this is a single kanji, "
                    "install or enable a KANJIDIC/kanji dictionary in "
                    "<code>Tools → YomiLens Settings → Dictionaries</code>.</div>"
                    "</div>"
                )

        tpl = _get_popup_tpl()
        kanji_enabled = "1" if (DB_MODE and DB and db_has_kanji_for_text(q)) else "0"
        auto_kanji = "1" if (
            kanji_enabled == "1"
            and (force_kanji or not any(entries for _term, entries in blocks))
        ) else "0"
        html = (
            tpl.replace("{{ROWS}}", "".join(rows))
            .replace("{{QUERY}}", _esc(q))
            .replace("{{HW_ENABLED}}", "1" if HANZI_WRITER else "0")
            .replace("{{KANJI_ENABLED}}", kanji_enabled)
            .replace("{{AUTO_KANJI}}", auto_kanji)
            .replace("{{PREFER_KANJI_ON_CLICK}}", "1" if PREFER_KANJI_ON_CLICK else "0")
            .replace("{{AUTO_SPEAK}}", "1" if (WEB_AUDIO_ENABLED and WEB_AUTO_SPEAK_ENABLED) else "0")
            .replace("{{THEME}}", POPUP_THEME)
        )
        # Keep user CSS as text so a closing style tag cannot inject HTML/scripts.
        css_json = json.dumps(CUSTOM_CSS).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        html += "<script>(function(){var s=document.createElement('style');s.id='yomilens-custom-css';s.textContent=" + css_json + ";document.head.appendChild(s);})();</script>"
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
def _action_db_import_zip(progress_cb=None, done_cb=None):
    path, _ = QFileDialog.getOpenFileName(mw, "Select Yomichan ZIP", "", "ZIP (*.zip)")
    if not path: return
    progress = None
    if progress_cb is None:
        progress = QProgressDialog("Preparing dictionary...", None, 0, 100, mw)
        progress.setWindowTitle("Install Dictionary")
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.setValue(0)
    def set_import_progress(pct, msg):
        if progress_cb is not None:
            progress_cb(pct, msg)
        else:
            progress.setValue(pct)
            progress.setLabelText(msg)
        QApplication.processEvents()
    set_import_progress(0, "Preparing dictionary...")
    try:
        if DB is None: _db_open()
        n = import_yomichan_zip_to_db(path, progress_cb=set_import_progress)
        global DB_MODE; DB_MODE = True
        _db_after_dictionary_change()
        set_import_progress(100, f"Imported {n:,} entries successfully.")
        if done_cb is not None:
            done_cb(True, f"Imported {n:,} entries successfully.")
        tooltip(f"Imported {n} entries to DB")
    except Exception as e:
        if done_cb is not None:
            done_cb(False, f"Import failed: {e}")
        tooltip(f"DB ZIP error: {e}", period=2000)
    finally:
        if progress is not None:
            progress.close()

def _action_db_import_folder():
    folder = QFileDialog.getExistingDirectory(mw, "Select Yomichan folder")
    if not folder: return
    try:
        if DB is None: _db_open()
        n = import_yomichan_folder_to_db(folder)
        global DB_MODE; DB_MODE = True
        _db_after_dictionary_change()
        tooltip(f"Imported {n} entries to DB")
    except Exception as e:
        tooltip(f"DB folder error: {e}", period=2000)

def _action_db_clear():
    try:
        _db_close()
        if os.path.exists(DB_PATH): os.remove(DB_PATH)
        _db_after_dictionary_change()
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
        cm = DB.execute("SELECT COUNT(*) FROM term_metadata").fetchone()[0]
        return f"DB: {c1} source(s), {c2} entries, {c3} kanji, {cm} metadata, max_len={ml}"
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
        cm = DB.execute("SELECT COUNT(*) FROM term_metadata WHERE source_id=?", (row['id'],)).fetchone()[0]
        suffix = f"   —  {cm} metadata" if cm else ""
        txt = f"[{mark}]  {row['title']}   —  {row['type']}   —  {base}{suffix}"
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
            _db_after_dictionary_change()
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
            _db_after_dictionary_change()
            tooltip("Order and state saved", period=1500)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save: {e}")
        self.accept()

def _action_db_manage():
    if DB is None: _db_open()
    dlg = _DbManageDialog(mw)
    dlg.exec()

class _YomiSettingsDialog(QDialog):
    def __init__(self, parent=None, initial_tab=None, initial_guide_page=None):
        super().__init__(parent or mw)
        self.setWindowTitle("YomiLens Settings")
        self.resize(820, 700)

        from aqt.qt import QTabWidget, QCheckBox

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        self.tabs = tabs
        root.addWidget(tabs, 1)

        tabs.addTab(self._build_general_tab(QCheckBox), "General")
        database_placeholder = QWidget(tabs)
        database_placeholder_layout = QVBoxLayout(database_placeholder)
        database_placeholder_layout.addWidget(QLabel("Loading Dictionaries…", database_placeholder))
        database_placeholder_layout.addStretch(1)
        database_tab_index = tabs.addTab(database_placeholder, "Dictionaries")
        tabs.addTab(self._build_web_lookup_tab(), "Web Lookup")
        tabs.addTab(self._build_anki_tab(), "Anki Export")
        guide_tab_index = tabs.addTab(self._build_guide_tab(initial_guide_page), "Guide")
        tabs.addTab(self._build_about_tab(), "☕ Support")

        if initial_tab == "guide":
            tabs.setCurrentIndex(guide_tab_index)

        self._database_tab_loaded = False
        def load_tab_on_demand(index):
            if index != database_tab_index or self._database_tab_loaded:
                return
            self._database_tab_loaded = True
            database_tab = self._build_database_tab()
            tabs.blockSignals(True)
            tabs.removeTab(database_tab_index)
            tabs.insertTab(database_tab_index, database_tab, "Dictionaries")
            tabs.setCurrentIndex(database_tab_index)
            tabs.blockSignals(False)
            database_placeholder.deleteLater()
        tabs.currentChanged.connect(load_tab_on_demand)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    @staticmethod
    def _style_primary_save(button):
        button.setMinimumHeight(36)
        button.setStyleSheet(
            "QPushButton {"
            "background-color:#1677d2; color:white; border:1px solid #1268b8;"
            "border-radius:6px; padding:7px 16px; font-weight:600;"
            "}"
            "QPushButton:hover { background-color:#2389e6; }"
            "QPushButton:pressed { background-color:#105fa9; }"
            "QPushButton:disabled { background-color:#7f9bb3; color:#e7edf2; }"
        )

    def _edit_custom_css(self):
        from aqt.qt import QPlainTextEdit, QTimer, QMenu, QComboBox, QInputDialog
        existing = getattr(mw, "_yomilens_css_dialog", None)
        if existing is not None:
            existing._yomilens_editor.setPlainText(CUSTOM_CSS)
            existing._yomilens_refresh_presets()
            geometry = getattr(existing, "_yomilens_geometry", None)
            if geometry is not None:
                existing.restoreGeometry(geometry)
            if existing._yomilens_preview is not None:
                existing._yomilens_preview.show()
            existing._yomilens_refresh_preview()
            existing.exec()
            existing._yomilens_geometry = existing.saveGeometry()
            if existing._yomilens_preview is not None:
                existing._yomilens_preview.hide()
                existing._yomilens_preview.setGeometry(0, 0, 1, 1)
            existing.move(-10000, -10000)
            self.raise_()
            self.activateWindow()
            return

        # Keep one Chromium preview alive for the whole Anki session. Reusing
        # it preserves full browser CSS support without destroying a native
        # web surface, which can leave an invisible click-blocking layer.
        dlg = QDialog(mw)
        mw._yomilens_css_dialog = dlg
        dlg.setWindowTitle('Custom CSS')
        dlg.resize(1040, 620)
        layout = QVBoxLayout(dlg)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel('My CSS presets:', dlg))
        preset_combo = QComboBox(dlg)
        preset_combo.setMinimumWidth(220)
        preset_row.addWidget(preset_combo, 1)
        load_preset_btn = QPushButton('Load', dlg)
        save_preset_btn = QPushButton('Save Preset', dlg)
        delete_preset_btn = QPushButton('Delete', dlg)
        preset_row.addWidget(load_preset_btn)
        preset_row.addWidget(save_preset_btn)
        preset_row.addWidget(delete_preset_btn)
        layout.addLayout(preset_row)

        content = QHBoxLayout()
        content.setSpacing(12)
        editor_panel = QWidget(dlg)
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(QLabel('Custom CSS', editor_panel))
        editor = QPlainTextEdit(dlg)
        editor.setMinimumWidth(320)
        editor.setPlainText(CUSTOM_CSS)
        example_css = '''/* YomiLens starter CSS. Change the values, then Preview and Save CSS. */

/* Popup font. Use a font installed on your computer. */
body { font-family: "Noto Sans JP", sans-serif; }

/* Headword, including Latin words. */
.t, .t.en-term { font-size: 32px; }

/* Reading pill. */
.reading-column > .r { font-size: 16px; padding: 2px 8px; }

/* Definitions: text size and line spacing. */
.reading-definitions .g { font-size: 16px; line-height: 1.5; }

/* Left reading column / right definition column: 30% / 70%. */
.reading-group { grid-template-columns: minmax(0, 3fr) minmax(0, 7fr); }

/* Dictionary label, frequency, and pitch graph text. */
.src { font-size: 12px; }
.frequency-badge { font-size: 11px; }
.pitch-graph { font-size: 14px; }

/* Per-dictionary examples (replace these names with your installed dictionary titles). */
.src[data-dictionary="Sample dictionary"] { background: #4876b8; color: #fff; }
.frequency-badge[data-dictionary="Frequency"] { border-color: #4876b8; }
.pitch-source[data-dictionary="Sample pitch dictionary"] { color: #4876b8; }

/* Term action buttons: shared style and per-button hooks. */
.term-actions { gap: 5px; }
.term-action { font-size: 11px; padding: 3px 7px; }
.term-anki { /* Add to Anki star */ }
.term-audio { /* Speaker */ }
.term-youglish { /* YG */ }
.term-images { /* IMG */ }

/* Kanji tab. */
.kanji-card { border-left-width: 4px; padding: 10px 12px; }
.kanji-char { font-size: 46px; }
.kanji-meaning { font-size: 17px; }
.kanji-row { font-size: 13px; }
.kanji-pill { font-size: 11px; padding: 2px 7px; }
.kanji-src { font-size: 11px; }

/* Optional light palette: remove the surrounding comment to enable.
body {
  --bg: #ffffff;
  --fg: #253348;
  --gloss-fg: #222222;
  --fg-muted: #666666;
  --accent: #4876b8;
  --reading-bg: #eef2f6;
  --reading-fg: #253348;
}
*/
'''
        colorful_css = '''/* Colorful stress test. Use this to verify that Custom CSS is applied. */

body {
  --bg: #fff4fb;
  --fg: #35204f;
  --gloss-fg: #173f35;
  --fg-muted: #7a4170;
  --accent: #ff3d81;
  --reading-bg: #d9fff2;
  --reading-fg: #075f54;
  font-family: "Avenir Next", "Noto Sans JP", sans-serif;
  background: linear-gradient(135deg, #fff4fb 0%, #fff8cf 48%, #dff9ff 100%);
}

.term { border-left: 6px solid #ff3d81; padding-left: 14px; }
.t, .t.en-term { color: #6a24c9; font-size: 38px; text-shadow: 2px 2px 0 #ffd84d; }
.src { color: #fff; background: #087f8c; border-radius: 6px; padding: 5px 12px; font-weight: 700; }
.reading-column > .r { color: #5a214f; background: #ffd6e8; border: 2px solid #ff70a6; border-radius: 6px; padding: 4px 10px; }
.reading-group { grid-template-columns: minmax(0, 3fr) minmax(0, 7fr); border-bottom: 2px dashed #ff9f1c; padding: 10px 0; }
.reading-definitions .g { color: #173f35; font-size: 18px; line-height: 1.6; }
.frequency-badge { color: #28205f; background: #ffe66d; border: 2px solid #ff9f1c; border-radius: 5px; padding: 3px 8px; }
.pitch-source { color: #fff; background: #7b2cbf; border-radius: 6px; padding: 8px; }
.pitch-graph { color: #00a8c6; font-size: 18px; }
.term-actions { gap: 7px; }
.term-action { color: #fff; border-width: 2px; box-shadow: 2px 2px 0 rgba(53, 32, 79, .25); }
.term-anki { background: #ef476f; border-color: #8f1741; }
.term-audio { background: #7b2cbf; border-color: #4b1877; }
.term-youglish { background: #087f8c; border-color: #04545d; }
.term-images { background: #ff9f1c; border-color: #a85d00; color: #35204f; }
.kanji-card { background: #e9ddff; border-left: 6px solid #ff3d81; border-radius: 8px; }
.kanji-char { color: #6a24c9; font-size: 52px; text-shadow: 2px 2px 0 #ffd84d; }
.kanji-meaning { color: #087f8c; font-size: 20px; }
.kanji-row { color: #7a4170; font-size: 15px; }
.kanji-label { color: #ef476f; }
.kanji-pill { color: #28205f; background: #ffe66d; border: 1px solid #ff9f1c; }
.kanji-src { color: #fff; background: #087f8c; border-radius: 4px; display: inline-block; padding: 2px 6px; }
.navbtn { color: #fff !important; background: #ef476f !important; border-color: #ffd166 !important; }
'''
        editor.setPlaceholderText(example_css)
        editor_layout.addWidget(editor, 1)
        content.addWidget(editor_panel, 1)

        def refresh_presets(selected_name=''):
            current_name = selected_name or str(preset_combo.currentData() or '')
            preset_combo.blockSignals(True)
            preset_combo.clear()
            preset_combo.addItem('Select a saved preset...', '')
            for name in sorted(CSS_PRESETS, key=str.casefold):
                preset_combo.addItem(name, name)
            selected_index = preset_combo.findData(current_name)
            preset_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            preset_combo.blockSignals(False)
            has_selection = bool(preset_combo.currentData())
            load_preset_btn.setEnabled(has_selection)
            delete_preset_btn.setEnabled(has_selection)

        def update_preset_buttons(_index=0):
            has_selection = bool(preset_combo.currentData())
            load_preset_btn.setEnabled(has_selection)
            delete_preset_btn.setEnabled(has_selection)

        def load_preset():
            name = str(preset_combo.currentData() or '')
            if not name or name not in CSS_PRESETS:
                return
            editor.setPlainText(CSS_PRESETS[name])
            refresh_preview()

        def save_preset():
            global CSS_PRESETS
            selected_name = str(preset_combo.currentData() or '')
            name, accepted = QInputDialog.getText(
                dlg, 'Save CSS Preset', 'Preset name:', text=selected_name
            )
            name = str(name).strip()
            if not accepted or not name:
                return
            name = name[:80]
            if name in CSS_PRESETS:
                _Yes = QMessageBox.StandardButton.Yes
                _No = QMessageBox.StandardButton.No
                answer = QMessageBox.question(
                    dlg,
                    'Replace CSS Preset',
                    f"Replace the saved preset '{name}'?",
                    _Yes | _No,
                    _No,
                )
                if answer != _Yes:
                    return
            CSS_PRESETS[name] = editor.toPlainText()
            _save_config()
            refresh_presets(name)
            tooltip(f"CSS preset '{name}' saved")

        def delete_preset():
            global CSS_PRESETS
            name = str(preset_combo.currentData() or '')
            if not name or name not in CSS_PRESETS:
                return
            _Yes = QMessageBox.StandardButton.Yes
            _No = QMessageBox.StandardButton.No
            answer = QMessageBox.question(
                dlg,
                'Delete CSS Preset',
                f"Delete the saved preset '{name}'?",
                _Yes | _No,
                _No,
            )
            if answer != _Yes:
                return
            del CSS_PRESETS[name]
            _save_config()
            refresh_presets()

        preset_combo.currentIndexChanged.connect(update_preset_buttons)
        load_preset_btn.clicked.connect(load_preset)
        save_preset_btn.clicked.connect(save_preset)
        delete_preset_btn.clicked.connect(delete_preset)
        refresh_presets()

        preview_panel = QWidget(dlg)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel('Preview', preview_panel))
        preview_header.addStretch(1)
        preview_mode = QComboBox(preview_panel)
        preview_mode.addItem('Dictionary', 'result')
        preview_mode.addItem('Kanji', 'kanji')
        preview_header.addWidget(preview_mode)
        preview_layout.addLayout(preview_header)
        preview = QWebEngineView(dlg) if QWebEngineView else None
        if preview:
            preview.setMinimumWidth(320)
            preview_layout.addWidget(preview, 1)
        else:
            unavailable = QLabel('Preview is unavailable in this Anki version.', preview_panel)
            unavailable.setWordWrap(True)
            preview_layout.addWidget(unavailable, 1)
        content.addWidget(preview_panel, 1)
        layout.addLayout(content, 1)

        def refresh_preview():
            if not preview:
                return
            from .term_metadata import pitch_graph, pitch_compact
            render_pitch = pitch_compact if PITCH_STYLE == 'compact' else pitch_graph
            action_sample = (
                "<div class='term-actions'>"
                "<button type='button' class='term-action term-anki' title='Add to Anki'>"
                "<svg viewBox='0 0 24 24'><path d='m12 3 2.78 5.63 6.22.9-4.5 4.39 1.06 6.2L12 17.2l-5.56 2.92 1.06-6.2L3 9.53l6.22-.9L12 3z'></path></svg>"
                "</button>"
                "<button type='button' class='term-action term-audio' title='Play audio'>"
                "<svg viewBox='0 0 24 24'><path d='M11 5 6 9H3v6h3l5 4V5z'></path><path d='M15.5 8.5a5 5 0 0 1 0 7'></path></svg>"
                "</button>"
                "<button type='button' class='term-action term-youglish'>YG</button>"
                "<button type='button' class='term-action term-images'>IMG</button>"
                "</div>"
            )
            sample = (
                "<div class='term'><div class='term-title-row'><div class='t'>食べる</div>" + action_sample + "</div>"
                "<div class='dictionary-reading-section' data-dictionary='Sample dictionary' data-source-id='1'>"
                "<div class='dictionary-heading'><div class='src' data-dictionary='Sample dictionary' data-source-id='1'>Sample dictionary</div>"
                "<div class='term-metadata'><span class='frequency-badge' data-metadata-kind='frequency' data-dictionary='Frequency' data-source-id='2'><span class='frequency-source'>Frequency</span>"
                "<span class='frequency-values'>1234, 5678</span></span></div></div>"
                "<div class='reading-group'><div class='reading-column'><span class='r'>たべる</span></div>"
                "<div class='reading-definitions'><div class='term-metadata'><div class='pitch-source' data-metadata-kind='pitch' data-dictionary='Sample pitch dictionary' data-source-id='3'>"
                "<span class='metadata-source'>Sample pitch dictionary</span><span class='pitch-pattern'>"
                + render_pitch('たべる', 2) + "<span>[2]</span></span></div></div>"
                "<div class='def'><div class='g'>to eat<br>to live on</div></div></div></div></div></div>"
            )
            kanji_sample = (
                "<div class='kanji-card'><div class='kanji-head'>"
                "<div class='kanji-char'>食</div><div class='kanji-main'>"
                "<div class='kanji-meaning'>eat; food; meal</div>"
                "<div class='kanji-row'><span class='kanji-label'>On:</span> ショク, ジキ</div>"
                "<div class='kanji-row'><span class='kanji-label'>Kun:</span> た.べる, く.う</div>"
                "<div class='kanji-row'><span class='kanji-label'>Tags:</span> common-use kanji</div>"
                "<div class='kanji-meta'><span class='kanji-pill'>strokes: 9</span>"
                "<span class='kanji-pill'>grade: 2</span><span class='kanji-pill'>jlpt: N5</span>"
                "<span class='kanji-pill'>freq: 328</span></div>"
                "<div class='kanji-src'>KANJIDIC2</div></div></div></div>"
            )
            page = _get_popup_tpl().replace('{{ROWS}}', sample).replace('{{THEME}}', POPUP_THEME)
            # Preview the layout without running popup handlers or auto audio.
            page = re.sub(r'<script\b[^>]*>[\s\S]*?</script\s*>', '', page, flags=re.I)
            page = page.replace(
                '<div id="kanji-body" class="kanji-list"></div>',
                '<div id="kanji-body" class="kanji-list">' + kanji_sample + '</div>',
            )
            if preview_mode.currentData() == 'kanji':
                page = page.replace(
                    '<div class="tab active" data-tab="result" title="Search">',
                    '<div class="tab" data-tab="result" title="Search">',
                )
                page = page.replace(
                    '<div class="tab" id="tab-kanji" data-tab="kanji" title="Kanji" style="display:none">',
                    '<div class="tab active" id="tab-kanji" data-tab="kanji" title="Kanji">',
                )
                page = page.replace(
                    '<div class="panel active" id="panel-result">',
                    '<div class="panel" id="panel-result" hidden aria-hidden="true">',
                )
                page = page.replace(
                    '<div class="panel" id="panel-kanji" hidden aria-hidden="true">',
                    '<div class="panel active" id="panel-kanji">',
                )
            css = json.dumps(editor.toPlainText()).replace('<', '\\u003c').replace('>', '\\u003e')
            page += "<script>var s=document.createElement('style');s.textContent=" + css + ";document.head.appendChild(s);</script>"
            preview.setHtml(page)

        preview_timer = QTimer(dlg)
        preview_timer.setSingleShot(True)
        preview_timer.setInterval(300)
        preview_timer.timeout.connect(refresh_preview)
        editor.textChanged.connect(preview_timer.start)
        preview_mode.currentIndexChanged.connect(lambda _index: refresh_preview())

        row = QHBoxLayout()
        layout.addLayout(row)
        reset = QPushButton('Reset', dlg)
        reset.clicked.connect(lambda: (editor.clear(), refresh_preview()))
        row.addWidget(reset)
        example_btn = QPushButton('Insert Example', dlg)
        example_btn.setToolTip('Replace the editor with a complete CSS example.')
        def insert_example(css_text):
            editor.setPlainText(css_text)
            refresh_preview()
        example_menu = QMenu(example_btn)
        original_action = example_menu.addAction('Original theme starter')
        colorful_action = example_menu.addAction('Colorful stress test')
        original_action.triggered.connect(lambda _checked=False: insert_example(example_css))
        colorful_action.triggered.connect(lambda _checked=False: insert_example(colorful_css))
        example_btn.setMenu(example_menu)
        row.addWidget(example_btn)
        preview_btn = QPushButton('Preview', dlg)
        preview_btn.setEnabled(preview is not None)
        preview_btn.clicked.connect(refresh_preview)
        row.addWidget(preview_btn)
        row.addStretch(1)
        cancel = QPushButton('Cancel', dlg)
        cancel.clicked.connect(dlg.reject)
        row.addWidget(cancel)
        save = QPushButton('Save CSS', dlg)
        self._style_primary_save(save)
        def save_css():
            global CUSTOM_CSS
            CUSTOM_CSS = editor.toPlainText()
            _save_config()
            _inject()
            dlg.accept()
        save.clicked.connect(save_css)

        row.addWidget(save)
        dlg._yomilens_editor = editor
        dlg._yomilens_preview = preview
        dlg._yomilens_refresh_preview = refresh_preview
        dlg._yomilens_refresh_presets = refresh_presets
        refresh_preview()
        dlg.exec()
        preview_timer.stop()
        dlg._yomilens_geometry = dlg.saveGeometry()
        if preview is not None:
            preview.hide()
            preview.setGeometry(0, 0, 1, 1)
        dlg.hide()
        dlg.move(-10000, -10000)
        self.raise_()
        self.activateWindow()

    def _build_general_tab(self, QCheckBox):
        from aqt.qt import QScrollArea, QGridLayout, QComboBox, QSpinBox, QPalette
        global LANG_PROFILE, HANZI_WRITER, PREFER_KANJI_ON_CLICK, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE, HOVER_SHIFT_MODE, POPUP_THEME, POPUP_WIDTH, POPUP_HEIGHT
        w = QWidget(self)
        v = QVBoxLayout(w)
        muted_color = w.palette().color(QPalette.ColorRole.PlaceholderText).name()
        v.addWidget(QLabel("Open popup for selected languages:"))

        # Scrollable grid of checkboxes — 2 columns
        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(360)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(4)
        scroll.setWidget(inner)
        v.addWidget(scroll)
        scroll_hint = QLabel("Scroll to see and select more languages.", w)
        scroll_hint.setStyleSheet(f"color:{muted_color};font-size:12px")
        v.addWidget(scroll_hint)

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

        cb_prefer_kanji = QCheckBox("Open clicked kanji in Kanji tab", w)
        cb_prefer_kanji.setChecked(bool(PREFER_KANJI_ON_CLICK))
        cb_prefer_kanji.setToolTip(
            "Looks up the clicked character normally, then opens its Kanji tab. "
            "Requires an enabled KANJIDIC/kanji dictionary."
        )
        v.addWidget(cb_prefer_kanji)
        kanji_note = QLabel("Requires an installed and enabled KANJIDIC/kanji dictionary.", w)
        kanji_note.setStyleSheet(f"color:{muted_color};font-size:12px;margin-left:22px")
        v.addWidget(kanji_note)

        trigger_row = QHBoxLayout()
        trigger_row.addWidget(QLabel("Trigger key:", w))
        trigger_combo = QComboBox(w)
        trigger_options = [
            ("None", "none"),
            ("Option / Alt", "alt"),
            ("Ctrl", "ctrl"),
            ("Shift", "shift"),
            ("Cmd / Win", "meta"),
        ]
        for label, value in trigger_options:
            trigger_combo.addItem(label, value)
        current_idx = next((i for i, (_label, value) in enumerate(trigger_options) if value == POPUP_TRIGGER_MOD), 0)
        trigger_combo.setCurrentIndex(current_idx)
        trigger_combo.setToolTip(
            "None opens after selecting text. Other options require holding that key while selecting, "
            "or pressing it after selecting text. Option on macOS is Alt on Windows/Linux."
        )
        trigger_row.addWidget(trigger_combo, 1)
        v.addLayout(trigger_row)

        cb_hover_shift = QCheckBox("Hook + Shift mode (hover + hold Shift to open popup)", w)
        cb_hover_shift.setChecked(bool(HOVER_SHIFT_MODE))
        cb_hover_shift.setToolTip(
            "When enabled, hovering over text while holding Shift will automatically "
            "look up the word under the cursor without needing to select/highlight text first."
        )
        v.addWidget(cb_hover_shift)

        sublookup_row = QHBoxLayout()
        sublookup_row.addWidget(QLabel("Popup lookup behavior:", w))
        sublookup_combo = QComboBox(w)
        sublookup_options = [
            ("Reuse current popup", "reuse"),
            ("Open nested popup", "nested"),
            ("Disable", "disabled"),
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

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Popup theme:", w))
        theme_combo = QComboBox(w)
        theme_options = [
            ("Default (Warm Sepia)", "default"),
            ("Tetsuryo Ink", "aux_bluets"),
            ("Emerald Spring", "emerald_spring"),
            ("Showa Matcha", "showa_matcha"),
            ("Sakura City Pop", "sakura_city_pop"),
            ("Aka Slate", "sakura_night"),
            ("Deep Sea Terminal", "lotus_noir"),
            ("Nord Frost", "violet_circuit"),
        ]
        for label, value in theme_options:
            theme_combo.addItem(label, value)
        theme_idx = next((i for i, (_label, value) in enumerate(theme_options) if value == POPUP_THEME), 0)
        theme_combo.setCurrentIndex(theme_idx)
        theme_combo.setToolTip(
            "Select the visual theme for your popup lookup window."
        )
        theme_row.addWidget(theme_combo, 1)
        v.addLayout(theme_row)
        pitch_row = QHBoxLayout()
        pitch_row.addWidget(QLabel('Pitch accent style:', w))
        pitch_combo = QComboBox(w)
        pitch_combo.addItem('Graph', 'graph')
        pitch_combo.addItem('Compact', 'compact')
        pitch_combo.setCurrentIndex(1 if PITCH_STYLE == 'compact' else 0)
        pitch_row.addWidget(pitch_combo, 1)
        v.addLayout(pitch_row)
        css_button = QPushButton('Custom CSS...', w)
        css_button.clicked.connect(self._edit_custom_css)
        v.addWidget(css_button)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Popup width (px):", w))
        width_spin = QSpinBox(w)
        width_spin.setRange(200, 1200)
        width_spin.setValue(POPUP_WIDTH)
        size_row.addWidget(width_spin, 1)

        size_row.addWidget(QLabel("Popup height (px):", w))
        height_spin = QSpinBox(w)
        height_spin.setRange(200, 1200)
        height_spin.setValue(POPUP_HEIGHT)
        size_row.addWidget(height_spin, 1)

        reset_btn = QPushButton("Reset size", w)
        reset_btn.setToolTip("Reset popup dimensions back to default (380x350 px)")
        def reset_size():
            width_spin.setValue(380)
            height_spin.setValue(350)
        reset_btn.clicked.connect(reset_size)
        size_row.addWidget(reset_btn)

        v.addLayout(size_row)

        save = QPushButton("Save Language Settings", w)
        self._style_primary_save(save)
        v.addWidget(save)
        apply_note = QLabel(
            "Saved settings are applied to the current review screen immediately when possible. "
            "For the most reliable result, restart Anki after saving.",
            w,
        )
        apply_note.setWordWrap(True)
        apply_note.setStyleSheet(f"color:{muted_color};font-size:12px")
        v.addWidget(apply_note)
        v.addStretch(1)

        def on_save():
            global LANG_PROFILE, HANZI_WRITER, PREFER_KANJI_ON_CLICK, POPUP_LANGS, POPUP_TRIGGER_MOD, POPUP_SUBLOOKUP_MODE, HOVER_SHIFT_MODE, POPUP_THEME, POPUP_WIDTH, POPUP_HEIGHT
            POPUP_LANGS = [code for code, cb_l in lang_cbs.items() if cb_l.isChecked()]
            if not POPUP_LANGS:
                POPUP_LANGS = ["zh"]
            LANG_PROFILE = _lang_profile_from_popup_langs()
            HANZI_WRITER = bool(cb_hw.isChecked())
            PREFER_KANJI_ON_CLICK = bool(cb_prefer_kanji.isChecked())
            POPUP_TRIGGER_MOD = str(trigger_combo.currentData() or "none")
            POPUP_SUBLOOKUP_MODE = str(sublookup_combo.currentData() or "reuse")
            HOVER_SHIFT_MODE = bool(cb_hover_shift.isChecked())
            global PITCH_STYLE
            PITCH_STYLE = str(pitch_combo.currentData() or 'graph')
            POPUP_THEME = str(theme_combo.currentData() or "default")
            POPUP_WIDTH = int(width_spin.value())
            POPUP_HEIGHT = int(height_spin.value())
            _save_config()
            _inject()
            tooltip(
                f'Popup languages: {", ".join(POPUP_LANGS)} | Trigger: {trigger_combo.currentText()} | '
                f'Lookup: {sublookup_combo.currentText()} | Theme: {theme_combo.currentText()} | '
                f'Size: {f"{POPUP_WIDTH}x{POPUP_HEIGHT}px" if (POPUP_WIDTH or POPUP_HEIGHT) else "Auto"} | '
                f'Hook+Shift: {"ON" if HOVER_SHIFT_MODE else "OFF"} | '
                f'HanziWriter: {"ON" if HANZI_WRITER else "OFF"}',
                period=1600,
            )
        save.clicked.connect(on_save)
        return w

    def _build_web_lookup_tab(self):
        from aqt.qt import QScrollArea, QGridLayout, QComboBox, QCheckBox, QPalette
        w = QWidget(self)
        palette = w.palette()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        muted_color = palette.color(QPalette.ColorRole.PlaceholderText).name()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        intro = QLabel(
            "Choose which language each dictionary source should query. "
            "Use Auto when the source title is clear enough for YomiLens to guess.",
            w,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{text_color};font-size:12px")
        v.addWidget(intro)

        hint_row = QHBoxLayout()
        refresh_hint = QLabel(
            "Just installed dictionaries? Click Refresh to load the new sources here.",
            w,
        )
        refresh_hint.setWordWrap(True)
        refresh_hint.setStyleSheet(f"color:{muted_color};font-size:12px")
        hint_row.addWidget(refresh_hint, 1)
        refresh_btn = QPushButton("Refresh", w)
        refresh_btn.setToolTip("Reload dictionary sources for this tab.")
        def refresh_web_lookup_tab():
            try:
                _db_open()
            except Exception:
                pass
            tabs = getattr(self, "tabs", None)
            if tabs:
                idx = tabs.indexOf(w)
                if idx >= 0:
                    tabs.removeTab(idx)
                    w.deleteLater()
                    tabs.insertTab(idx, self._build_web_lookup_tab(), "Web Lookup")
                    tabs.setCurrentIndex(idx)
            tooltip("Web lookup sources refreshed", period=1200)
        refresh_btn.clicked.connect(refresh_web_lookup_tab)
        hint_row.addWidget(refresh_btn)
        v.addLayout(hint_row)

        toggles = QFrame(w)
        toggle_row = QHBoxLayout(toggles)
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(18)
        cb_audio = QCheckBox("Show audio button", toggles)
        cb_auto_speak = QCheckBox("Auto speak", toggles)
        cb_yg = QCheckBox("Show YG button", toggles)
        cb_img = QCheckBox("Show IMG button", toggles)
        cb_audio.setChecked(bool(WEB_AUDIO_ENABLED))
        cb_auto_speak.setChecked(bool(WEB_AUTO_SPEAK_ENABLED))
        cb_yg.setChecked(bool(WEB_YG_ENABLED))
        cb_img.setChecked(bool(WEB_IMG_ENABLED))
        cb_audio.setToolTip("Show the Google audio button beside popup terms.")
        cb_auto_speak.setToolTip("Automatically play the first popup term when a popup opens.")
        cb_yg.setToolTip("Show the YouGlish button beside popup terms.")
        cb_img.setToolTip("Show the Google Images button beside popup terms.")
        for cb in (cb_audio, cb_auto_speak, cb_yg, cb_img):
            toggle_row.addWidget(cb)
        toggle_row.addStretch(1)
        v.addWidget(toggles)

        try:
            if DB is None:
                _db_open()
            cur = DB.execute("SELECT id,title,enabled FROM source ORDER BY priority ASC, id ASC")
            sources = [{"id": int(r[0]), "title": r[1] or "", "enabled": int(r[2] or 0)} for r in cur.fetchall()]
        except Exception:
            sources = []

        yg_combos = {}
        google_combos = {}
        audio_combos = {}
        if not sources:
            empty = QLabel(
                "No dictionary sources found yet. If you already installed dictionaries, click Refresh above.",
                w,
            )
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{muted_color}")
            v.addWidget(empty)
            v.addStretch(1)
        else:
            header = QFrame(w)
            header.setObjectName("webLookupHeader")
            header.setStyleSheet(
                f"QFrame#webLookupHeader{{border:none;border-bottom:1px solid {muted_color};"
                "background:transparent}"
                f"QLabel{{color:{text_color};background:transparent;border:none}}"
            )
            header_grid = QGridLayout(header)
            header_grid.setContentsMargins(4, 8, 18, 8)
            header_grid.setHorizontalSpacing(18)
            header_grid.setColumnStretch(0, 3)
            header_grid.setColumnStretch(1, 2)
            header_grid.setColumnStretch(2, 2)
            header_grid.setColumnStretch(3, 2)

            src_head = QLabel("<b>Dictionary source</b>", header)
            yg_head = QLabel("<b>YouGlish</b>", header)
            google_head = QLabel("<b>Google audio / IMG</b>", header)
            audio_head = QLabel("<b>Audio voice</b>", header)
            for head in (src_head, yg_head, google_head, audio_head):
                head.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                head.setMinimumHeight(28)
            yg_head.setMinimumWidth(150)
            google_head.setMinimumWidth(150)
            audio_head.setMinimumWidth(150)
            header_grid.addWidget(src_head, 0, 0)
            header_grid.addWidget(yg_head, 0, 1)
            header_grid.addWidget(google_head, 0, 2)
            header_grid.addWidget(audio_head, 0, 3)
            v.addWidget(header, 0)

            scroll = QScrollArea(w)
            scroll.setWidgetResizable(True)
            inner = QWidget()
            grid = QGridLayout(inner)
            grid.setContentsMargins(4, 8, 18, 8)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(8)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(0, 3)
            grid.setColumnStretch(1, 2)
            grid.setColumnStretch(2, 2)
            grid.setColumnStretch(3, 2)
            scroll.setWidget(inner)
            v.addWidget(scroll, 1)

            for row, source in enumerate(sources):
                title = source["title"]
                sid = str(source["id"])
                source_label = QLabel(title + ("" if source["enabled"] else " (disabled)"), inner)
                source_label.setWordWrap(True)
                source_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                source_label.setStyleSheet(
                    f"color:{text_color}" if source["enabled"] else f"color:{muted_color}"
                )

                yg_combo = QComboBox(inner)
                for label, slug, _google_hl in YOUGLISH_LANGUAGES:
                    yg_combo.addItem(label, slug)
                current_yg = YOUGLISH_SOURCE_LANGS.get(sid, "auto")
                yg_idx = next((i for i, (_label, slug, _hl) in enumerate(YOUGLISH_LANGUAGES) if slug == current_yg), 0)
                yg_combo.setCurrentIndex(yg_idx)
                yg_combo.setMinimumWidth(150)

                google_combo = QComboBox(inner)
                for label, code, _google_hl in GOOGLE_LANGUAGES:
                    google_combo.addItem(label, code)
                current_google = GOOGLE_SOURCE_LANGS.get(sid, "auto")
                google_idx = next((i for i, (_label, code, _hl) in enumerate(GOOGLE_LANGUAGES) if code == current_google), 0)
                google_combo.setCurrentIndex(google_idx)
                google_combo.setMinimumWidth(150)

                audio_combo = QComboBox(inner)
                for label, code in GOOGLE_AUDIO_VOICES:
                    audio_combo.addItem(label, code)
                current_audio = GOOGLE_AUDIO_SOURCE_LANGS.get(sid, "auto")
                audio_idx = next((i for i, (_label, code) in enumerate(GOOGLE_AUDIO_VOICES) if code == current_audio), 0)
                audio_combo.setCurrentIndex(audio_idx)
                audio_combo.setMinimumWidth(150)

                def mirror_google_from_yg(_idx, yg=yg_combo, google=google_combo, audio=audio_combo):
                    code = YOUGLISH_LANG_BY_SLUG.get(str(yg.currentData() or "auto"), ("", "auto"))[1]
                    if str(google.currentData() or "auto") == "auto" and code in GOOGLE_LANG_BY_CODE:
                        match = next((i for i, (_label, gcode, _hl) in enumerate(GOOGLE_LANGUAGES) if gcode == code), 0)
                        google.setCurrentIndex(match)
                    if str(audio.currentData() or "auto") == "auto":
                        audio_code = code if code in GOOGLE_AUDIO_VOICE_CODES else ""
                        if not audio_code:
                            audio_code = next((vcode for _label, vcode in GOOGLE_AUDIO_VOICES if vcode != "auto" and vcode.startswith(code + "-")), "")
                        if audio_code:
                            match = next((i for i, (_label, vcode) in enumerate(GOOGLE_AUDIO_VOICES) if vcode == audio_code), 0)
                            audio.setCurrentIndex(match)
                yg_combo.currentIndexChanged.connect(mirror_google_from_yg)

                def mirror_audio_from_google(_idx, google=google_combo, audio=audio_combo):
                    code = str(google.currentData() or "auto")
                    if str(audio.currentData() or "auto") == "auto" and code != "auto":
                        audio_code = code if code in GOOGLE_AUDIO_VOICE_CODES else ""
                        if not audio_code:
                            audio_code = next((vcode for _label, vcode in GOOGLE_AUDIO_VOICES if vcode != "auto" and vcode.startswith(code + "-")), "")
                        if audio_code:
                            match = next((i for i, (_label, vcode) in enumerate(GOOGLE_AUDIO_VOICES) if vcode == audio_code), 0)
                            audio.setCurrentIndex(match)
                google_combo.currentIndexChanged.connect(mirror_audio_from_google)

                yg_combos[sid] = yg_combo
                google_combos[sid] = google_combo
                audio_combos[sid] = audio_combo
                grid.addWidget(source_label, row, 0)
                grid.addWidget(yg_combo, row, 1)
                grid.addWidget(google_combo, row, 2)
                grid.addWidget(audio_combo, row, 3)

        save = QPushButton("Save Web Lookup Settings", w)
        self._style_primary_save(save)
        v.addWidget(save)
        note = QLabel(
            "YouGlish controls the YG button. Google controls IMG. Audio voice controls Google TTS/accent.",
            w,
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{muted_color};font-size:12px")
        v.addWidget(note)

        def on_save():
            global YOUGLISH_SOURCE_LANGS, GOOGLE_SOURCE_LANGS, GOOGLE_AUDIO_SOURCE_LANGS, WEB_AUDIO_ENABLED, WEB_YG_ENABLED, WEB_IMG_ENABLED, WEB_AUTO_SPEAK_ENABLED
            WEB_AUDIO_ENABLED = bool(cb_audio.isChecked())
            WEB_AUTO_SPEAK_ENABLED = bool(cb_auto_speak.isChecked())
            WEB_YG_ENABLED = bool(cb_yg.isChecked())
            WEB_IMG_ENABLED = bool(cb_img.isChecked())
            new_yg_map = {}
            for sid, combo in yg_combos.items():
                slug = str(combo.currentData() or "auto")
                if slug and slug in YOUGLISH_LANG_BY_SLUG:
                    new_yg_map[sid] = slug
            new_google_map = {}
            for sid, combo in google_combos.items():
                code = str(combo.currentData() or "auto")
                if code and code in GOOGLE_LANG_BY_CODE:
                    new_google_map[sid] = code
            new_audio_map = {}
            for sid, combo in audio_combos.items():
                code = str(combo.currentData() or "auto")
                if code and code in GOOGLE_AUDIO_VOICE_CODES:
                    new_audio_map[sid] = code
            YOUGLISH_SOURCE_LANGS = new_yg_map
            GOOGLE_SOURCE_LANGS = new_google_map
            GOOGLE_AUDIO_SOURCE_LANGS = new_audio_map
            _save_config()
            tooltip("Web lookup settings saved", period=1500)

        save.clicked.connect(on_save)
        return w

    def _build_guide_tab(self, initial_page=None):
        from aqt.qt import QGridLayout, QPalette, QPixmap, QScrollArea, QSizePolicy, QTabWidget
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        guide_tabs = QTabWidget(w)
        layout.addWidget(guide_tabs)

        palette = w.palette()
        card_bg = palette.color(QPalette.ColorRole.Base).name()
        alt_bg = palette.color(QPalette.ColorRole.AlternateBase).name()
        text = palette.color(QPalette.ColorRole.Text).name()
        muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
        border = palette.color(QPalette.ColorRole.Mid).name()

        whats_scroll = QScrollArea(guide_tabs)
        whats_scroll.setWidgetResizable(True)
        whats_scroll.setFrameShape(QFrame.Shape.NoFrame)
        whats_content = QWidget(whats_scroll)
        whats_layout = QVBoxLayout(whats_content)
        whats_layout.setContentsMargins(18, 16, 18, 18)
        whats_layout.setSpacing(12)
        whats_scroll.setWidget(whats_content)

        hero = QFrame(whats_content)
        hero.setStyleSheet(
            "QFrame{background:#0b5cad;border:0;border-radius:8px}"
            "QLabel{color:white;background:transparent;border:0}"
        )
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 14, 20, 14)
        kicker = QLabel("YOMILENS · LATEST UPDATE", hero)
        kicker.setStyleSheet("font-size:11px;font-weight:700;color:#cfe7ff")
        title = QLabel("More useful context, right inside Anki.", hero)
        title.setStyleSheet("font-size:22px;font-weight:700")
        intro = QLabel(
            "This update adds frequency and pitch-accent data, Anki Export, Custom CSS, "
            "persistent popup resizing, and a dedicated guide hub.",
            hero,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:13px;color:#e7f3ff")
        hero_layout.addWidget(kicker)
        hero_layout.addWidget(title)
        hero_layout.addWidget(intro)
        whats_layout.addWidget(hero)

        def add_update_card(title_text, body, setup, image_name=None):
            card = QFrame(whats_content)
            card.setStyleSheet(
                f"QFrame{{background:{card_bg};border:1px solid {border};border-radius:7px}}"
                f"QLabel{{background:transparent;border:0;color:{text}}}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 11, 14, 13)
            card_layout.setSpacing(7)
            card_title = QLabel(title_text, card)
            card_title.setStyleSheet("font-size:17px;font-weight:700;color:#0b5cad")
            card_body = QLabel(body, card)
            card_body.setWordWrap(True)
            card_body.setStyleSheet(f"font-size:13px;color:{text}")
            card_layout.addWidget(card_title)
            card_layout.addWidget(card_body)
            if image_name:
                image = QLabel(card)
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                pixmap = QPixmap(os.path.join(ADDON_DIR, "update_assets", image_name))
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        640, 300, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    image.setPixmap(pixmap)
                    image.setFixedHeight(pixmap.height())
                    card_layout.addWidget(image)
            setup_label = QLabel("<b>SETUP</b> &nbsp;" + setup, card)
            setup_label.setWordWrap(True)
            setup_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setup_label.setStyleSheet(
                f"background:{alt_bg};border-left:4px solid #0b5cad;padding:8px;"
                f"font-size:12px;color:{text}"
            )
            card_layout.addWidget(setup_label)
            whats_layout.addWidget(card)

        add_update_card(
            "Frequency + Pitch Accent",
            "Import Yomitan frequency and pitch-accent dictionaries. Matching metadata is "
            "grouped with the correct reading and can use either a graph or compact notation.",
            "Open <b>Dictionaries</b> to import the ZIP files. Choose the pitch display style "
            "from <b>General</b>.",
            "frequency-pitch.jpg",
        )
        add_update_card(
            "Anki Export",
            "Create notes from popup results with configurable field mappings, source-card fields, "
            "YomiLens blanks, or native Anki cloze syntax.",
            "Open <b>Anki Export</b>, choose a deck and note type, map the fields, save, then "
            "click the star beside a popup result.",
            "anki-export.jpg",
        )
        add_update_card(
            "Custom CSS",
            "Restyle dictionary results, Kanji entries, metadata badges, and action buttons with "
            "a live preview, starter examples, and your own saved presets.",
            "Open <b>General</b>, launch <b>Custom CSS</b>, select a starter or write your own CSS, "
            "then save it as a preset.",
            "custom-css.jpg",
        )
        add_update_card(
            "Persistent Popup Resizing",
            "Drag the popup to the size that fits your cards. YomiLens remembers the new dimensions "
            "instead of reverting to the old setting.",
            "Resize a popup directly, or set exact width and height values in <b>General</b>.",
            "popup-resize.jpg",
        )
        add_update_card(
            "Feature Guides",
            "The Guide tab and YomiLens website now collect setup instructions for these features "
            "and the rest of the add-on in one place.",
            "Use <b>Guide → Feature Guides</b>, or open the web guide below whenever you need a walkthrough.",
            "feature-guides.jpg",
        )

        feedback = QLabel(
            "<b>Built with community feedback</b><br>"
            "Many of these improvements began as user reports and requests, and more "
            "feedback-driven features are planned for future releases.<br><br>"
            "Thank you to everyone who reported issues and shared feedback through "
            "GitHub and Anki. Your suggestions continue to shape YomiLens.",
            whats_content,
        )
        feedback.setWordWrap(True)
        feedback.setOpenExternalLinks(True)
        feedback.setStyleSheet(
            f"background:{alt_bg};border-left:4px solid #0b5cad;padding:10px;"
            f"font-size:12px;color:{text}"
        )
        whats_layout.addWidget(feedback)

        guide_actions = QHBoxLayout()
        browse_guides = QPushButton("Browse Feature Guides", whats_content)
        open_web_guides = QPushButton("Open Web Guides", whats_content)
        for button in (browse_guides, open_web_guides):
            button.setMinimumHeight(38)
            button.setAutoDefault(False)
            button.setDefault(False)
            try:
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            except Exception:
                button.setFocusPolicy(Qt.NoFocus)
            guide_actions.addWidget(button)
        whats_layout.addLayout(guide_actions)
        whats_layout.addStretch(1)

        guides_scroll = QScrollArea(guide_tabs)
        guides_scroll.setWidgetResizable(True)
        guides_scroll.setFrameShape(QFrame.Shape.NoFrame)
        guides_page = QWidget(guides_scroll)
        guides_layout = QVBoxLayout(guides_page)
        guides_layout.setContentsMargins(20, 18, 20, 20)
        heading = QLabel("YomiLens feature guides", guides_page)
        heading.setStyleSheet("font-size:18px;font-weight:600;")
        guides_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(12)
        guides = [
            ("Popup lookup", "popup-lookup"),
            ("Anki Export", "anki-export"),
            ("Google Images", "google-images"),
            ("YouGlish", "youglish"),
            ("Audio", "audio"),
            ("Frequency dictionaries", "frequency"),
            ("Pitch accent", "pitch-accent"),
            ("Custom CSS", "custom-css"),
            ("Themes", "themes"),
            ("Hook + Shift", "hook-shift"),
            ("Nested popups", "nested-popups"),
            ("Kanji tab", "kanji-tab"),
            ("Hanzi Writer", "hanzi-writer"),
            ("Popup resizing", "popup-resize"),
            ("Add to DB", "add-to-db"),
        ]
        for index, (label, slug) in enumerate(guides):
            button = QPushButton(label, guides_page)
            button.setMinimumHeight(40)
            button.setAutoDefault(False)
            button.setDefault(False)
            try:
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            except Exception:
                button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip("Open " + label + " guide in your browser")
            button.clicked.connect(
                lambda checked=False, guide_slug=slug: QDesktopServices.openUrl(
                    QUrl("https://marshng.github.io/Yomilens/guides/" + guide_slug + "/")
                )
            )
            grid.addWidget(button, index // 2, index % 2)
        guides_layout.addLayout(grid)
        guides_layout.addStretch(1)
        guides_scroll.setWidget(guides_page)
        guide_tabs.addTab(guides_scroll, "Feature Guides")
        guide_tabs.addTab(whats_scroll, "What's New")
        browse_guides.clicked.connect(lambda: guide_tabs.setCurrentIndex(0))
        open_web_guides.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://marshng.github.io/Yomilens/guides/"))
        )
        if initial_page == "whats-new":
            guide_tabs.setCurrentIndex(1)
        return w

    def _build_about_tab(self):
        from aqt.qt import QPalette
        w = QWidget(self)
        palette = w.palette()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        muted_color = palette.color(QPalette.ColorRole.PlaceholderText).name()
        link_color = palette.color(QPalette.ColorRole.Link).name()
        border_color = palette.color(QPalette.ColorRole.Mid).name()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        v.setContentsMargins(24, 24, 24, 24)
        v.addStretch(1)

        title = QLabel("YomiLens Popup Dictionary", w)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:18px;font-weight:bold;color:{text_color}")
        v.addWidget(title)

        desc = QLabel(
            "A quick lookup lens for Anki — hover any word to look it up.\n"
            "Supports Chinese, Japanese, English, and more.", w
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f"font-size:13px;color:{muted_color};")
        desc.setWordWrap(True)
        v.addWidget(desc)

        sep = QFrame(w)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{border_color};margin:4px 40px")
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
            f'style="color:{link_color};font-size:12px">GitHub: MarshNg/yomilens-dictionaries</a>', w
        )
        github_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_lbl.setOpenExternalLinks(True)
        v.addWidget(github_lbl)

        credits = QLabel(
            f'<div style="font-size:11px;color:{text_color};line-height:1.45;text-align:left;">'
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
            'MongoDB english-words-definitions (Apache 2.0), ipa-dict (MIT).<br>'
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


    def _build_anki_tab(self):
        from aqt.qt import QScrollArea, QComboBox, QLineEdit, QGridLayout, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        global ANKI_DECK, ANKI_NOTE_TYPE, ANKI_FIELD_MAP, ANKI_REMOVE_HTML, ANKI_CLOZE_TERM
        from aqt.qt import QCheckBox
        w = QWidget(self)
        v = QVBoxLayout(w)
        
        info = QLabel(
            "<b>Set up Anki Export in three steps:</b><br>"
            "1. Choose the deck and note type you want to create.<br>"
            "2. For each field, enter what YomiLens should insert, such as "
            "<b>{term}</b>, <b>{reading}</b>, <b>{gloss}</b>, <b>{selection}</b>, "
            "or <b>{FieldName}</b> to copy an existing card field.<br>"
            "3. Save these settings, then click the <b>star (Add to Anki)</b> beside a popup result.<br>"
            "Use <b>{Cloze:FieldName}</b> for a YomiLens blank, or "
            "<b>{AnkiCloze:FieldName}</b> for Anki's native <b>{{c1::term}}</b> cloze syntax "
            "(the target note type must support Anki cloze deletions)."
        )
        info.setWordWrap(True)
        v.addWidget(info)

        guide_btn = QPushButton("Open Anki Export Guide", w)
        guide_btn.setMinimumHeight(36)
        guide_btn.setAutoDefault(False)
        guide_btn.setDefault(False)
        try:
            guide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            guide_btn.setFocusPolicy(Qt.NoFocus)
        guide_btn.setToolTip("Open the full Anki Export guide in your browser")
        guide_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://marshng.github.io/Yomilens/guides/anki-export/")
            )
        )
        guide_row = QHBoxLayout()
        guide_row.addWidget(guide_btn)
        guide_row.addStretch(1)
        v.addLayout(guide_row)
        
        h_deck = QHBoxLayout()
        h_deck.addWidget(QLabel("Target Deck:"))
        self.cb_deck = QComboBox()
        self.cb_deck.addItems(mw.col.decks.all_names())
        if ANKI_DECK: self.cb_deck.setCurrentText(ANKI_DECK)
        h_deck.addWidget(self.cb_deck, 1)
        v.addLayout(h_deck)
        
        h_model = QHBoxLayout()
        h_model.addWidget(QLabel("Target Note Type:"))
        self.cb_model = QComboBox()
        self.cb_model.addItems([m['name'] for m in mw.col.models.all()])
        if ANKI_NOTE_TYPE: self.cb_model.setCurrentText(ANKI_NOTE_TYPE)
        h_model.addWidget(self.cb_model, 1)
        v.addLayout(h_model)
        

        self.chk_remove_html = QCheckBox("Remove HTML tags (e.g. <b>) from copied fields")
        self.chk_remove_html.setChecked(bool(ANKI_REMOVE_HTML))
        v.addWidget(self.chk_remove_html)
        

        
        self.fields_scroll = QScrollArea()

        self.fields_scroll.setWidgetResizable(True)
        self.fields_inner = QWidget()
        self.fields_layout = QGridLayout(self.fields_inner)
        self.fields_layout.setContentsMargins(12, 10, 12, 10)
        self.fields_layout.setHorizontalSpacing(16)
        self.fields_layout.setVerticalSpacing(10)
        self.fields_layout.setColumnStretch(0, 1)
        self.fields_layout.setColumnStretch(1, 1)
        self.fields_scroll.setWidget(self.fields_inner)
        v.addWidget(self.fields_scroll, 1)
        
        self.field_inputs = {}
        def update_fields():
            while self.fields_layout.count():
                item = self.fields_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            self.field_inputs.clear()
            
            m_name = self.cb_model.currentText()
            if not m_name: return
            model = mw.col.models.by_name(m_name)
            if not model: return
            
            for index, f in enumerate(model['flds']):
                fname = f['name']
                field_cell = QWidget(self.fields_inner)
                field_layout = QVBoxLayout(field_cell)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(3)
                field_layout.addWidget(QLabel(fname, field_cell))
                le = QLineEdit(field_cell)
                le.setPlaceholderText("e.g. {term}, {Sentence}, {Cloze:Sentence}, {AnkiCloze:Sentence}")
                if ANKI_NOTE_TYPE == m_name and fname in ANKI_FIELD_MAP:
                    le.setText(ANKI_FIELD_MAP[fname])
                field_layout.addWidget(le)
                self.fields_layout.addWidget(field_cell, index // 2, index % 2)
                self.field_inputs[fname] = le
                
        self.cb_model.currentTextChanged.connect(update_fields)
        update_fields()
        
        save_btn = QPushButton("Save Anki Settings")
        self._style_primary_save(save_btn)
        def save_anki():
            global ANKI_DECK, ANKI_NOTE_TYPE, ANKI_FIELD_MAP, ANKI_REMOVE_HTML, ANKI_CLOZE_TERM
            ANKI_DECK = self.cb_deck.currentText()
            ANKI_NOTE_TYPE = self.cb_model.currentText()
            ANKI_FIELD_MAP = {fname: le.text().strip() for fname, le in self.field_inputs.items()}
            _save_config()
            from aqt.utils import tooltip
            tooltip("Anki Export Settings Saved!")
        save_btn.clicked.connect(save_anki)
        v.addWidget(save_btn)
        return w

    def _build_changelog_tab(self):

        """Create a tab displaying the changelog markdown as scrollable HTML."""
        from aqt.qt import QScrollArea, QTextEdit
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        # Load changelog file
        try:
            with open(os.path.join(ADDON_DIR, "CHANGELOG.md"), "r", encoding="utf-8") as f:
                md_content = f.read()
        except Exception:
            md_content = "(No changelog available)"
        # Simple markdown to HTML conversion (newlines -> <br>)
        html = md_content.replace("\n", "<br>")
        txt = QTextEdit(w)
        txt.setReadOnly(True)
        txt.setHtml(html)
        txt.setStyleSheet("background:#fafafa;color:#222;font-size:13px")
        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setWidget(txt)
        layout.addWidget(scroll, 1)
        return w

        
    def _build_database_tab(self):
        from aqt.qt import (QScrollArea, QFrame, QProgressBar,
                            QSizePolicy, QFont, QPalette)
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        page_scroll = QScrollArea(root)
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root_layout.addWidget(page_scroll)

        w = QWidget(page_scroll)
        page_scroll.setWidget(w)
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        palette = w.palette()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        muted_color = palette.color(QPalette.ColorRole.PlaceholderText).name()
        surface_color = palette.color(QPalette.ColorRole.Base).name()
        border_color = palette.color(QPalette.ColorRole.Mid).name()

        # ── DB stats + management buttons ─────────────────────────────────
        self.stats_label = QLabel(_db_stats_text(), w)
        self.stats_label.setStyleSheet(
            f"color:{muted_color};font-size:12px;margin-bottom:4px"
        )
        v.addWidget(self.stats_label)

        restart_box = QFrame(w)
        restart_box.setStyleSheet(
            "QFrame{background:#fff8e8;border:1px solid #e4c78f;border-radius:6px}"
            "QLabel{background:transparent;border:none;color:#6b542d;font-size:12px}"
        )
        restart_row = QHBoxLayout(restart_box)
        restart_row.setContentsMargins(9, 7, 9, 7)
        restart_notice = QLabel(
            "<b>Tip:</b> After changing dictionaries, restart Anki before using YomiLens again.",
            restart_box,
        )
        restart_notice.setWordWrap(True)
        restart_row.addWidget(restart_notice)
        v.addWidget(restart_box)

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

        import_progress_box = QFrame(w)
        import_progress_box.setStyleSheet(
            f"QFrame{{background:{surface_color};border:1px solid {border_color};border-radius:6px}}"
            f"QLabel{{background:transparent;border:none;color:{text_color};font-size:12px}}"
        )
        import_progress_layout = QVBoxLayout(import_progress_box)
        import_progress_layout.setContentsMargins(10, 8, 10, 8)
        import_progress_layout.setSpacing(5)
        import_progress_label = QLabel("Preparing dictionary...", import_progress_box)
        import_progress_label.setWordWrap(True)
        import_progress_bar = QProgressBar(import_progress_box)
        import_progress_bar.setRange(0, 100)
        import_progress_bar.setValue(0)
        import_progress_bar.setTextVisible(True)
        import_progress_bar.setMinimumHeight(18)
        import_progress_layout.addWidget(import_progress_label)
        import_progress_layout.addWidget(import_progress_bar)
        import_progress_box.hide()
        v.addWidget(import_progress_box)

        def update_manual_import_progress(pct, message):
            import_progress_box.show()
            import_progress_bar.setValue(max(0, min(100, int(pct))))
            import_progress_label.setText(message)

        def finish_manual_import(success, message):
            import_zip.setEnabled(True)
            import_progress_label.setText(("✓ " if success else "Import failed: ") + message.replace("Import failed: ", ""))
            import_progress_label.setStyleSheet(
                "color:#238636;font-weight:600" if success else "color:#c62828;font-weight:600"
            )
            refresh_stats()

        def run_manual_import():
            import_progress_label.setStyleSheet(f"color:{text_color}")
            import_progress_bar.setValue(0)
            import_progress_box.show()
            import_zip.setEnabled(False)
            _action_db_import_zip(update_manual_import_progress, finish_manual_import)
            if import_progress_bar.value() == 0 and import_progress_label.text() == "Preparing dictionary...":
                import_progress_box.hide()
                import_zip.setEnabled(True)

        import_zip.clicked.connect(run_manual_import)

        more_dicts_box = QFrame(w)
        more_dicts_box.setStyleSheet(
            f"QFrame{{background:{surface_color};border:1px solid {border_color};border-radius:6px}}"
            f"QLabel{{background:transparent;border:none;color:{text_color};font-size:12px}}"
            "QPushButton{padding:4px 10px;font-size:11px}"
        )
        more_dicts_row = QHBoxLayout(more_dicts_box)
        more_dicts_row.setContentsMargins(10, 7, 8, 7)
        more_dicts_row.setSpacing(10)
        more_dicts_text = QLabel(
            "Looking for another language? Download a Yomitan dictionary ZIP, "
            "then install it here with <b>Import ZIP</b>.",
            more_dicts_box,
        )
        more_dicts_text.setWordWrap(True)
        more_dicts_btn = QPushButton("Browse Dictionaries", more_dicts_box)
        more_dicts_btn.setMinimumHeight(28)
        more_dicts_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/MarvNC/yomitan-dictionaries")
            )
        )
        more_dicts_row.addWidget(more_dicts_text, 1)
        more_dicts_row.addWidget(more_dicts_btn, 0)
        v.addWidget(more_dicts_box)

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
        self._dl_status.setStyleSheet(f"color:{muted_color};font-size:12px")
        v.addWidget(self._dl_status)

        # The whole tab scrolls, so this list grows with its cards instead of
        # introducing a second nested scrollbar on smaller screens.
        scroll_inner = QWidget()
        self._dl_cards_layout = QVBoxLayout(scroll_inner)
        self._dl_cards_layout.setSpacing(8)
        self._dl_cards_layout.setContentsMargins(2, 4, 6, 4)
        self._dl_cards_layout.addStretch(1)
        v.addWidget(scroll_inner)

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

        def set_status(msg, color=None):
            self._dl_status.setText(msg)
            self._dl_status.setStyleSheet(
                f"color:{color or muted_color};font-size:11px"
            )

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
            lbl.setStyleSheet(
                f"color:{text_color};margin-top:10px;margin-bottom:4px;padding-left:2px"
            )
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
                f"QFrame#dictCard{{border:1px solid {border_color};border-radius:6px;"
                f"background:{surface_color}}}"
                "QFrame#dictCard QLabel{border:none;background:transparent}"
            )
            h = QHBoxLayout(card)
            h.setContentsMargins(14, 12, 14, 12)
            h.setSpacing(14)

            # left: text
            txt = QVBoxLayout()
            txt.setSpacing(4)
            title_lbl = QLabel(f"<b style='font-size:13px;color:{text_color}'>{title}</b>"
                               f"&nbsp;&nbsp;<span style='color:{muted_color};font-size:12px'>"
                               f"{size_mb} MB</span>", card)
            title_lbl.setTextFormat(Qt.TextFormat.RichText)
            desc_lbl = QLabel(desc, card)
            desc_lbl.setStyleSheet(
                f"color:{muted_color};font-size:12px;border:none"
            )
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
            prog_pct.setStyleSheet(
                f"font-size:11px;color:{muted_color};border:none;background:transparent"
            )
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
                        _db_after_dictionary_change()
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
        return root

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

class _WhatsNewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        from aqt.qt import QCheckBox, QPalette, QPixmap, QScrollArea, QSizePolicy, QTimer

        self._QPixmap = QPixmap
        self._QTimer = QTimer
        self.setWindowTitle("What's New in YomiLens")
        self.resize(780, 640)
        self.setMinimumSize(640, 500)

        palette = self.palette()
        card_bg = palette.color(QPalette.ColorRole.Base).name()
        text = palette.color(QPalette.ColorRole.Text).name()
        muted = palette.color(QPalette.ColorRole.PlaceholderText).name()
        border = palette.color(QPalette.ColorRole.Mid).name()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 10)
        root.setSpacing(0)

        hero = QFrame(self)
        hero.setObjectName("whatsNewHero")
        hero.setStyleSheet(
            "#whatsNewHero { background:#0b5cad; border:0; }"
            "#whatsNewHero QLabel { color:white; background:transparent; }"
        )
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 16, 24, 16)
        kicker = QLabel("YOMILENS · MAJOR UPDATE", hero)
        kicker.setStyleSheet("font-size:12px;font-weight:700;color:#cfe7ff")
        title = QLabel("Look up more. Leave Anki less.", hero)
        title.setStyleSheet("font-size:24px;font-weight:750")
        intro = QLabel(
            "Web Lookup, new themes, Hook + Shift, and nested popups are ready. "
            "Here is the quick tour and exactly where to turn each feature on.",
            hero,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size:14px;color:#e7f3ff")
        hero_layout.addWidget(kicker)
        hero_layout.addWidget(title)
        hero_layout.addWidget(intro)
        root.addWidget(hero)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 16, 18, 16)
        content_layout.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        def image_label(filename, max_width=640, max_height=440):
            label = QLabel(content)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            path = os.path.join(ADDON_DIR, "update_assets", filename)
            pixmap = self._QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    max_width,
                    max_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                label.setPixmap(pixmap)
                label.setFixedHeight(pixmap.height())
            else:
                label.setText("Preview unavailable")
                label.setStyleSheet(f"color:{muted};padding:20px")
            return label

        def feature_card(number, title_text, badge, body, setup_html, image_name=None, callouts=None):
            card = QFrame(content)
            card.setObjectName(f"featureCard{number}")
            card.setStyleSheet(
                f"#{card.objectName()} {{ background:{card_bg}; border:1px solid {border}; "
                "border-radius:8px; }}"
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 14, 16, 16)
            box.setSpacing(8)

            heading = QLabel(
                f"<span style='color:#0b5cad;font-weight:800'>0{number}</span> "
                f"<span style='font-size:18px;font-weight:750;color:{text}'>{title_text}</span> "
                f"<span style='color:#0b5cad;font-size:12px;font-weight:700'>{badge}</span>",
                card,
            )
            box.addWidget(heading)
            desc = QLabel(body, card)
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color:{text};font-size:14px")
            box.addWidget(desc)

            if image_name:
                box.addWidget(image_label(image_name))

            if callouts:
                callout_row = QHBoxLayout()
                callout_row.setSpacing(8)
                for callout_title, callout_body in callouts:
                    callout = QLabel(
                        f"<b style='color:#0b5cad'>↑ {callout_title}</b><br>"
                        f"<span style='color:{muted}'>{callout_body}</span>",
                        card,
                    )
                    callout.setWordWrap(True)
                    callout.setAlignment(Qt.AlignmentFlag.AlignTop)
                    callout.setStyleSheet(
                        f"background:{palette.color(QPalette.ColorRole.AlternateBase).name()};"
                        f"border:1px solid {border};border-radius:6px;padding:9px"
                    )
                    callout_row.addWidget(callout, 1)
                box.addLayout(callout_row)

            setup = QLabel(
                f"<div style='color:{text}'><b style='color:#0b5cad'>SETUP</b> &nbsp;{setup_html}</div>",
                card,
            )
            setup.setWordWrap(True)
            setup.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            setup.setStyleSheet(
                f"background:{palette.color(QPalette.ColorRole.AlternateBase).name()};"
                f"border-left:4px solid #0b5cad;padding:10px;font-size:13px;color:{text}"
            )
            box.addWidget(setup)
            content_layout.addWidget(card)
            return card

        feature_card(
            1,
            "Web Lookup",
            "NEW",
            "Keep pronunciation, real-world video examples, and visual context inside your study flow.",
            "Open <b>Tools → YomiLens Settings → Web Lookup</b>. Click <b>Refresh</b> after installing "
            "dictionaries, enable the buttons you want, choose a language/voice for each source, then "
            "click <b>Save Web Lookup Settings</b>.",
            "web-lookup.png",
            [
                ("Speaker", "Play Google audio using the language and voice assigned to that dictionary."),
                ("YG", "Open YouGlish examples for the term in the selected language."),
                ("IMG", "Open Google Images with the same language hint for visual context."),
            ],
        )

        themes = feature_card(
            2,
            "Themes + Dark Mode",
            "8 STYLES",
            "Choose a warm paper look, graphic retro ink, or a dark palette designed to stay readable in Anki dark mode.",
            "Open <b>Tools → YomiLens Settings → General</b>, scroll to <b>Popup theme</b>, choose a "
            "theme, and click <b>Save Language Settings</b>. Try <b>Deep Sea Terminal</b>, "
            "<b>Aka Slate</b>, or <b>Nord Frost</b> for dark mode.",
        )
        theme_gallery = QHBoxLayout()
        theme_gallery.setSpacing(12)
        theme_gallery.addWidget(image_label("theme-deep-sea.png", 300, 300), 1)
        theme_gallery.addWidget(image_label("theme-aka-slate.png", 300, 300), 1)
        themes.layout().insertLayout(2, theme_gallery)

        feature_card(
            3,
            "Hook + Shift",
            "FASTER LOOKUP",
            "Look up the word under your pointer without selecting it first: hover, hold Shift, and YomiLens hooks the term.",
            "Open <b>Tools → YomiLens Settings → General</b>, enable <b>Hook + Shift mode</b>, "
            "then click <b>Save Language Settings</b>. During review, place the pointer over a word and hold "
            "<b>Shift</b>. You can still use normal selection lookup alongside it.",
        )

        feature_card(
            4,
            "Nested Popup",
            "LOOK UP INSIDE LOOKUP",
            "Select a word inside a dictionary result to open a child popup while keeping the original entry in place.",
            "Open <b>Tools → YomiLens Settings → General</b>. Set <b>Popup lookup behavior</b> to "
            "<b>Open nested popup</b>, then save. Select text inside an open popup to create the child; "
            "its <b>×</b> closes only the child popup.",
            "nested-popup.png",
        )

        content_layout.addStretch(1)

        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 0)
        self.dismiss_checkbox = QCheckBox("Don't show this update again", footer)
        self.dismiss_checkbox.setChecked(DISMISSED_WHATS_NEW_VERSION == WHATS_NEW_VERSION)
        footer_layout.addWidget(self.dismiss_checkbox)
        footer_layout.addStretch(1)
        settings_btn = QPushButton("Open Settings", footer)
        settings_btn.setMinimumHeight(36)
        settings_btn.clicked.connect(self._open_settings)
        got_it = QPushButton("Got it", footer)
        got_it.setMinimumHeight(36)
        got_it.setDefault(True)
        got_it.setStyleSheet(
            "QPushButton { background:#0b5cad;color:white;border:1px solid #084b8d;"
            "border-radius:6px;padding:7px 20px;font-weight:700; }"
            "QPushButton:hover { background:#126fc9; }"
        )
        got_it.clicked.connect(self.accept)
        footer_layout.addWidget(settings_btn)
        footer_layout.addWidget(got_it)
        root.addWidget(footer)

        self.finished.connect(self._save_dismissal)

    def _save_dismissal(self, _result):
        global DISMISSED_WHATS_NEW_VERSION
        DISMISSED_WHATS_NEW_VERSION = (
            WHATS_NEW_VERSION if self.dismiss_checkbox.isChecked() else ""
        )
        _save_config()

    def _open_settings(self):
        self.accept()
        self._QTimer.singleShot(0, _action_yomi_settings)


def _show_whats_new(force=False):
    global DISMISSED_WHATS_NEW_VERSION
    if not force and DISMISSED_WHATS_NEW_VERSION == WHATS_NEW_VERSION:
        return
    if not force and getattr(mw, "_yomilens_whats_new_shown", False):
        return
    mw._yomilens_whats_new_shown = True
    DISMISSED_WHATS_NEW_VERSION = WHATS_NEW_VERSION
    _save_config()
    _action_yomi_settings(initial_tab="guide", initial_guide_page="whats-new")



def _action_yomi_settings(initial_tab=None, initial_guide_page=None):
    from aqt.qt import QApplication
    dlg = _YomiSettingsDialog(
        mw,
        initial_tab=initial_tab,
        initial_guide_page=initial_guide_page,
    )
    try:
        dlg.exec()
    finally:
        dlg.deleteLater()
        QApplication.processEvents()
        mw.raise_()
        mw.activateWindow()
        mw.web.setFocus()

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

    from aqt.qt import QTimer
    QTimer.singleShot(1200, _show_whats_new)

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

def cleanup_on_exit():
    global _server
    try:
        wins = getattr(mw, "_yomilens_web_popups", None)
        if wins:
            for w in list(wins):
                try:
                    w.close()
                except Exception:
                    pass
            wins.clear()
    except Exception:
        pass

    if _server:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
        _server = None
    _db_close()

gui_hooks.profile_will_close.append(cleanup_on_exit)

if mw and mw.app:
    try:
        mw.app.aboutToQuit.connect(cleanup_on_exit)
    except Exception:
        pass

# Hook AddonManager cleanup points to release database file locks on Windows when deleting/updating.
try:
    from aqt.addons import AddonManager
    _addon_dir_name = os.path.basename(ADDON_DIR)

    if not hasattr(AddonManager, "_old_backupUserFiles_yomilens") and hasattr(AddonManager, "backupUserFiles"):
        AddonManager._old_backupUserFiles_yomilens = AddonManager.backupUserFiles

        def _yomilens_backup_user_files(self, *args, **kwargs):
            target = str(args[0]) if args else ""
            if target == _addon_dir_name or os.path.basename(target) == _addon_dir_name:
                cleanup_on_exit()
            return self._old_backupUserFiles_yomilens(*args, **kwargs)

        AddonManager.backupUserFiles = _yomilens_backup_user_files

    if not hasattr(AddonManager, "_old_deleteAddon_hanzi_popup"):
        AddonManager._old_deleteAddon_hanzi_popup = AddonManager.deleteAddon

        def _my_delete_addon(self, dir_name):
            if dir_name == _addon_dir_name:
                cleanup_on_exit()
            return self._old_deleteAddon_hanzi_popup(dir_name)

        AddonManager.deleteAddon = _my_delete_addon
except Exception:
    pass
