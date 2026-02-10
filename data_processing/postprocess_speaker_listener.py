#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import bible_sources
    from data_processing.quote_cleanup import cleanup_quote_with_riddle
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    from quote_cleanup import cleanup_quote_with_riddle  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

STATUS_OK = "ok"
STATUS_NEEDS_FIX = "needs_fix"
STATUS_UNRESOLVED = "unresolved"

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
    "me",
    "i",
    "we",
    "us",
    "my",
    "our",
    "his",
    "their",
    "hers",
    "himself",
    "herself",
    "themselves",
}

HE_PRONOUNS = {
    "הוּא",
    "הִיא",
    "הֵם",
    "הֶם",
    "הֵן",
    "הֶן",
    "אַתָּה",
    "אַתְּ",
    "אַתֶּם",
    "אַתֶּן",
    "אֲנִי",
    "אֲנַחְנוּ",
    "לוֹ",
    "לָהּ",
    "לָהֶם",
    "לָהֶן",
    "אֵלָיו",
    "אֵלַי",
    "אֲלֵיהֶם",
    "אֲלֵיהֶן",
}

AUDIT_PROMPT = [
    "You are auditing Bible quote metadata.",
    "For each item, decide whether speaker/listener values are good concrete entities.",
    "good examples: Moses, Pharaoh, Jacob, the LORD, the LORD God, children of Israel.",
    "bad examples: he, she, they, them, him, her, you, thou, me, us, reporting clauses like 'he said unto me', malformed names like 'God the LORD'.",
    "If a bad value can be fixed by expanding quote verses to include explicit names, provide new verse range and corrected names in both languages.",
    "Return JSON only with this shape:",
    '{"results":[{"idx":0,"status":"ok|needs_fix|unresolved","issues":["..."],"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","quote_verse_start":1,"quote_verse_end":2,"reason":"..."}]}',
    "Rules:",
    "1) status=ok when both speaker/listener are good and no range expansion is needed.",
    "2) status=needs_fix only when you can confidently resolve names.",
    "3) status=unresolved when uncertain.",
    "4) quote_verse_start/end must stay in the same chapter.",
    "5) keep existing values unchanged when status=ok.",
]


@dataclass
class Stats:
    files: int = 0
    items: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    ok: int = 0
    needs_fix: int = 0
    unresolved: int = 0
    fixed_items: int = 0
    heuristic_ok: int = 0
    skipped_existing: int = 0
    errors: int = 0


def _iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(path.glob("*.json"))
    else:
        yield path


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


def _chapter_context(
    code: str,
    chapter: int,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> List[Dict]:
    verse_nums = sorted(
        {
            verse
            for (v_code, v_chapter, verse), text in english_map.items()
            if v_code == code and v_chapter == chapter and text and hebrew_map.get((v_code, v_chapter, verse))
        }
    )
    return [
        {
            "v": verse,
            "en": english_map[(code, chapter, verse)],
            "he": hebrew_map[(code, chapter, verse)],
        }
        for verse in verse_nums
    ]


def _get_book_chapter(item: Dict) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int]]:
    source = item.get("source", {})
    ref_start = source.get("ref_start")
    ref_end = source.get("ref_end")
    if not isinstance(ref_start, str) or not isinstance(ref_end, str):
        return None, None, None, None
    try:
        book_s, chapter_s, verse_s = bible_sources.parse_reference(ref_start)
        book_e, chapter_e, verse_e = bible_sources.parse_reference(ref_end)
    except ValueError:
        return None, None, None, None
    if book_s != book_e or chapter_s != chapter_e:
        return None, None, None, None
    return book_s, chapter_s, min(verse_s, verse_e), max(verse_s, verse_e)


def _call_llm_for_items(
    model: str,
    context: List[Dict],
    inputs: List[Dict],
) -> Tuple[List[Dict], Dict[str, int | bool]]:
    base_prompt = {
        "context_verses": context,
        "items": inputs,
        "instructions": AUDIT_PROMPT,
    }

    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_error: Optional[Exception] = None

    for attempt in range(1, 4):
        prompt = dict(base_prompt)
        if attempt > 1:
            prompt["strict_json_retry"] = (
                "Previous output was invalid JSON. Return strict JSON only, parsable with json.loads. "
                "No comments, no markdown, no trailing text."
            )

        response = chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                }
            ],
        )
        attempts += 1
        content = response["message"]["content"].strip()

        prompt_tokens = response.get("prompt_eval_count")
        response_tokens = response.get("eval_count")
        if prompt_tokens is None or response_tokens is None:
            estimated_calls += 1
            prompt_tokens = _estimate_tokens(json.dumps(prompt, ensure_ascii=False))
            response_tokens = _estimate_tokens(content)

        total_prompt_tokens += int(prompt_tokens)
        total_response_tokens += int(response_tokens)

        try:
            payload = _parse_json_payload(content)
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise ValueError("LLM output missing results list")
            return results, {
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
                "calls": attempts,
            }
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            continue

    raise ValueError(f"LLM JSON parse failed after {attempts} attempts: {last_error}")


def _sanitize_status(value: object) -> str:
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {STATUS_OK, STATUS_NEEDS_FIX, STATUS_UNRESOLVED}:
            return value
    return STATUS_UNRESOLVED


def _sanitize_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _sanitize_int(value: object, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _norm_en(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _norm_he(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _is_suspicious_en(name: str) -> bool:
    value = _norm_en(name)
    if not value:
        return True
    if value in EN_PRONOUNS:
        return True
    if value.startswith(("he ", "she ", "they ", "them ", "him ", "her ", "you ", "thou ", "thee ", "ye ")):
        return True
    if " said " in value or value.startswith("he said") or value.startswith("she said"):
        return True
    if "god the lord" in value:
        return True
    if value in {"the man", "the woman", "the people", "people", "man", "woman"}:
        return True
    return False


def _is_suspicious_he(name: str) -> bool:
    value = _norm_he(name)
    if not value:
        return True
    if value in HE_PRONOUNS:
        return True
    if "וַיֹּאמֶר" in value or "ויאמר" in value:
        return True
    if value in {"הָעָם", "אִישׁ", "הָאִשָּׁה", "הָאִשָּׁה", "אֲנָשִׁים"}:
        return True
    return False


def _should_audit_with_llm(item: Dict, llm_all: bool) -> bool:
    if llm_all:
        return True

    speaker_en = item.get("en", {}).get("speaker", "")
    listener_en = item.get("en", {}).get("listener", "")
    speaker_he = item.get("he", {}).get("speaker", "")
    listener_he = item.get("he", {}).get("listener", "")

    return any(
        (
            _is_suspicious_en(str(speaker_en)),
            _is_suspicious_en(str(listener_en)),
            _is_suspicious_he(str(speaker_he)),
            _is_suspicious_he(str(listener_he)),
        )
    )


def _build_input(item: Dict, idx: int, start: int, end: int) -> Dict:
    return {
        "idx": idx,
        "id": item.get("id"),
        "quote_verse_start": start,
        "quote_verse_end": end,
        "speaker_en": item.get("en", {}).get("speaker"),
        "listener_en": item.get("en", {}).get("listener"),
        "speaker_he": item.get("he", {}).get("speaker"),
        "listener_he": item.get("he", {}).get("listener"),
        "quote_en": item.get("en", {}).get("quote"),
        "quote_he": item.get("he", {}).get("quote"),
    }


def _apply_fix(
    item: Dict,
    book: str,
    chapter: int,
    suggested: Dict,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> bool:
    start = _sanitize_int(suggested.get("quote_verse_start"), 0)
    end = _sanitize_int(suggested.get("quote_verse_end"), 0)
    if start <= 0 or end <= 0:
        return False
    if start > end:
        start, end = end, start

    code = bible_sources.BOOK_NAME_TO_CODE.get(book)
    if not code:
        return False
    new_en, new_he, missing = bible_sources.collect_range_text(
        code=code,
        chapter=chapter,
        start=start,
        end=end,
        english_map=english_map,
        hebrew_map=hebrew_map,
    )
    if missing or not new_en or not new_he:
        return False

    en = dict(item.get("en", {}))
    he = dict(item.get("he", {}))
    source = dict(item.get("source", {}))

    riddle_en = en.get("riddle", "")
    riddle_he = he.get("riddle", "")
    en["quote"] = cleanup_quote_with_riddle(new_en, riddle_en, "en")
    he["quote"] = cleanup_quote_with_riddle(new_he, riddle_he, "he")

    speaker_en = _sanitize_name(suggested.get("speaker_en"))
    listener_en = _sanitize_name(suggested.get("listener_en"))
    speaker_he = _sanitize_name(suggested.get("speaker_he"))
    listener_he = _sanitize_name(suggested.get("listener_he"))
    if speaker_en:
        en["speaker"] = speaker_en
    if listener_en:
        en["listener"] = listener_en
    if speaker_he:
        he["speaker"] = speaker_he
    if listener_he:
        he["listener"] = listener_he

    source["ref_start"] = f"{book} {chapter}:{start}"
    source["ref_end"] = f"{book} {chapter}:{end}"
    source["line_start"] = start
    source["line_end"] = end

    item["en"] = en
    item["he"] = he
    item["source"] = source
    return True


def _process_file(
    path: Path,
    out_path: Path,
    audit_path: Path,
    issue_log_path: Path,
    model: str,
    mode: str,
    llm_all: bool,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> Stats:
    data = json.loads(path.read_text(encoding="utf-8"))
    items: List[Dict] = data.get("items", [])
    stats = Stats(files=1, items=len(items))

    if not items:
        audit_payload = {
            "file": str(path),
            "mode": mode,
            "items_total": 0,
            "results": [],
        }
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if mode == "fix":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return stats

    by_chapter: Dict[Tuple[str, int], List[Tuple[int, Dict]]] = {}
    missing_ref_results: List[Dict] = []
    results_by_idx: Dict[int, Dict] = {}

    for idx, item in enumerate(items):
        book, chapter, start, end = _get_book_chapter(item)
        if not book or chapter is None or start is None or end is None:
            missing_ref_results.append(
                {
                    "idx": idx,
                    "id": item.get("id"),
                    "status": STATUS_UNRESOLVED,
                    "issues": ["bad_or_missing_ref"],
                    "reason": "missing/bad ref_start/ref_end",
                }
            )
            continue
        if not _should_audit_with_llm(item, llm_all=llm_all):
            results_by_idx[idx] = {
                "idx": idx,
                "id": item.get("id"),
                "status": STATUS_OK,
                "issues": [],
                "reason": "heuristic_clear",
                "speaker_en": item.get("en", {}).get("speaker"),
                "listener_en": item.get("en", {}).get("listener"),
                "speaker_he": item.get("he", {}).get("speaker"),
                "listener_he": item.get("he", {}).get("listener"),
                "quote_verse_start": start,
                "quote_verse_end": end,
            }
            stats.heuristic_ok += 1
            continue
        by_chapter.setdefault((book, chapter), []).append((idx, item))

    for result in missing_ref_results:
        results_by_idx[result["idx"]] = result

    for (book, chapter), chapter_items in by_chapter.items():
        code = bible_sources.BOOK_NAME_TO_CODE.get(book)
        if not code:
            for idx, item in chapter_items:
                result = {
                    "idx": idx,
                    "id": item.get("id"),
                    "status": STATUS_UNRESOLVED,
                    "issues": ["unknown_book"],
                    "reason": f"unknown book {book}",
                }
                results_by_idx[idx] = result
            continue

        context = _chapter_context(code, chapter, english_map, hebrew_map)
        inputs = []
        for idx, item in chapter_items:
            _, _, start, end = _get_book_chapter(item)
            assert start is not None and end is not None
            inputs.append(_build_input(item, idx, start, end))

        llm_results, call_stats = _call_llm_for_items(model=model, context=context, inputs=inputs)
        stats.llm_calls += int(call_stats.get("calls", 1))
        stats.prompt_tokens += int(call_stats["prompt_tokens"])
        stats.response_tokens += int(call_stats["response_tokens"])
        if bool(call_stats["estimated"]):
            stats.estimated_calls += 1

        for raw in llm_results:
            idx = _sanitize_int(raw.get("idx"), -1)
            if idx < 0:
                continue
            result = {
                "idx": idx,
                "id": items[idx].get("id") if idx < len(items) else None,
                "status": _sanitize_status(raw.get("status")),
                "issues": raw.get("issues") if isinstance(raw.get("issues"), list) else [],
                "reason": _sanitize_name(raw.get("reason")),
                "speaker_en": _sanitize_name(raw.get("speaker_en")),
                "listener_en": _sanitize_name(raw.get("listener_en")),
                "speaker_he": _sanitize_name(raw.get("speaker_he")),
                "listener_he": _sanitize_name(raw.get("listener_he")),
                "quote_verse_start": raw.get("quote_verse_start"),
                "quote_verse_end": raw.get("quote_verse_end"),
            }
            results_by_idx[idx] = result

    for idx, item in enumerate(items):
        if idx in results_by_idx:
            continue
        results_by_idx[idx] = {
            "idx": idx,
            "id": item.get("id"),
            "status": STATUS_UNRESOLVED,
            "issues": ["llm_missing_result"],
            "reason": "LLM did not return a result for this item",
        }

    issue_lines: List[str] = []
    audit_results: List[Dict] = []

    for idx, item in enumerate(items):
        result = results_by_idx[idx]
        status = _sanitize_status(result.get("status"))
        result["status"] = status

        if status == STATUS_OK:
            stats.ok += 1
        elif status == STATUS_NEEDS_FIX:
            stats.needs_fix += 1
        else:
            stats.unresolved += 1

        book, chapter, cur_start, cur_end = _get_book_chapter(item)
        audit_item = {
            "idx": idx,
            "id": item.get("id"),
            "status": status,
            "issues": result.get("issues", []),
            "reason": result.get("reason", ""),
            "current": {
                "speaker_en": item.get("en", {}).get("speaker"),
                "listener_en": item.get("en", {}).get("listener"),
                "speaker_he": item.get("he", {}).get("speaker"),
                "listener_he": item.get("he", {}).get("listener"),
                "quote_verse_start": cur_start,
                "quote_verse_end": cur_end,
            },
            "suggested": {
                "speaker_en": result.get("speaker_en"),
                "listener_en": result.get("listener_en"),
                "speaker_he": result.get("speaker_he"),
                "listener_he": result.get("listener_he"),
                "quote_verse_start": result.get("quote_verse_start"),
                "quote_verse_end": result.get("quote_verse_end"),
            },
        }
        audit_results.append(audit_item)

        if status != STATUS_OK:
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(path),
                        "id": item.get("id"),
                        "status": status,
                        "issues": result.get("issues", []),
                        "reason": result.get("reason", ""),
                        "current": audit_item["current"],
                        "suggested": audit_item["suggested"],
                    },
                    ensure_ascii=False,
                )
            )

        if mode == "fix" and status == STATUS_NEEDS_FIX and book and chapter is not None:
            if _apply_fix(
                item=item,
                book=book,
                chapter=chapter,
                suggested=result,
                english_map=english_map,
                hebrew_map=hebrew_map,
            ):
                stats.fixed_items += 1

    if issue_lines:
        issue_log_path.parent.mkdir(parents=True, exist_ok=True)
        with issue_log_path.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    audit_payload = {
        "file": str(path),
        "mode": mode,
        "items_total": len(items),
        "ok": stats.ok,
        "needs_fix": stats.needs_fix,
        "unresolved": stats.unresolved,
        "fixed_items": stats.fixed_items,
        "results": audit_results,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "fix":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="data/quotes", help="quote JSON file or directory")
    parser.add_argument("--mode", choices=["report", "fix"], default="report")
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--out-dir", default="data/quotes_expanded", help="only used in fix mode")
    parser.add_argument("--audit-dir", default="data/speaker_listener_audit")
    parser.add_argument("--issues-log", default="data/speaker_listener_issues.jsonl")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--llm-all", action="store_true", help="audit every item with the LLM (slow)")
    parser.add_argument("--force", action="store_true", help="reprocess files even if audit/fix outputs exist")
    args = parser.parse_args()

    target = (ROOT / args.path).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    audit_dir = (ROOT / args.audit_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()
    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()

    tqdm.write(f"Loading English verses: {english_xml}")
    english_map = bible_sources.load_english_verse_map(english_xml)
    tqdm.write(f"Loading Hebrew verses: {hebrew_zip}")
    hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)

    paths = list(_iter_inputs(target))
    if args.limit_files:
        paths = paths[: args.limit_files]

    queue: List[Path] = []
    skipped_existing = 0
    for path in paths:
        audit_path = audit_dir / path.name
        out_path = out_dir / path.name
        exists = audit_path.exists() and (args.mode == "report" or out_path.exists())
        if exists and not args.force:
            skipped_existing += 1
            continue
        queue.append(path)

    if args.force or not issues_log.exists():
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        issues_log.write_text("", encoding="utf-8")

    tqdm.write(
        f"Speaker/listener {args.mode} queue: total={len(paths)} pending={len(queue)} "
        f"skipped_existing={skipped_existing}"
    )
    if not queue:
        return 0

    total = Stats(skipped_existing=skipped_existing)
    for path in tqdm(queue, desc=f"speaker-listener-{args.mode}", unit="file"):
        audit_path = audit_dir / path.name
        out_path = out_dir / path.name
        try:
            stats = _process_file(
                path=path,
                out_path=out_path,
                audit_path=audit_path,
                issue_log_path=issues_log,
                model=args.model,
                mode=args.mode,
                llm_all=args.llm_all,
                english_map=english_map,
                hebrew_map=hebrew_map,
            )
        except Exception as exc:
            total.errors += 1
            tqdm.write(f"ERROR {path}: {exc}")
            continue

        total.files += stats.files
        total.items += stats.items
        total.llm_calls += stats.llm_calls
        total.prompt_tokens += stats.prompt_tokens
        total.response_tokens += stats.response_tokens
        total.estimated_calls += stats.estimated_calls
        total.ok += stats.ok
        total.needs_fix += stats.needs_fix
        total.unresolved += stats.unresolved
        total.fixed_items += stats.fixed_items
        total.heuristic_ok += stats.heuristic_ok

    tqdm.write(
        "Done: files={files}, items={items}, ok={ok}, needs_fix={needs_fix}, unresolved={unresolved}, "
        "fixed_items={fixed_items}, heuristic_ok={heuristic_ok}, llm_calls={llm_calls}, prompt_tokens={prompt_tokens}, "
        "response_tokens={response_tokens}, estimated_calls={estimated_calls}, "
        "skipped_existing={skipped_existing}, errors={errors}, audit_dir={audit_dir}, issues_log={issues_log}".format(
            files=total.files,
            items=total.items,
            ok=total.ok,
            needs_fix=total.needs_fix,
            unresolved=total.unresolved,
            fixed_items=total.fixed_items,
            heuristic_ok=total.heuristic_ok,
            llm_calls=total.llm_calls,
            prompt_tokens=total.prompt_tokens,
            response_tokens=total.response_tokens,
            estimated_calls=total.estimated_calls,
            skipped_existing=total.skipped_existing,
            errors=total.errors,
            audit_dir=audit_dir,
            issues_log=issues_log,
        )
    )
    return 1 if total.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
