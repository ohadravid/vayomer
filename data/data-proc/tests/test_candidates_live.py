from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_proc.candidates_pipeline import build_candidates_eval_pack, run_build_candidates
from data_proc.llm import OllamaJsonClient
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.utils.text_cleanup import cleanup_hebrew_quote

TEST_SEED = 32988


@pytest.fixture(scope="module")
def seeded_candidate_llm() -> OllamaJsonClient:
    return OllamaJsonClient(
        model="gemma4:26b",
        max_retries=2,
        fallback_model=None,
        request_options={"seed": TEST_SEED},
    )


def test_live_run_build_candidates_writes_real_genesis_chapter(tmp_path, seeded_candidate_llm) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidate_issues.jsonl"

    shards, issues = run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=seeded_candidate_llm,
        english_xml=DEFAULT_ENGLISH_XML,
        hebrew_zip=DEFAULT_HEBREW_ZIP,
        book_filter="GEN",
        chapter_filter=3,
        resume=False,
    )

    assert [(shard.book_code, shard.chapter) for shard in shards] == [("GEN", 3)]
    shard = shards[0]
    assert len(shard.items) >= 2
    kept_ids = {item.id for item in shard.items}
    assert "genesis-03-09-09" in kept_ids
    verse_13_items = [
        item
        for item in shard.items
        if item.id.startswith("genesis-03-13-13") and item.ref.start == 13 and item.ref.end == 13
    ]
    assert verse_13_items
    assert any(
        "what is this that thou hast done" in item.en.riddle.lower()
        or "serpent beguiled me" in item.en.riddle.lower()
        for item in verse_13_items
    )
    assert (shard_dir / "genesis-003.json").exists()
    aggregate = [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(aggregate) == len(shard.items)
    for item in shard.items:
        assert item.en.riddle in item.en.quote
        assert cleanup_hebrew_quote(item.he.riddle) in cleanup_hebrew_quote(item.he.quote)
        assert 0.0 <= item.meta.confidence <= 1.0
    assert issues_log.exists()
    assert issues or issues_log.read_text(encoding="utf-8").strip()


def test_live_build_candidates_eval_pack_writes_reviewable_artifacts(tmp_path, seeded_candidate_llm) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidate_issues.jsonl"
    out_dir = tmp_path / "candidates_eval"

    run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=seeded_candidate_llm,
        english_xml=DEFAULT_ENGLISH_XML,
        hebrew_zip=DEFAULT_HEBREW_ZIP,
        book_filter="GEN",
        limit=3,
        resume=False,
    )
    payload = build_candidates_eval_pack(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        out_dir=out_dir,
        sample_size=4,
        seed=TEST_SEED,
    )

    assert sorted(path.name for path in out_dir.iterdir()) == ["eval_items.json", "review.md"]
    assert payload["sample_size"] == 4
    review = (out_dir / "review.md").read_text(encoding="utf-8")
    assert "# Candidate Eval" in review
    for item in payload["items"]:
        assert item["id"] in review
