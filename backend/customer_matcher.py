"""
DukaanVoice Multilingual Customer Identification & Script Normalization Engine.
Provides deterministic transliteration of Kannada Unicode script to Latin,
canonical phonetic normalization, and bounded candidate matching to identify
customers across Kannada and Latin scripts without modifying database records.
"""

import re
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session
from models import Customer

# =====================================================================
# Kannada Unicode Character Definitions (U+0C80 - U+0CFF)
# =====================================================================

KANNADA_INDEPENDENT_VOWELS = {
    0x0C85: "a",
    0x0C86: "aa",
    0x0C87: "i",
    0x0C88: "ee",
    0x0C89: "u",
    0x0C8A: "oo",
    0x0C8B: "ru",
    0x0C8E: "e",
    0x0C8F: "e",
    0x0C90: "ai",
    0x0C92: "o",
    0x0C93: "o",
    0x0C94: "au",
}

KANNADA_CONSONANTS = {
    0x0C95: "k",
    0x0C96: "kh",
    0x0C97: "g",
    0x0C98: "gh",
    0x0C99: "ng",
    0x0C9A: "ch",
    0x0C9B: "chh",
    0x0C9C: "j",
    0x0C9D: "jh",
    0x0C9E: "ny",
    0x0C9F: "t",
    0x0CA0: "th",
    0x0CA1: "d",
    0x0CA2: "dh",
    0x0CA3: "n",
    0x0CA4: "t",
    0x0CA5: "th",
    0x0CA6: "d",
    0x0CA7: "dh",
    0x0CA8: "n",
    0x0CAA: "p",
    0x0CAB: "ph",
    0x0CAC: "b",
    0x0CAD: "bh",
    0x0CAE: "m",
    0x0CAF: "y",
    0x0CB0: "r",
    0x0CB1: "r",
    0x0CB2: "l",
    0x0CB3: "l",
    0x0CB5: "v",
    0x0CB6: "sh",
    0x0CB7: "sh",
    0x0CB8: "s",
    0x0CB9: "h",
}

KANNADA_MATRAS = {
    0x0CBE: "aa",
    0x0CBF: "i",
    0x0CC0: "ee",
    0x0CC1: "u",
    0x0CC2: "oo",
    0x0CC3: "ru",
    0x0CC6: "e",
    0x0CC7: "e",
    0x0CC8: "ai",
    0x0CCA: "o",
    0x0CCB: "o",
    0x0CCC: "au",
}

VIRAMA = 0x0CCD
ANUSVARA = 0x0C82
VISARGA = 0x0C83


def contains_kannada(text: str) -> bool:
    """Checks whether the text contains any Kannada Unicode code points."""
    return any(0x0C80 <= ord(c) <= 0x0CFF for c in text)


def transliterate_kannada_to_latin(text: str) -> str:
    """
    Deterministically transliterates Kannada Unicode characters into Latin script.
    Follows standard Indic phonetics:
    - Base consonants have an inherent 'a' unless followed by Virama or Matra.
    - Anusvara is normalized based on context.
    """
    if not contains_kannada(text):
        return text

    res = []
    i = 0
    n = len(text)
    while i < n:
        cp = ord(text[i])
        if cp in KANNADA_INDEPENDENT_VOWELS:
            res.append(KANNADA_INDEPENDENT_VOWELS[cp])
            i += 1
        elif cp in KANNADA_CONSONANTS:
            base = KANNADA_CONSONANTS[cp]
            if i + 1 < n:
                nxt = ord(text[i + 1])
                if nxt == VIRAMA:
                    res.append(base)
                    i += 2
                elif nxt in KANNADA_MATRAS:
                    res.append(base + KANNADA_MATRAS[nxt])
                    i += 2
                elif nxt == ANUSVARA:
                    # Anusvara following consonant
                    res.append(base + "am")
                    i += 2
                else:
                    res.append(base + "a")
                    i += 1
            else:
                res.append(base + "a")
                i += 1
        elif cp == ANUSVARA:
            res.append("m")
            i += 1
        elif cp == VISARGA:
            res.append("h")
            i += 1
        else:
            res.append(text[i])
            i += 1

    return "".join(res)


def canonical_phonetic(name: str) -> str:
    """
    Converts a name (either Kannada script or Latin script) into a canonical
    normalized phonetic key for comparison:
    1. Transliterate Kannada characters to Latin.
    2. Lowercase and strip punctuation.
    3. Normalize long/short vowel variants ('aa'->'a', 'ee'->'i', 'oo'->'u').
    4. Normalize 'w'->'v', 'sh'->'s' in bounded contexts.
    5. Strip trailing unstressed vowels ('a', 'u', 'e') in Indian names > 3 chars.
    """
    s = transliterate_kannada_to_latin(name)
    s = re.sub(r"[^a-zA-Z0-9\s]", "", s).lower().strip()
    s = s.replace("aa", "a").replace("ee", "i").replace("oo", "u").replace("ii", "i").replace("uu", "u")
    s = s.replace("w", "v").replace("sh", "s")
    s = s.replace("md", "nd").replace("mt", "nt")

    words = s.split()
    norm_words = []
    for w in words:
        # Strip trailing unstressed vowel for Dravidian/Sanskrit name variations
        # (e.g. Ramesh / Ramesha -> rames, Suresh / Suresha -> sures, Kumar / Kumara -> kumar)
        if len(w) > 4 and w.endswith(("a", "u", "e")):
            w = w[:-1]
        norm_words.append(w)

    return " ".join(norm_words)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes the Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    len_s1, len_s2 = len(s1), len(s2)
    current_row = list(range(len_s2 + 1))
    for i, c1 in enumerate(s1):
        next_row = [i + 1] * (len_s2 + 1)
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            next_row[j + 1] = min(
                next_row[j] + 1,
                current_row[j + 1] + 1,
                current_row[j] + cost
            )
        current_row = next_row

    return current_row[len_s2]


def match_customer_candidates(name_query: str, candidates: Sequence[Customer]) -> list[Customer]:
    """
    Safely matches a customer name query against candidate records using a bounded
    multi-tier strategy:
    Tier 1: Exact case-insensitive match (e.g. 'Ramesh' == 'Ramesh').
    Tier 2: Transliterated exact match (e.g. 'ರಮೇಶ್' == 'Ramesh').
    Tier 3: Canonical phonetic match (e.g. 'Ramesha' == 'Ramesh', 'ರಮೇಶ' == 'Ramesh').
    Tier 4: Prefix / word match (e.g. 'Ramesh' matches 'Ramesh Kumar' if no exact 'Ramesh').
    Tier 5: Bounded edit distance (Levenshtein distance <= 1 for len <= 6, <= 2 for len > 6),
            strictly requiring matching initial character to avoid false phonetic guessing.

    Never weakly guesses unrelated customers (e.g. 'Suresh' will NEVER match 'Ramesh').
    Returns a list of matching Customer instances. If multiple match, caller triggers disambiguation.
    """
    cleaned_query = name_query.strip()
    if not cleaned_query or not candidates:
        return []

    q_lower = cleaned_query.lower()

    # Tier 1: Exact case-insensitive match
    t1_matches = [c for c in candidates if c.name.strip().lower() == q_lower]
    if t1_matches:
        return t1_matches

    # Tier 2: Transliterated exact match
    q_translit = transliterate_kannada_to_latin(cleaned_query).strip().lower()
    t2_matches = [
        c for c in candidates
        if transliterate_kannada_to_latin(c.name).strip().lower() == q_translit
    ]
    if t2_matches:
        return t2_matches

    # Tier 3: Canonical phonetic exact match
    q_canon = canonical_phonetic(cleaned_query)
    if q_canon:
        t3_matches = [c for c in candidates if canonical_phonetic(c.name) == q_canon]
        if t3_matches:
            return t3_matches

    # Tier 4: Prefix / Word match (e.g. query 'Ramesh' matches candidate 'Ramesh Kumar')
    t4_matches = []
    for c in candidates:
        c_canon = canonical_phonetic(c.name)
        c_words = c_canon.split()
        q_words = q_canon.split()
        if (
            c_canon.startswith(q_canon + " ")
            or (q_words and c_words and q_words[0] == c_words[0] and len(q_words[0]) >= 3)
        ):
            t4_matches.append(c)

    if t4_matches:
        return t4_matches

    # Tier 5: Bounded edit distance
    # Only allowed if:
    # 1. Names share the identical starting letter/sound
    # 2. Distance is <= 1 for len <= 6, or <= 2 for len > 6
    t5_matches = []
    max_allowed_dist = 1 if len(q_canon) <= 6 else 2

    for c in candidates:
        c_canon = canonical_phonetic(c.name)
        if not c_canon or not q_canon:
            continue
        # Initial character must match exactly
        if c_canon[0] != q_canon[0]:
            continue
        dist = levenshtein_distance(q_canon, c_canon)
        if dist <= max_allowed_dist:
            t5_matches.append(c)

    return t5_matches


def find_matching_customers(db: Session, name_query: str) -> list[Customer]:
    """
    Queries customers from the database and returns matching candidates using
    deterministic script transliteration, canonical phonetics, and bounded matching.
    Preserves database records and original customer names without mutation.
    """
    cleaned = name_query.strip()
    if not cleaned:
        return []

    # 1. First try direct SQL exact match (fast path)
    exact = db.scalars(
        select(Customer).where(Customer.name.ilike(cleaned))
    ).all()
    if exact:
        return list(exact)

    # 2. Fetch all customers from DB to apply bounded cross-script matching
    all_customers = list(db.scalars(select(Customer)).all())
    return match_customer_candidates(cleaned, all_customers)
