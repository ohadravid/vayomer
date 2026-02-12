#!/usr/bin/env python3
from __future__ import annotations

import re
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

try:
    from data_processing import bible_sources
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]

SPACE_RE = re.compile(r"\s+")
HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")
TOKEN_RE = re.compile(r"[a-z0-9\u05D0-\u05EA]+")

HEBREW_PREFIX_CHARS = set("ולבכמשה")
HEBREW_PREFIX_WORDS = {"אל", "ואל"}
EN_QUESTION_STARTS = {"what", "why", "how", "where", "who", "whence", "when", "whither"}
HE_QUESTION_STARTS = {"מה", "למה", "מדוע", "מי", "מתי", "איך", "האם"}
EN_REPORTING_STARTS = {"and", "then", "he", "she", "they", "said", "saith", "saying"}
HE_REPORTING_STARTS = {"ויאמר", "ויאמרו", "ותאמר", "ותאמרו", "לאמר", "נאם"}
EN_WEAK_START_TOKENS = {
    "he",
    "she",
    "they",
    "them",
    "you",
    "thou",
    "thee",
    "ye",
    "it",
    "this",
    "that",
}
EN_DANGLING_EDGE_TOKENS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "for",
    "that",
    "which",
    "who",
    "whom",
    "of",
    "to",
    "unto",
    "in",
    "on",
    "at",
    "with",
    "from",
    "by",
    "as",
    "if",
    "because",
    "lest",
    "therefore",
    "then",
}
HE_DANGLING_EDGE_BASE_TOKENS = {"את", "אל", "כי", "אם", "אשר", "עם", "על", "גם", "או"}
EN_DRAMATIC_TOKENS = {
    "behold",
    "die",
    "death",
    "wrath",
    "evil",
    "curse",
    "covenant",
    "peace",
    "blood",
    "burn",
    "destroy",
    "slay",
    "bury",
    "grave",
}
HE_DRAMATIC_BASE_TOKENS = {
    "הנני",
    "מות",
    "חמה",
    "רעה",
    "ברית",
    "שלום",
    "דם",
    "אש",
    "קבר",
    "קברתי",
    "חרון",
    "נקם",
    "כלה",
}

GOD_NAME_CANDIDATES_EN: List[List[str]] = [
    ["the", "lord", "god"],
    ["lord", "god"],
    ["the", "lord"],
    ["lord"],
    ["god"],
]
GOD_NAME_CANDIDATES_HE: List[List[str]] = [
    ["אדני", "יהוה"],
    ["יהוה", "אלהים"],
    ["יהוה"],
    ["אדני"],
    ["אלהים"],
]
EN_NAME_ALIASES = {
    "abraham": "abram",
}
EN_ENTITY_NON_NAME_TOKENS = {"the", "of", "and", "unto", "to", "son", "daughter"}
HE_ENTITY_NON_NAME_BASE_TOKENS = {"בן", "בת", "בני", "בית", "ו"}


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


def cleanup_hebrew_quote(text: str) -> str:
    # Keep lexical content + maqaf words, remove heavy cantillation and extra punctuation.
    cleaned = clean_text((text or "").replace("\u034F", ""))
    cleaned = HEBREW_CANTILLATION_RE.sub("", cleaned)
    cleaned = cleaned.replace("׃", "")
    cleaned = cleaned.replace("׀", "")
    cleaned = re.sub(r"\s*־\s*", "־", cleaned)
    return clean_text(cleaned)


def _normalized_char(ch: str, lang: str) -> str:
    if lang == "he":
        if ch in {"-", "־"}:
            return " "
        if HEBREW_ALL_MARKS_RE.match(ch):
            return ""
        if ch == "\u034F":
            return ""
        if "\u05D0" <= ch <= "\u05EA":
            return ch
        if ch.isalnum():
            return ch.lower()
        return " "
    if ch.isalnum():
        return ch.lower()
    return " "


def _normalized_with_index(text: str, lang: str) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    out_indices: List[int] = []
    prev_space = True

    for idx, ch in enumerate(text):
        norm = _normalized_char(ch, lang)
        if not norm:
            continue
        if norm == " ":
            if prev_space:
                continue
            out_chars.append(" ")
            out_indices.append(idx)
            prev_space = True
            continue
        out_chars.append(norm)
        out_indices.append(idx)
        prev_space = False

    while out_chars and out_chars[0] == " ":
        out_chars.pop(0)
        out_indices.pop(0)
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        out_indices.pop()

    return "".join(out_chars), out_indices


def tokenize_for_match(text: str, lang: str) -> List[str]:
    normalized, _ = _normalized_with_index(text, lang)
    if not normalized:
        return []
    return [m.group() for m in TOKEN_RE.finditer(normalized)]


def tokenize_with_spans(text: str, lang: str) -> List[Tuple[str, int, int]]:
    normalized, indices = _normalized_with_index(text, lang)
    if not normalized:
        return []

    tokens: List[Tuple[str, int, int]] = []
    for match in TOKEN_RE.finditer(normalized):
        start, end = match.span()
        if start >= len(indices) or end - 1 >= len(indices):
            continue
        orig_start = indices[start]
        orig_end = indices[end - 1] + 1
        tokens.append((match.group(), orig_start, orig_end))
    return tokens


def _find_subsequence(haystack: List[str], needle: List[str]) -> Optional[int]:
    if not haystack or not needle or len(needle) > len(haystack):
        return None
    limit = len(haystack) - len(needle) + 1
    for idx in range(limit):
        if haystack[idx : idx + len(needle)] == needle:
            return idx
    return None


def _token_match_with_prefix(token: str, entity_token: str, lang: str, allow_prefix: bool) -> bool:
    if token == entity_token:
        return True
    if lang != "he" or not allow_prefix:
        return False
    if not token.endswith(entity_token):
        return False
    prefix = token[: len(token) - len(entity_token)]
    if not prefix:
        return True
    if prefix in HEBREW_PREFIX_WORDS:
        return True
    return all(ch in HEBREW_PREFIX_CHARS for ch in prefix)


def _find_entity_subsequence(haystack: List[str], needle: List[str], lang: str) -> Optional[int]:
    if not haystack or not needle or len(needle) > len(haystack):
        return None
    limit = len(haystack) - len(needle) + 1
    for idx in range(limit):
        ok = True
        for j, entity_token in enumerate(needle):
            token = haystack[idx + j]
            allow_prefix = lang == "he" and j == 0
            if not _token_match_with_prefix(token, entity_token, lang=lang, allow_prefix=allow_prefix):
                ok = False
                break
        if ok:
            return idx
    return None


def _hebrew_base_token(token: str) -> str:
    base = token
    for _ in range(2):
        if len(base) <= 2:
            break
        if base[0] not in HEBREW_PREFIX_CHARS:
            break
        base = base[1:]
    return base


def _is_dangling_edge_token(token: str, lang: str) -> bool:
    if not token:
        return False
    if lang == "en":
        return token in EN_DANGLING_EDGE_TOKENS
    base = _hebrew_base_token(token)
    return token in HE_DANGLING_EDGE_BASE_TOKENS or base in HE_DANGLING_EDGE_BASE_TOKENS


def _has_dramatic_token(tokens: List[str], lang: str) -> bool:
    if not tokens:
        return False
    if lang == "en":
        return any(tok in EN_DRAMATIC_TOKENS for tok in tokens)
    return any(tok in HE_DRAMATIC_BASE_TOKENS or _hebrew_base_token(tok) in HE_DRAMATIC_BASE_TOKENS for tok in tokens)


def has_dangling_edges(text: str, lang: str) -> bool:
    tokens = tokenize_for_match(text, lang)
    if not tokens:
        return False
    return _is_dangling_edge_token(tokens[0], lang) or _is_dangling_edge_token(tokens[-1], lang)


def entity_in_quote(entity: str, quote: str, lang: str) -> bool:
    if not entity or not quote:
        return False
    if entity in quote:
        return True
    quote_tokens = tokenize_for_match(quote, lang)
    entity_tokens = tokenize_for_match(entity, lang)
    if not quote_tokens or not entity_tokens:
        return False
    if lang == "he" and len(entity_tokens) == 1:
        base = _hebrew_base_token(entity_tokens[0])
        if base in HE_DANGLING_EDGE_BASE_TOKENS:
            return False
    return _find_entity_subsequence(quote_tokens, entity_tokens, lang) is not None


def extract_substring_from_quote(quote: str, text: str, lang: str) -> Optional[str]:
    if not quote or not text:
        return None

    candidates = [text]
    if lang == "en":
        stripped = re.sub(r"^(?:the|a|an|o|ye)\s+", "", text, flags=re.I).strip()
        if stripped and stripped != text:
            candidates.append(stripped)

    quote_tokens = tokenize_with_spans(quote, lang)
    if not quote_tokens:
        return None
    quote_only_tokens = [tok for tok, _, _ in quote_tokens]

    for candidate in candidates:
        if candidate in quote:
            return clean_text(candidate)

        text_tokens = tokenize_for_match(candidate, lang)
        if not text_tokens:
            continue

        idx = _find_subsequence(quote_only_tokens, text_tokens)
        if idx is None:
            continue

        start = quote_tokens[idx][1]
        end = quote_tokens[idx + len(text_tokens) - 1][2]
        if lang == "he":
            while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
                start -= 1
            while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
                end += 1
        return clean_text(quote[start:end])

    return None


def _is_god_like_entity(entity: str, lang: str) -> bool:
    tokens = tokenize_for_match(entity, lang)
    if not tokens:
        return False
    if lang == "en":
        return any(tok in {"lord", "god"} for tok in tokens)
    return any(tok in {"יהוה", "אלהים", "אדני", "אל"} for tok in tokens)


def _extract_token_sequence_from_quote(quote: str, seq_tokens: List[str], lang: str) -> Optional[str]:
    if not quote or not seq_tokens:
        return None
    spans = tokenize_with_spans(quote, lang)
    if not spans:
        return None
    quote_tokens = [tok for tok, _, _ in spans]
    idx = _find_subsequence(quote_tokens, seq_tokens)
    if idx is None:
        return None
    start = spans[idx][1]
    end = spans[idx + len(seq_tokens) - 1][2]
    if lang == "he":
        while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
            start -= 1
        while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
            end += 1
    return clean_text(quote[start:end])


def best_god_name_in_quote(quote: str, lang: str) -> Optional[str]:
    candidates = GOD_NAME_CANDIDATES_EN if lang == "en" else GOD_NAME_CANDIDATES_HE
    for seq in candidates:
        match = _extract_token_sequence_from_quote(quote, seq, lang)
        if match:
            return match
    return None


def align_entity_to_quote(entity: str, quote: str, lang: str) -> str:
    entity = clean_text(entity)
    if not entity:
        return ""

    if _is_god_like_entity(entity, lang):
        best = best_god_name_in_quote(quote, lang)
        if best:
            return best

    direct = extract_substring_from_quote(quote, entity, lang)
    if direct:
        return direct

    if lang == "en":
        entity_tokens = tokenize_for_match(entity, "en")
        quote_tokens = tokenize_for_match(quote, "en")
        if len(entity_tokens) == 1 and quote_tokens:
            token = entity_tokens[0]
            alias = EN_NAME_ALIASES.get(token)
            if alias:
                alias_match = _extract_token_sequence_from_quote(quote, [alias], "en")
                if alias_match:
                    return alias_match

            best_tok = None
            best_ratio = 0.0
            for qt in set(quote_tokens):
                ratio = difflib.SequenceMatcher(None, token, qt).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_tok = qt
            if best_tok and best_ratio >= 0.8:
                fuzzy = _extract_token_sequence_from_quote(quote, [best_tok], "en")
                if fuzzy:
                    return fuzzy

    return entity


def riddle_mentions_entities(riddle: str, speaker: str, listener: str, lang: str) -> bool:
    riddle_tokens = tokenize_for_match(riddle, lang)
    if not riddle_tokens:
        return False
    speaker_tokens = tokenize_for_match(speaker, lang)
    listener_tokens = tokenize_for_match(listener, lang)
    if speaker_tokens and _find_entity_subsequence(riddle_tokens, speaker_tokens, lang) is not None:
        return True
    if listener_tokens and _find_entity_subsequence(riddle_tokens, listener_tokens, lang) is not None:
        return True

    # Also catch partial mentions inside multi-token entities, e.g. "לְמֹשֶׁה" for "מֹשֶׁה וְאַהֲרֹן".
    entity_tokens = list(speaker_tokens) + list(listener_tokens)
    if lang == "en":
        token_candidates = [tok for tok in entity_tokens if tok not in EN_ENTITY_NON_NAME_TOKENS]
    else:
        token_candidates = [
            tok
            for tok in entity_tokens
            if _hebrew_base_token(tok) not in HE_ENTITY_NON_NAME_BASE_TOKENS
        ]
    for etok in token_candidates:
        for rtok in riddle_tokens:
            if _token_match_with_prefix(rtok, etok, lang=lang, allow_prefix=(lang == "he")):
                return True

    if _is_god_like_entity(speaker, lang) or _is_god_like_entity(listener, lang):
        if lang == "en":
            return any(tok in {"lord", "god"} for tok in riddle_tokens)
        return any(tok in {"יהוה", "אלהים", "אדני"} for tok in riddle_tokens)
    return False


def fallback_riddle_from_quote(
    quote: str,
    speaker: str,
    listener: str,
    lang: str,
    min_tokens: int = 4,
    max_tokens: int = 14,
) -> Optional[str]:
    spans = tokenize_with_spans(quote, lang)
    if not spans:
        return None
    tokens = [token for token, _, _ in spans]
    if not tokens:
        return None

    speaker_tokens = tokenize_for_match(speaker, lang)
    listener_tokens = tokenize_for_match(listener, lang)
    speaker_god = _is_god_like_entity(speaker, lang)
    listener_god = _is_god_like_entity(listener, lang)

    def _window_has_entities(window_tokens: List[str]) -> bool:
        if speaker_tokens and _find_entity_subsequence(window_tokens, speaker_tokens, lang) is not None:
            return True
        if listener_tokens and _find_entity_subsequence(window_tokens, listener_tokens, lang) is not None:
            return True
        if speaker_god or listener_god:
            if lang == "en":
                if any(tok in {"lord", "god"} for tok in window_tokens):
                    return True
            else:
                if any(tok in {"יהוה", "אלהים", "אדני"} for tok in window_tokens):
                    return True
        return False

    n = len(spans)
    lo = min(min_tokens, n)
    hi = min(max_tokens, n)

    best_score: Optional[float] = None
    best_candidate: Optional[str] = None
    target_size = max(lo, min(9, hi))
    quote_mid = (n - 1) / 2.0

    for size in range(hi, lo - 1, -1):
        for start in range(0, n - size + 1):
            end = start + size
            window_tokens = tokens[start:end]
            first = window_tokens[0]
            last = window_tokens[-1]
            if lang == "en" and first in EN_REPORTING_STARTS:
                continue
            if lang == "he" and first in HE_REPORTING_STARTS:
                continue
            if _window_has_entities(window_tokens):
                continue

            orig_start = spans[start][1]
            orig_end = spans[end - 1][2]
            candidate = clean_text(quote[orig_start:orig_end])
            if not candidate:
                continue

            score = 0.0
            score -= abs(size - target_size) * 0.35
            window_mid = (start + end - 1) / 2.0
            score -= abs(window_mid - quote_mid) * 0.12

            if lang == "en" and first in EN_QUESTION_STARTS:
                score += 2.5
            if lang == "he" and first in HE_QUESTION_STARTS:
                score += 2.5
            if _has_dramatic_token(window_tokens, lang):
                score += 1.2
            if lang == "en" and first in EN_WEAK_START_TOKENS and first not in EN_QUESTION_STARTS:
                score -= 1.2

            if _is_dangling_edge_token(first, lang):
                score -= 1.0
            if _is_dangling_edge_token(last, lang):
                score -= 2.2

            if best_score is None or score > best_score:
                best_score = score
                best_candidate = candidate

    return best_candidate


@dataclass(frozen=True)
class VerseTandem:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    verse: int
    en_raw: str
    he_raw: str
    he_clean: str


@dataclass(frozen=True)
class RangeQuote:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    start: int
    end: int
    en_quote: str
    he_quote: str
    raw_quote_source: Dict[str, Dict[str, str]]
    missing: List[int]


class TandemBible:
    """Lightweight iterator over English+Hebrew verses in tandem."""

    def __init__(
        self,
        english_map: bible_sources.VerseMap,
        hebrew_map: bible_sources.VerseMap,
    ) -> None:
        self.english_map = english_map
        self.hebrew_map = hebrew_map

        by_chapter: Dict[Tuple[str, int], List[int]] = {}
        for (code, chapter, verse), en_text in english_map.items():
            if not en_text:
                continue
            he_text = hebrew_map.get((code, chapter, verse), "")
            if not he_text:
                continue
            by_chapter.setdefault((code, chapter), []).append(verse)
        self._by_chapter = {
            key: sorted(set(verses))
            for key, verses in by_chapter.items()
        }

    @classmethod
    def load(
        cls,
        english_xml: Path,
        hebrew_zip: Path,
    ) -> "TandemBible":
        english_map = bible_sources.load_english_verse_map(english_xml)
        hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)
        return cls(english_map=english_map, hebrew_map=hebrew_map)

    def iter_books(self, book_filter: str = "") -> Iterator[Tuple[str, str, str]]:
        key = book_filter.strip().casefold()
        for code, en_name, he_name in bible_sources.OT_BOOKS:
            if key and key not in {code.casefold(), en_name.casefold(), he_name.casefold()}:
                continue
            has_any = any(ch_code == code for ch_code, _ in self._by_chapter.keys())
            if has_any:
                yield code, en_name, he_name

    def iter_chapters(self, book_filter: str = "") -> Iterator[Tuple[str, int]]:
        allowed_codes = {code for code, _, _ in self.iter_books(book_filter=book_filter)}
        for code, chapter in sorted(
            self._by_chapter.keys(),
            key=lambda c: (bible_sources.BOOK_ORDER.get(c[0], 999), c[1]),
        ):
            if allowed_codes and code not in allowed_codes:
                continue
            yield code, chapter

    def iter_verses(self, book_code: str, chapter: int) -> Iterator[VerseTandem]:
        verse_nums = self._by_chapter.get((book_code, chapter), [])
        book_en = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code)
        book_he = bible_sources.BOOK_CODE_TO_HE.get(book_code, "")
        for verse in verse_nums:
            en_raw = clean_text(self.english_map.get((book_code, chapter, verse), ""))
            he_raw = clean_text(self.hebrew_map.get((book_code, chapter, verse), ""))
            if not en_raw or not he_raw:
                continue
            yield VerseTandem(
                book_code=book_code,
                book_en=book_en,
                book_he=book_he,
                chapter=chapter,
                verse=verse,
                en_raw=en_raw,
                he_raw=he_raw,
                he_clean=cleanup_hebrew_quote(he_raw),
            )

    def collect_range(self, book_code: str, chapter: int, start: int, end: int) -> RangeQuote:
        start, end = sorted((start, end))
        missing: List[int] = []
        en_parts: List[str] = []
        he_parts: List[str] = []
        raw_en: Dict[str, str] = {}
        raw_he: Dict[str, str] = {}

        for verse in range(start, end + 1):
            en_raw = clean_text(self.english_map.get((book_code, chapter, verse), ""))
            he_raw = clean_text(self.hebrew_map.get((book_code, chapter, verse), ""))
            if not en_raw or not he_raw:
                missing.append(verse)
                continue
            raw_en[str(verse)] = en_raw
            raw_he[str(verse)] = he_raw
            en_parts.append(en_raw)
            he_parts.append(cleanup_hebrew_quote(he_raw))

        return RangeQuote(
            book_code=book_code,
            book_en=bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
            book_he=bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
            chapter=chapter,
            start=start,
            end=end,
            en_quote=clean_text(" ".join(en_parts)),
            he_quote=clean_text(" ".join(he_parts)),
            raw_quote_source={"en": raw_en, "he": raw_he},
            missing=missing,
        )

    def iter_windows(
        self,
        book_code: str,
        chapter: int,
        max_window: int = 5,
        min_window: int = 1,
    ) -> Iterator[RangeQuote]:
        verse_nums = self._by_chapter.get((book_code, chapter), [])
        if not verse_nums:
            return
        verse_set = set(verse_nums)
        for start in verse_nums:
            for end in range(start + min_window - 1, start + max_window):
                if end not in verse_set:
                    break
                if any(v not in verse_set for v in range(start, end + 1)):
                    continue
                yield self.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
