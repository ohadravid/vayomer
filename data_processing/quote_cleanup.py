#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import List, Literal, Optional, Tuple

LangKey = Literal["en", "he"]

SPACE_RE = re.compile(r"\s+")
PUNCT_SPACE_RE = re.compile(r"\s*([,;:.!?])\s*")
REPEATED_PUNCT_RE = re.compile(r"([,;:.!?])\1+")
REPEATED_SPACED_PUNCT_RE = re.compile(r"([,;:.!?])\s+\1")
HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")
HEBREW_REPEATED_MARKS_RE = re.compile(r"([\u0591-\u05C7])\1+")
HEBREW_ORPHAN_MARKS_RE = re.compile(r"(?<![\u05D0-\u05EA\u0591-\u05C7])[\u0591-\u05C7]+")
TOKEN_RE = re.compile(r"[a-z0-9\u05D0-\u05EA]+")


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


def cleanup_quote_text(text: str, lang: LangKey) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""

    if lang == "he":
        cleaned = HEBREW_CANTILLATION_RE.sub("", cleaned)
        cleaned = cleaned.replace("\u034F", "")
        cleaned = cleaned.replace("־", "-")
        cleaned = cleaned.replace("׃", "")
        cleaned = cleaned.replace("׀", "")
        cleaned = HEBREW_REPEATED_MARKS_RE.sub(r"\1", cleaned)
        cleaned = HEBREW_ORPHAN_MARKS_RE.sub("", cleaned)
        cleaned = re.sub(r"\s*-\s*", "-", cleaned)

    cleaned = PUNCT_SPACE_RE.sub(r"\1 ", cleaned)
    cleaned = REPEATED_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = REPEATED_SPACED_PUNCT_RE.sub(r"\1", cleaned)
    return clean_text(cleaned)


def _normalized_char(ch: str, lang: LangKey) -> str:
    if lang == "he":
        if HEBREW_ALL_MARKS_RE.match(ch):
            return ""
        if ch == "\u034F":
            return ""
        if "\u05D0" <= ch <= "\u05EA":
            return ch
        if ch in {"-", "־"}:
            return " "
        if ch.isalnum():
            return ch.lower()
        return " "
    if ch.isalnum():
        return ch.lower()
    return " "


def _normalized_with_index(text: str, lang: LangKey) -> Tuple[str, List[int]]:
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


def _tokenize_with_spans(text: str, lang: LangKey) -> List[Tuple[str, int, int]]:
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


def _tokenize_for_match(text: str, lang: LangKey) -> List[str]:
    normalized, _ = _normalized_with_index(text, lang)
    if not normalized:
        return []
    return [match.group() for match in TOKEN_RE.finditer(normalized)]


def _find_subsequence(haystack: List[str], needle: List[str]) -> Optional[int]:
    if not haystack or not needle or len(needle) > len(haystack):
        return None
    limit = len(haystack) - len(needle) + 1
    for idx in range(limit):
        if haystack[idx : idx + len(needle)] == needle:
            return idx
    return None


def ensure_riddle_substring(quote: str, riddle: str, lang: LangKey) -> str:
    if not quote or not riddle:
        return quote
    if riddle in quote:
        return quote

    quote_tokens = _tokenize_with_spans(quote, lang)
    riddle_tokens = _tokenize_for_match(riddle, lang)
    if not quote_tokens or not riddle_tokens:
        return quote

    idx = _find_subsequence([token for token, _, _ in quote_tokens], riddle_tokens)
    if idx is None:
        return quote

    start = quote_tokens[idx][1]
    end = quote_tokens[idx + len(riddle_tokens) - 1][2]
    if lang == "he":
        while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
            start -= 1
        while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
            end += 1

    return cleanup_quote_text(f"{quote[:start]}{riddle}{quote[end:]}", lang)


def cleanup_quote_with_riddle(quote: str, riddle: str, lang: LangKey) -> str:
    cleaned_quote = cleanup_quote_text(quote, lang)
    return ensure_riddle_substring(cleaned_quote, riddle, lang)

