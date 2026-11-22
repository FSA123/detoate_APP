import unicodedata


def search_key(text):
    """
    Forma normalizată pentru căutare: fără diacritice, litere mici, spații
    simple. „Roșii  CHERRY” → „rosii cherry”, ca la casă să meargă și
    tastat fără diacritice. Acoperă și ş/ţ cu sedilă (tastaturi vechi).
    """
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def like_escape(text):
    """Escapează caracterele speciale LIKE, pentru folosire cu ESCAPE '\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
