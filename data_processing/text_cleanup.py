#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import List, Optional, Tuple

SPACE_RE = re.compile(r"\s+")
HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")
TOKEN_RE = re.compile(r"[a-z0-9\u05D0-\u05EA]+")

HEBREW_PREFIX_CHARS = set("ולבכמשה")
HEBREW_PREFIX_WORDS = {"אל", "ואל"}

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

EN_GOD_TOKENS = {"lord", "god"}
HE_GOD_TOKENS = {"יהוה", "אלהים", "אדני", "אל"}
EN_REPORTING_STARTS = {"and", "then", "he", "she", "they", "said", "saith", "saying"}
HE_REPORTING_STARTS = {"ויאמר", "ויאמרו", "ותאמר", "ותאמרו", "לאמר", "נאם"}
EN_QUESTION_STARTS = {"what", "why", "how", "where", "who", "whence", "when", "whither"}
HE_QUESTION_STARTS = {"מה", "למה", "מדוע", "מי", "מתי", "איך", "האם"}


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


def cleanup_hebrew_quote(text: str) -> str:
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


def token_count(text: str, lang: str) -> int:
    return len(tokenize_for_match(text, lang))


def has_weird_whitespace(*values: str) -> bool:
    return any("\n" in value or "\t" in value for value in values)


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


def entity_in_quote(entity: str, quote: str, lang: str) -> bool:
    entity = clean_text(entity)
    quote = clean_text(quote)
    if not entity or not quote:
        return False
    if entity in quote:
        return True
    quote_tokens = tokenize_for_match(quote, lang)
    entity_tokens = tokenize_for_match(entity, lang)
    if not quote_tokens or not entity_tokens:
        return False
    return _find_entity_subsequence(quote_tokens, entity_tokens, lang) is not None


def extract_substring_from_quote(quote: str, text: str, lang: str) -> Optional[str]:
    quote = clean_text(quote)
    text = clean_text(text)
    if not quote or not text:
        return None

    candidates = [text]
    if lang == "en":
        stripped = re.sub(r"^(?:the|a|an|o|ye)\s+", "", text, flags=re.I).strip()
        if stripped and stripped != text:
            candidates.append(stripped)

    quote_tokens = tokenize_with_spans(quote, lang)
    quote_only_tokens = [tok for tok, _, _ in quote_tokens]
    if not quote_only_tokens:
        return None

    for candidate in candidates:
        if candidate in quote:
            return clean_text(candidate)

        candidate_tokens = tokenize_for_match(candidate, lang)
        if not candidate_tokens:
            continue

        idx = _find_subsequence(quote_only_tokens, candidate_tokens)
        if idx is None:
            continue

        start = quote_tokens[idx][1]
        end = quote_tokens[idx + len(candidate_tokens) - 1][2]
        if lang == "he":
            while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
                start -= 1
            while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
                end += 1
        return clean_text(quote[start:end])

    return None


def _extract_token_sequence_from_quote(quote: str, seq_tokens: List[str], lang: str) -> Optional[str]:
    if not quote or not seq_tokens:
        return None
    spans = tokenize_with_spans(quote, lang)
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


def _is_god_like_entity(entity: str, lang: str) -> bool:
    tokens = tokenize_for_match(entity, lang)
    if not tokens:
        return False
    if lang == "en":
        return any(tok in EN_GOD_TOKENS for tok in tokens)
    return any(tok in HE_GOD_TOKENS for tok in tokens)


def best_god_name_in_quote(quote: str, lang: str) -> Optional[str]:
    candidates = GOD_NAME_CANDIDATES_EN if lang == "en" else GOD_NAME_CANDIDATES_HE
    for seq in candidates:
        match = _extract_token_sequence_from_quote(quote, seq, lang)
        if match:
            return match
    return None


def align_entity_to_quote(entity: str, quote: str, lang: str) -> str:
    entity = clean_text(entity)
    quote = clean_text(quote)
    if not entity:
        return ""

    if _is_god_like_entity(entity, lang):
        fullest = best_god_name_in_quote(quote, lang)
        if fullest:
            return fullest

    candidates = [entity]
    if lang == "en":
        dep = re.sub(r"[’']s\\b", "", entity, flags=re.I).strip()
        if dep and dep not in candidates:
            candidates.append(dep)
        match = re.match(r"(.+?)[’']s\\s+(.+)$", entity, flags=re.I)
        if match:
            owner = clean_text(match.group(1))
            owned = clean_text(match.group(2))
            if owner and owned:
                variants = [f"{owned} of {owner}", f"the {owned} of {owner}"]
                for variant in variants:
                    if variant not in candidates:
                        candidates.append(variant)
    elif lang == "he":
        tokens = tokenize_for_match(entity, "he")
        quote_tokens = tokenize_for_match(quote, "he")
        if tokens:
            alt_tokens: List[str] = []
            if tokens[0] in HEBREW_PREFIX_WORDS and len(tokens) > 1:
                alt_tokens = tokens[1:]
            else:
                first = tokens[0]
                if len(first) > 2 and first[0] in HEBREW_PREFIX_CHARS:
                    stripped = first[1:]
                    if stripped in quote_tokens:
                        alt_tokens = [stripped] + tokens[1:]
            if alt_tokens:
                alt_entity = _extract_token_sequence_from_quote(quote, alt_tokens, "he")
                if alt_entity and alt_entity not in candidates:
                    candidates.append(alt_entity)

    for candidate in candidates:
        extracted = extract_substring_from_quote(quote, candidate, lang)
        if extracted:
            return extracted
    return entity


def riddle_mentions_entities(riddle: str, speaker: str, listener: str, lang: str) -> bool:
    riddle_tokens = tokenize_for_match(riddle, lang)
    speaker_tokens = tokenize_for_match(speaker, lang)
    listener_tokens = tokenize_for_match(listener, lang)
    if not riddle_tokens:
        return False

    if speaker_tokens and _find_entity_subsequence(riddle_tokens, speaker_tokens, lang) is not None:
        return True
    if listener_tokens and _find_entity_subsequence(riddle_tokens, listener_tokens, lang) is not None:
        return True

    # Catch single-token mentions even when the full entity has multiple words.
    for token in set(speaker_tokens + listener_tokens):
        if not token:
            continue
        for r_token in riddle_tokens:
            if _token_match_with_prefix(r_token, token, lang=lang, allow_prefix=(lang == "he")):
                return True

    if _is_god_like_entity(speaker, lang) or _is_god_like_entity(listener, lang):
        if lang == "en":
            return any(token in EN_GOD_TOKENS for token in riddle_tokens)
        return any(token in HE_GOD_TOKENS for token in riddle_tokens)

    return False


def suggest_riddle_from_quote(
    quote: str,
    speaker: str,
    listener: str,
    lang: str,
    min_tokens: int = 4,
    max_tokens: int = 16,
) -> str:
    quote = clean_text(quote)
    if not quote or min_tokens <= 0 or max_tokens < min_tokens:
        return ""

    spans = tokenize_with_spans(quote, lang)
    if not spans:
        return ""

    target = (min_tokens + max_tokens) / 2.0
    best_phrase = ""
    best_score = float("-inf")

    for i in range(len(spans)):
        max_j = min(len(spans) - 1, i + max_tokens - 1)
        min_j = i + min_tokens - 1
        if min_j > max_j:
            continue
        for j in range(min_j, max_j + 1):
            window_tokens = [spans[k][0] for k in range(i, j + 1)]
            phrase = clean_text(quote[spans[i][1] : spans[j][2]])
            if not phrase:
                continue

            if riddle_mentions_entities(phrase, speaker, listener, lang):
                continue

            if lang == "he" and window_tokens[-1] in {"את", "אל", "ל", "ו"}:
                continue

            score = 100.0
            score -= abs(len(window_tokens) - target) * 6.0

            first = window_tokens[0] if window_tokens else ""
            if lang == "en":
                if first in EN_QUESTION_STARTS:
                    score += 8.0
                if first in EN_REPORTING_STARTS:
                    score -= 12.0
            else:
                if first in HE_QUESTION_STARTS:
                    score += 8.0
                if first in HE_REPORTING_STARTS:
                    score -= 12.0

            if i > 0:
                score += 2.0
            if phrase and phrase[-1] in {",", ";", ":"}:
                score -= 3.0

            if score > best_score:
                best_score = score
                best_phrase = phrase

    return clean_text(best_phrase)
