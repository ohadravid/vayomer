from __future__ import annotations

import json
from pathlib import Path

from data_proc.candidates_pipeline import (
    CandidateChapterShard,
    _chapter_candidate_windows,
    _chapter_shard_path,
    _rebuild_candidates_jsonl,
    run_build_candidates,
)
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.schema import CandidateItem
from data_proc.utils.bible_tandem import TandemBible


class _FakeTandem:
    def iter_chapters(self, book_filter: str = ""):
        return [
            ("GEN", 3),
            ("EXO", 24),
            ("1CH", 10),
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
        _candidate_shard(candidate_map, "1-chronicles-10-03-05"),
        _candidate_shard(candidate_map, "exodus-24-06-08"),
        _candidate_shard(candidate_map, "genesis-03-13-13"),
    ]

    _rebuild_candidates_jsonl(candidates_path, shards)

    lines = [json.loads(line)["id"] for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines == [
        "genesis-03-13-13",
        "exodus-24-06-08",
        "1-chronicles-10-03-05",
    ]


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
            ("EXO", 24): "exodus-24-06-08",
            ("1CH", 10): "1-chronicles-10-03-05",
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

    assert processed == [("GEN", 3), ("EXO", 24), ("1CH", 10)]
    assert [(shard.book_code, shard.chapter) for shard in shards] == processed
    assert not issues


def test_run_build_candidates_resumes_from_earliest_missing_chapter(candidate_map, tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidates_issues.jsonl"
    processed: list[tuple[str, int]] = []

    shard_dir.mkdir(parents=True, exist_ok=True)
    later_shard = _candidate_shard(candidate_map, "1-chronicles-10-03-05")
    (shard_dir / "1-chronicles-010.json").write_text(json.dumps(later_shard.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr("data_proc.candidates_pipeline.TandemBible.load", lambda **_: _FakeTandem())

    def fake_build_chapter_candidates(tandem, *, llm, book_code: str, chapter: int):
        processed.append((book_code, chapter))
        candidate_id_map = {
            ("GEN", 3): "genesis-03-13-13",
            ("EXO", 24): "exodus-24-06-08",
            ("1CH", 10): "1-chronicles-10-03-05",
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

    assert processed == [("GEN", 3), ("EXO", 24)]
    assert [(shard.book_code, shard.chapter) for shard in shards] == processed
    assert not issues
    aggregate_ids = [json.loads(line)["id"] for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert aggregate_ids == [
        "genesis-03-13-13",
        "exodus-24-06-08",
        "1-chronicles-10-03-05",
    ]


def test_run_build_candidates_noops_when_all_target_chapters_exist(candidate_map, tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidates_issues.jsonl"

    shard_dir.mkdir(parents=True, exist_ok=True)
    for candidate_id in ("genesis-03-13-13", "exodus-24-06-08", "1-chronicles-10-03-05"):
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
        "exodus-24-06-08",
        "1-chronicles-10-03-05",
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
