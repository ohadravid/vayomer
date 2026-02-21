#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from data_processing import bible_sources, bible_tandem, text_cleanup
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    import bible_tandem  # type: ignore[no-redef]
    import text_cleanup  # type: ignore[no-redef]


@dataclass(frozen=True)
class VerseIndexEntry:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    verse: int
    quote_en: str
    quote_he: str
    en_tokens: frozenset[str]
    he_tokens: frozenset[str]


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


def _strip_wrapping_quotes(text: str) -> str:
    value = _sanitize_str(text)
    if not value:
        return ""
    return value.strip(' "\'"')


def _source_bounds(source: Dict) -> Tuple[str, int, int, int]:
    if not isinstance(source, dict):
        return "", 0, 0, 0
    return (
        _sanitize_str(source.get("book_code")),
        _sanitize_int(source.get("chapter"), 0),
        _sanitize_int(source.get("quote_verse_start"), 0),
        _sanitize_int(source.get("quote_verse_end"), 0),
    )


def _candidate_bonus_words(
    quote: str,
    riddle: str,
    lang: str,
    max_candidates: int = 30,
) -> List[str]:
    quote = _sanitize_str(quote)
    riddle = _sanitize_str(riddle)
    if not quote:
        return []

    riddle_tokens = set(text_cleanup.tokenize_for_match(riddle, lang))
    spans = text_cleanup.tokenize_with_spans(quote, lang)
    out: List[str] = []
    seen_norm: Set[str] = set()

    for token, start, end in spans:
        norm = _sanitize_str(token).casefold()
        if not norm:
            continue
        if norm in seen_norm:
            continue
        if norm in riddle_tokens:
            continue
        if len(norm) <= 1:
            continue

        surface = _sanitize_str(quote[start:end])
        if not surface:
            continue

        extracted = text_cleanup.extract_substring_from_quote(quote, surface, lang)
        if not extracted:
            continue
        if text_cleanup.token_count(extracted, lang) != 1:
            continue

        seen_norm.add(norm)
        out.append(extracted)
        if len(out) >= max_candidates:
            break

    return out


def _validate_bonus(
    *,
    quote: str,
    riddle: str,
    candidate: str,
    lang: str,
    min_tokens: int = 1,
    max_tokens: int = 2,
) -> Tuple[Optional[str], str]:
    raw = _strip_wrapping_quotes(candidate)
    if not raw:
        return None, "empty bonus value"

    extracted = text_cleanup.extract_substring_from_quote(quote, raw, lang)
    if not extracted:
        return None, "value is not in quote"

    in_riddle = text_cleanup.extract_substring_from_quote(riddle, extracted, lang)
    if in_riddle:
        return None, "value appears in riddle"

    tokens = text_cleanup.token_count(extracted, lang)
    if tokens < min_tokens:
        return None, f"value has fewer than {min_tokens} tokens"
    if tokens > max_tokens:
        return None, f"value has more than {max_tokens} tokens"

    return extracted, ""


def _prompt_select(prompt: str, minimum: int, maximum: int) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw.isdigit():
            print("Please type a number.")
            continue
        value = int(raw)
        if value < minimum or value > maximum:
            print(f"Please choose a number between {minimum} and {maximum}.")
            continue
        return value


def _prompt_yes_no(prompt: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        raw = input(f"{prompt} {suffix} ").strip().lower()
        if not raw:
            return default_yes
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _build_verse_index(english_xml: Path, hebrew_zip: Path) -> List[VerseIndexEntry]:
    tandem = bible_tandem.TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    entries: List[VerseIndexEntry] = []

    for book_code, chapter in tandem.iter_chapters():
        for verse in tandem.iter_verses(book_code, chapter):
            quote_en = text_cleanup.clean_text(verse.en_raw)
            quote_he = text_cleanup.clean_text(verse.he_clean)
            if not quote_en or not quote_he:
                continue
            entries.append(
                VerseIndexEntry(
                    book_code=verse.book_code,
                    book_en=verse.book_en,
                    book_he=verse.book_he,
                    chapter=verse.chapter,
                    verse=verse.verse,
                    quote_en=quote_en,
                    quote_he=quote_he,
                    en_tokens=frozenset(text_cleanup.tokenize_for_match(quote_en, "en")),
                    he_tokens=frozenset(text_cleanup.tokenize_for_match(quote_he, "he")),
                )
            )
    return entries


def _collect_hint_candidates(
    *,
    entries: List[VerseIndexEntry],
    bonus_word_en: str,
    bonus_word_he: str,
    current_quote_en: str,
    current_quote_he: str,
    source: Dict,
    max_candidates: int,
) -> List[VerseIndexEntry]:
    cleaned_word_en = _sanitize_str(bonus_word_en)
    cleaned_word_he = _sanitize_str(bonus_word_he)
    if not cleaned_word_en or not cleaned_word_he:
        return []

    query_tokens_en = text_cleanup.tokenize_for_match(cleaned_word_en, "en")
    query_tokens_he = text_cleanup.tokenize_for_match(cleaned_word_he, "he")
    if not query_tokens_en or not query_tokens_he:
        return []
    query_token_set_en = set(query_tokens_en)
    query_token_set_he = set(query_tokens_he)

    source_code, source_chapter, _, _ = _source_bounds(source)
    cleaned_current_quote_en = _sanitize_str(current_quote_en)
    cleaned_current_quote_he = _sanitize_str(current_quote_he)

    candidates: List[VerseIndexEntry] = []
    for entry in entries:
        if (
            source_code
            and source_chapter > 0
            and entry.book_code.casefold() == source_code.casefold()
            and entry.chapter == source_chapter
        ):
            continue

        if cleaned_current_quote_en and entry.quote_en == cleaned_current_quote_en:
            continue
        if cleaned_current_quote_he and entry.quote_he == cleaned_current_quote_he:
            continue

        if not query_token_set_en.issubset(entry.en_tokens):
            continue
        if not query_token_set_he.issubset(entry.he_tokens):
            continue

        if not text_cleanup.extract_substring_from_quote(entry.quote_en, cleaned_word_en, "en"):
            continue
        if not text_cleanup.extract_substring_from_quote(entry.quote_he, cleaned_word_he, "he"):
            continue

        candidates.append(entry)
        if len(candidates) >= max_candidates:
            break

    return candidates


def _edit_bonus_for_lang(
    *,
    lang_node: Dict,
    lang: str,
    max_bonus_candidates: int,
) -> bool:
    quote = _sanitize_str(lang_node.get("quote"))
    riddle = _sanitize_str(lang_node.get("riddle"))
    current_bonus = _sanitize_str(lang_node.get("bonus"))
    if current_bonus:
        return False

    candidates = _candidate_bonus_words(
        quote=quote,
        riddle=riddle,
        lang=lang,
        max_candidates=max_bonus_candidates,
    )
    if not candidates:
        print(f"[{lang}] No candidate words found in quote.")
    else:
        print(f"[{lang}] Candidate bonus words:")
        for idx, candidate in enumerate(candidates, start=1):
            print(f"  {idx}. {candidate}")

    print(f"[{lang}] Select one candidate, 0 to skip, or -1 to type custom value.")
    choice = input("Choice: ").strip()
    while True:
        if choice == "0":
            return False
        if choice == "-1":
            raw_custom = input(f"[{lang}] Custom bonus value: ").strip()
            fixed, reason = _validate_bonus(
                quote=quote,
                riddle=riddle,
                candidate=raw_custom,
                lang=lang,
            )
            if fixed:
                lang_node["bonus"] = fixed
                print(f"[{lang}] bonus set to: {fixed}")
                return True
            print(f"[{lang}] Invalid value: {reason}")
            choice = input("Choice (0 skip / -1 custom / number): ").strip()
            continue
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                fixed, reason = _validate_bonus(
                    quote=quote,
                    riddle=riddle,
                    candidate=candidates[idx - 1],
                    lang=lang,
                )
                if fixed:
                    lang_node["bonus"] = fixed
                    print(f"[{lang}] bonus set to: {fixed}")
                    return True
                print(f"[{lang}] Invalid value: {reason}")
            else:
                print(f"[{lang}] Please choose a number between 1 and {len(candidates)}.")
        else:
            print(f"[{lang}] Please choose 0, -1, or a valid number.")
        choice = input("Choice (0 skip / -1 custom / number): ").strip()


def _choose_hint_for_lang(
    *,
    en_node: Dict,
    he_node: Dict,
    source: Dict,
    entries: List[VerseIndexEntry],
    max_hint_candidates: int,
) -> bool:
    bonus_en = _sanitize_str(en_node.get("bonus"))
    bonus_he = _sanitize_str(he_node.get("bonus"))
    quote_en = _sanitize_str(en_node.get("quote"))
    quote_he = _sanitize_str(he_node.get("quote"))
    if not bonus_en or not bonus_he or not quote_en or not quote_he:
        return False

    en_existing_hint = en_node.get("bonus_hint")
    he_existing_hint = he_node.get("bonus_hint")
    has_en_existing_hint = isinstance(en_existing_hint, dict) and bool(_sanitize_str(en_existing_hint.get("quote")))
    has_he_existing_hint = isinstance(he_existing_hint, dict) and bool(_sanitize_str(he_existing_hint.get("quote")))

    def _hint_ref(hint: object) -> Tuple[str, int, int, int]:
        if not isinstance(hint, dict):
            return "", 0, 0, 0
        source_node = hint.get("source", {})
        if not isinstance(source_node, dict):
            return "", 0, 0, 0
        book = _sanitize_str(source_node.get("book"))
        chapter = _sanitize_int(source_node.get("chapter"), 0)
        start = _sanitize_int(source_node.get("start"), 0)
        end = _sanitize_int(source_node.get("end"), 0)
        book_code = ""
        for code, en_name, he_name in bible_sources.OT_BOOKS:
            if book.casefold() == en_name.casefold() or book == he_name:
                book_code = code
                break
        if not book_code:
            book_code = book.casefold()
        return book_code, chapter, start, end

    existing_refs_match = False
    if has_en_existing_hint and has_he_existing_hint:
        existing_refs_match = _hint_ref(en_existing_hint) == _hint_ref(he_existing_hint)

    candidates = _collect_hint_candidates(
        entries=entries,
        bonus_word_en=bonus_en,
        bonus_word_he=bonus_he,
        current_quote_en=quote_en,
        current_quote_he=quote_he,
        source=source,
        max_candidates=max_hint_candidates,
    )

    print(f"[en] Bonus word: {bonus_en}")
    print(f"[he] Bonus word: {bonus_he}")
    if has_en_existing_hint:
        hint_quote = _sanitize_str(en_existing_hint.get("quote"))
        hint_source = en_existing_hint.get("source", {}) if isinstance(en_existing_hint, dict) else {}
        book = _sanitize_str(hint_source.get("book"))
        chapter = _sanitize_int(hint_source.get("chapter"), 0)
        start = _sanitize_int(hint_source.get("start"), 0)
        end = _sanitize_int(hint_source.get("end"), 0)
        print(f"[en] Existing hint: {book} {chapter}:{start}-{end} | {hint_quote}")
    if has_he_existing_hint:
        hint_quote = _sanitize_str(he_existing_hint.get("quote"))
        hint_source = he_existing_hint.get("source", {}) if isinstance(he_existing_hint, dict) else {}
        book = _sanitize_str(hint_source.get("book"))
        chapter = _sanitize_int(hint_source.get("chapter"), 0)
        start = _sanitize_int(hint_source.get("start"), 0)
        end = _sanitize_int(hint_source.get("end"), 0)
        print(f"[he] Existing hint: {book} {chapter}:{start}-{end} | {hint_quote}")
    if (has_en_existing_hint or has_he_existing_hint) and not existing_refs_match:
        print("Existing EN/HE hints are not aligned to the same source verse.")

    if not candidates:
        print("No paired EN/HE hint candidates found.")
        if (has_en_existing_hint or has_he_existing_hint) and _prompt_yes_no(
            "Keep current hint values as-is?",
            default_yes=True,
        ):
            return False
        before_en_hint = copy.deepcopy(en_node.get("bonus_hint"))
        before_he_hint = copy.deepcopy(he_node.get("bonus_hint"))
        en_node["bonus_hint"] = None
        he_node["bonus_hint"] = None
        changed = en_node.get("bonus_hint") != before_en_hint or he_node.get("bonus_hint") != before_he_hint
        if changed:
            print("Both hints set to null.")
        return changed

    print(f"Suggested paired hint quotes (max {max_hint_candidates}):")
    for idx, entry in enumerate(candidates, start=1):
        print(f"  {idx}. {entry.book_en} / {entry.book_he} {entry.chapter}:{entry.verse}")
        print(f"     en: {entry.quote_en}")
        print(f"     he: {entry.quote_he}")

    options_count = len(candidates)
    print("0 = keep current values")
    print(f"{options_count + 1} = set both hints to null")
    selected = _prompt_select(
        f"Choose paired hint option (0-{options_count + 1}): ",
        0,
        options_count + 1,
    )

    if selected == 0:
        return False
    if selected == options_count + 1:
        before_en_hint = copy.deepcopy(en_node.get("bonus_hint"))
        before_he_hint = copy.deepcopy(he_node.get("bonus_hint"))
        en_node["bonus_hint"] = None
        he_node["bonus_hint"] = None
        changed = en_node.get("bonus_hint") != before_en_hint or he_node.get("bonus_hint") != before_he_hint
        if changed:
            print("Both hints set to null.")
        return changed

    picked = candidates[selected - 1]
    before_en_hint = copy.deepcopy(en_node.get("bonus_hint"))
    before_he_hint = copy.deepcopy(he_node.get("bonus_hint"))
    en_node["bonus_hint"] = {
        "quote": picked.quote_en,
        "source": {
            "book": picked.book_en,
            "chapter": picked.chapter,
            "start": picked.verse,
            "end": picked.verse,
        },
    }
    he_node["bonus_hint"] = {
        "quote": picked.quote_he,
        "source": {
            "book": picked.book_he,
            "chapter": picked.chapter,
            "start": picked.verse,
            "end": picked.verse,
        },
    }
    changed = en_node.get("bonus_hint") != before_en_hint or he_node.get("bonus_hint") != before_he_hint
    print(f"Paired hint selected: {picked.book_en} / {picked.book_he} {picked.chapter}:{picked.verse}")
    return changed


def _edit_item(
    *,
    item: Dict,
    verse_index_cache: Optional[List[VerseIndexEntry]],
    english_xml: Path,
    hebrew_zip: Path,
    max_bonus_candidates: int,
    max_hint_candidates: int,
) -> Tuple[bool, Optional[List[VerseIndexEntry]]]:
    item_id = _sanitize_str(item.get("id")) or "<no-id>"
    print("")
    print("=" * 80)
    print(f"Item: {item_id}")
    print("=" * 80)

    en = item.get("en", {})
    he = item.get("he", {})
    source = item.get("source", {})
    if not isinstance(en, dict) or not isinstance(he, dict):
        print("Item has invalid en/he payload, skipping.")
        return False, verse_index_cache
    if not isinstance(source, dict):
        source = {}

    before = copy.deepcopy(item)
    changed = False
    bonus_changed = False
    hint_changed = False

    if not _sanitize_str(en.get("bonus")):
        changed_now = _edit_bonus_for_lang(
            lang_node=en,
            lang="en",
            max_bonus_candidates=max_bonus_candidates,
        )
        changed = changed or changed_now
        bonus_changed = bonus_changed or changed_now
    else:
        print(f"[en] bonus already exists: {_sanitize_str(en.get('bonus'))}")

    if not _sanitize_str(he.get("bonus")):
        changed_now = _edit_bonus_for_lang(
            lang_node=he,
            lang="he",
            max_bonus_candidates=max_bonus_candidates,
        )
        changed = changed or changed_now
        bonus_changed = bonus_changed or changed_now
    else:
        print(f"[he] bonus already exists: {_sanitize_str(he.get('bonus'))}")

    en_bonus = _sanitize_str(en.get("bonus"))
    he_bonus = _sanitize_str(he.get("bonus"))
    if en_bonus and he_bonus:
        if verse_index_cache is None:
            print("Loading Bible sources for hint suggestions (one-time)...")
            verse_index_cache = _build_verse_index(english_xml=english_xml, hebrew_zip=hebrew_zip)

        changed_now = _choose_hint_for_lang(
            en_node=en,
            he_node=he,
            source=source,
            entries=verse_index_cache,
            max_hint_candidates=max_hint_candidates,
        )
        changed = changed or changed_now
        hint_changed = hint_changed or changed_now
    else:
        print("Missing bonus in one of the languages; skipping hint suggestions for this item.")

    if changed:
        if not _prompt_yes_no("Accept changes for this item?", default_yes=True):
            item.clear()
            item.update(before)
            print("Changes discarded for this item.")
            return False, verse_index_cache

        meta = item.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            item["meta"] = meta
        if bonus_changed:
            meta["bonus_source"] = "manual"
        if hint_changed:
            meta["bonus_hint_source"] = "manual"
        print("Changes accepted for this item.")
        return True, verse_index_cache

    print("No changes made for this item.")
    return False, verse_index_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactively set missing bonus words and bonus hint quotes in a chapter JSON file.",
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to a chapter JSON file (for example: data/manual_quotes/genesis-003.json).",
    )
    parser.add_argument(
        "--item-id",
        default="",
        help="Optional item id filter. If provided, only this item is edited.",
    )
    parser.add_argument(
        "--max-bonus-candidates",
        type=int,
        default=20,
        help="Maximum displayed bonus-word candidates per language when bonus is missing.",
    )
    parser.add_argument(
        "--max-hint-candidates",
        type=int,
        default=5,
        help="Maximum suggested paired hint-quote candidates (same source verse for EN+HE).",
    )
    parser.add_argument(
        "--english-xml",
        type=Path,
        default=Path(bible_sources.DEFAULT_ENGLISH_COLLECTION),
        help="Path to English XML source.",
    )
    parser.add_argument(
        "--hebrew-zip",
        type=Path,
        default=Path(bible_sources.DEFAULT_HEBREW_ZIP),
        help="Path to Hebrew Tanach zip source.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.file.resolve()
    if not input_path.is_file():
        print(f"Input file not found: {input_path}")
        return 1

    with input_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    items = payload.get("items")
    if not isinstance(items, list):
        print("Invalid file: missing top-level 'items' list.")
        return 1

    selected_items: List[Dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if args.item_id and _sanitize_str(item.get("id")) != args.item_id:
            continue
        selected_items.append(item)

    if not selected_items:
        if args.item_id:
            print(f"No item matched --item-id={args.item_id}")
        else:
            print("No editable items found.")
        return 1

    verse_index_cache: Optional[List[VerseIndexEntry]] = None
    any_changed = False
    for item in selected_items:
        changed, verse_index_cache = _edit_item(
            item=item,
            verse_index_cache=verse_index_cache,
            english_xml=args.english_xml,
            hebrew_zip=args.hebrew_zip,
            max_bonus_candidates=max(1, args.max_bonus_candidates),
            max_hint_candidates=max(1, args.max_hint_candidates),
        )
        any_changed = any_changed or changed

    if not any_changed:
        print("No file changes to save.")
        return 0

    if not _prompt_yes_no(f"Write updates to {input_path}?", default_yes=True):
        print("Skipped writing file.")
        return 0

    with input_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"Wrote: {input_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
