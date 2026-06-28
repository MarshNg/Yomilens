
# -*- coding: utf-8 -*-
# Yomichan/Yomitan exporter for Hanzi Popup add-on
import os, json, sqlite3, time, zipfile, math

def _detect_db_path(addon_dir):
    # try common names
    for name in ("yomi_index.db", "yomichan.db", "yomi.db"):
        p = os.path.join(addon_dir, name)
        if os.path.exists(p):
            return p
    # fallback: first .db in addon dir
    for fname in os.listdir(addon_dir):
        if fname.endswith(".db"):
            return os.path.join(addon_dir, fname)
    raise FileNotFoundError("Không tìm thấy file DB (yomi_index.db) trong thư mục add-on.")

def _rows_from_db(db_path, selected_titles=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if selected_titles:
        q = "SELECT s.title, t.term, t.reading, t.gloss FROM term t JOIN source s ON s.id=t.source_id WHERE s.title IN (%s)" % (
            ",".join("?"*len(selected_titles))
        )
        cur.execute(q, selected_titles)
    else:
        q = "SELECT s.title, t.term, t.reading, t.gloss FROM term t JOIN source s ON s.id=t.source_id WHERE s.enabled=1"
        cur.execute(q)
    for row in cur:
        yield dict(row)
    conn.close()

def _to_glossaries(gloss):
    if gloss is None:
        return []
    # split by newlines; strip empties
    lines = [s.strip() for s in str(gloss).splitlines()]
    lines = [s for s in lines if s]
    return lines if lines else [""]


def build_term_banks(rows, chunk_size=20000):
    """Yield (bank_index:int, entries:list[list]) for Yomitan v3
       Entry shape: [term, reading, definitionTags:str|null, rules:str|null, score:int, glossaries:list[str], sequence:int, termTags:str|null]
    """
    bucket, k = [], 1
    for r in rows:
        entry = [
            r.get("term",""),             # expression
            r.get("reading") or "",       # reading
            "",                           # definitionTags (space-separated) -> empty
            "",                           # deinflectionRules (legacy) -> empty
            0,                            # score
            _to_glossaries(r.get("gloss")),
            0,                            # sequence
            ""                           # termTags kept empty per user request
        ]
        bucket.append(entry)
        if len(bucket) >= max(1, int(chunk_size)):
            yield k, bucket
            k += 1
            bucket = []
    if bucket:
        yield k, bucket


def write_yomichan_zip(out_zip_path, addon_dir, selected_titles=None, chunk_size=20000, title=None, author=None, description=None):
    db_path = _detect_db_path(addon_dir)
    rows = list(_rows_from_db(db_path, selected_titles))
    # default meta
    if title is None:
        if selected_titles and len(selected_titles)==1:
            title = selected_titles[0]
        else:
            title = "Exported Dictionary"
    meta = {
        "title": title,
        "format": 3,
        "revision": str(int(time.time())),
    }
    if author: meta["author"] = author
    if description: meta["description"] = description

    with zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # index.json
        z.writestr("index.json", json.dumps(meta, ensure_ascii=False, separators=(",",":")))
        # term_banks
        for idx, entries in build_term_banks(rows, chunk_size=chunk_size):
            z.writestr(f"term_bank_{idx}.json", json.dumps(entries, ensure_ascii=False, separators=(",",":")))
    return out_zip_path, len(rows)
