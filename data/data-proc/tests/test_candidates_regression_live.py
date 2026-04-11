from __future__ import annotations

from dataclasses import dataclass

import pytest

from data_proc.candidates_pipeline import (
    DIALOGUE_BLOCKS_STRATEGY,
    FULL_CHAPTER_STRATEGY,
    PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY,
    CandidateStrategyEvaluation,
    _build_chapter_candidates,
    select_best_candidate_strategy,
)
from data_proc.llm import OllamaJsonClient
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.schema import CandidateItem
from data_proc.utils.bible_tandem import TandemBible
from data_proc.utils.text_cleanup import clean_text, cleanup_hebrew_quote

TEST_SEED = 32988
EVAL_CHAPTERS = [("GEN", chapter) for chapter in range(1, 51)] + [("EXO", 1), ("EXO", 2)]


@dataclass(frozen=True)
class CandidateTarget:
    book_code: str
    chapter: int
    verse: int
    expected_en: str | None = None
    expected_he: str | None = None
    speaker_en: str | None = None
    listener_en: str | None = None
    require_riddle_en: str | None = None


@dataclass(frozen=True)
class StrategyRun:
    strategy: str
    items: list[CandidateItem]
    issue_count: int
    llm_call_count: int


def _normalize_target_ref(book_code: str, chapter: int, verse: int, snippet: str) -> tuple[str, int, int]:
    corrections = {
        ("GEN", 4, 10, "השומר אחי אנכי"): ("GEN", 4, 9),
        ("GEN", 8, 22, "כי יצר לב האדם רע מנעריו"): ("GEN", 8, 21),
        ("GEN", 27, 28, "הברכה אחת היא לך אבי"): ("GEN", 27, 38),
    }
    return corrections.get((book_code, chapter, verse, snippet), (book_code, chapter, verse))


def _target(
    book_code: str,
    chapter: int,
    verse: int,
    *,
    expected_en: str | None = None,
    expected_he: str | None = None,
    speaker_en: str | None = None,
    listener_en: str | None = None,
    require_riddle_en: str | None = None,
) -> CandidateTarget:
    normalized_book, normalized_chapter, normalized_verse = _normalize_target_ref(
        book_code,
        chapter,
        verse,
        expected_he or expected_en or "",
    )
    return CandidateTarget(
        book_code=normalized_book,
        chapter=normalized_chapter,
        verse=normalized_verse,
        expected_en=expected_en,
        expected_he=expected_he,
        speaker_en=speaker_en,
        listener_en=listener_en,
        require_riddle_en=require_riddle_en,
    )


EXODUS_MUST_PASS_TARGETS = [
    _target("EXO", 1, 9, expected_en="the people of the children of Israel are", speaker_en="Pharaoh", listener_en="people"),
    _target("EXO", 1, 16, expected_en="When ye do the office of a midwife", speaker_en="Pharaoh", listener_en="midwives"),
    _target("EXO", 1, 22, expected_en="Every son that is born ye shall cast", speaker_en="Pharaoh", listener_en="people"),
    _target("EXO", 2, 7, expected_en="Shall I go and call thee a nurse", speaker_en="sister", listener_en="Pharaoh's daughter"),
    _target(
        "EXO",
        2,
        8,
        expected_en="Go.",
        speaker_en="Pharaoh's daughter",
        listener_en="sister",
        require_riddle_en="Go. And the maiden went and called the child's mother.",
    ),
    _target("EXO", 2, 9, expected_en="Take this child away, and nurse it for me", speaker_en="Pharaoh's daughter", listener_en="woman"),
    _target("EXO", 2, 13, expected_en="Wherefore smitest thou thy fellow?", speaker_en="Moses", listener_en="wrong"),
]

GENESIS_MUST_PASS_TARGETS = [
    _target("GEN", 3, 9, expected_he="איכה"),
    _target("GEN", 4, 10, expected_he="השומר אחי אנכי"),
    _target("GEN", 4, 13, expected_he="גדול עוני מנשא"),
    _target("GEN", 13, 8, expected_he="כי אנשים אחים אנחנו"),
    _target("GEN", 18, 23, expected_he="האף תספה צדיק עם רשע"),
    _target("GEN", 24, 17, expected_he="הגמיאיני נא מעט מים"),
    _target("GEN", 25, 30, expected_he="הלעיטני נא מן האדם האדם הזה"),
    _target("GEN", 31, 14, expected_he="העוד לנו חלק ונחלה בבית אבינו"),
    _target("GEN", 31, 40, expected_he="ביום אכלני חרב וקרח בלילה"),
    _target("GEN", 32, 11, expected_he="קטנתי מכל החסדים"),
    _target("GEN", 32, 27, expected_he="שלחני כי עלה השחר"),
    _target("GEN", 37, 8, expected_he="המלוך תמלוך עלינו"),
    _target("GEN", 38, 26, expected_he="צדקה ממני"),
    _target("GEN", 43, 9, expected_he="אנכי אערבנו"),
    _target("GEN", 45, 7, expected_he="כי למחיה שלחני אלהים לפניכם"),
    _target("GEN", 47, 9, expected_he="מעט ורעים היו ימי שני חיי"),
    _target("GEN", 50, 25, expected_he="והעלתם את עצמתי מזה"),
]

GENESIS_EVAL_TARGETS = [
    _target("GEN", 3, 9, expected_he="איכה"),
    _target("GEN", 4, 10, expected_he="השומר אחי אנכי"),
    _target("GEN", 4, 13, expected_he="גדול עוני מנשא"),
    _target("GEN", 8, 22, expected_he="כי יצר לב האדם רע מנעריו"),
    _target("GEN", 13, 8, expected_he="כי אנשים אחים אנחנו"),
    _target("GEN", 18, 23, expected_he="האף תספה צדיק עם רשע"),
    _target("GEN", 22, 12, expected_he="אל תשלח ידך אל הנער"),
    _target("GEN", 23, 15, expected_he="ארבע מאות שקל כסף"),
    _target("GEN", 24, 17, expected_he="הגמיאיני נא מעט מים"),
    _target("GEN", 25, 30, expected_he="הלעיטני נא מן האדם האדם הזה"),
    _target("GEN", 27, 28, expected_he="הברכה אחת הוא לך אבי"),
    _target("GEN", 31, 14, expected_he="העוד לנו חלק ונחלה בבית אבינו"),
    _target("GEN", 31, 40, expected_he="ביום אכלני חרב וקרח בלילה"),
    _target("GEN", 32, 11, expected_he="קטנתי מכל החסדים"),
    _target("GEN", 32, 27, expected_he="שלחני כי עלה השחר"),
    _target("GEN", 34, 30, expected_he="עכרתם אתי להבאישני"),
    _target("GEN", 37, 8, expected_he="המלוך תמלוך עלינו"),
    _target("GEN", 38, 26, expected_he="צדקה ממני"),
    _target("GEN", 42, 9, expected_he="מרגלים אתם"),
    _target("GEN", 43, 9, expected_he="אנכי אערבנו"),
    _target("GEN", 45, 7, expected_he="כי למחיה שלחני אלהים לפניכם"),
    _target("GEN", 47, 9, expected_he="מעט ורעים היו ימי שני חיי"),
    _target("GEN", 48, 16, expected_he="וידגו לרב בקרב הארץ"),
    _target("GEN", 50, 25, expected_he="והעלתם את עצמתי מזה"),
]


def _clean_en(text: str) -> str:
    return clean_text(text).casefold()


def _clean_he(text: str) -> str:
    return cleanup_hebrew_quote(text)


def _matches_target(item: CandidateItem, target: CandidateTarget) -> bool:
    if item.source.book_code != target.book_code or item.source.chapter != target.chapter:
        return False
    if not (item.source.quote_verse_start <= target.verse <= item.source.quote_verse_end):
        return False
    if target.expected_en is not None:
        expected_en = _clean_en(target.expected_en)
        if expected_en not in _clean_en(item.en.riddle) and expected_en not in _clean_en(item.en.quote):
            return False
    if target.expected_he is not None:
        expected_he = _clean_he(target.expected_he)
        if expected_he not in _clean_he(item.he.riddle) and expected_he not in _clean_he(item.he.quote):
            return False
    if target.speaker_en is not None and _clean_en(target.speaker_en) not in _clean_en(item.en.speaker):
        return False
    if target.listener_en is not None and _clean_en(target.listener_en) not in _clean_en(item.en.listener):
        return False
    if target.require_riddle_en is not None and _clean_en(target.require_riddle_en) not in _clean_en(item.en.riddle):
        return False
    return True


def _target_hits(items: list[CandidateItem], targets: list[CandidateTarget]) -> dict[CandidateTarget, CandidateItem]:
    hits: dict[CandidateTarget, CandidateItem] = {}
    for target in targets:
        match = next((item for item in items if _matches_target(item, target)), None)
        if match is not None:
            hits[target] = match
    return hits


def _build_strategy_run(strategy: str) -> StrategyRun:
    tandem = TandemBible.load(english_xml=DEFAULT_ENGLISH_XML, hebrew_zip=DEFAULT_HEBREW_ZIP)
    llm = OllamaJsonClient(
        model="gemma4:26b",
        max_retries=2,
        fallback_model=None,
        request_options={"seed": TEST_SEED},
    )
    items: list[CandidateItem] = []
    issue_count = 0
    llm_call_count = 0
    for book_code, chapter in EVAL_CHAPTERS:
        shard, issues = _build_chapter_candidates(
            tandem,
            llm=llm,
            book_code=book_code,
            chapter=chapter,
            strategy=strategy,
        )
        items.extend(shard.items)
        issue_count += len(issues)
        llm_call_count += shard.stats.get("llm_call_count", 0)
    return StrategyRun(
        strategy=strategy,
        items=items,
        issue_count=issue_count,
        llm_call_count=llm_call_count,
    )


@pytest.fixture(scope="module")
def strategy_runs() -> dict[str, StrategyRun]:
    return {
        FULL_CHAPTER_STRATEGY: _build_strategy_run(FULL_CHAPTER_STRATEGY),
        DIALOGUE_BLOCKS_STRATEGY: _build_strategy_run(DIALOGUE_BLOCKS_STRATEGY),
    }


def test_production_candidate_strategy_matches_live_regression_winner(strategy_runs: dict[str, StrategyRun]) -> None:
    evaluations = [
        CandidateStrategyEvaluation(
            strategy=run.strategy,
            passed_must_pass=len(_target_hits(run.items, EXODUS_MUST_PASS_TARGETS + GENESIS_MUST_PASS_TARGETS))
            == len(EXODUS_MUST_PASS_TARGETS + GENESIS_MUST_PASS_TARGETS),
            recall_hits=len(_target_hits(run.items, GENESIS_EVAL_TARGETS)),
            issue_count=run.issue_count,
            llm_call_count=run.llm_call_count,
        )
        for run in strategy_runs.values()
    ]

    assert select_best_candidate_strategy(evaluations) == PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY


def test_production_strategy_hits_high_value_targets(strategy_runs: dict[str, StrategyRun]) -> None:
    run = strategy_runs[PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY]
    hits = _target_hits(run.items, EXODUS_MUST_PASS_TARGETS + GENESIS_MUST_PASS_TARGETS)
    missing = [
        f"{target.book_code} {target.chapter}:{target.verse}"
        for target in EXODUS_MUST_PASS_TARGETS + GENESIS_MUST_PASS_TARGETS
        if target not in hits
    ]

    assert not missing, f"missing must-pass targets: {missing}"


def test_exodus_2_8_riddle_is_expanded_for_ux(strategy_runs: dict[str, StrategyRun]) -> None:
    run = strategy_runs[PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY]
    target = EXODUS_MUST_PASS_TARGETS[4]
    hit = _target_hits(run.items, [target])[target]

    assert _clean_en(hit.en.riddle) != "go"
    assert "called the child's mother" in _clean_en(hit.en.riddle)


def test_strategy_comparison_tracks_full_genesis_catalog_recall(strategy_runs: dict[str, StrategyRun]) -> None:
    recalls = {
        strategy: len(_target_hits(run.items, GENESIS_EVAL_TARGETS))
        for strategy, run in strategy_runs.items()
    }

    assert recalls[FULL_CHAPTER_STRATEGY] > 0
    assert recalls[DIALOGUE_BLOCKS_STRATEGY] > 0
