from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import click
from tqdm import tqdm

from data_proc.llm import JsonChatModel
from data_proc.pipeline import (
    _canonical_book_filter,
    _chapter_sort_key,
    _drop_outputs_from_resume_point,
    _find_resume_point_for_payloads,
    _trim_issues_log,
    chapter_output_path,
)
from data_proc.schema import (
    ChapterPayload,
    CharacterBank,
    CharacterBankEntry,
    ChoicePools,
    DropRecord,
    FinalQuoteItem,
    append_jsonl,
    iter_chapter_payloads,
    write_json,
    write_json_atomic,
)
from data_proc.utils import bible_sources
from data_proc.utils.text_cleanup import (
    clean_text,
    cleanup_hebrew_quote,
    hebrew_surface_map,
    normalize_word,
    restore_hebrew_surface,
    restore_hebrew_surface_from_map,
)

LOG = logging.getLogger(__name__)

CHARACTER_TAXONOMY = (
    "divine",
    "leader",
    "king",
    "foreign_king",
    "prophet",
    "priest_levite",
    "family",
    "woman",
    "companion_sidekick",
    "people_group",
    "enemy_foreigner",
    "other",
)

HE_PREFIX_LETTERS = ("ו", "ב", "כ", "ל", "מ", "ש")
EN_ROLE_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
HE_REPORTING_WORDS = {"אמר", "ויאמר", "ויאמרו", "ותאמר", "ותאמרו", "לאמר", "ענה", "ויען", "קרא", "ויקרא"}
EN_PRONOUNS = {
    "i",
    "me",
    "my",
    "mine",
    "myself",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "thou",
    "thee",
    "thy",
    "thine",
    "ye",
    "we",
    "us",
    "our",
    "ours",
    "ourselves",
    "he",
    "she",
    "him",
    "her",
    "they",
    "them",
    "their",
    "theirs",
}
HE_PRONOUNS = {
    "אני",
    "אנכי",
    "אתה",
    "את",
    "אתם",
    "אתן",
    "אנחנו",
    "הוא",
    "היא",
    "הם",
    "הן",
    "אותי",
    "אתי",
    "אותו",
    "אותה",
    "להם",
    "להן",
    "לו",
    "לה",
    "לי",
    "לך",
    "לכם",
}
EN_EXCLUDED_GENERICS = {
    "king",
    "the king",
    "man",
    "the man",
    "men",
    "the men",
    "one",
    "officer",
    "officers",
    "priest",
    "the priest",
    "servant",
    "the servant",
    "father",
    "mother",
    "brother",
    "sister",
    "son",
    "sons",
    "daughter",
    "daughters",
    "young man",
    "young men",
}
EN_POSSESSIVE_STARTERS = {"his", "her", "their", "thy", "thine", "your", "my", "our", "its"}
EN_GROUP_MARKERS = {"people", "children", "sons", "brethren", "men", "egyptians", "creatures", "creature", "friends", "house"}
EN_OPTION_PLACEHOLDERS = {"speaker", "listener"}
EN_CONCRETE_ROLE_NOUNS = {
    "wife",
    "servant",
    "father",
    "mother",
    "brother",
    "sister",
    "son",
    "daughter",
    "king",
    "queen",
    "priest",
    "prophet",
    "woman",
    "man",
}
CANONICAL_DIVINE_EN = "the LORD"
CANONICAL_DIVINE_HE = "יְהוָה"
PURE_DIVINE_EN_ALIASES = {
    "god",
    "lord",
    "lord god",
    "lord god of israel",
    "lord god of hosts",
    "god almighty",
    "almighty",
    "most high",
    "most high god",
    "rock of israel",
}
PURE_DIVINE_HE_ALIASES = {
    "אלהים",
    "אלוהים",
    "אלוקים",
    "אל",
    "יהוה",
    "יהוה אלהים",
    "יהוה אלהי ישראל",
    "יהוה אלהים צבאות",
    "אדני",
    "אדני יהוה",
    "אל שדי",
    "צור ישראל",
}


@dataclass
class _BankAccumulator:
    en_forms: Counter[str]
    he_forms: Counter[str]
    normalized_en_aliases: set[str]
    normalized_he_aliases: set[str]
    books: set[str]
    observed_fields: set[str]
    count: int = 0


@dataclass(frozen=True)
class FieldOptionSelection:
    ids: list[str]


@dataclass(frozen=True)
class FieldCandidatePools:
    true_entry: CharacterBankEntry | None
    candidate_pool: list[CharacterBankEntry]
    preferred_categories: list[str]
    role_kind: str


def _book_name(code: str) -> str:
    return bible_sources.BOOK_CODE_TO_EN.get(code, code)


def _most_common_display(counter: Counter[str]) -> str:
    if not counter:
        return ""
    return min(counter.items(), key=lambda item: (-item[1], item[0].casefold(), item[0]))[0]


def _normalize_en_alias(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(r"^(?:all\s+the\s+|the\s+)", "", cleaned, flags=re.IGNORECASE)
    tokens = [normalize_word(match.group(0), "en") for match in EN_ROLE_WORD_RE.finditer(cleaned)]
    return " ".join(token for token in tokens if token)


def _normalize_he_token_for_alias(token: str, *, first: bool) -> str:
    normalized = normalize_word(token, "he")
    if not normalized:
        return ""
    if first and len(normalized) > 3 and normalized[0] in HE_PREFIX_LETTERS and normalized[1] == "ה":
        return normalized[2:]
    if first and normalized.startswith("ה") and len(normalized) > 2:
        return normalized[1:]
    return normalized


def _normalize_he_alias(text: str) -> str:
    tokens = cleanup_hebrew_quote(text).replace("־", " ").split()
    normalized_tokens = [
        _normalize_he_token_for_alias(token, first=index == 0)
        for index, token in enumerate(tokens)
    ]
    return " ".join(token for token in normalized_tokens if token)


def _is_pure_divine_alias(normalized_en: str, normalized_he: str) -> bool:
    return normalized_en in PURE_DIVINE_EN_ALIASES or normalized_he in PURE_DIVINE_HE_ALIASES


def _canonical_bank_key(en_text: str, he_text: str) -> tuple[str, str]:
    normalized_en = _normalize_en_alias(en_text)
    normalized_he = _normalize_he_alias(he_text)
    if _is_pure_divine_alias(normalized_en, normalized_he):
        return ("lord", "יהוה")
    return normalized_en, normalized_he


def _canonical_display_for_key(normalized_en: str, normalized_he: str, en_display: str, he_display: str) -> tuple[str, str]:
    if (normalized_en, normalized_he) == ("lord", "יהוה"):
        return CANONICAL_DIVINE_EN, CANONICAL_DIVINE_HE
    return en_display, he_display


def _looks_like_reporting_clause_en(text: str) -> bool:
    cleaned = clean_text(text).casefold()
    if not cleaned:
        return False
    words = cleaned.split()
    if not words:
        return False
    return words[0] in {"and", "then"} and any(
        word in {"said", "saith", "spake", "saying", "asked", "asking", "answered", "answering", "called", "calling"}
        for word in words[1:]
    )


def _looks_like_reporting_clause_he(text: str) -> bool:
    cleaned = cleanup_hebrew_quote(text)
    if not cleaned:
        return False
    first = normalize_word(cleaned.split()[0], "he")
    return first in HE_REPORTING_WORDS


def _is_bankable_role(en_text: str, he_text: str) -> bool:
    normalized_en = _normalize_en_alias(en_text)
    normalized_he = _normalize_he_alias(he_text)
    if not normalized_en or not normalized_he:
        return False
    if clean_text(en_text).split()[:1] and clean_text(en_text).split()[0].casefold() in EN_POSSESSIVE_STARTERS:
        return False
    if normalized_en in EN_PRONOUNS or normalized_he in HE_PRONOUNS:
        return False
    if _looks_like_reporting_clause_en(en_text) or _looks_like_reporting_clause_he(he_text):
        return False
    if clean_text(en_text).casefold() in EN_EXCLUDED_GENERICS:
        return False
    return True


def _stable_bank_entry_id(normalized_en: str, normalized_he: str) -> str:
    digest = hashlib.sha1(f"{normalized_en}|{normalized_he}".encode("utf-8")).hexdigest()[:12]
    return f"char-{digest}"


def _collect_bank_accumulators(payloads: Iterable[ChapterPayload]) -> dict[tuple[str, str], _BankAccumulator]:
    accumulators: dict[tuple[str, str], _BankAccumulator] = {}
    for payload in payloads:
        for item in payload.items:
            context_texts = [item.he.quote, item.he.riddle, *item.raw_quote_source.he.values()]
            for field in ("speaker", "listener"):
                en_text = getattr(item.en, field)
                he_text = restore_hebrew_surface(getattr(item.he, field), context_texts)
                if not _is_bankable_role(en_text, he_text):
                    continue
                normalized_en, normalized_he = _canonical_bank_key(en_text, he_text)
                key = (normalized_en, normalized_he)
                accumulator = accumulators.setdefault(
                    key,
                    _BankAccumulator(
                        en_forms=Counter(),
                        he_forms=Counter(),
                        normalized_en_aliases=set(),
                        normalized_he_aliases=set(),
                        books=set(),
                        observed_fields=set(),
                    ),
                )
                canonical_en, canonical_he = _canonical_display_for_key(
                    normalized_en,
                    normalized_he,
                    clean_text(en_text),
                    cleanup_hebrew_quote(he_text),
                )
                accumulator.en_forms[canonical_en] += 1
                accumulator.he_forms[canonical_he] += 1
                accumulator.normalized_en_aliases.add(_normalize_en_alias(en_text))
                accumulator.normalized_en_aliases.add(normalized_en)
                accumulator.normalized_he_aliases.add(_normalize_he_alias(he_text))
                accumulator.normalized_he_aliases.add(normalized_he)
                accumulator.books.add(item.source.book_code)
                accumulator.observed_fields.add(field)
                accumulator.count += 1
    return accumulators


def _classification_system_prompt() -> str:
    return (
        "Classify bilingual Bible characters or groups into a fixed taxonomy. "
        "Return JSON only with key items as an array of objects. "
        'Each object must have exactly keys "id" and "category". '
        "Use every input id exactly once. "
        "Copy every id exactly as given, character for character. "
        "Do not rename, normalize, shorten, or invent ids. "
        f"Allowed categories: {', '.join(CHARACTER_TAXONOMY)}. "
        'The values "speaker" and "listener" are not categories. '
        "Any input field such as observed_fields or seen_as_fields is only context and must never be copied into category. "
        "Use divine for God, LORD, or clearly divine beings. "
        "Use leader for major Israelite leaders or governors who are not best classed as king, prophet, or priest. "
        "Use king for Israelite or Judah kings and royal figures. "
        "Use foreign_king for foreign rulers such as Pharaoh or kings of other nations. "
        "Use prophet for prophets or seers. "
        "Use priest_levite for priests and Levites. "
        "Use family for relatives, patriarchs, matriarchs, spouses, children, or household members. "
        "Use woman for female figures when that is the most salient role. "
        "Use companion_sidekick for attendants, aides, allies, or close companions. "
        "Use people_group for collective groups or crowds. "
        "Use enemy_foreigner for hostile peoples, foreign groups, or enemies not best classed as foreign_king. "
        "Use other only when no category fits better. "
        "Never output any category string outside the allowed list, even if it is a close misspelling. "
        "If unsure, use other. "
        'Valid example: {"items":[{"id":"char-1","category":"divine"},{"id":"char-2","category":"people_group"}]}. '
        'Invalid example: {"items":[{"id":"char-1","category":"speaker"}]}. '
        'Invalid example: {"items":[{"id":"char-1","category":"conpanion_sidekick"}]}. '
        'Invalid example: {"items":[{"id":"charX","category":"divine"}]}.'
    )


def _classification_user_prompt(entries: list[CharacterBankEntry]) -> str:
    items = [
        {
            "id": entry.id,
            "en": entry.en,
            "he": entry.he,
            "books": [_book_name(code) for code in entry.books],
            "seen_as_fields": entry.observed_fields,
            "count": entry.count,
        }
        for entry in entries
    ]
    return (
        "Classify these bank entries.\n"
        f"entries: {json.dumps(items, ensure_ascii=False)}\n"
        "Return every id exactly once. "
        "Copy ids exactly from entries. "
        "Remember: seen_as_fields is context only, not the category."
    )


def _classification_repair_user_prompt(entries: list[CharacterBankEntry], previous_payload: dict) -> str:
    return (
        f"{_classification_user_prompt(entries)}\n"
        f"expected_ids: {[entry.id for entry in entries]}\n"
        f"previous_response: {json.dumps(previous_payload, ensure_ascii=False)}\n"
        f"Fix the response so every id appears exactly once and every category is one of: {', '.join(CHARACTER_TAXONOMY)}."
    )


def _single_classification_system_prompt() -> str:
    return (
        "Classify one bilingual Bible character or group into a fixed taxonomy. "
        "Return JSON only with key category. "
        f"Allowed categories: {', '.join(CHARACTER_TAXONOMY)}. "
        "Use only one of those exact values. "
        "Never output a near miss or misspelling. "
        "If unsure, use other. "
        'Valid example: {"category":"divine"}. '
        'Invalid example: {"category":"conpanion_sidekick"}.'
    )


def _single_classification_user_prompt(entry: CharacterBankEntry) -> str:
    payload = {
        "en": entry.en,
        "he": entry.he,
        "books": [_book_name(code) for code in entry.books],
        "seen_as_fields": entry.observed_fields,
        "count": entry.count,
    }
    return (
        "Classify this bank entry.\n"
        f"entry: {json.dumps(payload, ensure_ascii=False)}\n"
        "Return only the category."
    )


def _single_classification_repair_user_prompt(entry: CharacterBankEntry, previous_payload: dict) -> str:
    return (
        f"{_single_classification_user_prompt(entry)}\n"
        f"previous_response: {json.dumps(previous_payload, ensure_ascii=False)}\n"
        f"Return one exact category string from this list only: {', '.join(CHARACTER_TAXONOMY)}."
    )


def _single_bank_keep_system_prompt() -> str:
    return (
        "Decide whether one bilingual Bible bank entry should be kept for speaker/listener distractor options. "
        "Return JSON only with key keep as a boolean. "
        "Set keep=true only if the English and Hebrew refer to the same stable biblical character or stable group that is a good quiz option. "
        "Set keep=false for malformed bilingual pairs, pronouns, possessive descriptions, generic words, overly context-dependent phrases, or entries that are not stable characters or groups. "
        'Keep=true example: {"keep": true} for angel of the LORD / מלאך יהוה. '
        'Keep=true example: {"keep": true} for Hagar / הגר. '
        'Keep=true example: {"keep": true} for Egyptians / מצרים. '
        'Keep=true example: {"keep": true} for people / העם. '
        'Keep=true example: {"keep": true} for Noah and his sons / נח ואתבניו. '
        'Keep=true example: {"keep": true} for living creatures / כלנפש חיה. '
        'Keep=false example: {"keep": false} for Abraham / אליו. '
        'Keep=false example: {"keep": false} for Abraham / אליעזר. '
        'Keep=false example: {"keep": false} for Jacob / אבי. '
        'Keep=false example: {"keep": false} for Joseph / אתכם. '
        'Keep=false example: {"keep": false} for his father / אביו.'
    )


def _single_bank_keep_user_prompt(entry: CharacterBankEntry) -> str:
    payload = {
        "en": entry.en,
        "he": entry.he,
        "category": entry.category,
        "books": [_book_name(code) for code in entry.books],
        "seen_as_fields": entry.observed_fields,
        "count": entry.count,
    }
    return (
        "Should this bank entry be kept?\n"
        f"entry: {json.dumps(payload, ensure_ascii=False)}\n"
        "Keep only stable bilingual character or group entries that make good distractor options."
    )


def _parse_classification_payload(payload: dict, expected_ids: list[str]) -> dict[str, str]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("classification item must be an object")
        entry_id = item.get("id")
        category = item.get("category")
        if not isinstance(entry_id, str) or not isinstance(category, str):
            raise ValueError("classification item must contain string id and category")
        if entry_id in result:
            raise ValueError(f"duplicate classification id {entry_id}")
        if category not in CHARACTER_TAXONOMY:
            raise ValueError(f"unsupported category {category}")
        result[entry_id] = category
    if set(result) != set(expected_ids):
        raise ValueError(f"classification ids mismatch expected={expected_ids} actual={sorted(result)}")
    return result


def _parse_single_category(payload: dict) -> str:
    category = payload.get("category")
    if not isinstance(category, str) or category not in CHARACTER_TAXONOMY:
        raise ValueError(f"unsupported category {category}")
    return category


def _parse_keep_flag(payload: dict) -> bool:
    keep = payload.get("keep")
    if not isinstance(keep, bool):
        raise ValueError(f"unsupported keep value {keep}")
    return keep


def _chunked[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _dedupe_entries(entries: Iterable[CharacterBankEntry]) -> list[CharacterBankEntry]:
    seen_ids: set[str] = set()
    out: list[CharacterBankEntry] = []
    for entry in entries:
        if entry.id in seen_ids:
            continue
        seen_ids.add(entry.id)
        out.append(entry)
    return out


def _default_option_categories(role_kind: str, true_category: str | None) -> list[str]:
    if true_category == "divine":
        return ["leader", "prophet", "king", "family"]
    if role_kind == "group":
        return ["people_group", "family", "enemy_foreigner", "companion_sidekick"]
    return [
        category
        for category in (
            true_category,
            "leader",
            "prophet",
            "king",
            "family",
            "companion_sidekick",
            "foreign_king",
            "woman",
            "other",
        )
        if category
    ]


def _text_role_kind(en_text: str, he_text: str, category: str) -> str:
    normalized_en = _normalize_en_alias(en_text)
    normalized_he = _normalize_he_alias(he_text)
    en_tokens = {token for token in normalized_en.split() if token}
    if en_tokens & EN_GROUP_MARKERS:
        return "group"
    if " and " in clean_text(en_text).casefold() and ("sons" in en_tokens or "children" in en_tokens):
        return "group"
    if normalized_he.startswith("בני") or normalized_he.startswith("כלנפש") or normalized_he.startswith("בית"):
        return "group"
    if category == "divine":
        return "divine"
    if category in {"people_group", "enemy_foreigner"}:
        return "group"
    return "individual"


def _entry_role_kind(entry: CharacterBankEntry) -> str:
    return _text_role_kind(entry.en, entry.he, entry.category)


def _is_divine_alias(normalized_en: str, normalized_he: str) -> bool:
    return _is_pure_divine_alias(normalized_en, normalized_he)


def _aliases_are_confusable(first_en: str, first_he: str, second_en: str, second_he: str) -> bool:
    if not first_en or not second_en or not first_he or not second_he:
        return False
    if _is_divine_alias(first_en, first_he) and _is_divine_alias(second_en, second_he):
        return True
    if first_en.startswith("angel") and second_en.startswith("angel"):
        return True
    if first_he.startswith("מלאך") and second_he.startswith("מלאך"):
        return True
    return False


def _entry_confusable_cluster(entry: CharacterBankEntry) -> str:
    normalized_en = _normalize_en_alias(entry.en)
    normalized_he = _normalize_he_alias(entry.he)
    if _is_divine_alias(normalized_en, normalized_he):
        return "divine"
    if normalized_en.startswith("angel ") or normalized_en.startswith("angel of") or normalized_he.startswith("מלאך"):
        return "angel"
    return f"{normalized_en}|{normalized_he}"


def _looks_like_unresolved_individual_role(en_text: str, he_text: str, true_entry: CharacterBankEntry | None, role_kind: str) -> bool:
    if true_entry is not None or role_kind != "individual":
        return False

    normalized_en = _normalize_en_alias(en_text)
    normalized_he = _normalize_he_alias(he_text)
    if normalized_en in EN_OPTION_PLACEHOLDERS:
        return True
    if normalized_en in EN_PRONOUNS or normalized_he in HE_PRONOUNS:
        return True
    if _looks_like_reporting_clause_en(en_text) or _looks_like_reporting_clause_he(he_text):
        return True

    english_words = EN_ROLE_WORD_RE.findall(clean_text(en_text))
    if len(english_words) >= 3 and not any(token[:1].isupper() or token.isupper() for token in english_words):
        normalized_words = [normalize_word(token, "en") for token in english_words]
        if not normalized_words or normalized_words[-1] not in EN_CONCRETE_ROLE_NOUNS:
            return True
    if len(english_words) >= 5:
        return True
    return False


def _hebrew_context_texts(payloads: Iterable[ChapterPayload]) -> list[str]:
    texts: list[str] = []
    for payload in payloads:
        for item in payload.items:
            texts.extend([item.he.quote, item.he.riddle, *item.raw_quote_source.he.values()])
    return texts


def _restore_item_hebrew_roles_from_map(item: FinalQuoteItem, mapping: dict[str, str]) -> FinalQuoteItem:
    item_mapping = dict(mapping)
    item_mapping.update(hebrew_surface_map([item.he.quote, item.he.riddle, *item.raw_quote_source.he.values()]))
    return replace(
        item,
        he=replace(
            item.he,
            speaker=restore_hebrew_surface_from_map(item.he.speaker, item_mapping),
            listener=restore_hebrew_surface_from_map(item.he.listener, item_mapping),
        ),
    )


def _restore_bank_hebrew_surfaces_from_map(bank: CharacterBank, mapping: dict[str, str]) -> CharacterBank:
    return CharacterBank(
        taxonomy=list(bank.taxonomy),
        items=[
            replace(
                entry,
                he=restore_hebrew_surface_from_map(entry.he, mapping),
            )
            for entry in bank.items
        ],
    )


def _dedupe_entries_by_display(
    entries: Iterable[CharacterBankEntry],
    *,
    used_en: set[str] | None = None,
    used_he: set[str] | None = None,
) -> list[CharacterBankEntry]:
    seen_en = set() if used_en is None else set(used_en)
    seen_he = set() if used_he is None else set(used_he)
    out: list[CharacterBankEntry] = []
    for entry in entries:
        normalized_en = _normalize_en_alias(entry.en)
        normalized_he = _normalize_he_alias(entry.he)
        if normalized_en in seen_en or normalized_he in seen_he:
            continue
        seen_en.add(normalized_en)
        seen_he.add(normalized_he)
        out.append(entry)
    return out


def _dedupe_option_entries(
    entries: Iterable[CharacterBankEntry],
    *,
    used_en: set[str] | None = None,
    used_he: set[str] | None = None,
    used_clusters: set[str] | None = None,
) -> list[CharacterBankEntry]:
    seen_en = set() if used_en is None else set(used_en)
    seen_he = set() if used_he is None else set(used_he)
    seen_clusters = set() if used_clusters is None else set(used_clusters)
    out: list[CharacterBankEntry] = []
    for entry in entries:
        normalized_en = _normalize_en_alias(entry.en)
        normalized_he = _normalize_he_alias(entry.he)
        cluster = _entry_confusable_cluster(entry)
        if normalized_en in seen_en or normalized_he in seen_he or cluster in seen_clusters:
            continue
        seen_en.add(normalized_en)
        seen_he.add(normalized_he)
        seen_clusters.add(cluster)
        out.append(entry)
    return out


def _classify_bank_batch(entries: list[CharacterBankEntry], llm: JsonChatModel) -> dict[str, str]:
    if len(entries) == 1:
        payload = llm.chat_json(
            prompt_name="character-bank-classification-single",
            system_prompt=_single_classification_system_prompt(),
            user_prompt=_single_classification_user_prompt(entries[0]),
            required_keys=("category",),
        )
        try:
            return {entries[0].id: _parse_single_category(payload)}
        except ValueError:
            repair_payload = llm.chat_json(
                prompt_name="character-bank-classification-single-repair",
                system_prompt=_single_classification_system_prompt(),
                user_prompt=_single_classification_repair_user_prompt(entries[0], payload),
                required_keys=("category",),
            )
            return {entries[0].id: _parse_single_category(repair_payload)}

    expected_ids = [entry.id for entry in entries]
    payload = llm.chat_json(
        prompt_name="character-bank-classification",
        system_prompt=_classification_system_prompt(),
        user_prompt=_classification_user_prompt(entries),
        required_keys=("items",),
    )
    try:
        return _parse_classification_payload(payload, expected_ids)
    except ValueError as exc:
        LOG.warning("Character-bank classification batch failed validation size=%s error=%s", len(entries), exc)
        if len(entries) == 1:
            raise
        midpoint = len(entries) // 2
        categories: dict[str, str] = {}
        categories.update(_classify_bank_batch(entries[:midpoint], llm))
        categories.update(_classify_bank_batch(entries[midpoint:], llm))
        return categories


def build_character_bank(payloads: Iterable[ChapterPayload], llm: JsonChatModel, *, batch_size: int = 1) -> CharacterBank:
    accumulators = _collect_bank_accumulators(payloads)
    entries = [
        CharacterBankEntry(
            id=_stable_bank_entry_id(normalized_en, normalized_he),
            en=_most_common_display(accumulator.en_forms),
            he=_most_common_display(accumulator.he_forms),
            normalized_en_aliases=sorted(accumulator.normalized_en_aliases),
            normalized_he_aliases=sorted(accumulator.normalized_he_aliases),
            books=sorted(accumulator.books, key=lambda code: bible_sources.BOOK_ORDER.get(code, 999)),
            observed_fields=sorted(accumulator.observed_fields),
            count=accumulator.count,
            category="other",
        )
        for (normalized_en, normalized_he), accumulator in sorted(
            accumulators.items(),
            key=lambda item: (-item[1].count, item[0][0], item[0][1]),
        )
    ]
    if not entries:
        return CharacterBank(taxonomy=list(CHARACTER_TAXONOMY), items=[])

    categorized: list[CharacterBankEntry] = []
    for batch in tqdm(_chunked(entries, batch_size), desc="classify-character-bank"):
        categories = _classify_bank_batch(batch, llm)
        for entry in batch:
            categorized.append(replace(entry, category=categories[entry.id]))

    filtered: list[CharacterBankEntry] = []
    for entry in categorized:
        if entry.count > 1:
            filtered.append(entry)
            continue
        keep_payload = llm.chat_json(
            prompt_name="character-bank-keep-single",
            system_prompt=_single_bank_keep_system_prompt(),
            user_prompt=_single_bank_keep_user_prompt(entry),
            required_keys=("keep",),
        )
        if _parse_keep_flag(keep_payload):
            filtered.append(entry)
        else:
            LOG.info("Dropping singleton bank entry id=%s en=%s he=%s category=%s", entry.id, entry.en, entry.he, entry.category)

    return CharacterBank(
        taxonomy=list(CHARACTER_TAXONOMY),
        items=sorted(filtered, key=lambda entry: (-entry.count, entry.category, entry.en.casefold(), entry.he)),
    )


def _normalize_loaded_bank(bank: CharacterBank) -> CharacterBank:
    merged: dict[tuple[str, str, str], _BankAccumulator] = {}
    for entry in bank.items:
        normalized_en, normalized_he = _canonical_bank_key(entry.en, entry.he)
        category = "divine" if _is_pure_divine_alias(normalized_en, normalized_he) else entry.category
        key = (normalized_en, normalized_he, category)
        accumulator = merged.setdefault(
            key,
            _BankAccumulator(
                en_forms=Counter(),
                he_forms=Counter(),
                normalized_en_aliases=set(),
                normalized_he_aliases=set(),
                books=set(),
                observed_fields=set(),
            ),
        )
        canonical_en, canonical_he = _canonical_display_for_key(normalized_en, normalized_he, entry.en, entry.he)
        accumulator.en_forms[canonical_en] += max(entry.count, 1)
        accumulator.he_forms[canonical_he] += max(entry.count, 1)
        accumulator.normalized_en_aliases.update(entry.normalized_en_aliases)
        accumulator.normalized_en_aliases.add(normalized_en)
        accumulator.normalized_he_aliases.update(entry.normalized_he_aliases)
        accumulator.normalized_he_aliases.add(normalized_he)
        accumulator.books.update(entry.books)
        accumulator.observed_fields.update(entry.observed_fields)
        accumulator.count += max(entry.count, 1)

    items = [
        CharacterBankEntry(
            id=_stable_bank_entry_id(normalized_en, normalized_he),
            en=_most_common_display(accumulator.en_forms),
            he=_most_common_display(accumulator.he_forms),
            normalized_en_aliases=sorted(accumulator.normalized_en_aliases),
            normalized_he_aliases=sorted(accumulator.normalized_he_aliases),
            books=sorted(accumulator.books, key=lambda code: bible_sources.BOOK_ORDER.get(code, 999)),
            observed_fields=sorted(accumulator.observed_fields),
            count=accumulator.count,
            category=category,
        )
        for (normalized_en, normalized_he, category), accumulator in sorted(
            merged.items(),
            key=lambda item: (-item[1].count, item[0][2], item[0][0], item[0][1]),
        )
    ]
    return CharacterBank(
        taxonomy=list(bank.taxonomy or CHARACTER_TAXONOMY),
        items=items,
    )


def read_character_bank(path: Path) -> CharacterBank:
    return _normalize_loaded_bank(CharacterBank.from_dict(json.loads(path.read_text(encoding="utf-8"))))


def write_character_bank(path: Path, bank: CharacterBank) -> None:
    write_json_atomic(path, bank.to_dict())


def _book_distance(book_codes: Iterable[str], source_book_code: str) -> int:
    source_order = bible_sources.BOOK_ORDER.get(source_book_code, 999)
    distances = [abs(source_order - bible_sources.BOOK_ORDER.get(book_code, 999)) for book_code in book_codes]
    return min(distances) if distances else 999


def _entry_matches_role(entry: CharacterBankEntry, en_text: str, he_text: str) -> bool:
    return _normalize_en_alias(en_text) in entry.normalized_en_aliases and _normalize_he_alias(he_text) in entry.normalized_he_aliases


def _same_role_text(entry: CharacterBankEntry, en_text: str, he_text: str) -> bool:
    return _normalize_en_alias(entry.en) == _normalize_en_alias(en_text) or _normalize_he_alias(entry.he) == _normalize_he_alias(he_text)


def _same_entity_variant(entry: CharacterBankEntry, en_text: str, he_text: str) -> bool:
    return _aliases_are_confusable(
        _normalize_en_alias(entry.en),
        _normalize_he_alias(entry.he),
        _normalize_en_alias(en_text),
        _normalize_he_alias(he_text),
    )


class OptionsBuilder:
    def __init__(self, bank: CharacterBank, llm: JsonChatModel) -> None:
        self.bank = bank
        self.llm = llm
        self.entries_by_id = {entry.id: entry for entry in bank.items}
        self.entries_by_role: list[CharacterBankEntry] = list(bank.items)

    def _find_entry_for_role(self, en_text: str, he_text: str) -> CharacterBankEntry | None:
        for entry in self.entries_by_role:
            if _entry_matches_role(entry, en_text, he_text):
                return entry
        return None

    def _role_kind_for_item(self, item: FinalQuoteItem, field: str, true_entry: CharacterBankEntry | None) -> str:
        if true_entry is not None:
            return _entry_role_kind(true_entry)
        return _text_role_kind(getattr(item.en, field), getattr(item.he, field), "other")

    def _selectable_candidates(
        self,
        item: FinalQuoteItem,
        field: str,
        true_entry: CharacterBankEntry | None,
        opposite_entry: CharacterBankEntry | None,
    ) -> list[CharacterBankEntry]:
        true_en = getattr(item.en, field)
        true_he = getattr(item.he, field)
        opposite_field = "listener" if field == "speaker" else "speaker"
        opposite_en = getattr(item.en, opposite_field)
        opposite_he = getattr(item.he, opposite_field)

        out: list[CharacterBankEntry] = []
        for entry in self.bank.items:
            if true_entry is not None and entry.id == true_entry.id:
                continue
            if opposite_entry is not None and entry.id == opposite_entry.id:
                continue
            if _same_role_text(entry, true_en, true_he) or _same_entity_variant(entry, true_en, true_he):
                continue
            if _same_role_text(entry, opposite_en, opposite_he) or _same_entity_variant(entry, opposite_en, opposite_he):
                continue
            out.append(entry)
        return out

    def _category_plan_system_prompt(self, field: str) -> str:
        field_name = "speaker" if field == "speaker" else "listener"
        return (
            f"Choose 2 to 4 distractor categories for the {field_name} of a Bible riddle. "
            "Return JSON only with key categories as an array of exact taxonomy strings. "
            f"Allowed categories: {', '.join(CHARACTER_TAXONOMY)}. "
            "Use only those exact strings. "
            "Prefer categories that will make hard but fair distractors from the riddle context. "
            "Prefer familiar, common characters or groups over esoteric ones. "
            "Use at least 2 different categories when possible. "
            "Avoid choosing multiple categories that would mostly produce near-synonymous divine or angelic title variants. "
            "If the true role is divine, usually prefer mostly human categories with at most one divine-flavored category. "
            'Valid example: {"categories":["leader","prophet","king"]}.'
        )

    def _category_plan_user_prompt(
        self,
        item: FinalQuoteItem,
        field: str,
        true_entry: CharacterBankEntry | None,
        role_kind: str,
    ) -> str:
        opposite_field = "listener" if field == "speaker" else "speaker"
        true_category = true_entry.category if true_entry is not None else "unknown"
        return (
            f"book: {item.source.book}\n"
            f"field: {field}\n"
            f"english_riddle: {item.en.riddle}\n"
            f"hebrew_riddle: {item.he.riddle}\n"
            f"true_{field}_en: {getattr(item.en, field)}\n"
            f"true_{field}_he: {getattr(item.he, field)}\n"
            f"true_{field}_category: {true_category}\n"
            f"role_kind: {role_kind}\n"
            f"opposite_role_en: {getattr(item.en, opposite_field)}\n"
            f"opposite_role_he: {getattr(item.he, opposite_field)}\n"
            "Choose 2 to 4 categories for plausible but diverse distractors."
        )

    def _parse_category_plan(self, payload: dict) -> list[str]:
        categories = payload.get("categories")
        if not isinstance(categories, list):
            raise ValueError("categories must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for category in categories:
            if not isinstance(category, str) or category not in CHARACTER_TAXONOMY or category in seen:
                continue
            seen.add(category)
            out.append(category)
        if len(out) < 2:
            raise ValueError("need at least 2 valid categories")
        return out[:4]

    def _planned_categories(
        self,
        item: FinalQuoteItem,
        field: str,
        true_entry: CharacterBankEntry | None,
        role_kind: str,
    ) -> list[str]:
        default_categories = _default_option_categories(role_kind, true_entry.category if true_entry is not None else None)
        try:
            payload = self.llm.chat_json(
                prompt_name=f"{field}-options-categories",
                system_prompt=self._category_plan_system_prompt(field),
                user_prompt=self._category_plan_user_prompt(item, field, true_entry, role_kind),
                required_keys=("categories",),
            )
            planned = self._parse_category_plan(payload)
        except Exception:
            planned = list(default_categories)
        if role_kind == "group" or true_entry is None:
            planned = [*default_categories, *planned]
        if true_entry is not None and true_entry.category not in planned and true_entry.category != "divine":
            planned = [true_entry.category, *planned]
        seen: set[str] = set()
        out: list[str] = []
        for category in planned:
            if category in seen:
                continue
            seen.add(category)
            out.append(category)
        return out[:4]

    def _candidate_score(
        self,
        entry: CharacterBankEntry,
        item: FinalQuoteItem,
        field: str,
        role_kind: str,
    ) -> tuple[int, int, int, int, int, str]:
        return (
            0 if _entry_role_kind(entry) == role_kind else 1,
            0 if field in entry.observed_fields else 1,
            0 if item.source.book_code in entry.books else 1,
            _book_distance(entry.books, item.source.book_code),
            -entry.count,
            entry.id,
        )

    def _candidate_pools(self, item: FinalQuoteItem, field: str) -> FieldCandidatePools:
        true_entry = self._find_entry_for_role(getattr(item.en, field), getattr(item.he, field))
        opposite_field = "listener" if field == "speaker" else "speaker"
        opposite_entry = self._find_entry_for_role(getattr(item.en, opposite_field), getattr(item.he, opposite_field))
        role_kind = self._role_kind_for_item(item, field, true_entry)
        if _looks_like_unresolved_individual_role(getattr(item.en, field), getattr(item.he, field), true_entry, role_kind):
            raise ValueError(f"unresolved true {field} role")
        candidates = self._selectable_candidates(item, field, true_entry, opposite_entry)
        preferred_categories = self._planned_categories(item, field, true_entry, role_kind)

        used_en: set[str] = set()
        used_he: set[str] = set()
        used_clusters: set[str] = set()
        pool: list[CharacterBankEntry] = []

        def extend_pool(entries: Iterable[CharacterBankEntry], *, limit: int | None = None) -> None:
            nonlocal pool, used_en, used_he, used_clusters
            deduped = _dedupe_option_entries(
                entries,
                used_en=used_en,
                used_he=used_he,
                used_clusters=used_clusters,
            )
            if limit is not None:
                deduped = deduped[:limit]
            for entry in deduped:
                pool.append(entry)
                used_en.add(_normalize_en_alias(entry.en))
                used_he.add(_normalize_he_alias(entry.he))
                used_clusters.add(_entry_confusable_cluster(entry))

        sorted_candidates = sorted(
            _dedupe_entries(candidates),
            key=lambda entry: self._candidate_score(entry, item, field, role_kind),
        )
        same_role_candidates = [entry for entry in sorted_candidates if _entry_role_kind(entry) == role_kind]
        if role_kind == "group" and len(same_role_candidates) >= 3:
            sorted_candidates = same_role_candidates

        for category in preferred_categories:
            extend_pool(
                [
                    entry
                    for entry in sorted_candidates
                    if entry.category == category and _entry_role_kind(entry) == role_kind
                ],
                limit=1,
            )
        for category in preferred_categories:
            extend_pool(
                [
                    entry
                    for entry in sorted_candidates
                    if entry.category == category
                ],
                limit=1,
            )
        extend_pool(
            [
                entry
                for entry in sorted_candidates
                if item.source.book_code not in entry.books and _entry_role_kind(entry) == role_kind
            ],
            limit=4,
        )
        extend_pool(
            [
                entry
                for entry in sorted_candidates
                if _entry_role_kind(entry) == role_kind
            ],
            limit=8,
        )
        extend_pool(sorted_candidates, limit=12)

        if len(pool) < 3:
            raise ValueError(f"thin candidate pool for {field}")
        return FieldCandidatePools(
            true_entry=true_entry,
            candidate_pool=pool[:12],
            preferred_categories=preferred_categories,
            role_kind=role_kind,
        )

    def _option_selection_system_prompt(self, field: str) -> str:
        field_name = "speaker" if field == "speaker" else "listener"
        return (
            f"Choose hard but fair distractor options for the {field_name} of a Bible riddle. "
            "Return JSON only. "
            'Use exactly this shape: {"ids":["id1","id2","id3"]}. '
            'Choose exactly 3 unique ids from allowed_ids. '
            "Use only provided ids exactly. "
            "Do not choose the true answer or the opposite role. "
            "Prefer distractors that feel plausible from the riddle context, but are still clearly wrong. "
            "If possible, use at least 2 different categories across the 3 options. "
            "If possible, include at least 1 cross-book distractor. "
            "Avoid near-synonyms, duplicate title variants, or multiple almost-identical divine or angelic options. "
            "Prefer more common, recognizable characters or groups over esoteric ones when quality is otherwise similar. "
            'Valid example: {"ids":["char-a","char-b","char-c"]}.'
        )

    def _option_selection_user_prompt(self, item: FinalQuoteItem, field: str, pools: FieldCandidatePools) -> str:
        opposite_field = "listener" if field == "speaker" else "speaker"
        candidates = [
            {
                "id": entry.id,
                "en": entry.en,
                "he": entry.he,
                "category": entry.category,
                "books": [_book_name(code) for code in entry.books],
                "observed_fields": entry.observed_fields,
                "count": entry.count,
                "cross_book": item.source.book_code not in entry.books,
            }
            for entry in pools.candidate_pool
        ]
        return (
            f"book: {item.source.book}\n"
            f"field: {field}\n"
            f"english_riddle: {item.en.riddle}\n"
            f"hebrew_riddle: {item.he.riddle}\n"
            f"true_{field}_en: {getattr(item.en, field)}\n"
            f"true_{field}_he: {getattr(item.he, field)}\n"
            f"opposite_role_en: {getattr(item.en, opposite_field)}\n"
            f"opposite_role_he: {getattr(item.he, opposite_field)}\n"
            f"preferred_categories: {pools.preferred_categories}\n"
            f"role_kind: {pools.role_kind}\n"
            f"allowed_ids: {[entry.id for entry in pools.candidate_pool]}\n"
            f"candidates: {json.dumps(candidates, ensure_ascii=False)}\n"
            "Pick exactly 3 ids."
        )

    def _option_selection_repair_user_prompt(
        self,
        item: FinalQuoteItem,
        field: str,
        pools: FieldCandidatePools,
        previous_payload: dict,
    ) -> str:
        return (
            f"{self._option_selection_user_prompt(item, field, pools)}\n"
            f"previous_response: {json.dumps(previous_payload, ensure_ascii=False)}\n"
            "Fix the response so it uses exactly 3 unique ids from allowed_ids."
        )

    def _parse_field_selection(self, payload: dict, item: FinalQuoteItem, pools: FieldCandidatePools) -> FieldOptionSelection:
        ids = payload.get("ids")
        if not isinstance(ids, list) or len(ids) != 3:
            raise ValueError("ids must be a list of length 3")
        if len(set(ids)) != 3:
            raise ValueError("ids must be unique")
        allowed_ids = {entry.id for entry in pools.candidate_pool}
        if any(not isinstance(entry_id, str) or entry_id not in allowed_ids for entry_id in ids):
            raise ValueError("ids must come from candidate_pool")
        selected_entries = [self.entries_by_id[entry_id] for entry_id in ids]
        selection_has_cross_book = any(item.source.book_code not in entry.books for entry in selected_entries)
        selection_categories = {entry.category for entry in selected_entries}
        pool_has_cross_book = any(item.source.book_code not in entry.books for entry in pools.candidate_pool)
        pool_categories = {entry.category for entry in pools.candidate_pool}
        if not selection_has_cross_book and len(selection_categories) < 2 and (
            pool_has_cross_book or len(pool_categories) >= 2
        ):
            raise ValueError("selection lacks available diversity")
        return FieldOptionSelection(ids=list(ids))

    def _deterministic_field_selection(self, item: FinalQuoteItem, pools: FieldCandidatePools) -> FieldOptionSelection:
        selected: list[CharacterBankEntry] = []
        used_categories: set[str] = set()

        def add_entry(entry: CharacterBankEntry) -> None:
            if entry.id in {chosen.id for chosen in selected}:
                return
            if _entry_confusable_cluster(entry) in {_entry_confusable_cluster(chosen) for chosen in selected}:
                return
            selected.append(entry)
            used_categories.add(entry.category)

        for category in pools.preferred_categories:
            for entry in pools.candidate_pool:
                if entry.category == category:
                    add_entry(entry)
                    break
            if len(selected) >= 3:
                break

        if len(selected) < 3:
            for entry in pools.candidate_pool:
                if len(selected) >= 3:
                    break
                if used_categories and entry.category in used_categories and len(used_categories) < 2:
                    continue
                if not selected and item.source.book_code in entry.books:
                    continue
                add_entry(entry)

        if len(selected) < 3:
            for entry in pools.candidate_pool:
                if len(selected) >= 3:
                    break
                add_entry(entry)

        if len(selected) < 3:
            raise ValueError("deterministic fallback could not choose 3 unique options")
        return FieldOptionSelection(ids=[entry.id for entry in selected[:3]])

    def select_field_options(self, item: FinalQuoteItem, field: str) -> FieldOptionSelection:
        pools = self._candidate_pools(item, field)
        try:
            payload = self.llm.chat_json(
                prompt_name=f"{field}-options-selection",
                system_prompt=self._option_selection_system_prompt(field),
                user_prompt=self._option_selection_user_prompt(item, field, pools),
                required_keys=("ids",),
            )
            return self._parse_field_selection(payload, item, pools)
        except Exception as exc:
            LOG.warning("Primary %s option selection failed for %s: %s", field, item.id, exc)
            try:
                repair_payload = self.llm.chat_json(
                    prompt_name=f"{field}-options-selection-repair",
                    system_prompt=self._option_selection_system_prompt(field),
                    user_prompt=self._option_selection_repair_user_prompt(item, field, pools, payload if 'payload' in locals() else {}),
                    required_keys=("ids",),
                )
                return self._parse_field_selection(repair_payload, item, pools)
            except Exception as repair_exc:
                LOG.warning("Repair %s option selection failed for %s: %s", field, item.id, repair_exc)
                return self._deterministic_field_selection(item, pools)

    def apply_options(self, item: FinalQuoteItem) -> tuple[FinalQuoteItem, list[DropRecord], dict[str, object]]:
        issues: list[DropRecord] = []
        debug: dict[str, object] = {
            "speaker_bank_ids": [],
            "listener_bank_ids": [],
            "speaker_options": [],
            "listener_options": [],
        }
        selections: dict[str, FieldOptionSelection] = {}
        for field in ("speaker", "listener"):
            try:
                selection = self.select_field_options(item, field)
            except Exception as exc:
                issues.append(
                    DropRecord(
                        candidate_id=item.id,
                        book_code=item.source.book_code,
                        chapter=item.source.chapter,
                        start=item.ref.start,
                        end=item.ref.end,
                        stage="options",
                        reason=f"{field}_options_failed",
                        detail=str(exc),
                    )
                )
                continue
            selections[field] = selection
            debug[f"{field}_bank_ids"] = list(selection.ids)
            debug[f"{field}_options"] = [self.entries_by_id[entry_id].to_dict() for entry_id in selection.ids]

        speaker_entries = [self.entries_by_id[entry_id] for entry_id in selections.get("speaker", FieldOptionSelection([])).ids]
        listener_entries = [self.entries_by_id[entry_id] for entry_id in selections.get("listener", FieldOptionSelection([])).ids]
        updated = replace(
            item,
            en=replace(
                item.en,
                options=ChoicePools(
                    speaker=[entry.en for entry in speaker_entries],
                    listener=[entry.en for entry in listener_entries],
                ),
            ),
            he=replace(
                item.he,
                options=ChoicePools(
                    speaker=[entry.he for entry in speaker_entries],
                    listener=[entry.he for entry in listener_entries],
                ),
            ),
        )
        return updated, issues, debug


def _chapter_payload_with_mode(payload: ChapterPayload, items: list[FinalQuoteItem]) -> ChapterPayload:
    return ChapterPayload(
        book_code=payload.book_code,
        book=payload.book,
        book_he=payload.book_he,
        chapter=payload.chapter,
        mode=payload.mode,
        items=items,
    )


def _is_before_resume_key(book_code: str, chapter: int, resume_point: tuple[str, int] | None) -> bool:
    if resume_point is None:
        return False
    return _chapter_sort_key(book_code, chapter) < _chapter_sort_key(*resume_point)


def _normalized_overlap_riddle(text: str, lang: str) -> str:
    if lang == "en":
        return " ".join(
            normalized
            for normalized in (_normalize_en_alias(text).split())
            if normalized
        )
    return " ".join(
        normalized
        for normalized in (_normalize_he_alias(text).split())
        if normalized
    )


def _ranges_overlap(first: FinalQuoteItem, second: FinalQuoteItem) -> bool:
    return not (first.ref.end < second.ref.start or second.ref.end < first.ref.start)


def _items_are_overlapping_variants(first: FinalQuoteItem, second: FinalQuoteItem) -> bool:
    if first.source.book_code != second.source.book_code or first.source.chapter != second.source.chapter:
        return False
    if not _ranges_overlap(first, second):
        return False
    if _normalize_en_alias(first.en.speaker) != _normalize_en_alias(second.en.speaker):
        return False
    if _normalize_en_alias(first.en.listener) != _normalize_en_alias(second.en.listener):
        return False
    first_en = _normalized_overlap_riddle(first.en.riddle, "en")
    second_en = _normalized_overlap_riddle(second.en.riddle, "en")
    first_he = _normalized_overlap_riddle(first.he.riddle, "he")
    second_he = _normalized_overlap_riddle(second.he.riddle, "he")
    return (
        (first_en and second_en and (first_en in second_en or second_en in first_en))
        or (first_he and second_he and (first_he in second_he or second_he in first_he))
    )


def _filter_overlapping_chapter_items(payload: ChapterPayload) -> tuple[list[FinalQuoteItem], list[DropRecord]]:
    return sorted(payload.items, key=lambda value: (value.ref.start, value.ref.end, value.id)), []


def run_build_options(
    *,
    in_dir: Path,
    bank: CharacterBank,
    out_dir: Path,
    issues_log: Path | None,
    llm: JsonChatModel,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
    limit: int | None = None,
    resume: bool = True,
) -> tuple[list[ChapterPayload], list[DropRecord]]:
    canonical_book_filter = _canonical_book_filter(book_filter)
    all_payloads = [
        payload
        for payload in iter_chapter_payloads(in_dir)
        if (not canonical_book_filter or payload.book_code == canonical_book_filter)
        and (chapter_filter is None or payload.chapter == chapter_filter)
    ]
    hebrew_mapping = hebrew_surface_map(_hebrew_context_texts(all_payloads))
    bank = _restore_bank_hebrew_surfaces_from_map(bank, hebrew_mapping)
    resume_point = _find_resume_point_for_payloads(
        all_payloads,
        out_dir=out_dir,
        book_filter=canonical_book_filter,
        chapter_filter=chapter_filter,
    ) if resume else None

    out_dir.mkdir(parents=True, exist_ok=True)
    if issues_log is not None:
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        _trim_issues_log(
            issues_log,
            resume_point=resume_point if resume else None,
            book_filter=canonical_book_filter,
            chapter_filter=chapter_filter,
        )
    _drop_outputs_from_resume_point(
        out_dir,
        resume_point=resume_point,
        book_filter=canonical_book_filter,
        chapter_filter=chapter_filter,
    )

    builder = OptionsBuilder(bank=bank, llm=llm)
    written_payloads: list[ChapterPayload] = []
    issues: list[DropRecord] = []
    processed = 0

    for payload in tqdm(all_payloads, desc="build-options"):
        if _is_before_resume_key(payload.book_code, payload.chapter, resume_point):
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1

        restored_payload = _chapter_payload_with_mode(
            payload,
            [_restore_item_hebrew_roles_from_map(item, hebrew_mapping) for item in payload.items],
        )
        filtered_items, overlap_issues = _filter_overlapping_chapter_items(restored_payload)
        if overlap_issues:
            issues.extend(overlap_issues)
            if issues_log is not None:
                append_jsonl(issues_log, [issue.to_dict() for issue in overlap_issues])

        updated_items: list[FinalQuoteItem] = []
        for item in filtered_items:
            updated, item_issues, _ = builder.apply_options(item)
            updated_items.append(updated)
            issues.extend(item_issues)
            if issues_log is not None and item_issues:
                append_jsonl(issues_log, [issue.to_dict() for issue in item_issues])

        chapter_payload = _chapter_payload_with_mode(restored_payload, updated_items)
        write_json(chapter_output_path(out_dir, chapter_payload), chapter_payload.to_dict())
        written_payloads.append(chapter_payload)

    return written_payloads, issues


def _stable_eval_sample(payloads: list[ChapterPayload], sample_size: int) -> list[FinalQuoteItem]:
    per_book: dict[str, deque[FinalQuoteItem]] = defaultdict(deque)
    for payload in sorted(payloads, key=lambda value: _chapter_sort_key(value.book_code, value.chapter)):
        for item in sorted(payload.items, key=lambda value: (value.ref.start, value.ref.end, value.id)):
            per_book[payload.book_code].append(item)
    selected: list[FinalQuoteItem] = []
    ordered_books = sorted(per_book, key=lambda code: bible_sources.BOOK_ORDER.get(code, 999))
    while len(selected) < sample_size and any(per_book.values()):
        for book_code in ordered_books:
            if not per_book[book_code]:
                continue
            selected.append(per_book[book_code].popleft())
            if len(selected) >= sample_size:
                break
    return selected


def build_options_eval_pack(
    *,
    in_dir: Path,
    bank: CharacterBank,
    out_dir: Path,
    llm: JsonChatModel,
    sample_size: int,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
    seed: int | None = None,
) -> dict:
    payloads = iter_chapter_payloads(in_dir)
    hebrew_mapping = hebrew_surface_map(_hebrew_context_texts(payloads))
    bank = _restore_bank_hebrew_surfaces_from_map(bank, hebrew_mapping)
    canonical_book_filter = _canonical_book_filter(book_filter)
    filtered_payloads = [
        _chapter_payload_with_mode(
            restored_payload,
            _filter_overlapping_chapter_items(restored_payload)[0],
        )
        for payload in payloads
        for restored_payload in [
            _chapter_payload_with_mode(
                payload,
                [_restore_item_hebrew_roles_from_map(item, hebrew_mapping) for item in payload.items],
            )
        ]
        if (not canonical_book_filter or payload.book_code == canonical_book_filter)
        and (chapter_filter is None or payload.chapter == chapter_filter)
    ]
    sample_items = _stable_eval_sample(filtered_payloads, sample_size)
    builder = OptionsBuilder(bank=bank, llm=llm)

    eval_items: list[dict] = []
    for item in tqdm(sample_items, desc="build-options-eval"):
        updated, issues, debug = builder.apply_options(item)
        eval_items.append(
            {
                "id": item.id,
                "book_code": item.source.book_code,
                "book": item.source.book,
                "chapter": item.source.chapter,
                "ref": item.ref.to_dict(),
                "issues": [issue.to_dict() for issue in issues],
                "en": {
                    "riddle": updated.en.riddle,
                    "speaker": updated.en.speaker,
                    "listener": updated.en.listener,
                    "options": updated.en.options.to_dict(),
                },
                "he": {
                    "riddle": updated.he.riddle,
                    "speaker": updated.he.speaker,
                    "listener": updated.he.listener,
                    "options": updated.he.options.to_dict(),
                },
                "bank_context": debug,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_dir / "character_bank.json", bank.to_dict())
    eval_payload = {
        "seed": seed,
        "sample_size": len(eval_items),
        "taxonomy": list(bank.taxonomy),
        "items": eval_items,
    }
    write_json_atomic(out_dir / "eval_items.json", eval_payload)

    lines = ["# Options Eval", ""]
    if seed is not None:
        lines.extend([f"- Seed: `{seed}`", ""])
    lines.extend([f"- Items: `{len(eval_items)}`", ""])
    for item in eval_items:
        lines.extend(
            [
                f"## {item['id']}",
                f"- Ref: `{item['book']} {item['chapter']}:{item['ref']['start']}-{item['ref']['end']}`",
                f"- EN riddle: {item['en']['riddle']}",
                f"- HE riddle: {item['he']['riddle']}",
                f"- Truth speaker/listener: `{item['en']['speaker']}` / `{item['en']['listener']}`",
                f"- Speaker distractors: {', '.join(item['en']['options']['speaker']) or '(empty)'}",
                f"- Listener distractors: {', '.join(item['en']['options']['listener']) or '(empty)'}",
                "- Notes:",
                "",
            ]
        )
    (out_dir / "review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return eval_payload


def _build_llm_client(model: str, seed: int | None):
    from data_proc.llm import OllamaJsonClient

    options = {"seed": seed} if seed is not None else None
    return OllamaJsonClient(model=model, fallback_model=None, request_options=options)


@click.command("build-character-bank")
@click.option("--in-dir", type=click.Path(path_type=Path, exists=True, file_okay=False), default=Path("data/processed/generated"), show_default=True)
@click.option("--out-file", type=click.Path(path_type=Path, dir_okay=False), default=Path("data/processed/character_bank.json"), show_default=True)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option("--batch-size", type=int, default=1, show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_character_bank_command(
    in_dir: Path,
    out_file: Path,
    model: str,
    batch_size: int,
    seed: int | None,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    bank = build_character_bank(iter_chapter_payloads(in_dir), _build_llm_client(model, seed), batch_size=batch_size)
    write_character_bank(out_file, bank)
    click.echo(f"Wrote {len(bank.items)} character-bank entries to {out_file}.")


@click.command("build-options")
@click.option("--in-dir", type=click.Path(path_type=Path, exists=True, file_okay=False), default=Path("data/processed/generated"), show_default=True)
@click.option("--bank-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=Path("data/processed/character_bank.json"), show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("data/processed/generated_options"), show_default=True)
@click.option("--issues-log", type=click.Path(path_type=Path, dir_okay=False), default=Path("data/processed/generated_options_issues.jsonl"), show_default=True)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--limit", type=int, default=None)
@click.option("--resume/--no-resume", default=True, show_default=True)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_options_command(
    in_dir: Path,
    bank_file: Path,
    out_dir: Path,
    issues_log: Path | None,
    model: str,
    seed: int | None,
    book_filter: str | None,
    chapter_filter: int | None,
    limit: int | None,
    resume: bool,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    payloads, issues = run_build_options(
        in_dir=in_dir,
        bank=read_character_bank(bank_file),
        out_dir=out_dir,
        issues_log=issues_log,
        llm=_build_llm_client(model, seed),
        book_filter=book_filter,
        chapter_filter=chapter_filter,
        limit=limit,
        resume=resume,
    )
    click.echo(f"Wrote {len(payloads)} option chapter files; logged {len(issues)} option issues.")


@click.command("build-options-eval")
@click.option("--in-dir", type=click.Path(path_type=Path, exists=True, file_okay=False), default=Path("data/processed/generated"), show_default=True)
@click.option("--bank-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=Path("data/processed/character_bank.json"), show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("data/processed/options_eval"), show_default=True)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option("--sample-size", type=int, default=24, show_default=True)
@click.option("--seed", type=int, default=32988, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_options_eval_command(
    in_dir: Path,
    bank_file: Path,
    out_dir: Path,
    model: str,
    sample_size: int,
    seed: int,
    book_filter: str | None,
    chapter_filter: int | None,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    payload = build_options_eval_pack(
        in_dir=in_dir,
        bank=read_character_bank(bank_file),
        out_dir=out_dir,
        llm=_build_llm_client(model, seed),
        sample_size=sample_size,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
        seed=seed,
    )
    click.echo(f"Wrote options eval pack with {payload['sample_size']} items to {out_dir}.")
