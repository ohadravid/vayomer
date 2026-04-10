from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from data_proc.llm import OllamaJsonClient
from data_proc.options_pipeline import (
    CHARACTER_TAXONOMY,
    OptionsBuilder,
    _entry_role_kind,
    _hebrew_context_texts,
    _normalize_en_alias,
    _normalize_he_alias,
    _restore_bank_hebrew_surfaces_from_map,
    _restore_item_hebrew_roles_from_map,
    build_character_bank,
    build_options_eval_pack,
    read_character_bank,
    run_build_options,
)
from data_proc.schema import ChapterPayload, CharacterBank, CharacterBankEntry, write_json
from data_proc.utils.text_cleanup import hebrew_surface_map, strip_hebrew_marks

TEST_SEED = 32988
REPO_ROOT = Path(__file__).resolve().parents[3]
CHARACTER_BANK_PATH = REPO_ROOT / "data/processed/character_bank.json"


@pytest.fixture(scope="module")
def seeded_options_llm() -> OllamaJsonClient:
    return OllamaJsonClient(
        model="gemma4:26b",
        max_retries=2,
        fallback_model=None,
        request_options={"seed": TEST_SEED},
    )


@pytest.fixture(scope="module")
def curated_options_payloads(generated_payloads) -> list[ChapterPayload]:
    wanted = {
        ("GEN", 3),
        ("GEN", 4),
        ("GEN", 9),
        ("GEN", 16),
        ("GEN", 21),
        ("GEN", 24),
        ("GEN", 29),
    }
    return [payload for payload in generated_payloads if (payload.book_code, payload.chapter) in wanted]


@pytest.fixture(scope="module")
def curated_character_bank(curated_options_payloads, seeded_options_llm):
    return build_character_bank(curated_options_payloads, seeded_options_llm, batch_size=1)


@pytest.fixture(scope="module")
def curated_payloads_dir(tmp_path_factory, curated_options_payloads) -> Path:
    directory = tmp_path_factory.mktemp("generated-options-subset")
    for payload in curated_options_payloads:
        path = directory / f"{payload.book_code.lower()}-{payload.chapter:03d}.json"
        write_json(path, payload.to_dict())
    return directory


def _find_item(payloads: list[ChapterPayload], item_id: str):
    for payload in payloads:
        for item in payload.items:
            if item.id == item_id:
                return item
    raise KeyError(item_id)


def _bank_entry(entry_id: str, en: str, he: str, category: str, *, books: list[str], count: int, observed_fields: list[str]) -> CharacterBankEntry:
    return CharacterBankEntry(
        id=entry_id,
        en=en,
        he=he,
        normalized_en_aliases=[_normalize_en_alias(en)],
        normalized_he_aliases=[_normalize_he_alias(he)],
        books=books,
        observed_fields=observed_fields,
        count=count,
        category=category,
    )


def test_live_character_bank_classification_from_generated_payloads(curated_options_payloads, seeded_options_llm) -> None:
    base_item = _find_item(curated_options_payloads, "genesis-03-13-13")
    synthetic_payload = ChapterPayload(
        book_code="SYN",
        book="Synthetic",
        book_he="סינתטי",
        chapter=1,
        mode="llm",
        items=[
            replace(base_item, id="synthetic-lord-variant", en=replace(base_item.en, speaker="The LORD")),
            replace(base_item, id="synthetic-pronoun-variant", en=replace(base_item.en, speaker="I"), he=replace(base_item.he, speaker="אֲנִי")),
            replace(base_item, id="synthetic-mismatch-variant", en=replace(base_item.en, speaker="Abraham"), he=replace(base_item.he, speaker="אֱלִיעֶזֶר")),
        ],
    )
    bank = build_character_bank([*curated_options_payloads, synthetic_payload], seeded_options_llm, batch_size=1)

    assert bank.items
    assert {entry.category for entry in bank.items} <= set(CHARACTER_TAXONOMY)
    assert len({entry.id for entry in bank.items}) == len(bank.items)

    lord_entries = [
        entry
        for entry in bank.items
        if "lord" in entry.normalized_en_aliases and "יהוה" in entry.normalized_he_aliases
    ]
    assert len(lord_entries) == 1
    assert lord_entries[0].count >= 3
    assert lord_entries[0].category == "divine"
    assert not any("i" in entry.normalized_en_aliases for entry in bank.items)
    assert not any(entry.en == "Abraham" and entry.he == "אליעזר" for entry in bank.items)
    assert any(entry.en == "woman" and entry.category == "woman" for entry in bank.items)


def test_live_options_builder_picks_three_distractors_per_field(curated_options_payloads, curated_character_bank, seeded_options_llm) -> None:
    builder = OptionsBuilder(bank=curated_character_bank, llm=seeded_options_llm)
    sample_ids = [
        "genesis-03-09-09",
        "genesis-03-13-13",
        "genesis-16-08-10",
        "genesis-09-09-09",
        "genesis-09-12-12",
        "genesis-29-11-12",
    ]

    for item_id in sample_ids:
        item = _find_item(curated_options_payloads, item_id)
        updated, issues, debug = builder.apply_options(item)

        assert not issues, f"{item_id} produced issues: {issues}"
        for field in ("speaker", "listener"):
            other_field = "listener" if field == "speaker" else "speaker"
            en_options = getattr(updated.en.options, field)
            he_options = getattr(updated.he.options, field)
            assert len(en_options) == 3
            assert len(he_options) == 3
            assert len(set(en_options)) == 3
            assert len(set(he_options)) == 3
            assert getattr(updated.en, field) not in en_options
            assert getattr(updated.en, other_field) not in en_options
            assert getattr(updated.he, field) not in he_options
            assert getattr(updated.he, other_field) not in he_options
            bank_ids = debug[f"{field}_bank_ids"]
            bank_entries = debug[f"{field}_options"]
            assert len(bank_ids) == 3
            assert len(set(bank_ids)) == 3
            assert len(bank_entries) == 3
            assert (
                any(updated.source.book_code not in option["books"] for option in bank_entries)
                or len({option["category"] for option in bank_entries}) >= 2
            )

    lord_god_item = _find_item(curated_options_payloads, "genesis-03-13-13")
    updated_lord_god, issues_lord_god, debug_lord_god = builder.apply_options(lord_god_item)
    assert not issues_lord_god
    assert "LORD" not in updated_lord_god.en.options.speaker
    assert "God" not in updated_lord_god.en.options.speaker
    assert not any(option["category"] == "divine" and option["en"] in {"LORD", "God", "LORD God"} for option in debug_lord_god["speaker_options"])

    woman_item = _find_item(curated_options_payloads, "genesis-03-01-02")
    updated_woman, issues_woman, debug_woman = builder.apply_options(woman_item)
    assert not issues_woman
    assert "LORD" not in updated_woman.en.options.listener
    assert "God" not in updated_woman.en.options.listener
    assert not any(option["category"] == "divine" for option in debug_woman["listener_options"])

    living_creatures_item = _find_item(curated_options_payloads, "genesis-09-12-12")
    updated_living_creatures, issues_living_creatures, debug_living_creatures = builder.apply_options(living_creatures_item)
    assert not issues_living_creatures
    assert len(updated_living_creatures.en.options.listener) == 3
    assert not any(option["category"] == "divine" for option in debug_living_creatures["listener_options"])


def test_live_options_builder_prefers_diverse_speaker_categories_for_genesis_4(curated_options_payloads, seeded_options_llm) -> None:
    item = _find_item(curated_options_payloads, "genesis-04-06-06")
    bank = CharacterBank(
        taxonomy=list(CHARACTER_TAXONOMY),
        items=[
            _bank_entry("char-lord", "the LORD", "יְהוָה", "divine", books=["GEN"], count=30, observed_fields=["speaker"]),
            _bank_entry("char-cain", "Cain", "קַיִן", "family", books=["GEN"], count=5, observed_fields=["listener"]),
            _bank_entry("char-moses", "Moses", "מֹשֶׁה", "leader", books=["EXO"], count=20, observed_fields=["speaker"]),
            _bank_entry("char-samuel", "Samuel", "שְׁמוּאֵל", "prophet", books=["1SA"], count=10, observed_fields=["speaker"]),
            _bank_entry("char-saul", "Saul", "שָׁאוּל", "king", books=["1SA"], count=9, observed_fields=["speaker"]),
            _bank_entry("char-angel", "angel of the LORD", "מַלְאַךְ יְהוָה", "divine", books=["GEN"], count=7, observed_fields=["speaker"]),
            _bank_entry("char-satan", "Satan", "הַשָּׂטָן", "enemy_foreigner", books=["JOB"], count=9, observed_fields=["speaker"]),
        ],
    )

    builder = OptionsBuilder(bank=bank, llm=seeded_options_llm)
    selection = builder.select_field_options(item, "speaker")
    selected_entries = [builder.entries_by_id[entry_id] for entry_id in selection.ids]

    assert len(selection.ids) == 3
    assert len({entry.category for entry in selected_entries}) >= 2
    assert sum(1 for entry in selected_entries if entry.category == "divine") <= 1
    assert any(entry.category != "divine" for entry in selected_entries)


def test_live_options_builder_fills_listener_options_when_true_listener_is_not_in_bank(generated_payloads, seeded_options_llm) -> None:
    item = _find_item(generated_payloads, "job-13-01-03")
    bank = CharacterBank(
        taxonomy=list(CHARACTER_TAXONOMY),
        items=[
            _bank_entry("char-job", "Job", "אִיּוֹב", "family", books=["JOB"], count=20, observed_fields=["speaker"]),
            _bank_entry("char-people", "people", "הָעָם", "people_group", books=["EXO", "JOB"], count=40, observed_fields=["listener"]),
            _bank_entry("char-israel", "children of Israel", "בְּנֵי יִשְׂרָאֵל", "people_group", books=["EXO"], count=25, observed_fields=["listener"]),
            _bank_entry("char-chaldeans", "Chaldeans", "כַּשְׂדִּים", "enemy_foreigner", books=["JOB"], count=12, observed_fields=["listener"]),
            _bank_entry("char-brethren", "brethren", "אַחִים", "family", books=["GEN"], count=12, observed_fields=["listener"]),
            _bank_entry("char-servants", "servants", "עֲבָדִים", "companion_sidekick", books=["1SA"], count=8, observed_fields=["listener"]),
        ],
    )

    builder = OptionsBuilder(bank=bank, llm=seeded_options_llm)
    updated, issues, debug = builder.apply_options(item)

    assert not issues
    assert len(updated.en.options.listener) == 3
    assert len(updated.he.options.listener) == 3
    assert len(set(updated.en.options.listener)) == 3
    assert len(set(updated.he.options.listener)) == 3
    assert debug["listener_bank_ids"]


def test_live_run_build_options_writes_real_chapter_file(tmp_path, curated_options_payloads, curated_character_bank, seeded_options_llm) -> None:
    in_dir = tmp_path / "generated"
    out_dir = tmp_path / "generated_options"
    issues_log = tmp_path / "issues.jsonl"
    in_dir.mkdir(parents=True, exist_ok=True)

    source_payload = next(payload for payload in curated_options_payloads if payload.book_code == "GEN" and payload.chapter == 3)
    filtered_payload = ChapterPayload(
        book_code=source_payload.book_code,
        book=source_payload.book,
        book_he=source_payload.book_he,
        chapter=source_payload.chapter,
        mode=source_payload.mode,
        items=[item for item in source_payload.items if item.id in {"genesis-03-01-02", "genesis-03-09-09", "genesis-03-13-13"}],
    )
    write_json(in_dir / "genesis-003.json", filtered_payload.to_dict())

    payloads, issues = run_build_options(
        in_dir=in_dir,
        bank=curated_character_bank,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=seeded_options_llm,
        resume=False,
    )

    assert len(payloads) == 1
    assert (out_dir / "genesis-003.json").exists()
    written = json.loads((out_dir / "genesis-003.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in written["items"]] == ["genesis-03-01-02", "genesis-03-09-09", "genesis-03-13-13"]
    for item in written["items"]:
        assert len(item["en"]["options"]["speaker"]) == 3
        assert len(item["en"]["options"]["listener"]) == 3
        assert len(item["he"]["options"]["speaker"]) == 3
        assert len(item["he"]["options"]["listener"]) == 3
    assert not issues


def test_live_build_options_eval_pack_writes_reviewable_artifacts(curated_payloads_dir, curated_character_bank, seeded_options_llm, tmp_path) -> None:
    out_dir = tmp_path / "options_eval"

    payload = build_options_eval_pack(
        in_dir=curated_payloads_dir,
        bank=curated_character_bank,
        out_dir=out_dir,
        llm=seeded_options_llm,
        sample_size=6,
        seed=TEST_SEED,
    )

    assert sorted(path.name for path in out_dir.iterdir()) == ["character_bank.json", "eval_items.json", "review.md"]
    assert payload["seed"] == TEST_SEED
    assert payload["sample_size"] == 6

    written = json.loads((out_dir / "eval_items.json").read_text(encoding="utf-8"))
    review = (out_dir / "review.md").read_text(encoding="utf-8")
    assert written["seed"] == TEST_SEED
    assert len(written["items"]) == 6
    for item in written["items"]:
        assert set(item["en"]["options"]) == {"speaker", "listener"}
        assert set(item["he"]["options"]) == {"speaker", "listener"}
        assert "bank_context" in item
        assert f"## {item['id']}" in review


def test_live_run_build_options_restores_pointed_hebrew_roles_and_options(generated_payloads, seeded_options_llm, tmp_path) -> None:
    in_dir = tmp_path / "generated"
    out_dir = tmp_path / "generated_options"
    issues_log = tmp_path / "issues.jsonl"
    in_dir.mkdir(parents=True, exist_ok=True)

    wanted = {
        ("GEN", 16): {"genesis-16-02-02"},
        ("GEN", 24): {"genesis-24-05-05"},
        ("GEN", 39): {"genesis-39-06-07"},
    }
    for payload in generated_payloads:
        key = (payload.book_code, payload.chapter)
        if key not in wanted:
            continue
        filtered = ChapterPayload(
            book_code=payload.book_code,
            book=payload.book,
            book_he=payload.book_he,
            chapter=payload.chapter,
            mode=payload.mode,
            items=[item for item in payload.items if item.id in wanted[key]],
        )
        write_json(in_dir / f"{payload.book_code.lower()}-{payload.chapter:03d}.json", filtered.to_dict())

    payloads, issues = run_build_options(
        in_dir=in_dir,
        bank=read_character_bank(CHARACTER_BANK_PATH),
        out_dir=out_dir,
        issues_log=issues_log,
        llm=seeded_options_llm,
        resume=False,
    )

    assert len(payloads) == 3
    assert not issues

    genesis16 = json.loads((out_dir / "genesis-016.json").read_text(encoding="utf-8"))["items"][0]
    assert genesis16["he"]["speaker"] == "שָׂרַי"
    assert genesis16["he"]["listener"] == "אַבְרָם"

    genesis24 = json.loads((out_dir / "genesis-024.json").read_text(encoding="utf-8"))["items"][0]
    assert len(genesis24["en"]["options"]["speaker"]) == 3
    assert len(genesis24["he"]["options"]["speaker"]) == 3

    genesis39 = json.loads((out_dir / "genesis-039.json").read_text(encoding="utf-8"))["items"][0]
    assert genesis39["he"]["speaker"] == "אֵֽשֶׁת־אֲדֹנָיו"


def test_live_options_builder_restores_pointed_hebrew_options_from_full_context(generated_payloads, seeded_options_llm) -> None:
    item = _find_item(generated_payloads, "genesis-16-02-02")
    hebrew_mapping = hebrew_surface_map(_hebrew_context_texts(generated_payloads))
    bank = _restore_bank_hebrew_surfaces_from_map(read_character_bank(CHARACTER_BANK_PATH), hebrew_mapping)
    restored_item = _restore_item_hebrew_roles_from_map(item, hebrew_mapping)

    builder = OptionsBuilder(bank=bank, llm=seeded_options_llm)
    updated, issues, _ = builder.apply_options(restored_item)

    assert not issues
    assert updated.he.speaker == "שָׂרַי"
    assert updated.he.listener == "אַבְרָם"
    assert all(strip_hebrew_marks(option) != option for option in updated.he.options.speaker)
    assert all(strip_hebrew_marks(option) != option for option in updated.he.options.listener)


def test_live_options_builder_prefers_group_listener_distractors_for_house_of_pharaoh(generated_payloads, seeded_options_llm) -> None:
    item = _find_item(generated_payloads, "genesis-50-04-04")
    hebrew_mapping = hebrew_surface_map(_hebrew_context_texts(generated_payloads))
    bank = _restore_bank_hebrew_surfaces_from_map(read_character_bank(CHARACTER_BANK_PATH), hebrew_mapping)
    restored_item = _restore_item_hebrew_roles_from_map(item, hebrew_mapping)

    builder = OptionsBuilder(bank=bank, llm=seeded_options_llm)
    updated, issues, debug = builder.apply_options(restored_item)

    assert not issues
    assert len(updated.en.options.listener) == 3
    assert len(updated.he.options.listener) == 3
    selected_entries = [builder.entries_by_id[entry_id] for entry_id in debug["listener_bank_ids"]]
    assert all(_entry_role_kind(entry) == "group" for entry in selected_entries)
