from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from click.testing import CliRunner

from data_proc.candidates_pipeline import (
    MINIMAL_CANDIDATE_BOOK_CODES,
    CandidateChapterShard,
    _assign_unique_candidate_ids,
    _align_english_riddle_to_quote,
    _chapter_candidate_windows,
    _chapter_shard_path,
    _default_candidate_book_scope,
    _rebuild_candidates_jsonl,
    build_candidates_command,
    run_build_candidates,
)
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.schema import CandidateItem
from data_proc.utils.bible_tandem import TandemBible


class _FakeTandem:
    def iter_chapters(self, book_filter: str = ""):
        return [
            ("GEN", 3),
            ("EXO", 2),
            ("1CH", 16),
        ]


def _candidate_shard(candidate_map: dict[str, CandidateItem], candidate_id: str) -> CandidateChapterShard:
    item = candidate_map[candidate_id]
    return CandidateChapterShard(
        book_code=item.source.book_code,
        book=item.source.book,
        book_he=item.source.book_he,
        chapter=item.source.chapter,
        mode="llm",
        items=[item],
        stats={"window_count": 1, "prefiltered_count": 0, "llm_window_count": 1, "kept_count": 1, "issue_count": 0},
    )


def test_rebuild_candidates_jsonl_orders_items_canonically(candidate_map, tmp_path) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shards = [
        _candidate_shard(candidate_map, "1-chronicles-16-15-15"),
        _candidate_shard(candidate_map, "exodus-02-13-13"),
        _candidate_shard(candidate_map, "genesis-03-13-13"),
    ]

    _rebuild_candidates_jsonl(candidates_path, shards)

    lines = [json.loads(line)["id"] for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines == [
        "genesis-03-13-13",
        "exodus-02-13-13",
        "1-chronicles-16-15-15",
    ]


def test_align_english_riddle_to_quote_recovers_exact_kjv_substring() -> None:
    quote = "And the king of Egypt called for the midwives, and said unto them, Why have ye done this thing, and have saved the men children alive?"
    aligned = _align_english_riddle_to_quote(quote, "why have you done this")

    assert aligned in {
        "Why have ye done this",
        "Why have ye done this thing",
    }
    assert aligned in quote


def test_align_english_riddle_to_quote_rejects_unrelated_text() -> None:
    quote = "And he said, When ye do the office of a midwife to the Hebrew women, and see them upon the stools; if it be a son, then ye shall kill him: but if it be a daughter, then she shall live."

    assert _align_english_riddle_to_quote(quote, "shall i go and call thee a nurse") == ""


def test_default_candidate_book_scope_uses_minimal_set_unless_overridden() -> None:
    assert _default_candidate_book_scope(book_filter=None, full_canon=False) == MINIMAL_CANDIDATE_BOOK_CODES
    assert _default_candidate_book_scope(book_filter="GEN", full_canon=False) is None
    assert _default_candidate_book_scope(book_filter=None, full_canon=True) is None


def test_assign_unique_candidate_ids_suffixes_same_verse_collisions(candidate_map) -> None:
    first = candidate_map["genesis-03-13-13"]
    second = replace(
        first,
        en=replace(first.en, riddle="The serpent beguiled me, and I did eat."),
        he=replace(first.he, riddle="הַנָּחָשׁ הִשִּׁיאַנִי וָאֹכֵל"),
    )

    assigned = _assign_unique_candidate_ids([first, second])

    assert [item.id for item in assigned] == ["genesis-03-13-13-1", "genesis-03-13-13-2"]


def test_build_candidates_command_defaults_to_minimal_book_scope(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr("data_proc.candidates_pipeline._build_llm_client", lambda model, seed: object())

    def fake_run_build_candidates(**kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr("data_proc.candidates_pipeline.run_build_candidates", fake_run_build_candidates)

    result = CliRunner().invoke(
        build_candidates_command,
        [
            "--candidates-out",
            str(tmp_path / "candidates.jsonl"),
            "--shard-dir",
            str(tmp_path / "candidate_shards"),
            "--issues-log",
            str(tmp_path / "issues.jsonl"),
            "--quiet-llm",
        ],
    )

    assert result.exit_code == 0
    assert captured["allowed_book_codes"] == MINIMAL_CANDIDATE_BOOK_CODES


def test_build_candidates_command_allows_full_canon_override(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr("data_proc.candidates_pipeline._build_llm_client", lambda model, seed: object())

    def fake_run_build_candidates(**kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr("data_proc.candidates_pipeline.run_build_candidates", fake_run_build_candidates)

    result = CliRunner().invoke(
        build_candidates_command,
        [
            "--candidates-out",
            str(tmp_path / "candidates.jsonl"),
            "--shard-dir",
            str(tmp_path / "candidate_shards"),
            "--issues-log",
            str(tmp_path / "issues.jsonl"),
            "--full-canon",
            "--quiet-llm",
        ],
    )

    assert result.exit_code == 0
    assert captured["allowed_book_codes"] is None


def test_run_build_candidates_clean_state_starts_from_genesis(candidate_map, tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidates_issues.jsonl"
    processed: list[tuple[str, int]] = []

    monkeypatch.setattr("data_proc.candidates_pipeline.TandemBible.load", lambda **_: _FakeTandem())

    def fake_build_chapter_candidates(tandem, *, llm, book_code: str, chapter: int):
        processed.append((book_code, chapter))
        candidate_id_map = {
            ("GEN", 3): "genesis-03-13-13",
            ("EXO", 2): "exodus-02-13-13",
            ("1CH", 16): "1-chronicles-16-15-15",
        }
        return _candidate_shard(candidate_map, candidate_id_map[(book_code, chapter)]), []

    monkeypatch.setattr("data_proc.candidates_pipeline._build_chapter_candidates", fake_build_chapter_candidates)

    shards, issues = run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
        limit=3,
        resume=True,
    )

    assert processed == [("GEN", 3), ("EXO", 2), ("1CH", 16)]
    assert [(shard.book_code, shard.chapter) for shard in shards] == processed
    assert not issues


def test_run_build_candidates_resumes_from_earliest_missing_chapter(candidate_map, tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidates_issues.jsonl"
    processed: list[tuple[str, int]] = []

    shard_dir.mkdir(parents=True, exist_ok=True)
    later_shard = _candidate_shard(candidate_map, "1-chronicles-16-15-15")
    (shard_dir / "1-chronicles-016.json").write_text(json.dumps(later_shard.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr("data_proc.candidates_pipeline.TandemBible.load", lambda **_: _FakeTandem())

    def fake_build_chapter_candidates(tandem, *, llm, book_code: str, chapter: int):
        processed.append((book_code, chapter))
        candidate_id_map = {
            ("GEN", 3): "genesis-03-13-13",
            ("EXO", 2): "exodus-02-13-13",
            ("1CH", 16): "1-chronicles-16-15-15",
        }
        return _candidate_shard(candidate_map, candidate_id_map[(book_code, chapter)]), []

    monkeypatch.setattr("data_proc.candidates_pipeline._build_chapter_candidates", fake_build_chapter_candidates)

    shards, issues = run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
        limit=2,
        resume=True,
    )

    assert processed == [("GEN", 3), ("EXO", 2)]
    assert [(shard.book_code, shard.chapter) for shard in shards] == processed
    assert not issues
    aggregate_ids = [json.loads(line)["id"] for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert aggregate_ids == [
        "genesis-03-13-13",
        "exodus-02-13-13",
        "1-chronicles-16-15-15",
    ]


def test_run_build_candidates_noops_when_all_target_chapters_exist(candidate_map, tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidates_issues.jsonl"

    shard_dir.mkdir(parents=True, exist_ok=True)
    for candidate_id in ("genesis-03-13-13", "exodus-02-13-13", "1-chronicles-16-15-15"):
        shard = _candidate_shard(candidate_map, candidate_id)
        path = _chapter_shard_path(shard_dir, book=shard.book, chapter=shard.chapter)
        path.write_text(json.dumps(shard.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr("data_proc.candidates_pipeline.TandemBible.load", lambda **_: _FakeTandem())

    def fake_build_chapter_candidates(*args, **kwargs):
        raise AssertionError("should not rebuild existing chapters when resume=True and all shards exist")

    monkeypatch.setattr("data_proc.candidates_pipeline._build_chapter_candidates", fake_build_chapter_candidates)

    shards, issues = run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
        resume=True,
    )

    assert shards == []
    assert issues == []
    aggregate_ids = [json.loads(line)["id"] for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert aggregate_ids == [
        "genesis-03-13-13",
        "exodus-02-13-13",
        "1-chronicles-16-15-15",
    ]


def test_chapter_candidate_windows_focuses_genesis_3_on_anchor_ranges() -> None:
    tandem = TandemBible.load(english_xml=DEFAULT_ENGLISH_XML, hebrew_zip=DEFAULT_HEBREW_ZIP)
    windows = _chapter_candidate_windows(tandem, book_code="GEN", chapter=3)

    ranges = {(window.start, window.end) for window in windows}
    assert len(windows) == 19
    assert (9, 9) in ranges
    assert (13, 13) in ranges
    assert (14, 15) in ranges
    assert (22, 23) in ranges
