#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import text_cleanup
except ModuleNotFoundError:
    import text_cleanup  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("speaker", "listener")
LANGS = ("en", "he")

SAMPLE_PICK_PROMPT = [
    "You are selecting multiple-choice distractor options for a Bible quote puzzle.",
    "Each candidate index is one aligned EN/HE entity pair from the same source item.",
    "Return strict JSON only with shape:",
    '{"regular_add":[0,1],"hard_add":[2,3],"reason":"..."}',
    "Goal:",
    "1) Select options that make guessing speaker/listener challenging.",
    "2) regular_add = normal difficulty distractors (still challenging and context-relevant).",
    "3) hard_add = harder distractors (similar role/name/theme/quote context).",
    "Entity hygiene (critical):",
    "4) Select only concrete solvable entity labels (people, groups, titles, or stable named entities).",
    "5) Reject clauses/fragments like 'and he said', 'let the...', 'when ...', or any narrative sentence pieces.",
    "6) Reject pronouns and ultra-generic labels like 'he', 'them', 'the man', 'the woman'.",
    "6d) Semi-name group labels are acceptable when concrete in context: 'the people', 'children of Israel', 'his brethren', \"Moses' father in law\".",
    "Examples:",
    "6a) Good: 'Pharaoh', 'the king of Egypt', 'Moses', 'the Hebrew midwives', 'Aaron', 'children of Israel'.",
    "6b) Bad: 'and he said', 'let the earth', 'him', 'them', 'a soul', 'the voice of swearing'.",
    "6c) Also bad: labels beginning with reporting clauses, e.g. 'And the king of Egypt said to ...'.",
    "Guidance:",
    "7) For normal difficulty, keep plausible same-domain entities (kings with kings, family with family, prophet with prophet, etc).",
    "8) For hard difficulty, prefer near-confusable entities or lookalike contexts.",
    "9) Use quote context, not only names.",
    "10) It is acceptable for an option to fit both regular and hard.",
    "11) Never include more than one divine-name alias in the same bucket.",
    "Rules:",
    "12) Use only indices from candidates[].",
    "13) Do not invent labels.",
    "14) If uncertain, return fewer indices.",
]

VALIDATE_PROMPT = [
    "You are validating selected distractor options for a Bible quote puzzle.",
    "Selections are aligned EN/HE entity pairs.",
    "Return strict JSON only with shape:",
    '{"drop_regular":[1],"drop_hard":[0],"reason":"..."}',
    "Task:",
    "1) Remove weak/easy/irrelevant options relative to the target answer and target quote context.",
    "2) hard options should be at least as confusing as regular options.",
    "3) Remove any non-entity labels, clauses, pronouns, or generic placeholders.",
    "4) Keep options inside the same semantic domain when possible.",
    "4b) Keep concrete semi-name groups when valid for the context (the people, children of Israel, his brethren, etc).",
    "5) Keep at most one divine-name alias per bucket.",
    "Examples to drop:",
    "4a) 'and he said', 'let the ...', 'him', 'them', 'a soul', bare function words.",
    "Rules:",
    "6) Use only indices from selected_regular[] and selected_hard[].",
    "7) If all selected options are good, return empty arrays.",
    "8) Be conservative; if uncertain, keep.",
]

SOLUTION_VALIDATE_PROMPT = [
    "You are validating puzzle answer metadata for a Bible quote interaction.",
    "Return strict JSON only with shape:",
    '{"status":"keep|drop","reason":"...","checks":{"en_speaker_correct":true,"en_listener_correct":true,"he_speaker_correct":true,"he_listener_correct":true,"direction_speaker_to_listener":true,"solvable_entities":true}}',
    "Task:",
    "1) Check whether labeled speaker/listener are indeed who says and who is addressed.",
    "2) Use quote + riddle context in both English and Hebrew.",
    "3) Ensure direction is speaker -> listener for the riddle content.",
    "4) Treat plain names/titles as valid labels: 'Moses', 'Aaron', 'the LORD', 'פרעה', 'מֹשֶׁה'.",
    "5) Do NOT reject a plain label because the quote text starts with narrative wrappers like 'And NAME said'.",
    "6) Focus on semantic correctness of who speaks and who is addressed.",
    "Rules:",
    "7) status=keep only when all checks are clearly true.",
    "8) If uncertain, use status=drop.",
]

EN_PRONOUNS = {
    "he",
    "she",
    "they",
    "them",
    "him",
    "her",
    "you",
    "thou",
    "thee",
    "ye",
    "i",
    "me",
    "we",
    "us",
    "it",
    "my",
    "our",
    "his",
    "their",
    "hers",
    "himself",
    "herself",
    "themselves",
}

EN_GENERIC = {
    "a man",
    "the man",
    "man",
    "a woman",
    "the woman",
    "woman",
    "any",
    "anyone",
    "someone",
    "somebody",
    "everyone",
    "every man",
    "those men",
    "a soul",
    "their secret",
    "his young men",
    "his neighbour",
    "his neighbor",
    "his master",
    "her master",
}

EN_BAD_STARTS = (
    "and ",
    "then ",
    "if ",
    "when ",
    "because ",
    "therefore ",
    "for ",
    "to ",
    "that ",
    "let ",
)

EN_BAD_MARKERS = (
    " said ",
    " saith ",
    " saying ",
    " spake ",
    " shalt ",
    " shall ",
    " and to ",
)

HE_PRONOUNS = {
    "הוא",
    "היא",
    "הם",
    "הן",
    "אותו",
    "אותה",
    "להם",
    "להן",
    "לו",
    "לה",
}

HE_GENERIC = {
    "איש",
    "האיש",
    "אשה",
    "האשה",
    "האנשים",
}

HE_BAD_MARKERS = (
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "ותאמרו",
    "לאמר",
    "ויהי",
    "והיה",
    "ויצו",
    "ויענו",
)

EN_NON_PERSON_HINTS = {
    "altar",
    "tabernacle",
    "plague",
    "goat",
    "lamb",
    "breastplate",
    "offering",
    "sacrifice",
    "blood",
    "earth",
    "land",
    "house",
    "voice",
    "issue",
    "secret",
    "soul",
}

HE_NON_PERSON_HINTS = {
    "מזבח",
    "המזבח",
    "משכן",
    "נגע",
    "עז",
    "כבש",
    "חושן",
    "קרבן",
    "מנחה",
    "זבח",
    "דם",
    "ארץ",
    "בית",
    "הבית",
    "קול",
    "נפש",
    "גרה",
    "קרבנו",
    "מקריב",
    "כשב",
    "הגרה",
}

HE_BAD_SINGLE_TOKENS = {
    "ה",
    "דברו",
    "יחנו",
    "והביאה",
    "ולקחת",
    "ממעלי",
}

HE_PREFIX_CHARS = set("ולבכמשה")
DIVINE_ALIAS_GROUPS: Tuple[Dict[str, Dict[str, object]], ...] = (
    {
        "values": {
            "en": {
                "canonical": "God",
                "aliases": (
                    "GOD",
                    "god",
                    "the LORD",
                    "LORD",
                    "the Lord",
                    "Lord",
                    "the LORD God",
                    "LORD God",
                    "the Lord GOD",
                    "Lord GOD",
                    "Adonai",
                    "Hashem",
                    "G-d",
                    "Gd",
                    "YHWH",
                    "Jehovah",
                ),
            },
            "he": {
                "canonical": "אֱלֹהִים",
                "aliases": (
                    "אלוהים",
                    "אֱלֹהִים",
                    "אלהים",
                    "אלקים",
                    "יהוה אלוהים",
                    "יהוה אֱלֹהִים",
                    "יהוה אלהים",
                    "יְהוָה אלוהים",
                    "יְהוָה אֱלֹהִים",
                    "יְהוָה אלהים",
                    "אדני",
                    "אדוני",
                    "אֲדֹנָי",
                    "אֲדֹנָי יְהוָה",
                    "יְהוָה",
                    "יְהֹוָה",
                    "יְהוִה",
                    "יהוה",
                    "השם",
                    "ה׳",
                    "ה'",
                    "יי",
                ),
            },
        }
    },
)
DIVINE_ALIAS_LOOKUP: Dict[str, Dict[str, str]] = {lang: {} for lang in LANGS}


@dataclass(frozen=True)
class Candidate:
    label: str
    label_norm: str
    quote: str
    riddle: str
    item_id: str
    book_code: str
    book: str
    chapter: int
    verse_start: int
    verse_end: int
    label_tokens: Tuple[str, ...]
    quote_tokens: Tuple[str, ...]


@dataclass(frozen=True)
class AlignedCandidate:
    en: Candidate
    he: Candidate


@dataclass
class Stats:
    files_seen: int = 0
    files_written: int = 0
    files_skipped_existing: int = 0
    items_seen: int = 0
    items_solution_checked: int = 0
    items_dropped_solution_python: int = 0
    items_dropped_solution_check: int = 0
    items_written: int = 0
    fields_built: int = 0
    fields_insufficient_regular: int = 0
    fields_insufficient_hard: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    errors: int = 0


def _add_llm_stats(stats: Stats, llm_stats: Dict[str, int | bool]) -> None:
    stats.llm_calls += int(llm_stats.get("calls", 0))
    stats.prompt_tokens += int(llm_stats.get("prompt_tokens", 0))
    stats.response_tokens += int(llm_stats.get("response_tokens", 0))
    if bool(llm_stats.get("estimated", False)):
        stats.estimated_calls += 1


def _sanitize_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return text_cleanup.clean_text(value)


def _sanitize_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "yes", "1"}:
            return True
        if token in {"false", "no", "0"}:
            return False
    return False


def _sanitize_keep_drop(value: object) -> str:
    if not isinstance(value, str):
        return ""
    status = value.strip().lower()
    if status in {"keep", "drop"}:
        return status
    return ""


def _normalize_alias_key(text: str, lang: str) -> str:
    normalized = (text or "").lower()
    if lang == "he":
        normalized = normalized.replace("\u05be", " ")
        normalized = re.sub(r"[\u0591-\u05C7]", "", normalized)
        normalized = re.sub(r"ה['׳]", "השם", normalized)
    normalized = re.sub(r"[^\w\u0590-\u05FF]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if lang == "en":
        normalized = re.sub(r"^the\s+", "", normalized)
    return normalized


def _canonicalize_divine_name(value: str, lang: str) -> Optional[str]:
    key = _normalize_alias_key(value, lang)
    if not key:
        return None
    canonical = DIVINE_ALIAS_LOOKUP.get(lang, {}).get(key, "")
    return canonical or None


def _normalize_divine_alias(value: str, lang: str) -> Optional[str]:
    canonical = _canonicalize_divine_name(value, lang)
    if not canonical:
        return None
    return _normalize_alias_key(canonical, lang)


for _group in DIVINE_ALIAS_GROUPS:
    values = _group.get("values", {}) if isinstance(_group, dict) else {}
    if not isinstance(values, dict):
        continue
    for _lang in LANGS:
        entry = values.get(_lang, {})
        if not isinstance(entry, dict):
            continue
        canonical_value = _sanitize_str(entry.get("canonical"))
        aliases = entry.get("aliases")
        if not canonical_value or not isinstance(aliases, (list, tuple)):
            continue
        key = _normalize_alias_key(canonical_value, _lang)
        if key:
            DIVINE_ALIAS_LOOKUP[_lang][key] = canonical_value
        for alias in aliases:
            alias_text = _sanitize_str(alias)
            alias_key = _normalize_alias_key(alias_text, _lang)
            if alias_key:
                DIVINE_ALIAS_LOOKUP[_lang][alias_key] = canonical_value


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _parse_json_payload(content: str) -> Dict:
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", content, re.S)
        if not match:
            raise
        data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("LLM output is not an object")
    return data


def _call_llm_json(model: str, payload: Dict, max_attempts: int = 3) -> Tuple[Dict, Dict[str, int | bool]]:
    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_content = ""

    for attempt in range(1, max_attempts + 1):
        prompt = dict(payload)
        if attempt > 1:
            prompt["strict_json_retry"] = (
                "Previous output was invalid JSON. Return strict JSON only, parsable by json.loads."
            )

        response = chat(
            model=model,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            format="json",
            options={"temperature": 0.2, "num_predict": 384},
        )
        attempts += 1
        content = response["message"]["content"].strip()
        last_content = content

        prompt_tokens = response.get("prompt_eval_count")
        response_tokens = response.get("eval_count")
        if prompt_tokens is None or response_tokens is None:
            estimated_calls += 1
            prompt_tokens = _estimate_tokens(json.dumps(prompt, ensure_ascii=False))
            response_tokens = _estimate_tokens(content)

        total_prompt_tokens += int(prompt_tokens)
        total_response_tokens += int(response_tokens)

        try:
            data = _parse_json_payload(content)
            return data, {
                "calls": attempts,
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
            }
        except Exception:
            continue

    repaired = ""
    if last_content:
        repaired = re.sub(r",(\s*[}\]])", r"\1", last_content)
    if repaired:
        try:
            data = _parse_json_payload(repaired)
            return data, {
                "calls": attempts,
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
            }
        except Exception:
            pass

    return {}, {
        "calls": attempts,
        "prompt_tokens": total_prompt_tokens,
        "response_tokens": total_response_tokens,
        "estimated": bool(estimated_calls > 0),
    }


def _chapter_filter(expr: str) -> Set[int]:
    out: Set[int] = set()
    if not expr.strip():
        return out
    for part in expr.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                lo, hi = sorted((int(a.strip()), int(b.strip())))
                for chapter in range(lo, hi + 1):
                    out.add(chapter)
            continue
        if token.isdigit():
            out.add(int(token))
    return out


def _book_match(payload: Dict, book_filter: str) -> bool:
    if not book_filter.strip():
        return True
    target = book_filter.strip().casefold()
    code = _sanitize_str(payload.get("book_code")).casefold()
    book = _sanitize_str(payload.get("book")).casefold()
    return target in {code, book}


def _iter_input_files(in_dir: Path, include_draft: bool) -> Iterable[Path]:
    files = sorted(path for path in in_dir.rglob("*.json") if path.is_file())
    if include_draft:
        yield from files
        return
    for path in files:
        if path.stem.endswith("-draft"):
            continue
        yield path


def _normalize_label(label: str, lang: str) -> str:
    text = _sanitize_str(label)
    if not text:
        return ""
    divine = _normalize_divine_alias(text, lang)
    if divine:
        return divine
    tokens = text_cleanup.tokenize_for_match(text, lang)
    if lang == "en" and tokens and tokens[0] in {"the", "a", "an"} and len(tokens) > 1:
        tokens = tokens[1:]
    if tokens:
        return " ".join(tokens)
    return text.casefold() if lang == "en" else text


def _hebrew_unprefixed_tokens(tokens: Sequence[str]) -> Set[str]:
    out: Set[str] = set()
    for token in tokens:
        current = token
        out.add(current)
        while len(current) > 2 and current[0] in HE_PREFIX_CHARS:
            current = current[1:]
            out.add(current)
    return out


def _is_probably_non_person_label(label: str, lang: str) -> bool:
    tokens = set(text_cleanup.tokenize_for_match(label, lang))
    if not tokens:
        return False
    if lang == "en":
        return bool(tokens.intersection(EN_NON_PERSON_HINTS))
    if lang == "he":
        expanded = _hebrew_unprefixed_tokens(list(tokens))
        return bool(expanded.intersection(HE_NON_PERSON_HINTS))
    return False


def _is_viable_entity_label(label: str, lang: str, strict: bool) -> bool:
    raw = _sanitize_str(label)
    if not raw:
        return False
    if raw.startswith(("־", "-")):
        return False
    if re.search(r"[,:;?!]", raw):
        return False

    norm = _normalize_label(raw, lang)
    if not norm:
        return False
    tokens = text_cleanup.tokenize_for_match(raw, lang)
    if not tokens:
        return False

    max_tokens = 5 if strict else 7
    if len(tokens) > max_tokens:
        return False
    if _is_probably_non_person_label(raw, lang):
        return False

    if lang == "en":
        raw_lower = raw.casefold()
        lower = norm.casefold()
        if lower in EN_PRONOUNS or lower in EN_GENERIC:
            return False
        if any(token in EN_PRONOUNS for token in tokens):
            non_possessive = [
                token for token in tokens if token in EN_PRONOUNS and token not in {"his", "her", "their"}
            ]
            if non_possessive or len(tokens) == 1:
                return False
        if any(lower.startswith(prefix) for prefix in EN_BAD_STARTS):
            return False
        if any(marker in f" {lower} " for marker in EN_BAD_MARKERS):
            return False
        if lower.startswith("he that ") or lower.startswith("she that ") or " that " in lower:
            return False
        if strict and len(tokens) == 1 and lower in {"any", "all", "both", "one"}:
            return False
        if strict and not any(ch.isupper() for ch in raw):
            if raw_lower.startswith("the "):
                role = tokens[1] if len(tokens) > 1 else ""
                if role not in {
                    "lord",
                    "god",
                    "king",
                    "priest",
                    "prophet",
                    "pharaoh",
                    "midwife",
                    "midwives",
                    "servant",
                    "servants",
                    "daughter",
                    "daughters",
                    "sons",
                    "children",
                    "people",
                    "congregation",
                    "taskmasters",
                    "elder",
                    "elders",
                }:
                    return False
            elif not (tokens and tokens[0] in {"his", "her", "their"} and len(tokens) > 1):
                return False
        if strict and len(raw) > 42:
            return False
        return True

    if lang == "he":
        expanded_tokens = _hebrew_unprefixed_tokens(tokens)
        if norm in HE_PRONOUNS or norm in HE_GENERIC:
            return False
        if expanded_tokens.intersection(HE_PRONOUNS) or expanded_tokens.intersection(HE_GENERIC):
            return False
        if any(marker in norm for marker in HE_BAD_MARKERS):
            return False
        if len(tokens) == 1 and (len(tokens[0]) <= 2 or tokens[0] in HE_BAD_SINGLE_TOKENS):
            return False
        if strict and tokens and tokens[0].startswith("ו"):
            return False
        if expanded_tokens.intersection({"אל", "את", "על", "עם", "ל", "ב", "ה", "אם", "כי"}):
            return False
        if strict and len(raw) > 30:
            return False
        return True

    return True


def _token_set(text: str, lang: str) -> Set[str]:
    return set(text_cleanup.tokenize_for_match(text, lang))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    if inter == 0:
        return 0.0
    union = len(a.union(b))
    return inter / union if union else 0.0


def _stable_hash(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _candidate_seed_rank(candidate: Candidate, seed: str) -> int:
    key = (
        f"{seed}|{candidate.item_id}|{candidate.book}|{candidate.chapter}|"
        f"{candidate.verse_start}-{candidate.verse_end}|{candidate.label_norm}"
    )
    return _stable_hash(key)


def _candidate_score(
    *,
    candidate: Candidate,
    lang: str,
    answer_tokens: Set[str],
    target_quote_tokens: Set[str],
    target_riddle_tokens: Set[str],
) -> Tuple[float, float]:
    label_overlap = _jaccard(set(candidate.label_tokens), answer_tokens)
    quote_overlap = _jaccard(set(candidate.quote_tokens), target_quote_tokens)
    riddle_overlap = _jaccard(set(candidate.quote_tokens), target_riddle_tokens)

    quality_factor = 1.0
    if not _is_viable_entity_label(candidate.label, lang, strict=True):
        quality_factor = 0.65 if _is_viable_entity_label(candidate.label, lang, strict=False) else 0.0

    hard_score = ((0.58 * label_overlap) + (0.30 * quote_overlap) + (0.12 * riddle_overlap)) * quality_factor
    regular_balance = 1.0 - abs(label_overlap - 0.25)
    regular_score = ((0.56 * quote_overlap) + (0.24 * riddle_overlap) + (0.20 * regular_balance)) * quality_factor
    return regular_score, hard_score


def _sanitize_indices(raw: object, size: int) -> List[int]:
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    seen: Set[int] = set()
    for entry in raw:
        idx = _sanitize_int(entry, fallback=-1)
        if idx < 0 or idx >= size or idx in seen:
            continue
        seen.add(idx)
        out.append(idx)
    return out


def _build_candidate(
    *,
    item: Dict,
    payload: Dict,
    lang: str,
    field: str,
) -> Optional[Candidate]:
    section = item.get(lang)
    if not isinstance(section, dict):
        return None

    label = _sanitize_str(section.get(field))
    quote = _sanitize_str(section.get("quote"))
    riddle = _sanitize_str(section.get("riddle"))
    if not label or not quote:
        return None

    label_norm = _normalize_label(label, lang)
    if not label_norm:
        return None

    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    book_code = _sanitize_str(source.get("book_code")) or _sanitize_str(payload.get("book_code"))
    book = _sanitize_str(source.get("book")) or _sanitize_str(payload.get("book"))
    chapter = _sanitize_int(source.get("chapter"), _sanitize_int(payload.get("chapter"), 0))
    verse_start = _sanitize_int(source.get("quote_verse_start"), 0)
    verse_end = _sanitize_int(source.get("quote_verse_end"), 0)
    item_id = _sanitize_str(item.get("id"))

    return Candidate(
        label=label,
        label_norm=label_norm,
        quote=quote,
        riddle=riddle,
        item_id=item_id,
        book_code=book_code,
        book=book,
        chapter=chapter,
        verse_start=verse_start,
        verse_end=verse_end,
        label_tokens=tuple(text_cleanup.tokenize_for_match(label, lang)),
        quote_tokens=tuple(text_cleanup.tokenize_for_match(quote, lang)),
    )


def _build_aligned_candidate(
    *,
    item: Dict,
    payload: Dict,
    field: str,
) -> Optional[AlignedCandidate]:
    en_candidate = _build_candidate(item=item, payload=payload, lang="en", field=field)
    he_candidate = _build_candidate(item=item, payload=payload, lang="he", field=field)
    if en_candidate is None or he_candidate is None:
        return None
    if not en_candidate.item_id or en_candidate.item_id != he_candidate.item_id:
        return None
    return AlignedCandidate(en=en_candidate, he=he_candidate)


def _collect_candidate_pools(
    payloads: Sequence[Tuple[Path, Dict]],
) -> Dict[str, List[AlignedCandidate]]:
    pools: Dict[str, List[AlignedCandidate]] = {field: [] for field in FIELDS}
    for _, payload in payloads:
        items = payload.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in FIELDS:
                candidate = _build_aligned_candidate(item=item, payload=payload, field=field)
                if candidate is None:
                    continue
                pools[field].append(candidate)
    return pools


def _normalized_book_key(value: str) -> str:
    return _sanitize_str(value).casefold()


def _same_book(
    candidate: AlignedCandidate,
    *,
    target_book_code: str,
    target_book: str,
) -> bool:
    if target_book_code:
        return _normalized_book_key(candidate.en.book_code) == _normalized_book_key(target_book_code)
    if not target_book:
        return True
    return _normalized_book_key(candidate.en.book) == _normalized_book_key(target_book)


def _aligned_candidate_key(candidate: AlignedCandidate) -> str:
    return f"{candidate.en.label_norm}|{candidate.he.label_norm}"


def _aligned_candidate_seed_rank(candidate: AlignedCandidate, seed: str) -> int:
    key = (
        f"{seed}|{candidate.en.item_id}|{candidate.en.book_code}|{candidate.en.book}|{candidate.en.chapter}|"
        f"{candidate.en.verse_start}-{candidate.en.verse_end}|{_aligned_candidate_key(candidate)}"
    )
    return _stable_hash(key)


def _prepare_candidate_queue(
    *,
    candidates: Sequence[AlignedCandidate],
    answer_norm_en: str,
    answer_norm_he: str,
    seed: str,
    option_count: int,
    same_book_only: bool,
    target_book_code: str,
    target_book: str,
) -> List[AlignedCandidate]:
    ordered = sorted(candidates, key=lambda c: _aligned_candidate_seed_rank(c, seed))
    strict_out: List[AlignedCandidate] = []
    relaxed_out: List[AlignedCandidate] = []
    seen_en_norms: Set[str] = set()
    seen_he_norms: Set[str] = set()
    for candidate in ordered:
        if same_book_only and not _same_book(
            candidate,
            target_book_code=target_book_code,
            target_book=target_book,
        ):
            continue
        if (
            candidate.en.label_norm == answer_norm_en
            or candidate.he.label_norm == answer_norm_he
            or candidate.en.label_norm == answer_norm_he
            or candidate.he.label_norm == answer_norm_en
        ):
            continue
        if (
            not candidate.en.label_norm
            or not candidate.he.label_norm
            or candidate.en.label_norm in seen_en_norms
            or candidate.he.label_norm in seen_he_norms
        ):
            continue
        seen_en_norms.add(candidate.en.label_norm)
        seen_he_norms.add(candidate.he.label_norm)
        if _is_viable_entity_label(candidate.en.label, "en", strict=True) and _is_viable_entity_label(
            candidate.he.label, "he", strict=True
        ):
            strict_out.append(candidate)
            continue
        if _is_viable_entity_label(candidate.en.label, "en", strict=False) and _is_viable_entity_label(
            candidate.he.label, "he", strict=False
        ):
            relaxed_out.append(candidate)

    strict_floor = max(option_count * 2, 8)
    if len(strict_out) >= strict_floor:
        return strict_out
    return strict_out + relaxed_out


def _clip_text(value: str, max_chars: int = 220) -> str:
    text = _sanitize_str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _candidate_to_prompt(candidate: AlignedCandidate, idx: int) -> Dict:
    return {
        "idx": idx,
        "label_en": candidate.en.label,
        "label_he": candidate.he.label,
        "quote_en": _clip_text(candidate.en.quote),
        "quote_he": _clip_text(candidate.he.quote),
        "riddle_en": _clip_text(candidate.en.riddle, max_chars=96),
        "riddle_he": _clip_text(candidate.he.riddle, max_chars=96),
        "source": {
            "item_id": candidate.en.item_id,
            "book_code": candidate.en.book_code,
            "book": candidate.en.book,
            "chapter": candidate.en.chapter,
            "start": candidate.en.verse_start,
            "end": candidate.en.verse_end,
        },
    }


def _selected_to_prompt(selected: Sequence[AlignedCandidate]) -> List[Dict]:
    return [
        {
            "idx": idx,
            "label_en": candidate.en.label,
            "label_he": candidate.he.label,
            "quote_en": _clip_text(candidate.en.quote),
            "quote_he": _clip_text(candidate.he.quote),
            "riddle_en": _clip_text(candidate.en.riddle, max_chars=96),
            "riddle_he": _clip_text(candidate.he.riddle, max_chars=96),
            "source": {
                "item_id": candidate.en.item_id,
                "book_code": candidate.en.book_code,
                "book": candidate.en.book,
                "chapter": candidate.en.chapter,
                "start": candidate.en.verse_start,
                "end": candidate.en.verse_end,
            },
        }
        for idx, candidate in enumerate(selected)
    ]


def _aligned_candidate_score(
    *,
    candidate: AlignedCandidate,
    answer_tokens_en: Set[str],
    answer_tokens_he: Set[str],
    target_quote_tokens_en: Set[str],
    target_quote_tokens_he: Set[str],
    target_riddle_tokens_en: Set[str],
    target_riddle_tokens_he: Set[str],
) -> Tuple[float, float]:
    regular_en, hard_en = _candidate_score(
        candidate=candidate.en,
        lang="en",
        answer_tokens=answer_tokens_en,
        target_quote_tokens=target_quote_tokens_en,
        target_riddle_tokens=target_riddle_tokens_en,
    )
    regular_he, hard_he = _candidate_score(
        candidate=candidate.he,
        lang="he",
        answer_tokens=answer_tokens_he,
        target_quote_tokens=target_quote_tokens_he,
        target_riddle_tokens=target_riddle_tokens_he,
    )
    quality = 1.0
    strict_en = _is_viable_entity_label(candidate.en.label, "en", strict=True)
    strict_he = _is_viable_entity_label(candidate.he.label, "he", strict=True)
    if not strict_en or not strict_he:
        quality = 0.72
        if not _is_viable_entity_label(candidate.en.label, "en", strict=False):
            return 0.0, 0.0
        if not _is_viable_entity_label(candidate.he.label, "he", strict=False):
            return 0.0, 0.0
    regular = ((regular_en + regular_he) / 2.0) * quality
    hard = ((hard_en + hard_he) / 2.0) * quality
    return regular, hard


def _append_candidate(
    *,
    bucket: List[AlignedCandidate],
    bucket_en_norms: Set[str],
    bucket_he_norms: Set[str],
    candidate: AlignedCandidate,
    max_count: int,
) -> bool:
    if len(bucket) >= max_count:
        return False
    if (
        not candidate.en.label_norm
        or not candidate.he.label_norm
        or candidate.en.label_norm in bucket_en_norms
        or candidate.he.label_norm in bucket_he_norms
    ):
        return False
    bucket.append(candidate)
    bucket_en_norms.add(candidate.en.label_norm)
    bucket_he_norms.add(candidate.he.label_norm)
    return True


def _fill_bucket_with_fallback(
    *,
    bucket: List[AlignedCandidate],
    other_bucket: Sequence[AlignedCandidate],
    queue: Sequence[AlignedCandidate],
    max_count: int,
    score_kind: str,
    answer_tokens_en: Set[str],
    answer_tokens_he: Set[str],
    target_quote_tokens_en: Set[str],
    target_quote_tokens_he: Set[str],
    target_riddle_tokens_en: Set[str],
    target_riddle_tokens_he: Set[str],
) -> None:
    if len(bucket) >= max_count:
        return

    bucket_en_norms = {candidate.en.label_norm for candidate in bucket}
    bucket_he_norms = {candidate.he.label_norm for candidate in bucket}
    other_en_norms = {candidate.en.label_norm for candidate in other_bucket}
    other_he_norms = {candidate.he.label_norm for candidate in other_bucket}
    scored: List[Tuple[float, AlignedCandidate]] = []

    for candidate in queue:
        regular_score, hard_score = _aligned_candidate_score(
            candidate=candidate,
            answer_tokens_en=answer_tokens_en,
            answer_tokens_he=answer_tokens_he,
            target_quote_tokens_en=target_quote_tokens_en,
            target_quote_tokens_he=target_quote_tokens_he,
            target_riddle_tokens_en=target_riddle_tokens_en,
            target_riddle_tokens_he=target_riddle_tokens_he,
        )
        score = hard_score if score_kind == "hard" else regular_score
        scored.append((score, candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    for allow_overlap in (False, True):
        for _, candidate in scored:
            if (
                candidate.en.label_norm in bucket_en_norms
                or candidate.he.label_norm in bucket_he_norms
            ):
                continue
            if not allow_overlap and (
                candidate.en.label_norm in other_en_norms
                or candidate.he.label_norm in other_he_norms
            ):
                continue
            if _append_candidate(
                bucket=bucket,
                bucket_en_norms=bucket_en_norms,
                bucket_he_norms=bucket_he_norms,
                candidate=candidate,
                max_count=max_count,
            ):
                if len(bucket) >= max_count:
                    return


def _quote_has_divine_name(quote: str, lang: str) -> bool:
    return bool(text_cleanup.best_god_name_in_quote(_sanitize_str(quote), lang))


def _entity_present_in_quote(entity: str, quote: str, lang: str) -> bool:
    if text_cleanup.entity_in_quote(entity, quote, lang):
        return True
    return bool(_normalize_divine_alias(entity, lang) and _quote_has_divine_name(quote, lang))


def _is_solution_entity_label(label: str, lang: str) -> bool:
    raw = _sanitize_str(label)
    if not raw:
        return False
    norm = _normalize_label(raw, lang)
    if not norm:
        return False
    tokens = text_cleanup.tokenize_for_match(raw, lang)
    if not tokens:
        return False

    if lang == "en":
        lower = raw.strip().lower()
        if lower in EN_PRONOUNS:
            return False
        if lower.startswith(("he ", "she ", "they ", "them ", "him ", "her ", "you ", "thou ", "thee ", "ye ")):
            return False
        if any(marker in f" {lower} " for marker in EN_BAD_MARKERS):
            return False
        if len(tokens) > 8:
            return False
        return True

    if lang == "he":
        expanded_tokens = _hebrew_unprefixed_tokens(tokens)
        if norm in HE_PRONOUNS or expanded_tokens.intersection(HE_PRONOUNS):
            return False
        if any(marker in norm for marker in HE_BAD_MARKERS):
            return False
        if len(tokens) > 8:
            return False
        return True

    return False


def _python_validate_solution(item: Dict) -> Tuple[bool, str]:
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
    for lang, section in (("en", en), ("he", he)):
        quote = _sanitize_str(section.get("quote"))
        if not quote:
            return False, f"{lang}_missing_quote"
        speaker = _sanitize_str(section.get("speaker"))
        listener = _sanitize_str(section.get("listener"))
        if not speaker:
            return False, f"{lang}_missing_speaker"
        if not listener:
            return False, f"{lang}_missing_listener"
        if not _is_solution_entity_label(speaker, lang):
            return False, f"{lang}_speaker_not_entity"
        if not _is_solution_entity_label(listener, lang):
            return False, f"{lang}_listener_not_entity"
        if not _entity_present_in_quote(speaker, quote, lang):
            return False, f"{lang}_speaker_not_in_quote"
        if not _entity_present_in_quote(listener, quote, lang):
            return False, f"{lang}_listener_not_in_quote"
        if _normalize_label(speaker, lang) == _normalize_label(listener, lang):
            return False, f"{lang}_speaker_listener_same"
    return True, "python_solution_ok"


def _llm_validate_solution(
    *,
    model: str,
    item: Dict,
    retries: int,
) -> Tuple[bool, str, Dict[str, int | bool]]:
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}

    payload = {
        "instructions": SOLUTION_VALIDATE_PROMPT,
        "context": {
            "item_id": _sanitize_str(item.get("id")),
            "book_code": _sanitize_str(source.get("book_code")),
            "book": _sanitize_str(source.get("book")),
            "chapter": _sanitize_int(source.get("chapter"), 0),
        },
        "en": {
            "quote": _sanitize_str(en.get("quote")),
            "riddle": _sanitize_str(en.get("riddle")),
            "speaker": _sanitize_str(en.get("speaker")),
            "listener": _sanitize_str(en.get("listener")),
        },
        "he": {
            "quote": _sanitize_str(he.get("quote")),
            "riddle": _sanitize_str(he.get("riddle")),
            "speaker": _sanitize_str(he.get("speaker")),
            "listener": _sanitize_str(he.get("listener")),
        },
    }

    data, llm_stats = _call_llm_json(
        model=model,
        payload=payload,
        max_attempts=max(1, retries),
    )

    status = _sanitize_keep_drop(data.get("status"))
    reason = _sanitize_str(data.get("reason")) or "solution_check_failed"
    checks = data.get("checks", {}) if isinstance(data.get("checks"), dict) else {}
    required_checks = (
        _to_bool(checks.get("en_speaker_correct")),
        _to_bool(checks.get("en_listener_correct")),
        _to_bool(checks.get("he_speaker_correct")),
        _to_bool(checks.get("he_listener_correct")),
        _to_bool(checks.get("direction_speaker_to_listener")),
        _to_bool(checks.get("solvable_entities")),
    )

    is_valid = status == "keep" and all(required_checks)
    return is_valid, reason, llm_stats


def _select_options_for_field(
    *,
    model: str,
    skip_llm: bool,
    field: str,
    item_id: str,
    answer_en: str,
    answer_he: str,
    target_quote_en: str,
    target_quote_he: str,
    target_riddle_en: str,
    target_riddle_he: str,
    candidates: Sequence[AlignedCandidate],
    option_count: int,
    sample_size: int,
    max_rounds: int,
    llm_retries: int,
    same_book_only: bool,
    target_book_code: str,
    target_book: str,
) -> Tuple[List[AlignedCandidate], List[AlignedCandidate], Dict[str, int | bool], List[str]]:
    llm_totals: Dict[str, int | bool] = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }
    notes: List[str] = []

    answer_norm_en = _normalize_label(answer_en, "en")
    answer_norm_he = _normalize_label(answer_he, "he")
    queue = _prepare_candidate_queue(
        candidates=candidates,
        answer_norm_en=answer_norm_en,
        answer_norm_he=answer_norm_he,
        seed=f"{item_id}:{field}",
        option_count=option_count,
        same_book_only=same_book_only,
        target_book_code=target_book_code,
        target_book=target_book,
    )
    strict_count = sum(
        1
        for candidate in queue
        if _is_viable_entity_label(candidate.en.label, "en", strict=True)
        and _is_viable_entity_label(candidate.he.label, "he", strict=True)
    )
    if strict_count < option_count * 2:
        notes.append(f"low_strict_candidates:{strict_count}")

    selected_regular: List[AlignedCandidate] = []
    selected_hard: List[AlignedCandidate] = []
    regular_en_norms: Set[str] = set()
    regular_he_norms: Set[str] = set()
    hard_en_norms: Set[str] = set()
    hard_he_norms: Set[str] = set()

    rounds = 0
    cursor = 0
    if not skip_llm:
        while rounds < max_rounds:
            if len(selected_regular) >= option_count and len(selected_hard) >= option_count:
                break
            if cursor >= len(queue):
                break

            batch = list(queue[cursor : cursor + sample_size])
            cursor += sample_size
            rounds += 1
            if not batch:
                break

            payload = {
                "instructions": SAMPLE_PICK_PROMPT,
                "selection_policy": {
                    "entity_only": True,
                    "avoid_clauses_pronouns_generic": True,
                },
                "target": {
                    "item_id": item_id,
                    "field": field,
                    "answer_en": answer_en,
                    "answer_he": answer_he,
                    "quote_en": target_quote_en,
                    "quote_he": target_quote_he,
                    "riddle_en": target_riddle_en,
                    "riddle_he": target_riddle_he,
                },
                "limits": {
                    "regular_target_count": option_count,
                    "hard_target_count": option_count,
                },
                "already_selected": {
                    "regular": _selected_to_prompt(selected_regular),
                    "hard": _selected_to_prompt(selected_hard),
                },
                "candidates": [_candidate_to_prompt(candidate, idx) for idx, candidate in enumerate(batch)],
            }
            data, llm_stats = _call_llm_json(
                model=model,
                payload=payload,
                max_attempts=max(1, llm_retries),
            )
            llm_totals["calls"] = int(llm_totals["calls"]) + int(llm_stats.get("calls", 0))
            llm_totals["prompt_tokens"] = int(llm_totals["prompt_tokens"]) + int(
                llm_stats.get("prompt_tokens", 0)
            )
            llm_totals["response_tokens"] = int(llm_totals["response_tokens"]) + int(
                llm_stats.get("response_tokens", 0)
            )
            llm_totals["estimated"] = bool(llm_totals["estimated"]) or bool(llm_stats.get("estimated", False))

            regular_indices = _sanitize_indices(data.get("regular_add"), len(batch))
            hard_indices = _sanitize_indices(data.get("hard_add"), len(batch))

            for idx in regular_indices:
                candidate = batch[idx]
                _append_candidate(
                    bucket=selected_regular,
                    bucket_en_norms=regular_en_norms,
                    bucket_he_norms=regular_he_norms,
                    candidate=candidate,
                    max_count=option_count,
                )
            for idx in hard_indices:
                candidate = batch[idx]
                _append_candidate(
                    bucket=selected_hard,
                    bucket_en_norms=hard_en_norms,
                    bucket_he_norms=hard_he_norms,
                    candidate=candidate,
                    max_count=option_count,
                )

        if selected_regular or selected_hard:
            payload = {
                "instructions": VALIDATE_PROMPT,
                "target": {
                    "item_id": item_id,
                    "field": field,
                    "answer_en": answer_en,
                    "answer_he": answer_he,
                    "quote_en": target_quote_en,
                    "quote_he": target_quote_he,
                    "riddle_en": target_riddle_en,
                    "riddle_he": target_riddle_he,
                },
                "selected_regular": _selected_to_prompt(selected_regular),
                "selected_hard": _selected_to_prompt(selected_hard),
            }
            data, llm_stats = _call_llm_json(
                model=model,
                payload=payload,
                max_attempts=max(1, llm_retries),
            )
            llm_totals["calls"] = int(llm_totals["calls"]) + int(llm_stats.get("calls", 0))
            llm_totals["prompt_tokens"] = int(llm_totals["prompt_tokens"]) + int(
                llm_stats.get("prompt_tokens", 0)
            )
            llm_totals["response_tokens"] = int(llm_totals["response_tokens"]) + int(
                llm_stats.get("response_tokens", 0)
            )
            llm_totals["estimated"] = bool(llm_totals["estimated"]) or bool(llm_stats.get("estimated", False))

            drop_regular = set(_sanitize_indices(data.get("drop_regular"), len(selected_regular)))
            drop_hard = set(_sanitize_indices(data.get("drop_hard"), len(selected_hard)))
            if drop_regular:
                selected_regular = [
                    candidate
                    for idx, candidate in enumerate(selected_regular)
                    if idx not in drop_regular
                ]
                regular_en_norms = {candidate.en.label_norm for candidate in selected_regular}
                regular_he_norms = {candidate.he.label_norm for candidate in selected_regular}
            if drop_hard:
                selected_hard = [
                    candidate for idx, candidate in enumerate(selected_hard) if idx not in drop_hard
                ]
                hard_en_norms = {candidate.en.label_norm for candidate in selected_hard}
                hard_he_norms = {candidate.he.label_norm for candidate in selected_hard}

    answer_tokens_en = _token_set(answer_en, "en")
    answer_tokens_he = _token_set(answer_he, "he")
    target_quote_tokens_en = _token_set(target_quote_en, "en")
    target_quote_tokens_he = _token_set(target_quote_he, "he")
    target_riddle_tokens_en = _token_set(target_riddle_en, "en")
    target_riddle_tokens_he = _token_set(target_riddle_he, "he")

    _fill_bucket_with_fallback(
        bucket=selected_regular,
        other_bucket=selected_hard,
        queue=queue,
        max_count=option_count,
        score_kind="regular",
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
    )
    _fill_bucket_with_fallback(
        bucket=selected_hard,
        other_bucket=selected_regular,
        queue=queue,
        max_count=option_count,
        score_kind="hard",
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
    )

    regular_selected = selected_regular[:option_count]
    hard_selected = selected_hard[:option_count]

    if len(regular_selected) < option_count:
        notes.append(f"regular_short:{len(regular_selected)}/{option_count}")
    if len(hard_selected) < option_count:
        notes.append(f"hard_short:{len(hard_selected)}/{option_count}")

    return regular_selected, hard_selected, llm_totals, notes


def _build_output_item(
    *,
    item: Dict,
    pools: Dict[str, List[AlignedCandidate]],
    model: str,
    skip_llm: bool,
    option_count: int,
    sample_size: int,
    max_rounds: int,
    llm_retries: int,
    same_book_only: bool,
    target_book_code: str,
    target_book: str,
) -> Tuple[Dict, Dict[str, int | bool], List[Dict]]:
    item_id = _sanitize_str(item.get("id"))
    out_item = copy.deepcopy(item)
    for lang in LANGS:
        section = out_item.get(lang)
        if not isinstance(section, dict):
            section = {}
            out_item[lang] = section
        section["speaker"] = _sanitize_str(section.get("speaker"))
        section["listener"] = _sanitize_str(section.get("listener"))
        section["options"] = {"speaker": [], "listener": []}
        section["hard_difficulty_options"] = {"speaker": [], "listener": []}

    llm_totals: Dict[str, int | bool] = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }
    issues: List[Dict] = []

    en_section = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he_section = item.get("he", {}) if isinstance(item.get("he"), dict) else {}

    for field in FIELDS:
        answer_en = _sanitize_str(en_section.get(field))
        answer_he = _sanitize_str(he_section.get(field))
        target_quote_en = _sanitize_str(en_section.get("quote"))
        target_quote_he = _sanitize_str(he_section.get("quote"))
        target_riddle_en = _sanitize_str(en_section.get("riddle"))
        target_riddle_he = _sanitize_str(he_section.get("riddle"))
        if not answer_en or not answer_he or not target_quote_en or not target_quote_he:
            issues.append(
                {
                    "id": item_id,
                    "field": field,
                    "status": "skip_missing_target_data",
                }
            )
            continue

        regular, hard, field_stats, notes = _select_options_for_field(
            model=model,
            skip_llm=skip_llm,
            field=field,
            item_id=item_id,
            answer_en=answer_en,
            answer_he=answer_he,
            target_quote_en=target_quote_en,
            target_quote_he=target_quote_he,
            target_riddle_en=target_riddle_en,
            target_riddle_he=target_riddle_he,
            candidates=pools[field],
            option_count=option_count,
            sample_size=sample_size,
            max_rounds=max_rounds,
            llm_retries=llm_retries,
            same_book_only=same_book_only,
            target_book_code=target_book_code,
            target_book=target_book,
        )
        llm_totals["calls"] = int(llm_totals["calls"]) + int(field_stats.get("calls", 0))
        llm_totals["prompt_tokens"] = int(llm_totals["prompt_tokens"]) + int(
            field_stats.get("prompt_tokens", 0)
        )
        llm_totals["response_tokens"] = int(llm_totals["response_tokens"]) + int(
            field_stats.get("response_tokens", 0)
        )
        llm_totals["estimated"] = bool(llm_totals["estimated"]) or bool(field_stats.get("estimated", False))

        out_item["en"]["options"][field] = [candidate.en.label for candidate in regular]
        out_item["he"]["options"][field] = [candidate.he.label for candidate in regular]
        out_item["en"]["hard_difficulty_options"][field] = [candidate.en.label for candidate in hard]
        out_item["he"]["hard_difficulty_options"][field] = [candidate.he.label for candidate in hard]

        if notes:
            issues.append(
                {
                    "id": item_id,
                    "field": field,
                    "status": "notes",
                    "notes": notes,
                }
            )

    return out_item, llm_totals, issues


def _out_path_for_input(in_path: Path, out_dir: Path, in_dir: Path) -> Path:
    try:
        rel = in_path.relative_to(in_dir)
    except ValueError:
        rel = Path(in_path.name)
    return out_dir / rel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--in-dir", default="data/quotes")
    parser.add_argument("--out-dir", default="data/quotes_options")
    parser.add_argument("--issues-log", default="data/quotes_options_issues.jsonl")
    parser.add_argument("--book", default="", help="book filter by code or name, e.g. GEN or Genesis")
    parser.add_argument("--chapters", default="", help="chapter filter, e.g. 1-3,12,15")
    parser.add_argument(
        "--same-book-only",
        action="store_true",
        help="restrict distractor candidates to the same book as the target item",
    )
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--option-count", type=int, default=4)
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--llm-retries", type=int, default=2)
    parser.add_argument(
        "--solution-check-model",
        default="gemma3:27b",
        help="model for solution validation (larger model recommended)",
    )
    parser.add_argument("--solution-check-retries", type=int, default=2)
    parser.add_argument("--skip-llm-solution-check", action="store_true")
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.option_count < 1:
        raise SystemExit("--option-count must be >= 1")
    if args.sample_size < 1:
        raise SystemExit("--sample-size must be >= 1")
    if args.max_rounds < 0:
        raise SystemExit("--max-rounds must be >= 0")
    if args.llm_retries < 1:
        raise SystemExit("--llm-retries must be >= 1")
    if args.solution_check_retries < 1:
        raise SystemExit("--solution-check-retries must be >= 1")

    in_dir = (ROOT / args.in_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()
    solution_check_model = _sanitize_str(args.solution_check_model) or _sanitize_str(args.model)
    if not in_dir.exists() or not in_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {in_dir}")

    chapter_filter = _chapter_filter(args.chapters)
    in_files = list(_iter_input_files(in_dir, include_draft=bool(args.include_draft)))
    if args.limit_files > 0:
        in_files = in_files[: args.limit_files]

    payloads: List[Tuple[Path, Dict]] = []
    stats = Stats()
    issue_lines: List[str] = []

    for in_path in tqdm(in_files, desc="load-files", unit="file"):
        stats.files_seen += 1
        try:
            payload = json.loads(in_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: PERF203
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": f"read_failed:{exc}",
                    },
                    ensure_ascii=False,
                )
            )
            continue
        if not isinstance(payload, dict):
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": "payload_not_object",
                    },
                    ensure_ascii=False,
                )
            )
            continue
        payloads.append((in_path, payload))

    if not payloads:
        tqdm.write("No readable payloads to process.")
        return 1 if stats.errors else 0

    pools = _collect_candidate_pools(payloads)

    queue: List[Tuple[Path, Dict]] = []
    for in_path, payload in payloads:
        if not _book_match(payload, args.book):
            continue
        chapter = _sanitize_int(payload.get("chapter"), 0)
        if chapter_filter and chapter not in chapter_filter:
            continue
        out_path = _out_path_for_input(in_path, out_dir, in_dir)
        if out_path.exists() and not args.force:
            stats.files_skipped_existing += 1
            continue
        queue.append((in_path, payload))

    tqdm.write(
        "Hard-option queue: files={files} pending={pending} skipped_existing={skipped} "
        "in_dir={in_dir} out_dir={out_dir} include_draft={include_draft} skip_llm={skip_llm} "
        "solution_check={solution_check} solution_check_model={solution_check_model} same_book_only={same_book_only}".format(
            files=len(payloads),
            pending=len(queue),
            skipped=stats.files_skipped_existing,
            in_dir=in_dir,
            out_dir=out_dir,
            include_draft=bool(args.include_draft),
            skip_llm=bool(args.skip_llm),
            solution_check=not bool(args.skip_llm_solution_check),
            solution_check_model=solution_check_model,
            same_book_only=bool(args.same_book_only),
        )
    )
    if not queue:
        return 1 if stats.errors else 0

    issues_log.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not issues_log.exists():
        issues_log.write_text("", encoding="utf-8")

    for in_path, payload in tqdm(queue, desc="hard-options", unit="file"):
        items = payload.get("items", [])
        if not isinstance(items, list):
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": "items_not_list",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        out_items: List[Dict] = []
        file_issues: List[Dict] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                stats.errors += 1
                file_issues.append(
                    {
                        "idx": idx,
                        "status": "item_not_object",
                    }
                )
                continue

            stats.items_seen += 1
            python_solution_ok, python_solution_reason = _python_validate_solution(item)
            if not python_solution_ok:
                stats.items_dropped_solution_python += 1

            llm_solution_ok = True
            llm_solution_reason = "solution_check_skipped"
            if not args.skip_llm_solution_check:
                stats.items_solution_checked += 1
                llm_solution_ok, llm_solution_reason, solution_stats = _llm_validate_solution(
                    model=solution_check_model,
                    item=item,
                    retries=args.solution_check_retries,
                )
                _add_llm_stats(stats, solution_stats)
            if not python_solution_ok or not llm_solution_ok:
                stats.items_dropped_solution_check += 1
                reasons: List[str] = []
                if not python_solution_ok:
                    reasons.append(f"python:{python_solution_reason}")
                if not llm_solution_ok:
                    reasons.append(f"llm:{llm_solution_reason or 'solution_check_failed'}")
                file_issues.append(
                    {
                        "idx": idx,
                        "id": _sanitize_str(item.get("id")),
                        "status": "drop_invalid_solution",
                        "reason": "; ".join(reasons) if reasons else "solution_check_failed",
                    }
                )
                continue

            source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
            target_book_code = _sanitize_str(source.get("book_code")) or _sanitize_str(payload.get("book_code"))
            target_book = _sanitize_str(source.get("book")) or _sanitize_str(payload.get("book"))

            out_item, field_stats, item_issues = _build_output_item(
                item=item,
                pools=pools,
                model=_sanitize_str(args.model),
                skip_llm=bool(args.skip_llm),
                option_count=args.option_count,
                sample_size=args.sample_size,
                max_rounds=args.max_rounds,
                llm_retries=args.llm_retries,
                same_book_only=bool(args.same_book_only),
                target_book_code=target_book_code,
                target_book=target_book,
            )
            _add_llm_stats(stats, field_stats)

            for lang in LANGS:
                for field in FIELDS:
                    stats.fields_built += 1
                    if len(out_item[lang]["options"][field]) < args.option_count:
                        stats.fields_insufficient_regular += 1
                    if len(out_item[lang]["hard_difficulty_options"][field]) < args.option_count:
                        stats.fields_insufficient_hard += 1

            if item_issues:
                for issue in item_issues:
                    merged = {"idx": idx}
                    merged.update(issue)
                    file_issues.append(merged)

            out_items.append(out_item)
            stats.items_written += 1

        out_payload = copy.deepcopy(payload)
        out_payload["items"] = out_items

        out_path = _out_path_for_input(in_path, out_dir, in_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stats.files_written += 1

        if file_issues:
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "output_file": str(out_path),
                        "status": "item_issues",
                        "issues": file_issues,
                    },
                    ensure_ascii=False,
                )
            )

    if issue_lines:
        with issues_log.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    tqdm.write(
        "Done: files_seen={files_seen}, files_written={files_written}, files_skipped_existing={files_skipped_existing}, "
        "items_seen={items_seen}, items_solution_checked={items_solution_checked}, items_dropped_solution_python={items_dropped_solution_python}, "
        "items_dropped_solution_check={items_dropped_solution_check}, items_written={items_written}, fields_built={fields_built}, "
        "fields_insufficient_regular={fields_insufficient_regular}, fields_insufficient_hard={fields_insufficient_hard}, "
        "llm_calls={llm_calls}, prompt_tokens={prompt_tokens}, response_tokens={response_tokens}, estimated_calls={estimated_calls}, "
        "errors={errors}, out_dir={out_dir}, issues_log={issues_log}".format(
            files_seen=stats.files_seen,
            files_written=stats.files_written,
            files_skipped_existing=stats.files_skipped_existing,
            items_seen=stats.items_seen,
            items_solution_checked=stats.items_solution_checked,
            items_dropped_solution_python=stats.items_dropped_solution_python,
            items_dropped_solution_check=stats.items_dropped_solution_check,
            items_written=stats.items_written,
            fields_built=stats.fields_built,
            fields_insufficient_regular=stats.fields_insufficient_regular,
            fields_insufficient_hard=stats.fields_insufficient_hard,
            llm_calls=stats.llm_calls,
            prompt_tokens=stats.prompt_tokens,
            response_tokens=stats.response_tokens,
            estimated_calls=stats.estimated_calls,
            errors=stats.errors,
            out_dir=out_dir,
            issues_log=issues_log,
        )
    )
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
