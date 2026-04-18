from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_proc.llm import OllamaJsonClient
from data_proc.pipeline import (
    CandidateDropError,
    CandidatePipeline,
    build_quotes_eval_pack,
    run_pipeline,
)
from data_proc.utils.text_cleanup import strip_hebrew_marks
from data_proc.utils.text_cleanup import whole_bonus_word_occurs, whole_word_occurs

TEST_SEED = 32988


@pytest.fixture(scope="module")
def live_pipeline(bible_corpus):
    return CandidatePipeline(
        corpus=bible_corpus,
        llm=OllamaJsonClient(
            model="gemma4:26b",
            max_retries=2,
            fallback_model=None,
            request_options={"seed": TEST_SEED},
        ),
    )


def test_live_ollama_can_pick_bonus_word_for_selected_example(candidate_map, live_pipeline) -> None:
    item = live_pipeline.process_candidate(candidate_map["genesis-03-13-13"])

    assert item.en.bonus
    assert item.he.bonus
    assert item.en.options.speaker == []
    assert item.en.options.listener == []
    assert item.he.options.speaker == []
    assert item.he.options.listener == []
    assert item.en.bonus.lower() not in item.en.riddle.lower()
    assert item.he.bonus not in item.he.riddle
    assert not whole_word_occurs(f"{item.en.speaker} {item.en.listener}", item.en.bonus, "en")
    assert not whole_bonus_word_occurs(f"{item.he.speaker} {item.he.listener}", item.he.bonus, "he")
    assert (item.en.bonus_hint.source.book, item.en.bonus_hint.source.chapter) != (item.source.book, item.source.chapter)
    assert (item.he.bonus_hint.source.book, item.he.bonus_hint.source.chapter) != (item.source.book_he, item.source.chapter)
    assert whole_word_occurs(item.en.bonus_hint.quote, item.en.bonus, "en")
    assert whole_bonus_word_occurs(item.he.bonus_hint.quote, item.he.bonus, "he")


def test_live_ollama_expands_quote_when_original_has_no_bonus_words(candidate_map, live_pipeline) -> None:
    original = candidate_map["genesis-03-09-09"]
    item = live_pipeline.process_candidate(original)

    assert (item.source.quote_verse_start, item.source.quote_verse_end) != (
        original.source.quote_verse_start,
        original.source.quote_verse_end,
    )
    assert item.source.quote_verse_start == 9
    assert item.source.quote_verse_end == 10
    assert item.ref.start == 9
    assert item.ref.end == 10
    assert not whole_word_occurs(original.en.quote, item.en.bonus, "en")
    assert not whole_bonus_word_occurs(original.he.quote, item.he.bonus, "he")


def test_live_ollama_keeps_multiple_clear_genesis_candidates(candidate_map, live_pipeline) -> None:
    candidate_ids = [
        "genesis-03-09-09",
        "genesis-03-13-13",
        "genesis-09-09-09",
        "genesis-21-12-12",
        "genesis-04-06-06",
    ]
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []

    for candidate_id in candidate_ids:
        try:
            live_pipeline.process_candidate(candidate_map[candidate_id])
            kept.append(candidate_id)
        except CandidateDropError as exc:
            dropped.append((candidate_id, exc.record.reason))

    assert "genesis-03-09-09" in kept
    assert "genesis-03-13-13" in kept
    assert len(kept) >= 3, f"kept={kept} dropped={dropped}"


def test_live_ollama_restores_hebrew_role_niqqud_in_output(candidate_map, live_pipeline) -> None:
    item = live_pipeline.process_candidate(candidate_map["genesis-03-13-13"])

    assert strip_hebrew_marks(item.he.speaker) in {"יהוה", "יהוה אלהים", "יהוהאלהים"}
    assert strip_hebrew_marks(item.he.listener) == "האשה"
    assert strip_hebrew_marks(item.he.speaker) != item.he.speaker
    assert strip_hebrew_marks(item.he.listener) != item.he.listener


def test_live_ollama_expands_quote_for_poor_single_verse_context(candidate_map, live_pipeline) -> None:
    candidate = live_pipeline.restore_hebrew_roles(live_pipeline.resolve_roles(candidate_map["genesis-48-02-02"]))
    prepared = live_pipeline.prepare_context_candidate(candidate)

    assert prepared.expansion == "before"
    assert prepared.candidate.source.quote_verse_start == 1
    assert prepared.candidate.source.quote_verse_end == 2
    assert "thy father is sick" in prepared.candidate.en.quote
    assert candidate_map["genesis-48-02-02"].en.riddle in prepared.candidate.en.quote
    assert candidate_map["genesis-48-02-02"].he.riddle in prepared.candidate.he.quote


def test_live_ollama_keeps_minimal_quote_when_context_is_clear(candidate_map, live_pipeline) -> None:
    candidate = live_pipeline.restore_hebrew_roles(candidate_map["genesis-03-13-13"])
    prepared = live_pipeline.prepare_context_candidate(candidate)

    assert prepared.expansion == "original"
    assert prepared.candidate.source.quote_verse_start == 13
    assert prepared.candidate.source.quote_verse_end == 13


def test_live_ollama_repairs_hebrew_role_from_english_support(candidate_map, live_pipeline) -> None:
    candidate = live_pipeline.restore_hebrew_roles(live_pipeline.resolve_roles(candidate_map["genesis-24-05-05"]))

    assert candidate.en.speaker == "servant"
    assert candidate.en.listener == "Abraham"
    assert candidate.he.speaker == "הָעֶבֶד"
    assert candidate.he.listener == "אַבְרָהָם"


def test_live_ollama_expands_context_until_named_speaker_is_present(candidate_map, live_pipeline) -> None:
    original = candidate_map["job-32-09-11"]
    item = live_pipeline.process_candidate(original)

    assert item.source.quote_verse_start < original.source.quote_verse_start
    assert item.source.quote_verse_end == original.source.quote_verse_end
    assert item.source.quote_verse_end - item.source.quote_verse_start + 1 <= 7
    assert item.en.speaker == "Elihu"
    assert item.en.speaker != "Job"
    assert whole_word_occurs(item.en.quote, item.en.speaker, "en")
    assert strip_hebrew_marks(item.he.speaker) == "אליהוא"
    assert strip_hebrew_marks(item.he.speaker) != "איוב"
    assert whole_word_occurs(item.he.quote, item.he.speaker, "he")
    assert item.en.riddle in item.en.quote
    assert item.he.riddle in item.he.quote


def test_live_run_pipeline_writes_real_chapter_file(candidate_map, tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    with candidates_path.open("w", encoding="utf-8") as handle:
        for candidate_id in ["genesis-03-09-09", "genesis-03-13-13"]:
            handle.write(json.dumps(candidate_map[candidate_id].to_dict(), ensure_ascii=False) + "\n")

    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=OllamaJsonClient(
            model="gemma4:26b",
            max_retries=2,
            fallback_model=None,
            request_options={"seed": TEST_SEED},
        ),
        english_xml=Path("English_Collection.4921q.0.xml"),
        hebrew_zip=Path("Tanach.xml.zip"),
        resume=False,
    )

    assert len(payloads) == 1
    assert len(payloads[0].items) == 2
    assert (out_dir / "genesis-003.json").exists()
    written = json.loads((out_dir / "genesis-003.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in written["items"]] == ["genesis-03-09-09", "genesis-03-13-13"]
    assert written["items"][0]["source"]["quote_verse_end"] == 10
    assert not dropped


def test_live_build_quotes_eval_pack_writes_reviewable_artifacts(candidate_map, tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes_eval"

    with candidates_path.open("w", encoding="utf-8") as handle:
        for candidate_id in ["genesis-03-09-09", "genesis-03-13-13", "genesis-04-06-06"]:
            handle.write(json.dumps(candidate_map[candidate_id].to_dict(), ensure_ascii=False) + "\n")

    payload = build_quotes_eval_pack(
        candidates_path=candidates_path,
        out_dir=out_dir,
        llm=OllamaJsonClient(
            model="gemma4:26b",
            max_retries=2,
            fallback_model=None,
            request_options={"seed": TEST_SEED},
        ),
        english_xml=Path("English_Collection.4921q.0.xml"),
        hebrew_zip=Path("Tanach.xml.zip"),
        sample_size=3,
        seed=TEST_SEED,
    )

    assert sorted(path.name for path in out_dir.iterdir()) == ["eval_items.json", "review.md"]
    assert payload["sample_size"] == 3
    review = (out_dir / "review.md").read_text(encoding="utf-8")
    assert "# Quotes Eval" in review
    for item in payload["items"]:
        assert item["id"] in review
        assert item["status"] in {"kept", "dropped"}
