"""Match a linked form to an existing page title.

Templates link display forms (Latin ``praeferō``, Old English ``ġiestrandæġ``)
while pages are titled by entry name (``praefero``). Wiktionary strips some
diacritics per language; rather than re-implementing every language's rules
we try, in order: exact title, then the title with combining marks removed.
The loose match is used only when it is unique, and never for
reconstructed languages, where diacritics are distinctive (ḱ ≠ k).
"""
import re
import unicodedata

# dotted/ligature letters Wiktionary drops from entry names (Old English ċ ġ, etc.)
EXTRA_FOLD = str.maketrans({"ċ": "c", "Ċ": "C", "ġ": "g", "Ġ": "G", "ȝ": "ȝ", "ꝥ": "þ"})
_SUFFIX_RE = re.compile(r"-[a-z]{2,5}$")


def is_reconstructed(lang):
    return lang.endswith("-pro")


def loose_key(title):
    t = unicodedata.normalize("NFD", title.translate(EXTRA_FOLD))
    return unicodedata.normalize("NFC", "".join(ch for ch in t if unicodedata.category(ch) != "Mn"))


def canonical_lang(code, known):
    """Map etymology-only codes (la-lat, la-vul, grc-koi, ...) to a language that has pages."""
    while code and code not in known and not is_reconstructed(code):
        stripped = _SUFFIX_RE.sub("", code)
        if stripped == code:
            break
        code = stripped
    return code


class TitleIndex:
    def __init__(self):
        self.exact = set()       # node keys "lang|title"
        self.loose = {}          # "lang|loosekey" -> title or None when ambiguous
        self.langs = set()

    def add(self, lang, title):
        self.langs.add(lang)
        self.exact.add(f"{lang}|{title}")
        if not is_reconstructed(lang):
            k = f"{lang}|{loose_key(title)}"
            prev = self.loose.get(k, title)
            self.loose[k] = title if prev == title else None

    def resolve(self, key):
        """Return (resolved_key, how) where how is 'exact', 'loose' or None (unresolved)."""
        lang, _, term = key.partition("|")
        lang = canonical_lang(lang, self.langs)
        k = f"{lang}|{term}"
        if k in self.exact:
            return k, "exact"
        if not is_reconstructed(lang):
            t = self.loose.get(f"{lang}|{loose_key(term)}")
            if t:
                return f"{lang}|{t}", "loose"
        return k, None
