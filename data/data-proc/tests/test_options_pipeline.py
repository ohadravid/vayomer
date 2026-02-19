from __future__ import annotations

from pathlib import Path

import pytest

from data_proc.options_pipeline import CHARACTER_TAXONOMY, FieldCandidatePools, OptionsBuilder, run_build_options
from data_proc.pipeline import chapter_output_path
from data_proc.schema import ChapterPayload, CharacterBank, CharacterBankEntry, iter_chapter_payloads, write_json


def _payload_by_key(payloads: list[ChapterPayload], book_code: str, chapter: int) -> ChapterPayload:
    for payload in payloads:
        if payload.book_code == book_code and payload.chapter == chapter:
            return payload
    raise KeyError((book_code, chapter))


def _write_payloads(directory: Path, payloads: list[ChapterPayload]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        write_json(chapter_output_path(directory, payload), payload.to_dict())


def _empty_bank() -> CharacterBank:
    return CharacterBank(taxonomy=list(CHARACTER_TAXONOMY), items=[])


def _bank_entry(entry_id: str, en: str, he: str, category: str, *, books: list[str]) -> CharacterBankEntry:
    return CharacterBankEntry(
        id=entry_id,
        en=en,
        he=he,
        normalized_en_aliases=[en.casefold()],
        normalized_he_aliases=[he],
        books=books,
        observed_fields=["listener"],
        count=5,
        category=category,
    )


def test_iter_chapter_payloads_returns_canonical_order_for_real_generated_dir(generated_payloads) -> None:
    assert [(payload.book_code, payload.chapter) for payload in generated_payloads[:3]] == [
        ("GEN", 3),
        ("GEN", 4),
        ("GEN", 6),
    ]


def test_run_build_options_clean_state_starts_from_genesis(generated_payloads, tmp_path, monkeypatch) -> None:
    selected_payloads = [
        _payload_by_key(generated_payloads, "GEN", 3),
        _payload_by_key(generated_payloads, "EXO", 24),
        _payload_by_key(generated_payloads, "1CH", 10),
    ]
    in_dir = tmp_path / "generated"
    out_dir = tmp_path / "generated_options"
    issues_log = tmp_path / "generated_options_issues.jsonl"

    _write_payloads(in_dir, selected_payloads)
    monkeypatch.setattr("data_proc.options_pipeline.OptionsBuilder.apply_options", lambda self, item: (item, [], {}))

    payloads, dropped = run_build_options(
        in_dir=in_dir,
        bank=_empty_bank(),
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        limit=3,
        resume=True,
    )

    assert [(payload.book_code, payload.chapter) for payload in payloads] == [
        ("GEN", 3),
        ("EXO", 24),
        ("1CH", 10),
    ]
    assert not dropped


def test_run_build_options_resumes_from_earliest_missing_chapter(generated_payloads, tmp_path, monkeypatch) -> None:
    genesis_payload = _payload_by_key(generated_payloads, "GEN", 3)
    exodus_payload = _payload_by_key(generated_payloads, "EXO", 24)
    chronicles_payload = _payload_by_key(generated_payloads, "1CH", 10)
    in_dir = tmp_path / "generated"
    out_dir = tmp_path / "generated_options"
    issues_log = tmp_path / "generated_options_issues.jsonl"

    _write_payloads(in_dir, [genesis_payload, exodus_payload, chronicles_payload])
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(chapter_output_path(out_dir, chronicles_payload), chronicles_payload.to_dict())
    monkeypatch.setattr("data_proc.options_pipeline.OptionsBuilder.apply_options", lambda self, item: (item, [], {}))

    payloads, dropped = run_build_options(
        in_dir=in_dir,
        bank=_empty_bank(),
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        limit=2,
        resume=True,
    )

    assert [(payload.book_code, payload.chapter) for payload in payloads] == [
        ("GEN", 3),
        ("EXO", 24),
    ]
    assert not dropped
    assert chapter_output_path(out_dir, genesis_payload).exists()
    assert chapter_output_path(out_dir, exodus_payload).exists()
    assert not chapter_output_path(out_dir, chronicles_payload).exists()


def test_run_build_options_on_complete_dir_rebuilds_last_canonical_chapter(generated_payloads, tmp_path, monkeypatch) -> None:
    selected_payloads = [
        _payload_by_key(generated_payloads, "GEN", 3),
        _payload_by_key(generated_payloads, "EXO", 24),
        _payload_by_key(generated_payloads, "1CH", 10),
    ]
    in_dir = tmp_path / "generated"
    out_dir = tmp_path / "generated_options"
    issues_log = tmp_path / "generated_options_issues.jsonl"

    _write_payloads(in_dir, selected_payloads)
    _write_payloads(out_dir, selected_payloads)
    monkeypatch.setattr("data_proc.options_pipeline.OptionsBuilder.apply_options", lambda self, item: (item, [], {}))

    payloads, dropped = run_build_options(
        in_dir=in_dir,
        bank=_empty_bank(),
        out_dir=out_dir,
        issues_log=issues_log,
        llm=object(),
        limit=1,
        resume=True,
    )

    assert [(payload.book_code, payload.chapter) for payload in payloads] == [("1CH", 10)]
    assert not dropped


def test_iter_chapter_payloads_sorts_canonical_order_even_when_filenames_are_alphabetical(tmp_path, generated_payloads) -> None:
    payloads = [
        _payload_by_key(generated_payloads, "1CH", 10),
        _payload_by_key(generated_payloads, "EXO", 24),
        _payload_by_key(generated_payloads, "GEN", 3),
    ]
    in_dir = tmp_path / "generated"
    in_dir.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        write_json(chapter_output_path(in_dir, payload), payload.to_dict())

    ordered = iter_chapter_payloads(in_dir)

    assert [(payload.book_code, payload.chapter) for payload in ordered] == [
        ("GEN", 3),
        ("EXO", 24),
        ("1CH", 10),
    ]


def test_parse_field_selection_rejects_homogeneous_choices_when_pool_is_more_diverse(generated_payloads) -> None:
    payload = _payload_by_key(generated_payloads, "GEN", 9)
    item = next(item for item in payload.items if item.id == "genesis-09-09-09")
    bank = CharacterBank(
        taxonomy=list(CHARACTER_TAXONOMY),
        items=[
            _bank_entry("char-adam", "Adam", "אָדָם", "family", books=["GEN"]),
            _bank_entry("char-abraham", "Abraham", "אַבְרָהָם", "family", books=["GEN"]),
            _bank_entry("char-jacob", "Jacob", "יַעֲקֹב", "family", books=["GEN"]),
            _bank_entry("char-people", "people", "הָעָם", "people_group", books=["GEN"]),
        ],
    )
    builder = OptionsBuilder(bank=bank, llm=object())
    pools = FieldCandidatePools(
        true_entry=None,
        candidate_pool=bank.items,
        preferred_categories=["family", "people_group"],
        role_kind="group",
    )

    with pytest.raises(ValueError, match="lacks available diversity"):
        builder._parse_field_selection({"ids": ["char-adam", "char-abraham", "char-jacob"]}, item, pools)
