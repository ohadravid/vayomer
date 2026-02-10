#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from tqdm import tqdm

try:
    from data_processing import bible_sources
    from data_processing.quote_cleanup import cleanup_quote_with_riddle, cleanup_quote_text
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    from quote_cleanup import cleanup_quote_with_riddle, cleanup_quote_text  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Stats:
    files: int = 0
    items: int = 0
    changed_files: int = 0
    changed_items: int = 0
    changed_lang_quotes: int = 0
    unresolved_en: int = 0
    unresolved_he: int = 0
    major_diffs: int = 0
    minor_diffs: int = 0
    missing_refs: int = 0
    missing_verses: int = 0
    shifted_ranges: int = 0


def _iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(path.glob("*.json"))
    else:
        yield path


def _write_log_entries(log_path: Path, entries: List[Dict]) -> None:
    if not entries:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _build_item_log(path: Path, item: Dict, status: str, **extra: object) -> Dict:
    source = item.get("source", {})
    return {
        "file": str(path),
        "id": item.get("id"),
        "status": status,
        "ref_start": source.get("ref_start"),
        "ref_end": source.get("ref_end"),
        **extra,
    }


def _drop_old_hebrew_verse_markers(text: str) -> str:
    return re.sub(
        r"(^|[\.;:!?׃]\s+)([\u05d0-\u05ea]{1,3})(\s+)",
        lambda m: m.group(1),
        text,
    )


def _apply_parenthetical_replacements(text: str) -> str:
    pattern = re.compile(r"([^\s()]+)\s*\(([^()]+)\)")
    previous = None
    current = text
    while current != previous:
        previous = current
        current = pattern.sub(r"\2", current)
    return current


def _normalize_hebrew_old(text: str) -> str:
    text = _drop_old_hebrew_verse_markers(bible_sources.clean_text(text))
    text = _apply_parenthetical_replacements(text)
    text = re.sub(r"[\u0591-\u05C7]", "", text)
    text = (
        text.replace("יהוה", "אלוהים")
        .replace("אדני", "אלוהים")
        .replace("אלהים", "אלוהים")
    )
    return re.sub(r"[^\u05D0-\u05EA]+", "", text)


def _normalize_hebrew_new(text: str) -> str:
    text = bible_sources.clean_text(text).replace("\u034F", "")
    text = _apply_parenthetical_replacements(text)
    text = re.sub(r"[\u0591-\u05C7]", "", text)
    text = (
        text.replace("יהוה", "אלוהים")
        .replace("אדני", "אלוהים")
        .replace("אלהים", "אלוהים")
    )
    return re.sub(r"[^\u05D0-\u05EA]+", "", text)


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _cleanup_item(item: Dict, stats: Stats) -> bool:
    item_changed = False

    for lang in ("en", "he"):
        section = item.get(lang)
        if not isinstance(section, dict):
            continue

        quote = section.get("quote")
        riddle = section.get("riddle")
        if not isinstance(quote, str):
            continue

        if isinstance(riddle, str):
            cleaned_quote = cleanup_quote_with_riddle(quote, riddle, lang)
        else:
            cleaned_quote = cleanup_quote_text(quote, lang)

        if cleaned_quote != quote:
            section["quote"] = cleaned_quote
            item_changed = True
            stats.changed_lang_quotes += 1

        if isinstance(riddle, str) and riddle and riddle not in section.get("quote", ""):
            if lang == "en":
                stats.unresolved_en += 1
            else:
                stats.unresolved_he += 1

    return item_changed


def _process_file(
    path: Path,
    out_path: Path,
    log_path: Path,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
    he_major_threshold: float,
    log_minor: bool,
    shifts: List[int],
) -> Stats:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])

    stats = Stats(files=1, items=len(items))
    file_changed = False
    file_major = 0
    file_minor = 0
    file_missing_refs = 0
    file_missing_verses = 0
    file_shifted = 0
    log_entries: List[Dict] = []
    new_items: List[Dict] = []

    for item in items:
        rewritten = dict(item)

        if _cleanup_item(rewritten, stats):
            file_changed = True
            stats.changed_items += 1

        source = rewritten.get("source", {})
        ref_start = source.get("ref_start")
        ref_end = source.get("ref_end")

        if not isinstance(ref_start, str) or not isinstance(ref_end, str):
            stats.missing_refs += 1
            file_missing_refs += 1
            log_entries.append(
                _build_item_log(path, rewritten, "missing_ref", reason="missing ref_start/ref_end")
            )
            new_items.append(rewritten)
            continue

        try:
            book_s, chapter_s, verse_s = bible_sources.parse_reference(ref_start)
            book_e, chapter_e, verse_e = bible_sources.parse_reference(ref_end)
        except ValueError as exc:
            stats.missing_refs += 1
            file_missing_refs += 1
            log_entries.append(_build_item_log(path, rewritten, "bad_ref", reason=str(exc)))
            new_items.append(rewritten)
            continue

        if book_s != book_e or chapter_s != chapter_e:
            stats.missing_refs += 1
            file_missing_refs += 1
            log_entries.append(
                _build_item_log(
                    path,
                    rewritten,
                    "cross_chapter_span",
                    reason="ref_start/ref_end span multiple books/chapters",
                )
            )
            new_items.append(rewritten)
            continue

        code = bible_sources.BOOK_NAME_TO_CODE.get(book_s)
        if not code:
            stats.missing_refs += 1
            file_missing_refs += 1
            log_entries.append(_build_item_log(path, rewritten, "unknown_book", book=book_s))
            new_items.append(rewritten)
            continue

        start, end = sorted((verse_s, verse_e))
        current_en = rewritten.get("en", {}).get("quote", "")
        current_he = rewritten.get("he", {}).get("quote", "")
        current_he_norm = _normalize_hebrew_old(current_he)
        current_en_norm = bible_sources.normalize_english_for_compare(current_en)

        best: Tuple[float, float, int, str, str, List[int]] | None = None
        for shift in sorted(set(shifts)):
            c_start = start + shift
            c_end = end + shift
            if c_start < 1 or c_end < 1:
                continue
            cand_en, cand_he, cand_missing = bible_sources.collect_range_text(
                code=code,
                chapter=chapter_s,
                start=c_start,
                end=c_end,
                english_map=english_map,
                hebrew_map=hebrew_map,
            )
            he_ratio = _ratio(current_he_norm, _normalize_hebrew_new(cand_he))
            en_ratio = _ratio(current_en_norm, bible_sources.normalize_english_for_compare(cand_en))
            candidate = (he_ratio, en_ratio, shift, cand_en, cand_he, cand_missing)
            if best is None:
                best = candidate
                continue
            if he_ratio > best[0] + 1e-9:
                best = candidate
            elif abs(he_ratio - best[0]) <= 1e-9 and abs(shift) < abs(best[2]):
                best = candidate

        if best is None:
            new_en, new_he, missing = "", "", list(range(start, end + 1))
            en_ratio = 0.0
            he_ratio = 0.0
            applied_shift = 0
        else:
            he_ratio, en_ratio, applied_shift, new_en, new_he, missing = best

        if applied_shift != 0:
            stats.shifted_ranges += 1
            file_shifted += 1

        if missing:
            stats.missing_verses += 1
            file_missing_verses += 1
            log_entries.append(
                _build_item_log(
                    path,
                    rewritten,
                    "missing_verses",
                    missing_verses=missing,
                    applied_shift=applied_shift,
                )
            )

        is_major = he_ratio < he_major_threshold
        is_minor = he_ratio < 1.0 and not is_major
        if is_major:
            stats.major_diffs += 1
            file_major += 1
            log_entries.append(
                _build_item_log(
                    path,
                    rewritten,
                    "different_major",
                    he_ratio=round(he_ratio, 4),
                    en_ratio=round(en_ratio, 4),
                    applied_shift=applied_shift,
                    current_en=current_en,
                    current_he=current_he,
                    v3_en=new_en,
                    v3_he=new_he,
                )
            )
        elif is_minor and log_minor:
            stats.minor_diffs += 1
            file_minor += 1
            log_entries.append(
                _build_item_log(
                    path,
                    rewritten,
                    "different_minor",
                    he_ratio=round(he_ratio, 4),
                    en_ratio=round(en_ratio, 4),
                    applied_shift=applied_shift,
                )
            )
        elif is_minor:
            stats.minor_diffs += 1
            file_minor += 1

        rewritten_en = dict(rewritten.get("en", {}))
        rewritten_he = dict(rewritten.get("he", {}))

        if new_en:
            rewritten_en["quote"] = cleanup_quote_with_riddle(
                new_en,
                rewritten_en.get("riddle", ""),
                "en",
            )
            rewritten_en["book"] = book_s
        if new_he:
            rewritten_he["quote"] = cleanup_quote_with_riddle(
                new_he,
                rewritten_he.get("riddle", ""),
                "he",
            )
            rewritten_he["book"] = bible_sources.BOOK_CODE_TO_HE.get(code, rewritten_he.get("book", ""))

        rewritten["en"] = rewritten_en
        rewritten["he"] = rewritten_he
        new_items.append(rewritten)

    if file_changed:
        stats.changed_files = 1

    if not items:
        log_entries.append({"file": str(path), "status": "file_empty", "items": 0})
    else:
        log_entries.append(
            {
                "file": str(path),
                "status": "file_summary",
                "items": len(items),
                "major_diffs": file_major,
                "minor_diffs": file_minor,
                "missing_refs": file_missing_refs,
                "missing_verses": file_missing_verses,
                "shifted_ranges": file_shifted,
            }
        )

    out_data = {
        "source_file": data.get("source_file"),
        "items": new_items,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_log_entries(log_path, log_entries)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="data/quotes", help="quote JSON file or directory")
    parser.add_argument("--checked-dir", default="data/checked_quotes")
    parser.add_argument("--log", default="data/quote_diffs_v3.jsonl")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--he-major-threshold", type=float, default=0.95)
    parser.add_argument(
        "--shifts",
        default="-2,-1,0,1,2",
        help="comma-separated verse shifts to try for reference alignment",
    )
    parser.add_argument("--log-minor", action="store_true", help="include minor differences in the log")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="overwrite already-written checked files")
    args = parser.parse_args()

    target = (ROOT / args.path).resolve()
    checked_dir = (ROOT / args.checked_dir).resolve()
    log_path = (ROOT / args.log).resolve()
    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()
    shifts = [int(x.strip()) for x in args.shifts.split(",") if x.strip()]

    tqdm.write(f"Loading English verses: {english_xml}")
    english_map = bible_sources.load_english_verse_map(english_xml)
    tqdm.write(f"Loading Hebrew verses: {hebrew_zip}")
    hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)

    paths = list(_iter_inputs(target))
    if args.limit_files:
        paths = paths[: args.limit_files]

    queue: List[Tuple[Path, Path]] = []
    skipped_existing = 0
    for path in paths:
        out_path = checked_dir / path.name
        if not args.force and out_path.exists():
            skipped_existing += 1
            continue
        queue.append((path, out_path))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not log_path.exists():
        log_path.write_text("", encoding="utf-8")

    tqdm.write(
        f"Postprocess queue: total={len(paths)} pending={len(queue)} "
        f"skipped_existing={skipped_existing}"
    )
    if not queue:
        return 0

    total = Stats()
    errors = 0
    for path, out_path in tqdm(queue, desc="postprocess", unit="file"):
        try:
            stats = _process_file(
                path=path,
                out_path=out_path,
                log_path=log_path,
                english_map=english_map,
                hebrew_map=hebrew_map,
                he_major_threshold=args.he_major_threshold,
                log_minor=args.log_minor,
                shifts=shifts,
            )
        except Exception as exc:
            errors += 1
            tqdm.write(f"ERROR {path}: {exc}")
            continue

        total.files += stats.files
        total.items += stats.items
        total.changed_files += stats.changed_files
        total.changed_items += stats.changed_items
        total.changed_lang_quotes += stats.changed_lang_quotes
        total.unresolved_en += stats.unresolved_en
        total.unresolved_he += stats.unresolved_he
        total.major_diffs += stats.major_diffs
        total.minor_diffs += stats.minor_diffs
        total.missing_refs += stats.missing_refs
        total.missing_verses += stats.missing_verses
        total.shifted_ranges += stats.shifted_ranges

    tqdm.write(
        "Checked {files} files / {items} items, changed_files={changed_files}, "
        "changed_items={changed_items}, changed_lang_quotes={changed_lang_quotes}, "
        "major_diffs={major}, minor_diffs={minor}, missing_refs={missing_refs}, "
        "missing_verses={missing_verses}, shifted_ranges={shifted}, "
        "unresolved_en={unresolved_en}, unresolved_he={unresolved_he}, errors={errors}, "
        "output={checked_dir}, log={log_path}".format(
            files=total.files,
            items=total.items,
            changed_files=total.changed_files,
            changed_items=total.changed_items,
            changed_lang_quotes=total.changed_lang_quotes,
            major=total.major_diffs,
            minor=total.minor_diffs,
            missing_refs=total.missing_refs,
            missing_verses=total.missing_verses,
            shifted=total.shifted_ranges,
            unresolved_en=total.unresolved_en,
            unresolved_he=total.unresolved_he,
            errors=errors,
            checked_dir=checked_dir,
            log_path=log_path,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
