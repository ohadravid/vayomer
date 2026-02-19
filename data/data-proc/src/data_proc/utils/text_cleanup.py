#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Iterable

SPACE_RE = re.compile(r"\s+")
HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")
EN_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
HE_WORD_SPLIT_RE = re.compile(r"[^\u05D0-\u05EA\u0591-\u05C7]+")
HE_LETTER_CLUSTER_RE = re.compile(r"[\u05D0-\u05EA][\u0591-\u05C7]*")
HE_TOKEN_RE = re.compile(r"[\u05D0-\u05EA][\u05D0-\u05EA\u0591-\u05BD\u05BF\u05C1-\u05C2\u05C4-\u05C5\u05C7]*")
HE_PREFIX_LETTERS = ("ו", "ב", "כ", "ל", "מ", "ש")

EN_REPORTING_WORDS = {
    "and",
    "behold",
    "called",
    "saith",
    "said",
    "say",
    "saying",
    "spake",
    "spoke",
    "then",
}
HE_REPORTING_WORDS = {
    "אמר",
    "ויקרא",
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "ותאמרו",
    "לאמר",
    "נאם",
}

EN_BONUS_STOPWORDS = {
    "a",
    "all",
    "am",
    "an",
    "and",
    "art",
    "as",
    "at",
    "be",
    "because",
    "behold",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "him",
    "his",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "let",
    "me",
    "my",
    "not",
    "now",
    "of",
    "on",
    "said",
    "saith",
    "say",
    "saying",
    "she",
    "shall",
    "that",
    "the",
    "thee",
    "their",
    "them",
    "there",
    "they",
    "thou",
    "thy",
    "to",
    "unto",
    "us",
    "was",
    "were",
    "what",
    "where",
    "which",
    "who",
    "will",
    "with",
    "ye",
    "you",
}
HE_BONUS_STOPWORDS = {
    "אל",
    "אמר",
    "אשר",
    "את",
    "אתה",
    "אתם",
    "אני",
    "ב",
    "בי",
    "בו",
    "בה",
    "גם",
    "הוא",
    "היא",
    "הם",
    "הנה",
    "והנה",
    "ו",
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "זאת",
    "זה",
    "כי",
    "כל",
    "לא",
    "לאמר",
    "לה",
    "להם",
    "לו",
    "לי",
    "מן",
    "מה",
    "מי",
    "נא",
    "נאם",
    "עם",
    "על",
}

EN_RIDDLE_PUNCT_RE = re.compile(r"[,:;?!]")
EN_QUESTION_WORDS = {"what", "where", "why", "how", "who", "when", "whither", "whence"}
HE_QUESTION_PREFIXES = ("מה", "למה", "מדוע", "איכה", "מי", "איה")


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


def strip_hebrew_marks(text: str) -> str:
    stripped = (text or "").replace("\u034F", "")
    return HEBREW_ALL_MARKS_RE.sub("", stripped)


def cleanup_hebrew_quote(text: str) -> str:
    cleaned = clean_text((text or "").replace("\u034F", ""))
    cleaned = HEBREW_CANTILLATION_RE.sub("", cleaned)
    cleaned = cleaned.replace("׃", "")
    cleaned = cleaned.replace("׀", "")
    cleaned = re.sub(r"\s*־\s*", "־", cleaned)
    return clean_text(cleaned)


def _normalize_hebrew_token(token: str) -> str:
    normalized = strip_hebrew_marks(token)
    normalized = re.sub(r"[^\u05D0-\u05EA]+", "", normalized)
    return normalized


def normalize_word(word: str, lang: str) -> str:
    if lang == "he":
        return _normalize_hebrew_token(word)
    return re.sub(r"[^a-z]+", "", clean_text(word).casefold())


def word_pairs(text: str, lang: str) -> list[tuple[str, str]]:
    if lang == "en":
        cleaned = clean_text(text)
        return [(match.group(0), normalize_word(match.group(0), "en")) for match in EN_WORD_RE.finditer(cleaned)]

    cleaned = cleanup_hebrew_quote(text)
    cleaned = cleaned.replace("־", " ").replace("-", " ")
    raw_tokens = [token for token in HE_WORD_SPLIT_RE.split(cleaned) if token]
    out: list[tuple[str, str]] = []
    for token in raw_tokens:
        normalized = normalize_word(token, "he")
        if normalized:
            out.append((token, normalized))
    return out


def unique_words(text: str, lang: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for surface, normalized in word_pairs(text, lang):
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(surface)
    return out


def word_set(text: str, lang: str) -> set[str]:
    return {normalized for _, normalized in word_pairs(text, lang) if normalized}


def _hebrew_surface_variants(surface: str) -> list[str]:
    cleaned = cleanup_hebrew_quote(surface)
    if not cleaned:
        return []

    variants = [cleaned]
    clusters = HE_LETTER_CLUSTER_RE.findall(cleaned)
    if len(clusters) > 1 and normalize_word(clusters[0], "he") in HE_PREFIX_LETTERS:
        variants.append("".join(clusters[1:]))
        if len(clusters) > 2 and normalize_word(clusters[1], "he") == "ה":
            variants.append("".join(clusters[2:]))

    seen: set[str] = set()
    out: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            out.append(variant)
    return out


def hebrew_surface_map(texts: Iterable[str]) -> dict[str, str]:
    phrase_map: dict[str, str] = {}
    derived_map: dict[str, str] = {}
    direct_map: dict[str, str] = {}

    for text in texts:
        cleaned = cleanup_hebrew_quote(text)
        tokens: list[tuple[str, str, int, int]] = []
        for match in HE_TOKEN_RE.finditer(cleaned):
            surface = match.group(0)
            normalized = normalize_word(surface, "he")
            if not normalized:
                continue
            tokens.append((surface, normalized, match.start(), match.end()))
        if not tokens:
            continue

        normalized_tokens = [normalized for _, normalized, _, _ in tokens]

        for surface, normalized, _, _ in tokens:
            if normalized and normalized not in direct_map:
                direct_map[normalized] = surface
            for derived_surface in _hebrew_surface_variants(surface)[1:]:
                derived_key = normalize_word(derived_surface, "he")
                if derived_key and derived_key not in direct_map and derived_key not in derived_map:
                    derived_map[derived_key] = derived_surface

        for start in range(len(tokens)):
            span_normalized: list[str] = []
            span_start = tokens[start][2]
            for end in range(start, min(len(tokens), start + 4)):
                span_normalized.append(normalized_tokens[end])
                span_end = tokens[end][3]
                spaced_key = " ".join(span_normalized)
                collapsed_key = "".join(span_normalized)
                span_surface = cleaned[span_start:span_end]
                if spaced_key and spaced_key not in phrase_map:
                    phrase_map[spaced_key] = span_surface
                if collapsed_key and collapsed_key not in phrase_map:
                    phrase_map[collapsed_key] = span_surface

    mapping = dict(phrase_map)
    for key, value in derived_map.items():
        mapping.setdefault(key, value)
    mapping.update(direct_map)
    return mapping


def restore_hebrew_surface_from_map(text: str, mapping: dict[str, str]) -> str:
    cleaned = cleanup_hebrew_quote(text)
    pairs = word_pairs(cleaned, "he")
    if not pairs:
        return cleaned

    normalized_tokens = [normalized for _, normalized in pairs]
    spaced_key = " ".join(normalized_tokens)
    collapsed_key = "".join(normalized_tokens)
    if spaced_key in mapping:
        return mapping[spaced_key]
    if collapsed_key in mapping:
        return mapping[collapsed_key]

    restored_tokens = [mapping.get(normalized, surface) for surface, normalized in pairs]
    return " ".join(restored_tokens)


def restore_hebrew_surface(text: str, context_texts: Iterable[str]) -> str:
    return restore_hebrew_surface_from_map(text, hebrew_surface_map(context_texts))


def _hebrew_role_variants(normalized: str) -> set[str]:
    if not normalized:
        return set()

    bases = {normalized}
    if len(normalized) > 3 and normalized[0] in HE_PREFIX_LETTERS and normalized[1] == "ה":
        bases.add(normalized[1:])
        bases.add(normalized[2:])
    if normalized.startswith("ה") and len(normalized) > 2:
        bases.add(normalized[1:])

    variants: set[str] = set()
    for base in bases:
        if not base:
            continue
        variants.add(base)
        if not base.startswith("ה"):
            variants.add(f"ה{base}")
        for prefix in HE_PREFIX_LETTERS:
            variants.add(f"{prefix}{base}")
            if not base.startswith("ה"):
                variants.add(f"{prefix}ה{base}")
    return variants


def forbidden_word_set(text: str, lang: str) -> set[str]:
    normalized_words = word_set(text, lang)
    if lang != "he":
        return normalized_words

    expanded: set[str] = set()
    for normalized in normalized_words:
        expanded.update(_hebrew_role_variants(normalized))
    return expanded


def whole_word_occurs(text: str, word: str, lang: str) -> bool:
    text_tokens = [normalized for _, normalized in word_pairs(text, lang) if normalized]
    word_tokens = [normalized for _, normalized in word_pairs(word, lang) if normalized]
    if not text_tokens or not word_tokens:
        return False

    if lang != "he":
        span = len(word_tokens)
        return any(text_tokens[index : index + span] == word_tokens for index in range(len(text_tokens) - span + 1))

    def _hebrew_token_matches(target: str, observed: str) -> bool:
        target_variants = _hebrew_role_variants(target)
        observed_variants = _hebrew_role_variants(observed)
        return observed in target_variants or target in observed_variants or bool(target_variants & observed_variants)

    span = len(word_tokens)
    for index in range(len(text_tokens) - span + 1):
        window = text_tokens[index : index + span]
        if all(_hebrew_token_matches(target, observed) for target, observed in zip(word_tokens, window, strict=True)):
            return True
    return False


def subtract_words(text: str, excluded_text: str, lang: str, *, forbidden_texts: Iterable[str] = ()) -> list[str]:
    excluded = forbidden_word_set(excluded_text, lang)
    for forbidden_text in forbidden_texts:
        excluded.update(forbidden_word_set(forbidden_text, lang))
    seen: set[str] = set()
    out: list[str] = []
    for surface, normalized in word_pairs(text, lang):
        if not normalized or normalized in excluded or normalized in seen:
            continue
        seen.add(normalized)
        out.append(surface)
    return out


def candidate_bonus_words(text: str, riddle: str, lang: str, *, forbidden_texts: Iterable[str] = ()) -> list[str]:
    stopwords = HE_BONUS_STOPWORDS if lang == "he" else EN_BONUS_STOPWORDS
    reporting_words = HE_REPORTING_WORDS if lang == "he" else EN_REPORTING_WORDS
    out: list[str] = []
    seen: set[str] = set()
    for surface in subtract_words(text, riddle, lang, forbidden_texts=forbidden_texts):
        normalized = normalize_word(surface, lang)
        if not normalized or normalized in seen:
            continue
        if normalized in stopwords or normalized in reporting_words:
            continue
        if lang == "en" and len(normalized) < 3:
            continue
        seen.add(normalized)
        out.append(surface)
    return out


def normalize_words(words: Iterable[str], lang: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for word in words:
        normalized = normalize_word(word, lang)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _extra_riddle_clause_candidates(text: str, lang: str, *, max_words: int) -> list[str]:
    cleaned = cleanup_hebrew_quote(text) if lang == "he" else clean_text(text)
    if not cleaned:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        normalized_candidate = cleanup_hebrew_quote(candidate) if lang == "he" else clean_text(candidate)
        word_count = len([word for word in normalized_candidate.split() if word])
        if not normalized_candidate or word_count < 1 or word_count > max_words or normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        candidates.append(normalized_candidate)

    if lang == "en":
        if "?" in cleaned:
            question_prefix = cleaned[: cleaned.rfind("?")]
            start = max(question_prefix.rfind(","), question_prefix.rfind(";"), question_prefix.rfind(":"))
            add(cleaned[start + 1 : cleaned.rfind("?") + 1] if start >= 0 else cleaned[: cleaned.rfind("?") + 1])
        else:
            for separator in (",", ";", ":"):
                if separator in cleaned:
                    add(cleaned.rsplit(separator, 1)[-1])
    else:
        tokens = [surface for surface, normalized in word_pairs(cleaned, "he") if normalized]
        normalized_tokens = [normalized for _surface, normalized in word_pairs(cleaned, "he") if normalized]
        reporting_indices = [index for index, normalized in enumerate(normalized_tokens) if normalized in HE_REPORTING_WORDS]
        for reporting_index in reporting_indices:
            tail_tokens = tokens[reporting_index + 1 :]
            tail_normalized = normalized_tokens[reporting_index + 1 :]
            question_start = next(
                (
                    index
                    for index, normalized in enumerate(tail_normalized)
                    if any(normalized.startswith(prefix) for prefix in HE_QUESTION_PREFIXES)
                ),
                None,
            )
            if question_start is None:
                continue
            question_tokens = tail_tokens[question_start:]
            question_normalized = tail_normalized[question_start:]
            next_reporting = next(
                (
                    index
                    for index, normalized in enumerate(question_normalized)
                    if index > 0 and normalized in HE_REPORTING_WORDS
                ),
                None,
            )
            if next_reporting is not None:
                question_tokens = question_tokens[:next_reporting]
            add(" ".join(question_tokens))
            break

    return candidates


def candidate_riddle_spans(
    text: str,
    lang: str,
    *,
    preferred_word_count: int | None = None,
    max_words: int = 28,
    max_candidates: int = 36,
) -> list[str]:
    cleaned = cleanup_hebrew_quote(text) if lang == "he" else clean_text(text)
    if not cleaned:
        return []

    token_re = HE_TOKEN_RE if lang == "he" else EN_WORD_RE
    token_matches = list(token_re.finditer(cleaned))
    if not token_matches:
        return [cleaned]

    token_count = len(token_matches)
    start_limit = min(6, max(0, token_count - 1))
    if preferred_word_count is None:
        preferred_lengths = [3, 5, 7, 9, 12, 16, 20, 24, max_words]
    else:
        preferred_lengths = [
            max(2, preferred_word_count - 4),
            max(2, preferred_word_count - 2),
            max(2, preferred_word_count),
            max(2, preferred_word_count + 2),
            max(2, preferred_word_count + 4),
            max(2, preferred_word_count + 6),
        ]
    preferred_lengths = sorted(
        {
            min(token_count, length)
            for length in preferred_lengths
            if 2 <= length <= max_words and length <= token_count
        }
    )
    if token_count <= max_words:
        preferred_lengths.append(token_count)
    preferred_lengths = sorted(set(preferred_lengths))

    punctuation_endings: set[int] = set()
    if lang == "en":
        for punctuation_match in EN_RIDDLE_PUNCT_RE.finditer(cleaned):
            token_end = 0
            for index, token_match in enumerate(token_matches, start=1):
                if token_match.end() >= punctuation_match.start():
                    token_end = index
                    break
            if 2 <= token_end <= min(token_count, max_words):
                punctuation_endings.add(token_end)

    target_words = preferred_word_count if preferred_word_count is not None else min(token_count, 9)

    scored_spans: list[tuple[tuple[int, int, int, int], str]] = []
    seen: set[str] = set()
    for extra_candidate in _extra_riddle_clause_candidates(cleaned, lang, max_words=max_words):
        if extra_candidate in seen:
            continue
        seen.add(extra_candidate)
        extra_word_count = len([word for word in extra_candidate.split() if word])
        scored_spans.append(((-1, 0, 0, -extra_word_count), extra_candidate))

    for start_index in range(start_limit + 1):
        candidate_lengths = set(preferred_lengths)
        candidate_lengths.update(punctuation_endings)
        candidate_lengths.update({2, 3, 4, 5})
        candidate_lengths.update({target_words, target_words + 2, target_words + 4})
        candidate_lengths = {
            length
            for length in candidate_lengths
            if 2 <= length <= max_words and start_index + length <= token_count
        }
        for length in sorted(candidate_lengths):
            end_index = start_index + length - 1
            start_char = token_matches[start_index].start()
            end_char = token_matches[end_index].end()
            span = clean_text(cleaned[start_char:end_char])
            if not span or span in seen:
                continue
            seen.add(span)
            score = (
                abs(length - target_words),
                start_index,
                0 if length in punctuation_endings else 1,
                -length,
            )
            scored_spans.append((score, span))

    if cleaned not in seen:
        scored_spans.append(((abs(token_count - target_words), 0, 1, -token_count), cleaned))

    scored_spans.sort(key=lambda item: (item[0], item[1]))
    return [span for _, span in scored_spans[:max_candidates]]
