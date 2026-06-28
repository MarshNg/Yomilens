# -*- coding: utf-8 -*-
"""
German lemmatizer (verb conjugation + noun/adj inflection).
German infinitives end in -en (or -ern/-eln).
"""

IRREGULAR = {
    # sein
    "bin":"sein","bist":"sein","ist":"sein","sind":"sein","seid":"sein",
    "war":"sein","warst":"sein","waren":"sein","wart":"sein","wären":"sein",
    "gewesen":"sein",
    # haben
    "habe":"haben","hast":"haben","hat":"haben","haben":"haben","habt":"haben",
    "hatte":"haben","hattest":"haben","hatten":"haben","gehabt":"haben",
    # werden
    "werde":"werden","wirst":"werden","wird":"werden","werden":"werden","werdet":"werden",
    "wurde":"werden","wurdest":"werden","wurden":"werden","geworden":"werden",
    # gehen
    "gehe":"gehen","gehst":"gehen","geht":"gehen","gehen":"gehen","geht":"gehen",
    "ging":"gehen","gingst":"gehen","gingen":"gehen","gegangen":"gehen",
    # kommen
    "komme":"kommen","kommst":"kommen","kommt":"kommen",
    "kam":"kommen","kamst":"kommen","kamen":"kommen","gekommen":"kommen",
    # sehen
    "sehe":"sehen","siehst":"sehen","sieht":"sehen",
    "sah":"sehen","sahst":"sehen","sahen":"sehen","gesehen":"sehen",
    # wissen
    "weiß":"wissen","weißt":"wissen","wissen":"wissen",
    "wusste":"wissen","gewusst":"wissen",
    # können
    "kann":"können","kannst":"können","können":"können","könnt":"können",
    "konnte":"können","gekonnt":"können",
    # müssen
    "muss":"müssen","musst":"müssen","müssen":"müssen",
    "musste":"müssen","gemusst":"müssen",
    # wollen
    "will":"wollen","willst":"wollen","wollen":"wollen","wollt":"wollen",
    "wollte":"wollen","gewollt":"wollen",
    # dürfen
    "darf":"dürfen","darfst":"dürfen","dürfen":"dürfen","dürft":"dürfen",
    "durfte":"dürfen",
    # sollen
    "soll":"sollen","sollst":"sollen","sollen":"sollen","sollt":"sollen",
    "sollte":"sollen",
    # machen
    "mache":"machen","machst":"machen","macht":"machen",
    "machte":"machen","gemacht":"machen",
    # geben
    "gebe":"geben","gibst":"geben","gibt":"geben",
    "gab":"geben","gabst":"geben","gaben":"geben","gegeben":"geben",
    # nehmen
    "nehme":"nehmen","nimmst":"nehmen","nimmt":"nehmen",
    "nahm":"nehmen","genommen":"nehmen",
    # lassen
    "lasse":"lassen","lässt":"lassen","lässt":"lassen",
    "ließ":"lassen","gelassen":"lassen",
}

# Suffix rules: (to_strip, to_add)
RULES = [
    # ─── Verb: present ───
    ("est",     "en"),   # du arbeitest
    ("et",      "en"),   # er arbeitet
    ("st",      "en"),   # du gehst
    ("t",       "en"),   # er geht
    ("e",       "en"),   # ich gehe

    # ─── Verb: Konjunktiv II / preterite regular ───
    ("test",    "en"),   # du arbeitete→arbeiten
    ("ten",     "en"),   # sie arbeiteten
    ("te",      "en"),   # er arbeitete

    # ─── Verb: Partizip II (ge-...-t / ge-...-en) ───
    # ge- prefix removal + -t/-en: handled by suffix stripping
    ("t",       "en"),
    # ("en", "en"),   # already infinitive

    # ─── Noun: plural endings ───
    ("ungen",   "ung"),
    ("heiten",  "heit"),
    ("keiten",  "keit"),
    ("ungen",   "ung"),
    ("en",      ""),     # Frauen → Frau
    ("er",      ""),     # Bücher → Buch (approximate)
    ("e",       ""),     # Tage → Tag
    ("s",       ""),     # Autos → Auto
    ("n",       ""),     # Blumen → Blume

    # ─── Adj: inflected endings ───
    ("sten",    ""),     # ältesten → alt
    ("sten",    "en"),
    ("sten",    "er"),
    ("eren",    "er"),   # älteren → älter
    ("em",      ""),
    ("en",      ""),
    ("er",      ""),
    ("es",      ""),
    ("e",       ""),
]

# Common separable prefixes (from Yomitan de/grammar.js)
_SEPARABLE_PREFIXES = [
    "ab","an","auf","aus","bei","durch","ein","empor","entgegen","entlang",
    "fehl","fern","fest","fort","frei","heim","her","hin","hoch","los",
    "mit","nach","nieder","statt","um","vor","weg","weiter","wieder","zu",
    "zurück","zusammen",
]

def candidates(surface: str, cap: int = 60):
    s = (surface or "").strip().lower()
    if not s:
        return []
    out, seen = [], set()

    def add(x):
        if x and len(x) >= 2 and x not in seen:
            out.append(x); seen.add(x)

    add(s)
    if s in IRREGULAR:
        add(IRREGULAR[s])

    # ge- prefix: try removing for Partizip II
    if s.startswith("ge") and len(s) > 4:
        stem = s[2:]
        add(stem + "en")   # gemacht → machen
        add(stem)
        # separable Partizip II: ge + prefix + stem + en → prefix + stem + en
        for pref in _SEPARABLE_PREFIXES:
            if stem.startswith(pref) and len(stem) > len(pref) + 1:
                inner = stem[len(pref):]
                add(pref + inner + "en")   # e.g. geausgegeben → ausgeben

    # separable: aufgemacht → aufmachen; aufmacht → aufmachen
    for pref in _SEPARABLE_PREFIXES:
        if s.startswith(pref) and len(s) > len(pref) + 2:
            rest = s[len(pref):]
            # separable Partizip II: auf+ge+mach+t → aufmachen
            if rest.startswith("ge") and len(rest) > 3:
                inner = rest[2:]           # strip ge-
                for suffix, repl in RULES:
                    if inner.endswith(suffix) and len(inner) > len(suffix):
                        add(pref + inner[:-len(suffix)] + repl + "en")
                        add(pref + inner[:-len(suffix)] + repl)
            # present/past conjugated: aufmacht → aufmachen
            for suffix, repl in RULES:
                if rest.endswith(suffix) and len(rest) > len(suffix) + 1:
                    stem = rest[:-len(suffix)] + repl
                    add(pref + stem + "en")
                    add(pref + stem)
            if len(out) >= cap:
                break

    for suffix, repl in RULES:
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            base = s[:-len(suffix)] + repl
            add(base)
            add(base + "en")   # try infinitive
            if base in IRREGULAR:
                add(IRREGULAR[base])
        if len(out) >= cap:
            break

    return out

def keep_char(ch: str) -> bool:
    # Latin + German umlauts (ä ö ü ß)
    return ch.isalpha() and (ch.isascii() or ch in "äöüßÄÖÜ")
