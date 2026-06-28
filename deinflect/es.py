# -*- coding: utf-8 -*-
"""
Spanish lemmatizer (verb conjugation + noun/adj inflection).
Spanish has very regular verb morphology (-ar/-er/-ir verbs).
"""

IRREGULAR = {
    # ser
    "soy":"ser","eres":"ser","es":"ser","somos":"ser","sois":"ser","son":"ser",
    "era":"ser","eras":"ser","éramos":"ser","erais":"ser","eran":"ser",
    "fui":"ser","fuiste":"ser","fue":"ser","fuimos":"ser","fuisteis":"ser","fueron":"ser",
    "sido":"ser","siendo":"ser",
    # estar
    "estoy":"estar","estás":"estar","está":"estar","estamos":"estar","estáis":"estar","están":"estar",
    "estaba":"estar","estuve":"estar","estuvo":"estar","estado":"estar",
    # haber
    "he":"haber","has":"haber","ha":"haber","hemos":"haber","habéis":"haber","han":"haber",
    "había":"haber","hubo":"haber","habrá":"haber","habido":"haber",
    # tener
    "tengo":"tener","tienes":"tener","tiene":"tener","tenemos":"tener","tenéis":"tener","tienen":"tener",
    "tenía":"tener","tuve":"tener","tuvo":"tener","tendrá":"tener","tenido":"tener",
    # ir
    "voy":"ir","vas":"ir","va":"ir","vamos":"ir","vais":"ir","van":"ir",
    "iba":"ir","fui":"ir","fue":"ir","ido":"ir","yendo":"ir",
    # hacer
    "hago":"hacer","haces":"hacer","hace":"hacer","hacemos":"hacer","hacéis":"hacer","hacen":"hacer",
    "hacía":"hacer","hice":"hacer","hizo":"hacer","hará":"hacer","hecho":"hacer",
    # poder
    "puedo":"poder","puedes":"poder","puede":"poder","podemos":"poder","podéis":"poder","pueden":"poder",
    "podía":"poder","pudo":"poder","podrá":"poder","podido":"poder",
    # decir
    "digo":"decir","dices":"decir","dice":"decir","decimos":"decir","decís":"decir","dicen":"decir",
    "decía":"decir","dije":"decir","dijo":"decir","dirá":"decir","dicho":"decir","diciendo":"decir",
    # querer
    "quiero":"querer","quieres":"querer","quiere":"querer","queremos":"querer","queréis":"querer","quieren":"querer",
    "quería":"querer","quiso":"querer","querrá":"querer","querido":"querer",
    # saber
    "sé":"saber","sabes":"saber","sabe":"saber","sabemos":"saber","sabéis":"saber","saben":"saber",
    "sabía":"saber","supo":"saber","sabrá":"saber","sabido":"saber",
}

# Suffix rules: (to_strip, to_add)
RULES = [
    # ─── -ar: present indicative ───
    ("amos",    "ar"), ("áis",     "ar"), ("an",      "ar"),
    ("as",      "ar"), ("a",       "ar"), ("o",       "ar"),

    # ─── -ar: imperfect ───
    ("abamos",  "ar"), ("abais",   "ar"), ("aban",    "ar"),
    ("abas",    "ar"), ("aba",     "ar"),

    # ─── -ar: preterite ───
    ("asteis",  "ar"), ("aron",    "ar"), ("aste",    "ar"),
    ("é",       "ar"),

    # ─── -ar: future/conditional ───
    ("aré",     "ar"), ("arás",    "ar"), ("ará",     "ar"),
    ("aremos",  "ar"), ("aréis",   "ar"), ("arán",    "ar"),
    ("aría",    "ar"),

    # ─── -ar: participle ───
    ("adas",    "ar"), ("ados",    "ar"), ("ada",     "ar"), ("ado",     "ar"),

    # ─── -ar: gerund ───
    ("ando",    "ar"),

    # ─── -er: present ───
    ("emos",    "er"), ("éis",     "er"), ("en",      "er"),
    ("es",      "er"), ("e",       "er"),

    # ─── -er: imperfect ───
    ("íamos",   "er"), ("íais",    "er"), ("ían",     "er"),
    ("ías",     "er"), ("ía",      "er"),

    # ─── -er: preterite ───
    ("isteis",  "er"), ("ieron",   "er"), ("iste",    "er"), ("ió",      "er"),

    # ─── -er: participle ───
    ("idas",    "er"), ("idos",    "er"), ("ida",     "er"), ("ido",     "er"),

    # ─── -er: gerund ───
    ("iendo",   "er"),

    # ─── -ir: present ───
    ("imos",    "ir"), ("ís",      "ir"),
    ("es",      "ir"), ("e",       "ir"),

    # ─── -ir: preterite ───
    ("isteis",  "ir"), ("ieron",   "ir"), ("iste",    "ir"), ("ió",      "ir"),

    # ─── -ir: participle ───
    ("idas",    "ir"), ("idos",    "ir"), ("ida",     "ir"), ("ido",     "ir"),

    # ─── -ir: gerund ───
    ("iendo",   "ir"),

    # ─── Noun/adj: gender + number ───
    ("iones",   "ión"),  # canciones → canción
    ("eces",    "ez"),   # veces → vez
    ("ces",     "z"),    # voces → voz
    ("as",      "a"),
    ("os",      "o"),
    ("es",      ""),
    ("s",       ""),
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
    # Latin + Spanish accented chars (á é í ó ú ü ñ ¿ ¡ stripped in pick)
    return ch.isalpha() and (ch.isascii() or ord(ch) < 0x0250)
