#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import bible_sources
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

PROMPT_INSTRUCTIONS = [
    "Identify only direct speech quotes in this chapter.",
    "Exclude degenerate quotes (generic, low-information, procedural lists, or boring formulaic speech).",
    "Output JSON only, no markdown.",
    "Return an array of items. Each item MUST include:",
    "- riddle_verse_start, riddle_verse_end (integers for the short riddle span)",
    "- quote_verse_start, quote_verse_end (integers for the full quote span)",
    "- speaker_en, listener_en, speaker_he, listener_he",
    "- riddle_en, riddle_he (verbatim substrings from the quote, up to ~25 words)",
    "Rules:",
    "1) Quote span MUST include explicit speaker and listener names in BOTH languages.",
    "2) speaker_en/listener_en/speaker_he/listener_he MUST be verbatim substrings of the quote text.",
    "3) Riddle must NOT include speaker or listener names.",
    "4) Riddle must be a verbatim substring of the quote in the corresponding language (no paraphrase, no ellipses).",
    "5) Prefer concrete actions/objects/instructions for riddles.",
    "6) If explicit speaker/listener names are not present in the Hebrew text, skip that quote.",
    "Examples of bad riddles:",
    "- 'And the LORD spoke unto Moses, saying:'",
    "- 'This is the thing which the LORD hath commanded to be done.'",
]


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _parse_model_output(content: str) -> List[Dict]:
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", content, re.S)
        if not match:
            raise
        data = json.loads(match.group(1))

    if isinstance(data, dict):
        data = data.get("quotes") or data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("Model output must be a list")
    return data


def call_model(
    chapter: bible_sources.ChapterRecord,
    model: str,
) -> Tuple[List[Dict], Dict[str, int | bool]]:
    prompt = {
        "book": chapter.book_name_en,
        "book_he": chapter.book_name_he,
        "chapter": chapter.chapter,
        "verses": [
            {
                "v": verse.verse,
                "en": verse.en,
                "he": verse.he,
            }
            for verse in chapter.verses
        ],
        "instructions": PROMPT_INSTRUCTIONS,
    }

    response = chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            }
        ],
    )

    content = response["message"]["content"].strip()
    prompt_tokens = response.get("prompt_eval_count")
    response_tokens = response.get("eval_count")

    estimated = False
    if prompt_tokens is None or response_tokens is None:
        estimated = True
        prompt_tokens = _estimate_tokens(json.dumps(prompt, ensure_ascii=False))
        response_tokens = _estimate_tokens(content)

    output = _parse_model_output(content)
    stats = {
        "prompt_tokens": int(prompt_tokens),
        "response_tokens": int(response_tokens),
        "estimated": bool(estimated),
    }
    return output, stats


def build_candidates(
    chapter: bible_sources.ChapterRecord,
    model_out: List[Dict],
    english_xml: Path,
    hebrew_zip: Path,
) -> Dict:
    items = []
    for q in model_out:
        items.append(
            {
                "riddle_verse_start": q.get("riddle_verse_start"),
                "riddle_verse_end": q.get("riddle_verse_end"),
                "quote_verse_start": q.get("quote_verse_start"),
                "quote_verse_end": q.get("quote_verse_end"),
                "riddle_en": q.get("riddle_en"),
                "riddle_he": q.get("riddle_he"),
                "speaker_en": q.get("speaker_en"),
                "listener_en": q.get("listener_en"),
                "speaker_he": q.get("speaker_he"),
                "listener_he": q.get("listener_he"),
            }
        )

    return {
        "source_ref": chapter.source_ref,
        "book_code": chapter.book_code,
        "chapter": chapter.chapter,
        "source_files": {
            "english_xml": str(english_xml.name),
            "hebrew_zip": str(hebrew_zip.name),
        },
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--output-dir", default="data/quote_candidates")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--book", default="", help="optional book code/name filter (e.g. GEN or Genesis)")
    parser.add_argument("--limit", type=int, default=0, help="limit chapters processed (0 = no limit)")
    parser.add_argument("--force", action="store_true", help="overwrite outputs instead of resume mode")
    args = parser.parse_args()

    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()
    out_dir = (ROOT / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tqdm.write(f"Loading English verses: {english_xml}")
    english_map = bible_sources.load_english_verse_map(english_xml)
    tqdm.write(f"Loading Hebrew verses: {hebrew_zip}")
    hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)
    chapters = bible_sources.build_common_chapters(english_map, hebrew_map)

    if args.book:
        key = args.book.strip().casefold()
        chapters = [
            chapter
            for chapter in chapters
            if chapter.book_code.casefold() == key or chapter.book_name_en.casefold() == key
        ]

    if args.limit:
        chapters = chapters[: args.limit]

    if not chapters:
        tqdm.write("No matching chapters found.")
        return 1

    pending: List[Tuple[bible_sources.ChapterRecord, Path]] = []
    skipped_existing = 0
    for chapter in chapters:
        out_path = out_dir / bible_sources.chapter_filename(chapter)
        if not args.force and out_path.exists():
            skipped_existing += 1
            continue
        pending.append((chapter, out_path))

    tqdm.write(
        f"Preprocess queue: total={len(chapters)} pending={len(pending)} "
        f"skipped_existing={skipped_existing}"
    )
    if not pending:
        return 0

    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    errors = 0

    for chapter, out_path in tqdm(pending, desc="preprocess", unit="chap"):
        try:
            model_out, stats = call_model(chapter, args.model)
            payload = build_candidates(chapter, model_out, english_xml, hebrew_zip)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            total_prompt_tokens += int(stats["prompt_tokens"])
            total_response_tokens += int(stats["response_tokens"])
            if bool(stats["estimated"]):
                estimated_calls += 1
        except Exception as exc:
            errors += 1
            tqdm.write(f"ERROR {chapter.source_ref}: {exc}")

    tqdm.write(
        "Done: wrote={wrote}, errors={errors}, prompt_tokens={prompt_tokens}, "
        "response_tokens={response_tokens}, estimated_calls={estimated}".format(
            wrote=len(pending) - errors,
            errors=errors,
            prompt_tokens=total_prompt_tokens,
            response_tokens=total_response_tokens,
            estimated=estimated_calls,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
