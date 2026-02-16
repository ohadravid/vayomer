from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_processing import postprocess_hard_options


def _candidate(
    *,
    label: str,
    quote: str,
    lang: str,
    item_id: str,
    book: str = "Exodus",
    book_code: str = "EXO",
    chapter: int = 1,
) -> postprocess_hard_options.Candidate:
    return postprocess_hard_options.Candidate(
        label=label,
        label_norm=postprocess_hard_options._normalize_label(label, lang),
        quote=quote,
        riddle="sample riddle",
        item_id=item_id,
        book_code=book_code,
        book=book,
        chapter=chapter,
        verse_start=1,
        verse_end=1,
        label_tokens=tuple(postprocess_hard_options.text_cleanup.tokenize_for_match(label, lang)),
        quote_tokens=tuple(postprocess_hard_options.text_cleanup.tokenize_for_match(quote, lang)),
    )


def _aligned(
    *,
    item_id: str,
    en_label: str,
    he_label: str,
    en_quote: str,
    he_quote: str,
    book: str = "Exodus",
    book_code: str = "EXO",
    chapter: int = 1,
) -> postprocess_hard_options.AlignedCandidate:
    return postprocess_hard_options.AlignedCandidate(
        en=_candidate(
            label=en_label,
            quote=en_quote,
            lang="en",
            item_id=item_id,
            book=book,
            book_code=book_code,
            chapter=chapter,
        ),
        he=_candidate(
            label=he_label,
            quote=he_quote,
            lang="he",
            item_id=item_id,
            book=book,
            book_code=book_code,
            chapter=chapter,
        ),
    )


def test_normalize_label_collapses_divine_aliases() -> None:
    assert postprocess_hard_options._normalize_label("the LORD", "en") == postprocess_hard_options._normalize_label(
        "God", "en"
    )
    assert postprocess_hard_options._normalize_label("יְהוָה", "he") == postprocess_hard_options._normalize_label(
        "אֱלֹהִים", "he"
    )


def test_is_viable_entity_label_allows_semi_names() -> None:
    assert postprocess_hard_options._is_viable_entity_label("the people", "en", strict=True) is True
    assert postprocess_hard_options._is_viable_entity_label("children of Israel", "en", strict=True) is True
    assert postprocess_hard_options._is_viable_entity_label("his brethren", "en", strict=True) is True
    assert postprocess_hard_options._is_viable_entity_label("Moses' father in law", "en", strict=True) is True


def test_python_validate_solution_rejects_clause_like_speaker() -> None:
    item = {
        "id": "exodus-01-15-16",
        "en": {
            "quote": "And the king of Egypt spake to the Hebrew midwives.",
            "riddle": "to the Hebrew midwives",
            "speaker": "the king of Egypt",
            "listener": "the Hebrew midwives",
        },
        "he": {
            "quote": "וַיֹּאמֶר מֶלֶך מִצְרַיִם לַֽמְיַלְּדֹת הָֽעִבְרִיֹּת",
            "riddle": "לַֽמְיַלְּדֹת הָֽעִבְרִיֹּת",
            "speaker": "וַיֹּאמֶר מֶלֶך מִצְרַיִם לַֽמְיַלְּדֹת הָֽעִבְרִיֹּת",
            "listener": "לַֽמְיַלְּדֹת הָֽעִבְרִיֹּת",
        },
    }

    ok, reason = postprocess_hard_options._python_validate_solution(item)

    assert ok is False
    assert reason == "he_speaker_not_entity"


def test_select_options_for_field_uses_llm_and_fallback(monkeypatch) -> None:
    calls: List[Tuple[str, Dict]] = []

    def fake_call_llm_json(model: str, payload: Dict, max_attempts: int = 3):
        calls.append((model, payload))
        instructions = payload.get("instructions", [])
        first_line = instructions[0] if isinstance(instructions, list) and instructions else ""
        if "selecting multiple-choice distractor options" in first_line:
            return {"regular_add": [0], "hard_add": [1]}, {
                "calls": 1,
                "prompt_tokens": 10,
                "response_tokens": 4,
                "estimated": False,
            }
        return {"drop_regular": [], "drop_hard": []}, {
            "calls": 1,
            "prompt_tokens": 8,
            "response_tokens": 3,
            "estimated": False,
        }

    monkeypatch.setattr(postprocess_hard_options, "_call_llm_json", fake_call_llm_json)

    candidates = [
        _aligned(
            item_id="item-jacob",
            en_label="Jacob",
            he_label="יעקב",
            en_quote="And Jacob said unto Joseph.",
            he_quote="ויאמר יעקב אל יוסף",
        ),
        _aligned(
            item_id="item-joseph",
            en_label="Joseph",
            he_label="יוסף",
            en_quote="And Joseph said unto Jacob.",
            he_quote="ויאמר יוסף אל יעקב",
        ),
        _aligned(
            item_id="item-isaac",
            en_label="Isaac",
            he_label="יצחק",
            en_quote="And Isaac said unto Abraham.",
            he_quote="ויאמר יצחק אל אברהם",
        ),
        _aligned(
            item_id="item-abraham",
            en_label="Abraham",
            he_label="אברהם",
            en_quote="And Abraham said unto Sarah.",
            he_quote="ויאמר אברהם אל שרה",
        ),
        _aligned(
            item_id="item-moses",
            en_label="Moses",
            he_label="משה",
            en_quote="And Moses said unto Pharaoh.",
            he_quote="ויאמר משה אל פרעה",
        ),
        _aligned(
            item_id="item-god",
            en_label="God",
            he_label="אֱלֹהִים",
            en_quote="And God said unto Moses.",
            he_quote="ויאמר אֱלֹהִים אל משה",
        ),
        _aligned(
            item_id="item-lord",
            en_label="the LORD",
            he_label="יְהוָה",
            en_quote="And the LORD said unto Moses.",
            he_quote="ויאמר יְהוָה אל משה",
        ),
    ]

    regular, hard, stats, notes = postprocess_hard_options._select_options_for_field(
        model="dummy-model",
        skip_llm=False,
        field="speaker",
        item_id="exodus-03-11-11",
        answer_en="Moses",
        answer_he="מֹשֶׁה",
        target_quote_en="And Moses said unto God, Who am I?",
        target_quote_he="וַיֹּאמֶר מֹשֶׁה אֶל הָאֱלֹהִים מִי אָנֹכִי",
        target_riddle_en="Who am I?",
        target_riddle_he="מִי אָנֹכִי",
        candidates=candidates,
        option_count=4,
        sample_size=7,
        max_rounds=1,
        llm_retries=1,
        same_book_only=False,
        target_book_code="EXO",
        target_book="Exodus",
    )

    assert len(regular) == 4
    assert len(hard) == 4
    assert all(isinstance(candidate, postprocess_hard_options.AlignedCandidate) for candidate in regular)
    assert stats["calls"] == 2
    assert calls
    assert isinstance(notes, list)


def test_build_output_item_preserves_shape_and_aligned_options() -> None:
    speaker_pairs = [
        _aligned(
            item_id="spk-jacob",
            en_label="Jacob",
            he_label="יעקב",
            en_quote="And Jacob said unto Joseph.",
            he_quote="ויאמר יעקב אל יוסף",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="spk-joseph",
            en_label="Joseph",
            he_label="יוסף",
            en_quote="And Joseph said unto Jacob.",
            he_quote="ויאמר יוסף אל יעקב",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="spk-aaron",
            en_label="Aaron",
            he_label="אהרן",
            en_quote="And Aaron said unto Moses.",
            he_quote="ויאמר אהרן אל משה",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="spk-god",
            en_label="God",
            he_label="אֱלֹהִים",
            en_quote="And God said unto Moses.",
            he_quote="ויאמר אֱלֹהִים אל משה",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="spk-lord",
            en_label="the LORD",
            he_label="יְהוָה",
            en_quote="And the LORD said unto Moses.",
            he_quote="ויאמר יְהוָה אל משה",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="spk-pharaoh",
            en_label="Pharaoh",
            he_label="פרעה",
            en_quote="And Pharaoh said unto Moses.",
            he_quote="ויאמר פרעה אל משה",
            book="Exodus",
            book_code="EXO",
        ),
    ]
    listener_pairs = [
        _aligned(
            item_id="lst-jacob",
            en_label="Jacob",
            he_label="יעקב",
            en_quote="And Joseph said unto Jacob.",
            he_quote="ויאמר יוסף אל יעקב",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="lst-joseph",
            en_label="Joseph",
            he_label="יוסף",
            en_quote="And Jacob said unto Joseph.",
            he_quote="ויאמר יעקב אל יוסף",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="lst-aaron",
            en_label="Aaron",
            he_label="אהרן",
            en_quote="And Moses said unto Aaron.",
            he_quote="ויאמר משה אל אהרן",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="lst-israel",
            en_label="Israel",
            he_label="יִשְׂרָאֵל",
            en_quote="And Moses said unto Israel.",
            he_quote="ויאמר משה אל ישראל",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="lst-god",
            en_label="God",
            he_label="אֱלֹהִים",
            en_quote="And Moses said unto God.",
            he_quote="ויאמר משה אל אֱלֹהִים",
            book="Exodus",
            book_code="EXO",
        ),
        _aligned(
            item_id="lst-lord",
            en_label="the LORD",
            he_label="יְהוָה",
            en_quote="And Moses said unto the LORD.",
            he_quote="ויאמר משה אל יְהוָה",
            book="Exodus",
            book_code="EXO",
        ),
    ]

    pools = {"speaker": speaker_pairs, "listener": listener_pairs}
    pair_map = {
        candidate.en.label: candidate.he.label
        for candidate in speaker_pairs + listener_pairs
    }

    item = {
        "id": "exodus-03-11-11",
        "source": {"book_code": "EXO", "book": "Exodus", "chapter": 3},
        "en": {
            "quote": "And Moses said unto God, Who am I?",
            "riddle": "Who am I?",
            "speaker": "Moses",
            "listener": "God",
        },
        "he": {
            "quote": "וַיֹּאמֶר מֹשֶׁה אֶל הָאֱלֹהִים מִי אָנֹכִי",
            "riddle": "מִי אָנֹכִי",
            "speaker": "מֹשֶׁה",
            "listener": "הָאֱלֹהִים",
        },
        "raw_quote_source": {"en": {"11": "And Moses said unto God, Who am I?"}},
    }

    out_item, stats, issues = postprocess_hard_options._build_output_item(
        item=item,
        pools=pools,
        model="dummy-model",
        skip_llm=True,
        option_count=4,
        sample_size=4,
        max_rounds=0,
        llm_retries=1,
        same_book_only=True,
        target_book_code="EXO",
        target_book="Exodus",
    )

    assert out_item["id"] == "exodus-03-11-11"
    assert out_item["raw_quote_source"] == item["raw_quote_source"]
    assert out_item["en"]["speaker"] == "Moses"
    assert out_item["he"]["listener"] == "הָאֱלֹהִים"
    assert len(out_item["en"]["options"]["speaker"]) == 4
    assert len(out_item["he"]["options"]["speaker"]) == 4
    assert len(out_item["en"]["hard_difficulty_options"]["listener"]) == 4
    assert len(out_item["he"]["hard_difficulty_options"]["listener"]) == 4

    for idx, en_label in enumerate(out_item["en"]["options"]["speaker"]):
        assert pair_map[en_label] == out_item["he"]["options"]["speaker"][idx]
    for idx, en_label in enumerate(out_item["en"]["hard_difficulty_options"]["listener"]):
        assert pair_map[en_label] == out_item["he"]["hard_difficulty_options"]["listener"][idx]

    assert stats["calls"] == 0
    assert isinstance(issues, list)


def test_out_path_for_input_keeps_relative_filename() -> None:
    in_dir = Path("/tmp/in")
    out_dir = Path("/tmp/out")
    in_path = Path("/tmp/in/exodus-003.json")
    out_path = postprocess_hard_options._out_path_for_input(in_path, out_dir, in_dir)
    assert out_path == Path("/tmp/out/exodus-003.json")
