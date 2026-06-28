# -*- coding: utf-8 -*-
"""
French lemmatizer (verb conjugation + noun/adjective inflection).
Generates base form candidates from conjugated/inflected surface forms.
"""

# Irregular verb map: conjugated → infinitive
IRREGULAR = {
    # être
    "suis":"être","es":"être","est":"être","sommes":"être","êtes":"être","sont":"être",
    "étais":"être","était":"être","étions":"être","étiez":"être","étaient":"être",
    "fus":"être","fut":"être","fûmes":"être","fûtes":"être","furent":"être",
    "serai":"être","seras":"être","sera":"être","serons":"être","serez":"être","seront":"être",
    "été":"être","étant":"être",
    # avoir
    "ai":"avoir","as":"avoir","a":"avoir","avons":"avoir","avez":"avoir","ont":"avoir",
    "avais":"avoir","avait":"avoir","avions":"avoir","aviez":"avoir","avaient":"avoir",
    "eus":"avoir","eut":"avoir","eûmes":"avoir","eûtes":"avoir","eurent":"avoir",
    "aurai":"avoir","auras":"avoir","aura":"avoir","aurons":"avoir","aurez":"avoir","auront":"avoir",
    "eu":"avoir","ayant":"avoir",
    # aller
    "vais":"aller","vas":"aller","va":"aller","allons":"aller","allez":"aller","vont":"aller",
    "allais":"aller","allait":"aller","irai":"aller","iras":"aller","ira":"aller",
    # faire
    "fais":"faire","fait":"faire","faisons":"faire","faites":"faire","font":"faire",
    "faisais":"faire","faisait":"faire","ferai":"faire","feras":"faire","fera":"faire",
    "fis":"faire","fit":"faire",
    # pouvoir
    "peux":"pouvoir","peut":"pouvoir","pouvons":"pouvoir","pouvez":"pouvoir","peuvent":"pouvoir",
    "pouvais":"pouvoir","pourrai":"pouvoir",
    # vouloir
    "veux":"vouloir","veut":"vouloir","voulons":"vouloir","voulez":"vouloir","veulent":"vouloir",
    "voulais":"vouloir","voudrai":"vouloir",
    # savoir
    "sais":"savoir","sait":"savoir","savons":"savoir","savez":"savoir","savent":"savoir",
    "savais":"savoir","saurai":"savoir","su":"savoir",
    # venir
    "viens":"venir","vient":"venir","venons":"venir","venez":"venir","viennent":"venir",
    "venais":"venir","viendrai":"venir","venu":"venir",
    # prendre
    "prends":"prendre","prend":"prendre","prenons":"prendre","prenez":"prendre","prennent":"prendre",
    "prenais":"prendre","prendrai":"prendre","pris":"prendre",
    # voir
    "vois":"voir","voit":"voir","voyons":"voir","voyez":"voir","voient":"voir",
    "voyais":"voir","verrai":"voir","vu":"voir",
    # dire
    "dis":"dire","dit":"dire","disons":"dire","dites":"dire","disent":"dire",
    "disais":"dire","dirai":"dire",
    # mettre
    "mets":"mettre","met":"mettre","mettons":"mettre","mettez":"mettre","mettent":"mettre",
    "mettais":"mettre","mettrai":"mettre","mis":"mettre",
    # partir
    "pars":"partir","part":"partir","partons":"partir","partez":"partir","partent":"partir",
}

# Suffix rules: (ending_to_strip, ending_to_add)
# Ordered longest-first within each category
RULES = [
    # ─── -er verbs: présent ───
    # -ger verbs (manger, ranger): mangeons → manger; -cer (commencer): commençons → commencer
    ("eons",    "er"),  # mangeons → manger
    ("çons",    "cer"), # commençons → commencer
    ("ons",     "er"), ("ez",      "er"), ("ent",     "er"),
    ("e",       "er"), ("es",      "er"),

    # ─── -er verbs: imparfait ───
    ("ais",     "er"), ("ait",     "er"), ("ions",    "er"),
    ("iez",     "er"), ("aient",   "er"),

    # ─── -er verbs: futur ───
    ("erai",    "er"), ("eras",    "er"), ("era",     "er"),
    ("erons",   "er"), ("erez",    "er"), ("eront",   "er"),

    # ─── -er verbs: passé composé / participe ───
    ("ées",     "er"), ("ée",      "er"), ("és",      "er"), ("é",       "er"),

    # ─── -ir verbs (type finir): présent ───
    ("issons",  "ir"), ("issez",   "ir"), ("issent",  "ir"),
    ("is",      "ir"), ("it",      "ir"),

    # ─── -ir verbs: participe ───
    ("ies",     "ir"), ("ie",      "ir"),

    # ─── -re verbs: présent ───
    ("ons",     "re"), ("ez",      "re"), ("ent",     "re"),
    ("s",       "re"),

    # ─── Noun/adj plurals ───
    ("aux",     "al"),   # journaux → journal, chevaux → cheval
    ("eaux",    "eau"),  # gâteaux → gâteau
    ("s",       ""),     # generic plural

    # ─── Adj agreement ───
    ("ves",     "f"),    # actives → actif
    ("nnes",    "n"),    # bonnes → bon
    ("tes",     "t"),    # petites → petit
    ("des",     "d"),
    ("ses",     "s"),
    ("es",      ""),
    ("e",       ""),
]

def candidates(surface: str, cap: int = 50):
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

    for suffix, repl in RULES:
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            base = s[:-len(suffix)] + repl
            add(base)
            if base in IRREGULAR:
                add(IRREGULAR[base])
        if len(out) >= cap:
            break

    return out

def keep_char(ch: str) -> bool:
    # Latin + Latin Extended (accented French chars)
    return ch.isalpha() and (ch.isascii() or ord(ch) < 0x0250)
