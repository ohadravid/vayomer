from __future__ import annotations

from data_proc.schema import (
    BonusHint,
    CandidateSource,
    ChapterPayload,
    CharacterBank,
    CharacterBankEntry,
    ChoicePools,
    FinalLangText,
    FinalMeta,
    FinalQuoteItem,
    FinalSource,
    HintSourceRef,
    RefRange,
)


def test_candidate_schema_deserializes_representative_line(candidate_map) -> None:
    item = candidate_map["genesis-03-09-09"]

    assert item.source.book_code == "GEN"
    assert item.en.quote == "And the LORD God called unto Adam, and said unto him, Where art thou?"
    assert item.he.listener == "הָֽאָדָם"
    assert item.source.speaker_mention_verse == 9
    assert item.source.listener_mention_verse == 9

    serialized = item.to_dict()
    assert "options" not in serialized["en"]
    assert "options" not in serialized["he"]


def test_final_chapter_payload_serializes_exact_output_shape(candidate_map) -> None:
    candidate = candidate_map["genesis-03-09-09"]
    final_item = FinalQuoteItem(
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
            bonus="Adam",
            bonus_hint=BonusHint(
                quote="And Adam called his wife's name Eve; because she was the mother of all living.",
                source=HintSourceRef(book="Genesis", chapter=3, start=20, end=20),
            ),
        ),
        he=FinalLangText(
            quote=candidate.he.quote,
            riddle=candidate.he.riddle,
            speaker=candidate.he.speaker,
            listener=candidate.he.listener,
            book=candidate.he.book,
            options=ChoicePools.empty(),
            bonus="הָֽאָדָם",
            bonus_hint=BonusHint(
                quote="וַיִּקְרָא הָֽאָדָם שֵׁם אִשְׁתּוֹ חַוָּה כִּי הִוא הָיְתָה אֵם כָּל־חָי",
                source=HintSourceRef(book="בראשית", chapter=3, start=20, end=20),
            ),
        ),
        raw_quote_source=candidate.raw_quote_source,
        ref=RefRange(chapter=3, start=9, end=9),
        meta=FinalMeta(
            mode="llm",
            source="data-proc",
            template_item_id="",
            bonus_source="llm",
            bonus_hint_source="aligned-bible-search",
        ),
    )
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[final_item],
    )

    serialized = payload.to_dict()

    assert serialized["items"][0]["en"]["options"] == {"speaker": [], "listener": []}
    assert serialized["items"][0]["he"]["options"] == {"speaker": [], "listener": []}
    assert serialized["items"][0]["meta"]["bonus_hint_source"] == "aligned-bible-search"

    reparsed = ChapterPayload.from_dict(serialized)
    assert reparsed == payload


def test_candidate_source_round_trips_optional_mention_verses() -> None:
    payload = {
        "book_code": "EXO",
        "book": "Exodus",
        "book_he": "שמות",
        "chapter": 2,
        "quote_verse_start": 8,
        "quote_verse_end": 8,
        "speaker_mention_verse": 7,
        "listener_mention_verse": 7,
    }

    parsed = CandidateSource.from_dict(payload)

    assert parsed.speaker_mention_verse == 7
    assert parsed.listener_mention_verse == 7
    assert parsed.to_dict()["speaker_mention_verse"] == 7
    assert parsed.to_dict()["listener_mention_verse"] == 7


def test_final_lang_text_parses_legacy_empty_list_options() -> None:
    parsed = FinalLangText.from_dict(
        {
            "quote": "And God said, Let there be light.",
            "riddle": "Let there be light.",
            "speaker": "God",
            "listener": "creation",
            "book": "Genesis",
            "options": [],
            "bonus": "light",
            "bonus_hint": {
                "quote": "And God saw the light, that it was good.",
                "source": {"book": "Genesis", "chapter": 1, "start": 4, "end": 4},
            },
        }
    )

    assert parsed.options == ChoicePools.empty()


def test_character_bank_round_trip() -> None:
    bank = CharacterBank(
        taxonomy=["divine", "leader", "other"],
        items=[
            CharacterBankEntry(
                id="char-abc123",
                en="the LORD",
                he="יְהוָה",
                normalized_en_aliases=["lord"],
                normalized_he_aliases=["יהוה"],
                books=["GEN", "EXO"],
                observed_fields=["speaker"],
                count=12,
                category="divine",
            )
        ],
    )

    serialized = bank.to_dict()

    assert serialized["items"][0]["books"] == ["GEN", "EXO"]
    assert serialized["items"][0]["category"] == "divine"
    assert CharacterBank.from_dict(serialized) == bank
