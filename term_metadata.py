"""Yomitan term metadata storage and compact popup rendering."""
import html
import json
import math
import re
import unicodedata


def reading_key(value):
    value = unicodedata.normalize('NFKC', value or '')
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in value)


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS term_metadata (
        term TEXT NOT NULL, reading TEXT NOT NULL, kind TEXT NOT NULL,
        data TEXT NOT NULL, source_id INTEGER NOT NULL
        REFERENCES source(id) ON DELETE CASCADE,
        UNIQUE(term, reading, kind, data, source_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_term_metadata_term ON term_metadata(term)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_term_metadata_source ON term_metadata(source_id)')


def import_bank(db, text, source_id):
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError('Metadata bank must contain an array')
    rows = []
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 3:
            continue
        term, kind, data = entry
        if not isinstance(term, str) or not term or kind not in ('freq', 'pitch'):
            continue
        reading = data.get('reading', '') if isinstance(data, dict) else ''
        if not isinstance(reading, str):
            continue
        if kind == 'freq':
            value = data.get('frequency', data) if isinstance(data, dict) else data
            if isinstance(value, dict):
                value = value.get('value')
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                continue
            if isinstance(value, (int, float)) and not math.isfinite(value):
                continue
        elif not isinstance(data, dict) or not reading or not isinstance(data.get('pitches'), list):
            continue
        rows.append((term, reading_key(reading), kind, json.dumps(data, ensure_ascii=False), source_id))
    before = db.total_changes
    db.executemany('INSERT OR IGNORE INTO term_metadata VALUES(?,?,?,?,?)', rows)
    return db.total_changes - before


def morae(reading):
    result = []
    for char in reading_key(reading):
        if char in 'ゃゅょぁぃぅぇぉゎ' and result:
            result[-1] += char
        else:
            result.append(char)
    return result


def pitch_graph(reading, position):
    units = morae(reading)
    count = len(units)
    if not count or count > 64 or isinstance(position, bool):
        return ''
    if isinstance(position, int) and 0 <= position <= count:
        levels = [('H' if (i == 0 if position == 1 else i > 0 and (position == 0 or i < position)) else 'L')
                  for i in range(count + 1)]
        suffix = True
    elif isinstance(position, str) and re.fullmatch('[HL]+', position) and len(position) in (count, count + 1):
        levels = list(position)
        suffix = len(levels) == count + 1
    else:
        return ''
    width = max(48, len(levels) * 28)
    points = [(14 + i * 28, 10 if level == 'H' else 29) for i, level in enumerate(levels)]
    path = ' '.join('{},{}'.format(x, y) for x, y in points)
    label = '{} [{}]'.format(reading, position)
    parts = ['<svg class="pitch-graph" role="img" aria-label="{}" viewBox="0 0 {} 56" width="{}" height="56">'.format(html.escape(label, quote=True), width, width),
             '<polyline points="{}" fill="none" stroke="currentColor" stroke-width="2"/>'.format(path)]
    for i, (x, y) in enumerate(points):
        is_suffix = suffix and i == count
        parts.append('<circle cx="{}" cy="{}" r="3" fill="{}" stroke="currentColor"/>'.format(x, y, 'var(--bg)' if is_suffix else 'currentColor'))
        if not is_suffix:
            parts.append('<text x="{}" y="51" text-anchor="middle" fill="currentColor">{}</text>'.format(x, html.escape(units[i])))
    return ''.join(parts) + '</svg>'


def pitch_compact(reading, position):
    units = morae(reading)
    count = len(units)
    if not pitch_graph(reading, position):
        return ''
    if isinstance(position, int):
        levels = [('H' if (i == 0 if position == 1 else i > 0 and (position == 0 or i < position)) else 'L')
                  for i in range(count + 1)]
    else:
        levels = list(position)
    parts = []
    for i, unit in enumerate(units):
        high = levels[i] == 'H'
        drop = high and i + 1 < len(levels) and levels[i + 1] == 'L'
        classes = 'pitch-mora' + (' pitch-high' if high else '') + (' pitch-drop' if drop else '')
        parts.append('<span class="{}">{}</span>'.format(classes, html.escape(unit)))
    return '<span class="pitch-compact" role="img" aria-label="{}">{}</span>'.format(
        html.escape('{} [{}]'.format(reading, position), quote=True), ''.join(parts))


def render_metadata(db, term, readings, only_kind=None, pitch_style='graph'):
    if db is None:
        return ''
    accepted = {reading_key(r or term) for r in readings}
    rows = db.execute('''SELECT m.kind,m.reading,m.data,s.title,s.id FROM term_metadata m
        JOIN source s ON s.id=m.source_id WHERE m.term=? AND s.enabled=1
        ORDER BY s.priority,s.id,m.rowid''', (term,)).fetchall()
    parts = []
    frequencies = {}
    seen = set()
    for kind, reading, raw, source, source_id in rows:
        if only_kind and kind != only_kind:
            continue
        if reading and reading not in accepted:
            continue
        data = json.loads(raw)
        source_html = html.escape(source)
        source_attr = html.escape(source, quote=True)
        if kind == 'freq':
            value = data.get('frequency', data) if isinstance(data, dict) else data
            if isinstance(value, dict):
                value = value.get('displayValue', str(value['value']))
            values = frequencies.setdefault((source_id, source), [])
            value = str(value)
            if value not in values:
                values.append(value)
            continue
        else:
            graphs = []
            for pitch in data.get('pitches', []):
                if not isinstance(pitch, dict):
                    continue
                render_pitch = pitch_compact if pitch_style == 'compact' else pitch_graph
                graph = render_pitch(data['reading'], pitch.get('position'))
                if graph:
                    tags = pitch.get('tags', [])
                    tag_text = ' '.join(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else ''
                    graphs.append('<span class="pitch-pattern">{}<span>[{}] {}</span></span>'.format(graph, html.escape(str(pitch['position'])), html.escape(tag_text)))
            if not graphs:
                continue
            markup = (
                '<div class="pitch-source" data-metadata-kind="pitch" '
                'data-dictionary="{}" data-source-id="{}">'
                '<span class="metadata-source">{}</span>{}</div>'
            ).format(source_attr, source_id, source_html, ''.join(graphs))
        if markup not in seen:
            seen.add(markup)
            parts.append(markup)
    badges = [
        '<span class="frequency-badge" data-metadata-kind="frequency" '
        'data-dictionary="{}" data-source-id="{}">'
        '<span class="frequency-source">{}</span><span class="frequency-values">{}</span></span>'.format(
            html.escape(source, quote=True), sid, html.escape(source), html.escape(', '.join(values)))
        for (sid, source), values in frequencies.items()
    ]
    parts = badges + parts
    return '<div class="term-metadata">{}</div>'.format(''.join(parts)) if parts else ''
