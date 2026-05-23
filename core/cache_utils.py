import re
import unicodedata

# Palabras vacías en español e inglés
STOP_WORDS = {
    'que', 'es', 'un', 'una', 'el', 'la', 'los', 'las', 'de', 'del', 'en',
    'a', 'para', 'por', 'con', 'se', 'me', 'te', 'como', 'cuando', 'donde',
    'cual', 'cuales', 'mas', 'pero', 'si', 'no', 'hay', 'puedo', 'puedes',
    'what', 'is', 'a', 'an', 'the', 'of', 'in', 'to', 'for', 'how', 'when',
    'where', 'can', 'could', 'i', 'you', 'do', 'does', 'this', 'that', 'it',
}

SIMILARITY_THRESHOLD = 0.72   # 72% de palabras en común = misma pregunta
MIN_WORDS_FOR_FUZZY  = 4      # preguntas cortas requieren match exacto


def normalizar_pregunta(texto: str) -> str:
    """Normaliza una pregunta: minúsculas, sin acentos, sin puntuación, sin stop words."""
    t = texto.lower().strip()
    # Quitar acentos
    t = ''.join(c for c in unicodedata.normalize('NFKD', t) if not unicodedata.combining(c))
    # Quitar puntuación salvo espacios
    t = re.sub(r'[^\w\s]', ' ', t)
    # Quitar espacios múltiples
    t = re.sub(r'\s+', ' ', t).strip()
    # Quitar stop words
    words = [w for w in t.split() if w not in STOP_WORDS and len(w) > 1]
    # Ordenar alfabéticamente para que el orden no importe
    return ' '.join(sorted(words))


def similitud(a: str, b: str) -> float:
    """Similitud Jaccard entre dos preguntas normalizadas."""
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def buscar_similar(pregunta_norm: str, candidatos: list, threshold: float = SIMILARITY_THRESHOLD):
    """
    Busca la mejor coincidencia entre una lista de objetos con .pregunta_normalizada.
    Retorna el objeto más similar si supera el threshold, o None.
    """
    palabras = pregunta_norm.split()

    # Para preguntas muy cortas exigimos match casi exacto
    t = 0.92 if len(palabras) < MIN_WORDS_FOR_FUZZY else threshold

    mejor = None
    mejor_sim = 0.0
    for entry in candidatos:
        s = similitud(pregunta_norm, entry.pregunta_normalizada)
        if s > mejor_sim:
            mejor_sim = s
            mejor = entry

    return mejor if mejor_sim >= t else None
