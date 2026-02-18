#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
import sys
import types
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_processing import bible_sources, bible_tandem, text_cleanup


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


def _has_hebrew(text: str) -> bool:
    return bool(re.search(r"[\u05D0-\u05EA]", text or ""))


def _strip_match_punctuation(text: str, lang: str) -> str:
    value = _sanitize_str(text)
    if not value:
        return ""
    if lang == "he":
        # Keep Hebrew letters/spaces and strip punctuation for loose substring matching.
        value = re.sub(r"[^\u05D0-\u05EA\s]", " ", value)
    else:
        value = re.sub(r"[^\w\s]", " ", value)
    return _sanitize_str(value)


EN_ADDRESS_RE = re.compile(
    r"^(?:And\s+)?(?P<speaker>.+?)\s+"
    r"(?:called|cried|spake|said|saith|answered)\s+"
    r"(?:unto|to)\s+"
    r"(?P<listener>.+?)(?:,|;|:|\.|$)",
    flags=re.IGNORECASE,
)
HE_ADDRESS_RE = re.compile(r"^\S+\s+(?P<speaker>.+?)\s+א[ֵֶ]?ל[-־](?P<listener>[\u0590-\u05FF־]+)")
EN_PRONOUNS = {"he", "she", "him", "her", "them", "they", "you", "thou", "thee", "ye", "it"}


def _clean_inferred_entity_en(value: str) -> str:
    entity = _sanitize_str(value)
    entity = re.sub(r"^(?:and|then)\s+", "", entity, flags=re.IGNORECASE).strip()
    entity = entity.strip(" ,;:.!?")
    return entity


def _clean_inferred_entity_he(value: str) -> str:
    entity = _sanitize_str(value)
    entity = entity.strip(" ,;:.!?")
    return entity


def _infer_entities_from_en_quote(quote: str) -> Tuple[str, str]:
    text = _sanitize_str(quote)
    match = EN_ADDRESS_RE.search(text)
    if not match:
        return "", ""
    speaker = _clean_inferred_entity_en(match.group("speaker"))
    listener = _clean_inferred_entity_en(match.group("listener"))
    if listener.casefold() in EN_PRONOUNS:
        return speaker, ""
    return speaker, listener


def _infer_entities_from_he_quote(quote: str) -> Tuple[str, str]:
    text = _sanitize_str(quote)
    match = HE_ADDRESS_RE.search(text)
    if not match:
        return "", ""
    speaker = _clean_inferred_entity_he(match.group("speaker"))
    listener = _clean_inferred_entity_he(match.group("listener"))
    return speaker, listener


def _slug_from_book_code(book_code: str) -> str:
    book_en = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code)
    slug = re.sub(r"[^a-z0-9]+", "-", book_en.lower()).strip("-")
    return slug or book_code.lower()


def _chapter_filename(book_code: str, chapter: int) -> str:
    return f"{_slug_from_book_code(book_code)}-{chapter:03d}.json"


def _parse_verse_range(expr: str) -> Tuple[int, int]:
    token = _sanitize_str(expr).replace(" ", "")
    match = re.fullmatch(r"(\d+)(?::(\d+))?", token)
    if not match:
        raise SystemExit(f"Bad --verse value '{expr}'. Expected 'N' or 'N:M'.")
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if start <= 0 or end <= 0:
        raise SystemExit("Verse numbers must be positive.")
    if start > end:
        start, end = end, start
    return start, end


def _book_alias_map() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for code, en, he in bible_sources.OT_BOOKS:
        aliases[_sanitize_str(code).casefold()] = code
        aliases[_sanitize_str(en).casefold()] = code
        aliases[_sanitize_str(he).casefold()] = code
    aliases["song of solomon"] = "SON"
    return aliases


def _resolve_book_code(book_value: str) -> str:
    token = _sanitize_str(book_value)
    if not token:
        raise SystemExit("Missing --book.")
    aliases = _book_alias_map()
    exact = aliases.get(token.casefold())
    if exact:
        return exact

    compact = re.sub(r"[^a-z0-9\u0590-\u05FF]+", "", token.casefold())
    compact_aliases = {
        re.sub(r"[^a-z0-9\u0590-\u05FF]+", "", key): value for key, value in aliases.items()
    }
    compact_hit = compact_aliases.get(compact)
    if compact_hit:
        return compact_hit

    near: List[Tuple[int, str]] = []
    for key, code in aliases.items():
        if compact and compact in re.sub(r"[^a-z0-9\u0590-\u05FF]+", "", key):
            near.append((len(key), code))
    if near:
        near.sort()
        return near[0][1]

    fuzzy = difflib.get_close_matches(token.casefold(), aliases.keys(), n=1, cutoff=0.72)
    if fuzzy:
        return aliases[fuzzy[0]]

    valid = ", ".join(sorted({en for _, en, _ in bible_sources.OT_BOOKS}))
    raise SystemExit(f"Unknown book '{book_value}'. Example valid values: {valid}")


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _find_matching_items(payload: Dict, book_code: str, chapter: int, start: int, end: int) -> List[Dict]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    out: List[Dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if not isinstance(source, dict):
            continue
        src_code = _sanitize_str(source.get("book_code")) or _sanitize_str(payload.get("book_code"))
        src_ch = _sanitize_int(source.get("chapter"), _sanitize_int(payload.get("chapter"), 0))
        src_start = _sanitize_int(source.get("quote_verse_start"), 0)
        src_end = _sanitize_int(source.get("quote_verse_end"), 0)
        if src_code == book_code and src_ch == chapter and src_start == start and src_end == end:
            out.append(item)
    return out


def _pick_template_item(book_code: str, chapter: int, start: int, end: int) -> Optional[Dict]:
    chapter_file = _chapter_filename(book_code, chapter)
    search_dirs = (
        ROOT / "data" / "quotes_options",
        ROOT / "data" / "quotes",
        ROOT / "data" / "rebuilt_quotes_bonus",
        ROOT / "data" / "rebuilt_quotes",
    )
    for base in search_dirs:
        payload = _load_json(base / chapter_file)
        if not payload:
            continue
        matches = _find_matching_items(payload, book_code, chapter, start, end)
        if matches:
            return matches[0]
    return None


def _extract_riddle_or_die(quote: str, requested: str, lang: str, arg_name: str) -> str:
    requested_clean = _sanitize_str(requested)
    attempts: List[str] = [requested_clean]
    if lang == "he":
        loose = _strip_match_punctuation(requested_clean, lang)
        if loose and loose not in attempts:
            attempts.append(loose)

    for candidate in attempts:
        riddle = text_cleanup.extract_substring_from_quote(quote, candidate, lang)
        if riddle:
            return riddle

    raise SystemExit(
        f"{arg_name} must be a substring of the {lang.upper()} quote span after normalization. "
        f"Received: '{requested}'"
    )


def _load_payloads_for_pool(
    *,
    pool_dir: Path,
    manual_dir: Path,
    include_manual_pool: bool,
) -> List[Tuple[Path, Dict]]:
    payloads: List[Tuple[Path, Dict]] = []
    seen: set[Path] = set()

    def scan(base: Path) -> None:
        if not base.exists() or not base.is_dir():
            return
        for path in sorted(base.rglob("*.json")):
            if not path.is_file() or path in seen:
                continue
            if path.stem.endswith("-draft"):
                continue
            payload = _load_json(path)
            if payload is None:
                continue
            seen.add(path)
            payloads.append((path, payload))

    scan(pool_dir)
    if include_manual_pool:
        scan(manual_dir)
    return payloads


def _load_hard_options_module(skip_llm: bool):
    def install_stub(module_name: str) -> bool:
        if module_name == "ollama" and skip_llm:
            stub = types.ModuleType("ollama")

            def _chat_unavailable(*_args, **_kwargs):
                raise RuntimeError("ollama is required when LLM option selection is enabled.")

            stub.chat = _chat_unavailable  # type: ignore[attr-defined]
            sys.modules["ollama"] = stub
            return True
        if module_name == "tqdm":
            stub = types.ModuleType("tqdm")

            class _TqdmStub:
                @staticmethod
                def write(message: str) -> None:
                    print(message)

                def __call__(self, iterable, **_kwargs):
                    return iterable

            stub.tqdm = _TqdmStub()  # type: ignore[attr-defined]
            sys.modules["tqdm"] = stub
            return True
        return False

    for _ in range(4):
        try:
            from data_processing import postprocess_hard_options  # type: ignore[import]
            return postprocess_hard_options
        except ModuleNotFoundError as exc:
            if exc.name and install_stub(exc.name):
                continue
            raise SystemExit(
                f"Missing Python dependency '{exc.name}'. Run via `uv run python ...` or install deps."
            ) from exc

    raise SystemExit("Could not load postprocess_hard_options dependencies.")


def _build_manual_item_id(
    *,
    book_code: str,
    chapter: int,
    start: int,
    end: int,
    riddle_en: str,
    riddle_he: str,
) -> str:
    slug = _slug_from_book_code(book_code)
    digest = hashlib.sha256(f"{book_code}|{chapter}|{start}|{end}|{riddle_en}|{riddle_he}".encode("utf-8")).hexdigest()
    return f"manual-{slug}-{chapter:02d}-{start:02d}-{end:02d}-{digest[:8]}"


def _sort_items(items: Sequence[Dict]) -> List[Dict]:
    def key(item: Dict) -> Tuple[int, int, str]:
        source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
        start = _sanitize_int(source.get("quote_verse_start"), 9999)
        end = _sanitize_int(source.get("quote_verse_end"), 9999)
        item_id = _sanitize_str(item.get("id"))
        return start, end, item_id

    return sorted(items, key=key)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a manual quote+riddle item from a verse range and write it into data/manual_quotes, "
            "with options selected using the existing hard-options selector."
        )
    )
    parser.add_argument("--book", required=True, help="Book code or name (e.g. GEN, Genesis)")
    parser.add_argument("--chapter", type=int, required=True, help="Chapter number")
    parser.add_argument("--verse", required=True, help="Verse or range (N or N:M)")

    parser.add_argument("--riddle", default="", help="Convenience value for English riddle (or both when identical)")
    parser.add_argument("--riddle-en", default="", help="English riddle text (must be a substring of EN quote)")
    parser.add_argument("--riddle-he", default="", help="Hebrew riddle text (must be a substring of HE quote)")

    parser.add_argument("--speaker-en", default="", help="English speaker label override")
    parser.add_argument("--speaker-he", default="", help="Hebrew speaker label override")
    parser.add_argument("--listener-en", default="", help="English listener label override")
    parser.add_argument("--listener-he", default="", help="Hebrew listener label override")

    parser.add_argument("--item-id", default="", help="Optional item id override")
    parser.add_argument("--pool-dir", default="data/quotes_options", help="Directory used to build option pools")
    parser.add_argument("--manual-dir", default="data/manual_quotes", help="Manual output directory")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)

    parser.add_argument("--model", default="gemma3:4b", help="Model used for option picking (if LLM enabled)")
    parser.add_argument("--option-count", type=int, default=4)
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--llm-retries", type=int, default=2)
    parser.add_argument("--skip-llm", action="store_true", help="Use deterministic fallback option selection only")
    parser.add_argument("--same-book-only", action="store_true")
    parser.add_argument(
        "--no-manual-pool",
        action="store_true",
        help="Do not include existing data/manual_quotes entries in option pools",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _normalize_cli_args(raw_args: Sequence[str]) -> List[str]:
    key_aliases = {
        "book": "book",
        "chapter": "chapter",
        "verse": "verse",
        "riddle": "riddle",
        "riddle-en": "riddle-en",
        "riddle_en": "riddle-en",
        "riddle-he": "riddle-he",
        "riddle_he": "riddle-he",
        "speaker-en": "speaker-en",
        "speaker_en": "speaker-en",
        "speaker-he": "speaker-he",
        "speaker_he": "speaker-he",
        "listener-en": "listener-en",
        "listener_en": "listener-en",
        "listener-he": "listener-he",
        "listener_he": "listener-he",
        "item-id": "item-id",
        "item_id": "item-id",
        "pool-dir": "pool-dir",
        "pool_dir": "pool-dir",
        "manual-dir": "manual-dir",
        "manual_dir": "manual-dir",
        "english-xml": "english-xml",
        "english_xml": "english-xml",
        "hebrew-zip": "hebrew-zip",
        "hebrew_zip": "hebrew-zip",
        "model": "model",
        "option-count": "option-count",
        "option_count": "option-count",
        "sample-size": "sample-size",
        "sample_size": "sample-size",
        "max-rounds": "max-rounds",
        "max_rounds": "max-rounds",
        "llm-retries": "llm-retries",
        "llm_retries": "llm-retries",
        "skip-llm": "skip-llm",
        "same-book-only": "same-book-only",
        "no-manual-pool": "no-manual-pool",
        "dry-run": "dry-run",
    }

    out: List[str] = []
    for arg in raw_args:
        if arg.startswith("-"):
            out.append(arg)
            continue
        if "=" not in arg:
            out.append(arg)
            continue
        key, value = arg.split("=", 1)
        mapped = key_aliases.get(key.strip())
        if not mapped:
            out.append(arg)
            continue
        out.append(f"--{mapped}")
        if mapped in {"skip-llm", "same-book-only", "no-manual-pool", "dry-run"}:
            if value.strip().lower() in {"", "1", "true", "yes", "on"}:
                continue
            # Explicit false means don't enable the flag.
            out.pop()
            continue
        out.append(value)
    return out


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(_normalize_cli_args(sys.argv[1:]))

    if args.chapter <= 0:
        raise SystemExit("--chapter must be > 0")
    if args.option_count < 1:
        raise SystemExit("--option-count must be >= 1")
    if args.sample_size < 1:
        raise SystemExit("--sample-size must be >= 1")
    if args.max_rounds < 0:
        raise SystemExit("--max-rounds must be >= 0")
    if args.llm_retries < 1:
        raise SystemExit("--llm-retries must be >= 1")

    postprocess_hard_options = _load_hard_options_module(skip_llm=bool(args.skip_llm))

    book_code = _resolve_book_code(args.book)
    chapter = args.chapter
    start, end = _parse_verse_range(args.verse)

    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()
    if not english_xml.exists():
        raise SystemExit(f"Missing English source XML: {english_xml}")
    if not hebrew_zip.exists():
        raise SystemExit(f"Missing Hebrew source ZIP: {hebrew_zip}")

    tandem = bible_tandem.TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    range_quote = tandem.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
    if range_quote.missing:
        missing = ",".join(str(v) for v in range_quote.missing)
        raise SystemExit(
            f"Missing verse text for {book_code} {chapter}:{start}-{end}. Missing verses: {missing}"
        )
    if not range_quote.en_quote or not range_quote.he_quote:
        raise SystemExit(f"Empty quote span for {book_code} {chapter}:{start}-{end}")

    template = _pick_template_item(book_code=book_code, chapter=chapter, start=start, end=end)
    template_en = template.get("en", {}) if isinstance(template, dict) and isinstance(template.get("en"), dict) else {}
    template_he = template.get("he", {}) if isinstance(template, dict) and isinstance(template.get("he"), dict) else {}

    speaker_en = _sanitize_str(args.speaker_en) or _sanitize_str(template_en.get("speaker"))
    speaker_he = _sanitize_str(args.speaker_he) or _sanitize_str(template_he.get("speaker"))
    listener_en = _sanitize_str(args.listener_en) or _sanitize_str(template_en.get("listener"))
    listener_he = _sanitize_str(args.listener_he) or _sanitize_str(template_he.get("listener"))
    inferred_speaker_en, inferred_listener_en = _infer_entities_from_en_quote(range_quote.en_quote)
    inferred_speaker_he, inferred_listener_he = _infer_entities_from_he_quote(range_quote.he_quote)
    speaker_en = speaker_en or inferred_speaker_en
    speaker_he = speaker_he or inferred_speaker_he
    listener_en = listener_en or inferred_listener_en
    listener_he = listener_he or inferred_listener_he
    if not (speaker_en and speaker_he and listener_en and listener_he):
        raise SystemExit(
            "Could not infer speaker/listener for this verse range. "
            "Pass --speaker-en --speaker-he --listener-en --listener-he."
        )

    speaker_en = text_cleanup.align_entity_to_quote(speaker_en, range_quote.en_quote, "en")
    speaker_he = text_cleanup.align_entity_to_quote(speaker_he, range_quote.he_quote, "he")
    listener_en = text_cleanup.align_entity_to_quote(listener_en, range_quote.en_quote, "en")
    listener_he = text_cleanup.align_entity_to_quote(listener_he, range_quote.he_quote, "he")

    if not text_cleanup.entity_in_quote(speaker_en, range_quote.en_quote, "en"):
        raise SystemExit(f"English speaker is not present in quote: '{speaker_en}'")
    if not text_cleanup.entity_in_quote(listener_en, range_quote.en_quote, "en"):
        raise SystemExit(f"English listener is not present in quote: '{listener_en}'")
    if not text_cleanup.entity_in_quote(speaker_he, range_quote.he_quote, "he"):
        raise SystemExit(f"Hebrew speaker is not present in quote: '{speaker_he}'")
    if not text_cleanup.entity_in_quote(listener_he, range_quote.he_quote, "he"):
        raise SystemExit(f"Hebrew listener is not present in quote: '{listener_he}'")

    shared = _sanitize_str(args.riddle)
    requested_riddle_en = _sanitize_str(args.riddle_en)
    requested_riddle_he = _sanitize_str(args.riddle_he)

    if shared:
        shared_has_hebrew = _has_hebrew(shared)
        if not requested_riddle_en and not shared_has_hebrew:
            requested_riddle_en = shared
        if not requested_riddle_he and shared_has_hebrew:
            requested_riddle_he = shared
        if not requested_riddle_en and text_cleanup.extract_substring_from_quote(range_quote.en_quote, shared, "en"):
            requested_riddle_en = shared
        if not requested_riddle_he and (
            text_cleanup.extract_substring_from_quote(range_quote.he_quote, shared, "he")
            or text_cleanup.extract_substring_from_quote(range_quote.he_quote, _strip_match_punctuation(shared, "he"), "he")
        ):
            requested_riddle_he = shared

    if not requested_riddle_en:
        requested_riddle_en = _sanitize_str(template_en.get("riddle"))
    if not requested_riddle_he:
        requested_riddle_he = _sanitize_str(template_he.get("riddle"))
    if not requested_riddle_en:
        requested_riddle_en = text_cleanup.suggest_riddle_from_quote(
            quote=range_quote.en_quote,
            speaker=speaker_en,
            listener=listener_en,
            lang="en",
            min_tokens=2,
            max_tokens=12,
        )
    if not requested_riddle_he:
        requested_riddle_he = text_cleanup.suggest_riddle_from_quote(
            quote=range_quote.he_quote,
            speaker=speaker_he,
            listener=listener_he,
            lang="he",
            min_tokens=1,
            max_tokens=8,
        )

    if not requested_riddle_en:
        raise SystemExit(
            "Missing English riddle. Provide --riddle-en (or a shared --riddle that matches EN), "
            "or use a verse range with an existing template item."
        )
    if not requested_riddle_he:
        raise SystemExit(
            "Missing Hebrew riddle. Provide --riddle-he (or a shared --riddle that matches HE), "
            "or use a verse range with an existing template item."
        )

    riddle_en = _extract_riddle_or_die(range_quote.en_quote, requested_riddle_en, "en", "--riddle-en/--riddle")
    riddle_he = _extract_riddle_or_die(range_quote.he_quote, requested_riddle_he, "he", "--riddle-he/--riddle")

    if text_cleanup.riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en"):
        raise SystemExit("English riddle mentions speaker/listener; pick a different riddle substring.")
    if text_cleanup.riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he"):
        raise SystemExit("Hebrew riddle mentions speaker/listener; pick a different riddle substring.")

    item_id = _sanitize_str(args.item_id) or _build_manual_item_id(
        book_code=book_code,
        chapter=chapter,
        start=start,
        end=end,
        riddle_en=riddle_en,
        riddle_he=riddle_he,
    )

    base_item: Dict = {
        "id": item_id,
        "source": {
            "method": "manual",
            "book_code": book_code,
            "book": range_quote.book_en,
            "book_he": range_quote.book_he,
            "chapter": chapter,
            "quote_verse_start": start,
            "quote_verse_end": end,
        },
        "en": {
            "quote": range_quote.en_quote,
            "riddle": riddle_en,
            "speaker": speaker_en,
            "listener": listener_en,
            "book": range_quote.book_en,
        },
        "he": {
            "quote": range_quote.he_quote,
            "riddle": riddle_he,
            "speaker": speaker_he,
            "listener": listener_he,
            "book": range_quote.book_he,
        },
        "raw_quote_source": range_quote.raw_quote_source,
        "ref": {
            "chapter": chapter,
            "start": start,
            "end": end,
        },
        "meta": {
            "mode": "manual",
            "source": "manual-script",
            "template_item_id": _sanitize_str(template.get("id")) if isinstance(template, dict) else "",
        },
    }

    pool_dir = (ROOT / args.pool_dir).resolve()
    manual_dir = (ROOT / args.manual_dir).resolve()
    payloads = _load_payloads_for_pool(
        pool_dir=pool_dir,
        manual_dir=manual_dir,
        include_manual_pool=not bool(args.no_manual_pool),
    )
    if not payloads:
        raise SystemExit(
            f"No payloads found to build options from. Check --pool-dir (resolved: {pool_dir})."
        )

    pools = postprocess_hard_options._collect_candidate_pools(payloads)
    item_with_options, llm_stats, option_notes = postprocess_hard_options._build_output_item(
        item=base_item,
        pools=pools,
        model=_sanitize_str(args.model),
        skip_llm=bool(args.skip_llm),
        option_count=args.option_count,
        sample_size=args.sample_size,
        max_rounds=args.max_rounds,
        llm_retries=args.llm_retries,
        same_book_only=bool(args.same_book_only),
        target_book_code=book_code,
        target_book=range_quote.book_en,
    )

    out_path = manual_dir / _chapter_filename(book_code, chapter)
    existing = _load_json(out_path) or {}

    out_payload = copy.deepcopy(existing) if existing else {}
    out_payload["book_code"] = book_code
    out_payload["book"] = range_quote.book_en
    out_payload["book_he"] = range_quote.book_he
    out_payload["chapter"] = chapter
    out_payload["mode"] = "manual"

    items = out_payload.get("items")
    if not isinstance(items, list):
        items = []
    items = [entry for entry in items if isinstance(entry, dict)]
    replaced = False
    for idx, entry in enumerate(items):
        if _sanitize_str(entry.get("id")) == item_id:
            items[idx] = item_with_options
            replaced = True
            break
    if not replaced:
        items.append(item_with_options)
    out_payload["items"] = _sort_items(items)

    if not args.dry_run:
        manual_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    regular_speaker = len(item_with_options.get("en", {}).get("options", {}).get("speaker", []))
    regular_listener = len(item_with_options.get("en", {}).get("options", {}).get("listener", []))
    hard_speaker = len(item_with_options.get("en", {}).get("hard_difficulty_options", {}).get("speaker", []))
    hard_listener = len(item_with_options.get("en", {}).get("hard_difficulty_options", {}).get("listener", []))

    print(
        json.dumps(
            {
                "status": "dry_run" if args.dry_run else ("updated" if replaced else "created"),
                "file": str(out_path),
                "id": item_id,
                "book_code": book_code,
                "chapter": chapter,
                "verse_start": start,
                "verse_end": end,
                "template_used": bool(template),
                "options_counts_en": {
                    "speaker": regular_speaker,
                    "listener": regular_listener,
                },
                "hard_options_counts_en": {
                    "speaker": hard_speaker,
                    "listener": hard_listener,
                },
                "llm_stats": llm_stats,
                "notes": option_notes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
