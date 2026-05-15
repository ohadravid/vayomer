from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from data_proc.pipeline import CandidateDropError, _validate_required_text, run_pipeline
from data_proc.schema import (
    BonusHint,
    CandidateItem,
    ChoicePools,
    DropRecord,
    FinalLangText,
    FinalMeta,
    FinalQuoteItem,
    FinalSource,
    HintSourceRef,
    RawQuoteSource,
    RefRange,
)


def _write_candidates(path: Path, items: list[CandidateItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")


def _final_item_from_candidate(candidate: CandidateItem, *, en_bonus: str = "called", he_bonus: str = "וַיִּקְרָא") -> FinalQuoteItem:
    return FinalQuoteItem(
        id=candidate.id,
        source=FinalSource(
            method="llm",
            book_code=candidate.source.book_code,
            book=candidate.source.book,
            book_he=candidate.source.book_he,
            chapter=candidate.source.chapter,
            quote_verse_start=candidate.source.quote_verse_start,
            quote_verse_end=candidate.source.quote_verse_end,
        ),
        en=FinalLangText(
            quote=candidate.en.quote,
            riddle=candidate.en.riddle,
            speaker=candidate.en.speaker,
            listener=candidate.en.listener,
            book=candidate.en.book,
            options=ChoicePools.empty(),
            bonus=en_bonus,
            bonus_hint=BonusHint(
                quote="And to Seth, to him also there was born a son; and he called his name Enos.",
                source=HintSourceRef(book="Genesis", chapter=4, start=26, end=26),
            ),
        ),
        he=FinalLangText(
            quote=candidate.he.quote,
            riddle=candidate.he.riddle,
            speaker=candidate.he.speaker,
            listener=candidate.he.listener,
            book=candidate.he.book,
            options=ChoicePools.empty(),
            bonus=he_bonus,
            bonus_hint=BonusHint(
                quote="וּלְשֵׁת גַּם־הוּא יֻלַּד־בֵּן וַיִּקְרָא אֶת־שְׁמוֹ אֱנוֹשׁ",
                source=HintSourceRef(book="בראשית", chapter=4, start=26, end=26),
            ),
        ),
        raw_quote_source=candidate.raw_quote_source,
        ref=RefRange(
            chapter=candidate.ref.chapter,
            start=candidate.ref.start,
            end=candidate.ref.end,
        ),
        meta=FinalMeta(
            mode="llm",
            source="data-proc",
            template_item_id="",
            bonus_source="llm",
            bonus_hint_source="aligned-bible-search",
        ),
    )


class _DummyCorpus:
    def __init__(self, *args, **kwargs) -> None:
        pass


def test_validate_required_text_allows_quote_and_mention_raw_source_union(candidate_map) -> None:
    quote_candidate = candidate_map["genesis-03-13-13"]
    mention_candidate = candidate_map["genesis-03-09-09"]
    candidate = replace(
        quote_candidate,
        source=replace(quote_candidate.source, speaker_mention_verse=9),
        raw_quote_source=RawQuoteSource(
            en={
                "9": mention_candidate.raw_quote_source.en["9"],
                "13": quote_candidate.raw_quote_source.en["13"],
            },
            he={
                "9": mention_candidate.raw_quote_source.he["9"],
                "13": quote_candidate.raw_quote_source.he["13"],
            },
        ),
    )

    _validate_required_text(candidate)


def test_run_pipeline_writes_files_and_issue_log_with_real_artifacts(candidate_map, tmp_path, monkeypatch) -> None:
    first = candidate_map["genesis-03-13-13"]
    second = candidate_map["genesis-01-11-11"]
    third = candidate_map["genesis-03-09-09"]
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    _write_candidates(candidates_path, [first, second, third])
    monkeypatch.setattr("data_proc.pipeline.BibleCorpus", _DummyCorpus)

    results = iter(
        [
            _final_item_from_candidate(first, en_bonus="serpent", he_bonus="הַנָּחָשׁ"),
            CandidateDropError(
                DropRecord(
                    candidate_id=second.id,
                    book_code=second.source.book_code,
                    chapter=second.source.chapter,
                    start=second.source.quote_verse_start,
                    end=second.source.quote_verse_end,
                    stage="semantic",
                    reason="english_validation_failed",
                    detail="creation is not a concrete addressed listener",
                )
            ),
            _final_item_from_candidate(third),
        ]
    )

    def scripted_process(self, candidate: CandidateItem):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("data_proc.pipeline.CandidatePipeline.process_candidate", scripted_process)

    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
        resume=False,
    )

    assert len(payloads) == 1
    assert len(payloads[0].items) == 2
    assert (out_dir / "genesis-003.json").exists()
    written = json.loads((out_dir / "genesis-003.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in written["items"]] == ["genesis-03-09-09", "genesis-03-13-13"]
    assert written["items"][0]["en"]["options"] == {"speaker": [], "listener": []}
    assert dropped[0].candidate_id == second.id
    assert second.id in issues_log.read_text(encoding="utf-8")


def test_run_pipeline_dedupes_overlapping_chapter_riddle_turns(candidate_map, tmp_path, monkeypatch) -> None:
    first = candidate_map["exodus-32-02-02"]
    second = replace(
        first,
        id="synthetic-exodus-32-duplicate",
        source=replace(first.source, quote_verse_start=2, quote_verse_end=2),
        ref=RefRange(chapter=32, start=2, end=2),
    )
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    _write_candidates(candidates_path, [first, second])
    monkeypatch.setattr("data_proc.pipeline.BibleCorpus", _DummyCorpus)

    def corrected_item(candidate: CandidateItem) -> FinalQuoteItem:
        item = _final_item_from_candidate(candidate, en_bonus="covenant", he_bonus="בְּרִית")
        return replace(
            item,
            en=replace(item.en, speaker="the people", listener="Moses"),
            he=replace(item.he, speaker="הָעָם", listener="מֹשֶׁה"),
        )

    results = iter([corrected_item(first), corrected_item(second)])

    def scripted_process(self, candidate: CandidateItem):
        return next(results)

    monkeypatch.setattr("data_proc.pipeline.CandidatePipeline.process_candidate", scripted_process)

    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
        resume=False,
    )

    assert len(payloads) == 1
    assert [item.id for item in payloads[0].items] == [first.id]
    assert payloads[0].items[0].en.speaker == "the people"
    assert dropped[0].candidate_id == second.id
    assert dropped[0].reason == "duplicate_riddle_turn"
    written = json.loads((out_dir / "exodus-032.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in written["items"]] == [first.id]


def test_run_pipeline_flushes_kept_chapter_file_before_later_interrupt(candidate_map, tmp_path, monkeypatch) -> None:
    first = candidate_map["genesis-03-13-13"]
    second = candidate_map["genesis-04-06-06"]
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    _write_candidates(candidates_path, [first, second])
    monkeypatch.setattr("data_proc.pipeline.BibleCorpus", _DummyCorpus)

    calls = iter([
        _final_item_from_candidate(first, en_bonus="serpent", he_bonus="הַנָּחָשׁ"),
        KeyboardInterrupt("stop after first keep"),
    ])

    def scripted_process(self, candidate: CandidateItem):
        result = next(calls)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr("data_proc.pipeline.CandidatePipeline.process_candidate", scripted_process)

    with pytest.raises(KeyboardInterrupt):
        run_pipeline(
            candidates_path=candidates_path,
            out_dir=out_dir,
            issues_log=issues_log,
            llm=object(),
            english_xml=Path("ignored.xml"),
            hebrew_zip=Path("ignored.zip"),
        )

    written_path = out_dir / "genesis-003.json"
    assert written_path.exists()
    written = json.loads(written_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in written["items"]] == ["genesis-03-13-13"]


def test_run_pipeline_resumes_from_earliest_incomplete_chapter(candidate_map, tmp_path, monkeypatch) -> None:
    first = candidate_map["genesis-01-11-11"]
    second = candidate_map["genesis-03-13-13"]
    third = candidate_map["genesis-04-06-06"]
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    _write_candidates(candidates_path, [first, second, third])
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_payload = {
        "book_code": "GEN",
        "book": "Genesis",
        "book_he": "בראשית",
        "chapter": 3,
        "mode": "llm",
        "items": [],
    }
    (out_dir / "genesis-003.json").write_text(json.dumps(existing_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    issues_log.write_text(
        json.dumps(
            {
                "candidate_id": second.id,
                "book_code": "GEN",
                "chapter": 3,
                "start": 1,
                "end": 1,
                "stage": "semantic",
                "reason": "old",
                "detail": "old drop",
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "candidate_id": first.id,
                "book_code": "GEN",
                "chapter": 1,
                "start": 1,
                "end": 1,
                "stage": "semantic",
                "reason": "old",
                "detail": "old drop",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("data_proc.pipeline.BibleCorpus", _DummyCorpus)

    processed_ids: list[str] = []

    def scripted_process(self, candidate: CandidateItem):
        processed_ids.append(candidate.id)
        if candidate.id == second.id:
            return _final_item_from_candidate(second, en_bonus="serpent", he_bonus="הַנָּחָשׁ")
        return _final_item_from_candidate(third, en_bonus="wroth", he_bonus="חָרָה")

    monkeypatch.setattr("data_proc.pipeline.CandidatePipeline.process_candidate", scripted_process)

    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
    )

    assert processed_ids == ["genesis-04-06-06"]
    assert [payload.chapter for payload in payloads] == [4]
    assert first.id in issues_log.read_text(encoding="utf-8")
    assert second.id in issues_log.read_text(encoding="utf-8")
    assert not dropped


def test_run_pipeline_resumes_from_missing_earlier_chapter_hole(candidate_map, tmp_path, monkeypatch) -> None:
    first = candidate_map["genesis-01-11-11"]
    second = candidate_map["genesis-03-13-13"]
    third = candidate_map["genesis-04-06-06"]
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes"
    issues_log = tmp_path / "issues.jsonl"

    _write_candidates(candidates_path, [first, second, third])
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_payload = {
        "book_code": "GEN",
        "book": "Genesis",
        "book_he": "בראשית",
        "chapter": 4,
        "mode": "llm",
        "items": [_final_item_from_candidate(third).to_dict()],
    }
    (out_dir / "genesis-004.json").write_text(json.dumps(existing_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    issues_log.write_text(
        json.dumps(
            {
                "candidate_id": first.id,
                "book_code": "GEN",
                "chapter": 1,
                "start": 1,
                "end": 1,
                "stage": "semantic",
                "reason": "old",
                "detail": "completed chapter 1 previously",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("data_proc.pipeline.BibleCorpus", _DummyCorpus)

    processed_ids: list[str] = []

    def scripted_process(self, candidate: CandidateItem):
        processed_ids.append(candidate.id)
        if candidate.id == second.id:
            return _final_item_from_candidate(second, en_bonus="serpent", he_bonus="הַנָּחָשׁ")
        return _final_item_from_candidate(third, en_bonus="wroth", he_bonus="חָרָה")

    monkeypatch.setattr("data_proc.pipeline.CandidatePipeline.process_candidate", scripted_process)

    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        english_xml=Path("ignored.xml"),
        hebrew_zip=Path("ignored.zip"),
    )

    assert processed_ids == [second.id, third.id]
    assert [payload.chapter for payload in payloads] == [3, 4]
    assert not dropped
