from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

from data_proc.candidates_pipeline import build_candidates_command
from data_proc.candidates_pipeline import CandidateStrategyEvaluation, _candidate_prompt_system, select_best_candidate_strategy
from data_proc.corpus import BibleCorpus
from data_proc.llm import JsonResponseError, OllamaJsonClient, _parse_json_object
from data_proc.options_pipeline import (
    OptionsBuilder,
    _filter_overlapping_chapter_items,
    _text_role_kind,
    build_character_bank,
    read_character_bank,
)
from data_proc.pipeline import (
    CandidatePipeline,
    ValidationResult,
    _alignment_system_prompt,
    _alignment_user_prompt,
    build_chapter_payloads,
    build_quotes_command,
    build_quotes_eval_command,
    chapter_output_path,
)
from data_proc.schema import (
    BonusHint,
    ChapterPayload,
    ChoicePools,
    FinalLangText,
    FinalMeta,
    FinalQuoteItem,
    FinalSource,
    HintSourceRef,
    RefRange,
)
from data_proc.utils.text_cleanup import (
    candidate_bonus_words,
    candidate_riddle_spans,
    clean_text,
    cleanup_hebrew_quote,
    restore_hebrew_surface,
    whole_word_occurs,
)

TEST_SEED = 32988
REPO_ROOT = Path(__file__).resolve().parents[3]
CHARACTER_BANK_PATH = REPO_ROOT / "data/processed/character_bank.json"


@pytest.fixture(scope="module")
def seeded_live_llm() -> OllamaJsonClient:
    return OllamaJsonClient(
        model="gemma4:26b",
        max_retries=2,
        fallback_model=None,
        request_options={"seed": TEST_SEED},
    )


@pytest.fixture(scope="module")
def seeded_live_pipeline(bible_corpus: BibleCorpus, seeded_live_llm: OllamaJsonClient) -> CandidatePipeline:
    return CandidatePipeline(corpus=bible_corpus, llm=seeded_live_llm)


def test_hebrew_cleanup_and_bonus_word_helpers() -> None:
    cleaned = cleanup_hebrew_quote("וַיֹּאמֶר הַנָּחָשׁ אֶל־הָֽאִשָּׁה לֹֽא־מוֹת תְּמֻתֽוּן׃")
    assert cleaned == "וַיֹּאמֶר הַנָּחָשׁ אֶל־הָֽאִשָּׁה לֹֽא־מוֹת תְּמֻתֽוּן"
    assert candidate_bonus_words(
        "And the serpent said unto the woman, Ye shall not surely die:",
        "Ye shall not surely die:",
        "en",
    ) == ["serpent", "woman"]
    assert candidate_bonus_words(
        "And the serpent said unto the woman, Ye shall not surely die:",
        "Ye shall not surely die:",
        "en",
        forbidden_texts=("serpent", "woman"),
    ) == []
    assert candidate_bonus_words(
        "וַיֹּאמֶר הַנָּחָשׁ אֶל־הָֽאִשָּׁה לֹֽא־מוֹת תְּמֻתֽוּן",
        "לֹֽא־מוֹת תְּמֻתֽוּן",
        "he",
        forbidden_texts=("הַנָּחָשׁ", "הָֽאִשָּׁה"),
    ) == []
    hebrew_candidates = candidate_bonus_words(
        "וַיֹּאמֶר יְהוָה אֱלֹהִים לָאִשָּׁה מַה־זֹּאת עָשִׂית וַתֹּאמֶר הָֽאִשָּׁה הַנָּחָשׁ הִשִּׁיאַנִי וָאֹכֵֽל",
        "מַה־זֹּאת עָשִׂית",
        "he",
        forbidden_texts=("יְהוָה אֱלֹהִים", "הָֽאִשָּׁה"),
    )
    assert "לָאִשָּׁה" not in hebrew_candidates
    assert "הָֽאִשָּׁה" not in hebrew_candidates


def test_candidate_riddle_spans_include_exact_inner_clause() -> None:
    english_spans = candidate_riddle_spans(
        "Hearken to me; I also will shew mine opinion.",
        "en",
        preferred_word_count=6,
    )
    hebrew_spans = candidate_riddle_spans(
        "שִׁמְעָה־לִּי אֲחַוֶּה דֵעִי אַף־אָֽנִי",
        "he",
        preferred_word_count=3,
    )

    assert "I also will shew mine opinion" in english_spans
    assert all(span in clean_text("Hearken to me; I also will shew mine opinion.") for span in english_spans)
    assert "אֲחַוֶּה דֵעִי" in hebrew_spans
    assert all(cleanup_hebrew_quote(span) in cleanup_hebrew_quote("שִׁמְעָה־לִּי אֲחַוֶּה דֵעִי אַף־אָֽנִי") for span in hebrew_spans)
    question_spans_en = candidate_riddle_spans("And the LORD God called unto Adam, and said unto him, Where art thou?", "en")
    question_spans_he = candidate_riddle_spans("וַיִּקְרָא יְהוָה אֱלֹהִים אֶל־הָאָדָם וַיֹּאמֶר לוֹ אַיֶּכָּה", "he")
    assert "Where art thou?" in question_spans_en
    assert "אַיֶּכָּה" in question_spans_he
    assert "What is this that thou hast done?" in candidate_riddle_spans(
        "And the LORD God said unto the woman, What is this that thou hast done? And the woman said, The serpent beguiled me, and I did eat.",
        "en",
    )
    assert "מַה־זֹּאת עָשִׂית" in candidate_riddle_spans(
        "וַיֹּאמֶר יְהוָה אֱלֹהִים לָאִשָּׁה מַה־זֹּאת עָשִׂית וַתֹּאמֶר הָאִשָּׁה הַנָּחָשׁ הִשִּׁיאַנִי וָאֹכֵל",
        "he",
    )
    assert whole_word_occurs("And the LORD said unto Noah", "Noah", "en")
    assert whole_word_occurs("And the LORD God said unto the woman", "the LORD God", "en")
    assert whole_word_occurs("And the LORD God said unto the woman", "the woman", "en")
    assert whole_word_occurs("וַיֹּאמֶר יְהוָה לְנֹחַ", "נֹחַ", "he")
    assert whole_word_occurs("וַיֹּאמֶר יְהוָה אֱלֹהִים לָאִשָּׁה", "יְהוָה אֱלֹהִים", "he")
    assert whole_word_occurs("וַיֹּאמֶר יְהוָה לָאִשָּׁה", "הָֽאִשָּׁה", "he")
    assert whole_word_occurs("Where art thou?", "Where", "en")


def test_restore_hebrew_surface_recovers_full_niqqud_from_quote_context() -> None:
    context = [
        "וַיַּגֵּד לְיַעֲקֹב וַיֹּאמֶר הִנֵּה בִּנְךָ יוֹסֵף בָּא אֵלֶיךָ",
        "וַיֹּאמֶר יְהוָה אֱלֹהִים אֶל־הָאִשָּׁה מַה־זֹּאת עָשִׂית",
        "וַתִּשָּׂא אֵֽשֶׁת־אֲדֹנָיו אֶת־עֵינֶיהָ אֶל־יוֹסֵף",
    ]

    assert restore_hebrew_surface("יעקב", context) == "יַעֲקֹב"
    assert restore_hebrew_surface("יהוה", context) == "יְהוָה"
    assert restore_hebrew_surface("אלהים", context) == "אֱלֹהִים"
    assert restore_hebrew_surface("האשה", context) == "הָאִשָּׁה"
    assert restore_hebrew_surface("אשתאדניו", context) == "אֵֽשֶׁת־אֲדֹנָיו"


def test_text_role_kind_treats_house_roles_as_groups() -> None:
    assert _text_role_kind("house of Pharaoh", "בֵּית פַּרְעֹה", "other") == "group"


def test_aligned_external_hint_lookup_returns_same_reference(bible_corpus: BibleCorpus) -> None:
    hint = bible_corpus.find_first_aligned_hint(
        "Noah",
        "נֹחַ",
        source_book_code="GEN",
        source_chapter=6,
        source_start=13,
        source_end=13,
    )

    assert hint is not None
    assert hint.en_source.chapter == hint.he_source.chapter
    assert hint.en_source.start == hint.he_source.start == hint.en_source.end == hint.he_source.end
    assert hint.en_source.chapter != 6
    assert whole_word_occurs(hint.en_quote, "Noah", "en")
    assert whole_word_occurs(hint.he_quote, "נֹחַ", "he")


def test_prepare_bonus_candidate_expands_one_verse_when_needed(candidate_map, seeded_live_pipeline: CandidatePipeline) -> None:
    candidate = candidate_map["genesis-03-09-09"]
    prepared = seeded_live_pipeline.prepare_bonus_candidate(candidate)

    assert prepared.expansion == "after"
    assert prepared.candidate.source.quote_verse_start == 9
    assert prepared.candidate.source.quote_verse_end == 10
    assert prepared.candidate.ref.start == 9
    assert prepared.candidate.ref.end == 10
    assert prepared.candidate.en.riddle in prepared.candidate.en.quote
    assert prepared.candidate.he.riddle in prepared.candidate.he.quote
    assert "voice" in {word.casefold() for word in prepared.en_words}
    assert any(whole_word_occurs(prepared.candidate.he.quote, word, "he") for word in prepared.he_words)


def test_prepare_context_candidate_expands_one_verse_when_selected(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["genesis-24-17-17"]

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            assert prompt_name == "quote-context-expansion"
            assert "before_added_verse:" in user_prompt
            assert "after_added_verse:" in user_prompt
            assert "current_quote_has_english_speaker:" in user_prompt
            assert "current_quote_has_hebrew_listener:" in user_prompt
            return {"choice": "before", "reason": "before verse introduces the scene more clearly"}

    pipeline = CandidatePipeline(corpus=bible_corpus, llm=StubLLM())
    prepared = pipeline.prepare_context_candidate(candidate)

    assert prepared.expansion == "before"
    assert prepared.candidate.source.quote_verse_start == 16
    assert prepared.candidate.source.quote_verse_end == 17
    assert prepared.candidate.ref.start == 16
    assert prepared.candidate.ref.end == 17
    assert candidate.en.riddle in prepared.candidate.en.quote
    assert candidate.he.riddle in prepared.candidate.he.quote


def test_prepare_context_candidate_retries_when_first_choice_keeps_weak_context(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["genesis-24-17-17"]
    seen_prompts: list[str] = []

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            seen_prompts.append(prompt_name)
            if prompt_name == "quote-context-expansion":
                return {"choice": "none", "reason": "speaker is technically present"}
            if prompt_name == "quote-context-expansion-retry":
                assert "previous_choice: none" in user_prompt
                assert "weak generic role" in user_prompt
                return {"choice": "before", "reason": "before clarifies the scene"}
            raise AssertionError(f"unexpected prompt {prompt_name}")

    pipeline = CandidatePipeline(corpus=bible_corpus, llm=StubLLM())
    prepared = pipeline.prepare_context_candidate(candidate)

    assert seen_prompts == ["quote-context-expansion", "quote-context-expansion-retry"]
    assert prepared.expansion == "before"
    assert prepared.candidate.source.quote_verse_start == 16
    assert prepared.candidate.source.quote_verse_end == 17


def test_prepare_context_candidate_forces_before_after_choice_for_weak_context(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["genesis-24-17-17"]
    seen_prompts: list[str] = []

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            seen_prompts.append(prompt_name)
            if prompt_name == "quote-context-expansion":
                return {"choice": "none", "reason": "current quote already names speaker and listener"}
            if prompt_name == "quote-context-expansion-retry":
                return {"choice": "none", "reason": "still keeping minimal quote"}
            if prompt_name == "quote-context-expansion-forced":
                assert "Choose the better minimal expansion: before or after." in user_prompt
                return {"choice": "before", "reason": "before clarifies the scene"}
            raise AssertionError(f"unexpected prompt {prompt_name}")

    pipeline = CandidatePipeline(corpus=bible_corpus, llm=StubLLM())
    prepared = pipeline.prepare_context_candidate(candidate)

    assert seen_prompts == [
        "quote-context-expansion",
        "quote-context-expansion-retry",
        "quote-context-expansion-forced",
    ]
    assert prepared.expansion == "before"
    assert prepared.candidate.source.quote_verse_start == 16
    assert prepared.candidate.source.quote_verse_end == 17


def test_prepare_context_candidate_keeps_clear_single_verse_quote_minimal(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["genesis-03-13-13"]

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            raise AssertionError(f"unexpected prompt {prompt_name}")

    pipeline = CandidatePipeline(corpus=bible_corpus, llm=StubLLM())
    prepared = pipeline.prepare_context_candidate(candidate)

    assert prepared.expansion == "original"
    assert prepared.candidate.source.quote_verse_start == candidate.source.quote_verse_start
    assert prepared.candidate.source.quote_verse_end == candidate.source.quote_verse_end


def test_prepare_context_candidate_can_expand_short_multi_verse_quote(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["1-chronicles-16-15-16"]

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            assert prompt_name == "quote-context-expansion"
            assert "after_added_verse:" in user_prompt
            assert "before_added_verse:" in user_prompt
            return {"choice": "before", "reason": "before verse gives the fuller exhortation context"}

    pipeline = CandidatePipeline(corpus=bible_corpus, llm=StubLLM())
    prepared = pipeline.prepare_context_candidate(candidate)

    assert prepared.expansion == "before"
    assert prepared.candidate.source.quote_verse_start == 14
    assert prepared.candidate.source.quote_verse_end == 16
    assert candidate.en.riddle in prepared.candidate.en.quote
    assert candidate.he.riddle in prepared.candidate.he.quote


def test_validate_candidate_targets_riddle_not_other_turns(candidate_map, seeded_live_pipeline: CandidatePipeline) -> None:
    candidate = candidate_map["exodus-04-02-02"]
    resolved = seeded_live_pipeline.resolve_roles(candidate)
    english_result = seeded_live_pipeline.validate_candidate(resolved, "en")
    hebrew_result = seeded_live_pipeline.validate_candidate(resolved, "he")

    assert resolved.en.speaker == "LORD"
    assert resolved.en.listener == "Moses"
    assert resolved.he.speaker in {"יְהוָה", "יהוה"}
    assert resolved.he.listener in {"מֹשֶׁה", "משה"}
    assert english_result.speaker_is_speaking
    assert english_result.listener_is_addressed
    assert english_result.listener_is_character
    assert hebrew_result.speaker_is_speaking
    assert hebrew_result.listener_is_addressed


def test_validate_candidate_reconciles_hebrew_false_negative_from_english(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["exodus-04-02-02"]
    candidate = replace(
        candidate,
        en=replace(candidate.en, speaker="LORD", listener="Moses"),
        he=replace(candidate.he, speaker="יְהוָה", listener="מֹשֶׁה"),
    )
    responses = {
        "en-role-validation": (
            "LORD",
            "Moses",
            ValidationResult(
                speaker_is_speaking=True,
                listener_is_addressed=True,
                speaker_is_character=True,
                listener_is_character=True,
                reason="The LORD addresses Moses directly.",
            ),
        ),
        "he-role-validation": (
            "יְהוָה",
            "מֹשֶׁה",
            ValidationResult(
                speaker_is_speaking=True,
                listener_is_addressed=False,
                speaker_is_character=True,
                listener_is_character=True,
                reason="The people speak, but the listener is undercalled.",
            ),
        ),
    }

    class StubPipeline(CandidatePipeline):
        def _resolve_and_validate_lang(self, candidate, lang, *, english_speaker=None, english_listener=None, english_result=None):
            return responses[f"{lang}-role-validation"]

    pipeline = StubPipeline(corpus=bible_corpus, llm=object())
    result = pipeline.validate_candidate(candidate, "he")

    assert result.listener_is_addressed
    assert "English support confirms" in result.reason


def test_resolve_roles_corrects_reversed_speaker_and_listener(candidate_map, seeded_live_pipeline: CandidatePipeline) -> None:
    candidate = candidate_map["exodus-10-08-08"]
    candidate = replace(
        candidate,
        en=replace(candidate.en, speaker="Moses and Aaron", listener="Pharaoh"),
        he=replace(candidate.he, speaker="מֹשֶׁה ואהרון", listener="פַּרְעֹה"),
    )
    resolved = seeded_live_pipeline.resolve_roles(candidate)

    assert resolved.en.speaker == "Pharaoh"
    assert resolved.en.listener == "Moses and Aaron"
    assert resolved.he.speaker in {"פַּרְעֹה", "פרעה"}
    assert "מֹשֶׁה" in resolved.he.listener or "משה" in resolved.he.listener
    assert "אַהֲרֹן" in resolved.he.listener or "אהרון" in resolved.he.listener or "אהרן" in resolved.he.listener


def test_refine_riddles_edits_down_long_hebrew_riddle(candidate_map, bible_corpus: BibleCorpus) -> None:
    candidate = candidate_map["genesis-24-18-18"]

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            assert "allowed_riddles:" in user_prompt
            if prompt_name == "en-riddle-edit":
                return {"riddle": "Drink, my lord: and she hasted"}
            assert prompt_name == "he-riddle-edit"
            return {"riddle": "שְׁתֵה אֲדֹנִי"}

    refined = CandidatePipeline(corpus=bible_corpus, llm=StubLLM()).refine_riddles(candidate)

    assert refined.en.riddle in refined.en.quote
    assert refined.he.riddle in refined.he.quote
    assert len(refined.he.riddle.split()) < len(candidate.he.riddle.split())
    assert len(refined.en.riddle.split()) <= len(candidate.en.riddle.split())
    assert not refined.he.riddle.startswith("וַיֹּאמֶר")
    assert not refined.he.riddle.startswith("ויאמר")
    assert not whole_word_occurs(refined.he.riddle, refined.he.speaker, "he")
    assert not whole_word_occurs(refined.he.riddle, refined.he.listener, "he")
    assert "שְׁתֵה אֲדֹנִי" in refined.he.riddle or "שתה אדני" in cleanup_hebrew_quote(refined.he.riddle)


def test_alignment_prompt_caps_output_and_prefers_short_results(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]

    system_prompt = _alignment_system_prompt()
    user_prompt = _alignment_user_prompt(
        candidate,
        ["serpent", "woman", "garden", "voice"],
        ["הנחש", "האשה", "הגן", "קול"],
    )

    assert "Return at most 3 pairs total." in system_prompt
    assert "Prefer 1 or 2 strong pairs over a long list." in system_prompt
    assert "Keep the response short so the JSON object stays complete." in system_prompt
    assert "Choose zero to 3 aligned pairs." in user_prompt
    assert "Do not output extra pairs once the strongest matches are listed." in user_prompt


def test_select_bonus_with_live_llm_returns_valid_pair(candidate_map, seeded_live_pipeline: CandidatePipeline) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    resolved = seeded_live_pipeline.resolve_roles(candidate)
    prepared = seeded_live_pipeline.prepare_bonus_candidate(resolved)
    bonus = seeded_live_pipeline.select_bonus(prepared)

    assert bonus.en_word
    assert bonus.he_word
    assert not whole_word_occurs(prepared.candidate.en.riddle, bonus.en_word, "en")
    assert not whole_word_occurs(prepared.candidate.he.riddle, bonus.he_word, "he")
    assert bonus.hint.en_source.chapter == bonus.hint.he_source.chapter
    assert bonus.hint.en_source.chapter != prepared.candidate.source.chapter


def test_strict_json_retry_logic(monkeypatch) -> None:
    responses = iter(
        [
            SimpleNamespace(message=SimpleNamespace(content="not json")),
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
        ]
    )

    monkeypatch.setattr("data_proc.llm._ollama_chat", lambda **_: next(responses))
    client = OllamaJsonClient(model="gemma3:4b", max_retries=2)

    assert client.chat_json("retry-test", "system", "user") == {"ok": True}


def test_ollama_client_disables_thinking_and_applies_default_json_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_chat(*, model: str, messages, format: str, timeout: float, think, options=None):
        captured["model"] = model
        captured["format"] = format
        captured["timeout"] = timeout
        captured["think"] = think
        captured["options"] = options
        return SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma4:26b", max_retries=1, request_options={"seed": TEST_SEED})

    assert client.chat_json("json-shape", "system", "user") == {"ok": True}
    assert captured["think"] is False
    assert captured["options"] == {"temperature": 0, "num_predict": 128, "seed": TEST_SEED}


def test_ollama_client_raises_token_budget_for_candidate_chapter_extraction(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_chat(*, model: str, messages, format: str, timeout: float, think, options=None):
        captured["options"] = options
        return SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma4:26b", max_retries=1, request_options={"seed": TEST_SEED})

    assert client.chat_json("candidate-chapter-extract", "system", "user") == {"ok": True}
    assert captured["options"] == {"temperature": 0, "num_predict": 1024, "seed": TEST_SEED}


def test_candidate_prompt_keeps_json_output_short() -> None:
    prompt = _candidate_prompt_system()

    assert 'Return exactly one JSON object with a single top-level key items.' in prompt
    assert 'If there are no candidates, return {"items": []}.' in prompt
    assert "Keep reason very short, at most six words." in prompt


def test_select_best_candidate_strategy_prefers_must_pass_then_recall_then_cost() -> None:
    selected = select_best_candidate_strategy(
        [
            CandidateStrategyEvaluation(
                strategy="full_chapter",
                passed_must_pass=False,
                recall_hits=20,
                issue_count=1,
                llm_call_count=40,
            ),
            CandidateStrategyEvaluation(
                strategy="dialogue_blocks",
                passed_must_pass=True,
                recall_hits=18,
                issue_count=10,
                llm_call_count=50,
            ),
            CandidateStrategyEvaluation(
                strategy="other",
                passed_must_pass=True,
                recall_hits=18,
                issue_count=12,
                llm_call_count=20,
            ),
        ]
    )

    assert selected == "dialogue_blocks"


def test_strict_json_parser_accepts_fenced_json_with_trailing_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "data_proc.llm._ollama_chat",
        lambda **_: SimpleNamespace(
            message=SimpleNamespace(content='```json\n{"words": ["voice"]}\n```\nextra commentary')
        ),
    )
    client = OllamaJsonClient(model="gemma3:4b", max_retries=1)

    assert client.chat_json("english-bonus-words", "system", "user") == {"words": ["voice"]}


def test_strict_json_parser_salvages_inner_quotes_and_newlines_in_string_values() -> None:
    payload = _parse_json_object(
        '{\n'
        '  "speaker_is_speaking": false,\n'
        '  "listener_is_addressed": false,\n'
        '  "speaker_is_character": false,\n'
        '  "listener_is_character": false,\n'
        '  "reason": "The riddle "וימתו הצפרדעים"\nlooks narrative."\n'
        '}'
    )

    assert payload["speaker_is_speaking"] is False
    assert payload["reason"] == 'The riddle "וימתו הצפרדעים"\nlooks narrative.'


def test_strict_json_escalates_to_fallback_model_for_missing_required_keys(monkeypatch) -> None:
    seen_models: list[str] = []
    responses = {
        "gemma3:4b": SimpleNamespace(message=SimpleNamespace(content='{"word": "voice"}')),
        "gemma4:26b": SimpleNamespace(message=SimpleNamespace(content='{"words": ["voice"]}')),
    }

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_models.append(model)
        return responses[model]

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma3:4b", fallback_model="gemma4:26b", max_retries=1, fallback_retries=1)

    assert client.chat_json("english-bonus-words", "system", "user", required_keys=("words",)) == {"words": ["voice"]}
    assert seen_models == ["gemma3:4b", "gemma4:26b"]


def test_strict_json_rewrites_final_model_response_to_required_schema(monkeypatch) -> None:
    seen_models: list[str] = []
    responses = iter(
        [
            SimpleNamespace(message=SimpleNamespace(content='{"alignments": [{"en": "voice", "he": "קול"}]}')),
            SimpleNamespace(message=SimpleNamespace(content='{"alignments": [{"en": "voice", "he": "קול"}]}')),
            SimpleNamespace(message=SimpleNamespace(content='{"pairs": [{"en": "voice", "he": "קול"}]}')),
        ]
    )

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_models.append(model)
        return next(responses)

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma3:4b", fallback_model="gemma4:26b", max_retries=1, fallback_retries=1)

    assert client.chat_json("bonus-word-alignment", "system", "user", required_keys=("pairs",)) == {
        "pairs": [{"en": "voice", "he": "קול"}]
    }
    assert seen_models == ["gemma3:4b", "gemma4:26b", "gemma4:26b"]


def test_strict_json_retries_repair_with_other_model_after_invalid_rewrite(monkeypatch) -> None:
    seen_models: list[str] = []
    responses = iter(
        [
            SimpleNamespace(message=SimpleNamespace(content='{"alignments": [{"en": "voice", "he": "קול"}]}')),
            SimpleNamespace(message=SimpleNamespace(content='{"alignments": [{"en": "voice", "he": "קול"}]}')),
            SimpleNamespace(message=SimpleNamespace(content='{"pairs": [{"en": "voice')),
            SimpleNamespace(message=SimpleNamespace(content='{"pairs": [{"en": "voice", "he": "קול"}]}')),
        ]
    )

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_models.append(model)
        return next(responses)

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma3:4b", fallback_model="gemma4:26b", max_retries=1, fallback_retries=1)

    assert client.chat_json("bonus-word-alignment", "system", "user", required_keys=("pairs",)) == {
        "pairs": [{"en": "voice", "he": "קול"}]
    }
    assert seen_models == ["gemma3:4b", "gemma4:26b", "gemma4:26b", "gemma3:4b"]


def test_strict_json_retries_repair_with_tweaked_prompt(monkeypatch) -> None:
    seen_prompts: list[str] = []
    responses = iter(
        [
            SimpleNamespace(message=SimpleNamespace(content='{"pairs_list": [{"en": "voice", "he": "קול"}]}')),
            SimpleNamespace(message=SimpleNamespace(content='{"pairs": [{"en": "voice')),
            SimpleNamespace(message=SimpleNamespace(content='{"pairs": [{"en": "voice", "he": "קול"}]}')),
        ]
    )

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_prompts.append(messages[0]["content"])
        return next(responses)

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(model="gemma3:4b", max_retries=1)

    assert client.chat_json("bonus-word-alignment", "system", "user", required_keys=("pairs",)) == {
        "pairs": [{"en": "voice", "he": "קול"}]
    }
    assert "Rewrite the user's response into one valid JSON object." in seen_prompts[1]
    assert "Repair the user's malformed JSON into one valid JSON object." in seen_prompts[2]
    assert "Do not leave strings unterminated" in seen_prompts[2]


def test_strict_json_retry_raises_after_last_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "data_proc.llm._ollama_chat",
        lambda **_: SimpleNamespace(message=SimpleNamespace(content="still not json")),
    )
    client = OllamaJsonClient(model="gemma3:4b", max_retries=2)

    with pytest.raises(JsonResponseError):
        client.chat_json("retry-test", "system", "user")


def test_build_quotes_command_enables_default_fallback_model(tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    english_xml = tmp_path / "english.xml"
    hebrew_zip = tmp_path / "tanach.zip"
    out_dir = tmp_path / "out"
    captured: dict[str, OllamaJsonClient] = {}

    candidates_path.write_text("", encoding="utf-8")
    english_xml.write_text("", encoding="utf-8")
    hebrew_zip.write_text("", encoding="utf-8")

    def fake_run_pipeline(*, llm, **kwargs):
        captured["llm"] = llm
        return [], []

    monkeypatch.setattr("data_proc.pipeline.run_pipeline", fake_run_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        build_quotes_command,
        [
            "--candidates",
            str(candidates_path),
            "--out-dir",
            str(out_dir),
            "--english-xml",
            str(english_xml),
            "--hebrew-zip",
            str(hebrew_zip),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["llm"].model == "gemma4:26b"
    assert captured["llm"].fallback_model == "gemma4:26b"


def test_build_quotes_command_allows_disabling_fallback_model(tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    english_xml = tmp_path / "english.xml"
    hebrew_zip = tmp_path / "tanach.zip"
    out_dir = tmp_path / "out"
    captured: dict[str, OllamaJsonClient] = {}

    candidates_path.write_text("", encoding="utf-8")
    english_xml.write_text("", encoding="utf-8")
    hebrew_zip.write_text("", encoding="utf-8")

    def fake_run_pipeline(*, llm, **kwargs):
        captured["llm"] = llm
        return [], []

    monkeypatch.setattr("data_proc.pipeline.run_pipeline", fake_run_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        build_quotes_command,
        [
            "--candidates",
            str(candidates_path),
            "--out-dir",
            str(out_dir),
            "--fallback-model",
            "",
            "--english-xml",
            str(english_xml),
            "--hebrew-zip",
            str(hebrew_zip),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["llm"].fallback_model is None


def test_build_quotes_command_passes_seed_to_llm(tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    english_xml = tmp_path / "english.xml"
    hebrew_zip = tmp_path / "tanach.zip"
    out_dir = tmp_path / "out"
    captured: dict[str, OllamaJsonClient] = {}

    candidates_path.write_text("", encoding="utf-8")
    english_xml.write_text("", encoding="utf-8")
    hebrew_zip.write_text("", encoding="utf-8")

    def fake_run_pipeline(*, llm, **kwargs):
        captured["llm"] = llm
        return [], []

    monkeypatch.setattr("data_proc.pipeline.run_pipeline", fake_run_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        build_quotes_command,
        [
            "--candidates",
            str(candidates_path),
            "--out-dir",
            str(out_dir),
            "--seed",
            str(TEST_SEED),
            "--english-xml",
            str(english_xml),
            "--hebrew-zip",
            str(hebrew_zip),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["llm"].request_options == {"seed": TEST_SEED}


def test_build_candidates_command_passes_seed_to_llm(tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    shard_dir = tmp_path / "candidate_chapters"
    issues_log = tmp_path / "candidate_issues.jsonl"
    english_xml = tmp_path / "english.xml"
    hebrew_zip = tmp_path / "tanach.zip"
    captured: dict[str, OllamaJsonClient] = {}

    english_xml.write_text("", encoding="utf-8")
    hebrew_zip.write_text("", encoding="utf-8")

    def fake_run_build_candidates(*, llm, **kwargs):
        captured["llm"] = llm
        return [], []

    monkeypatch.setattr("data_proc.candidates_pipeline.run_build_candidates", fake_run_build_candidates)

    runner = CliRunner()
    result = runner.invoke(
        build_candidates_command,
        [
            "--candidates-out",
            str(candidates_path),
            "--shard-dir",
            str(shard_dir),
            "--issues-log",
            str(issues_log),
            "--seed",
            str(TEST_SEED),
            "--english-xml",
            str(english_xml),
            "--hebrew-zip",
            str(hebrew_zip),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["llm"].request_options == {"seed": TEST_SEED}


def test_build_quotes_eval_command_passes_seed_to_llm(tmp_path, monkeypatch) -> None:
    candidates_path = tmp_path / "candidates.jsonl"
    out_dir = tmp_path / "quotes_eval"
    english_xml = tmp_path / "english.xml"
    hebrew_zip = tmp_path / "tanach.zip"
    captured: dict[str, OllamaJsonClient] = {}

    candidates_path.write_text("", encoding="utf-8")
    english_xml.write_text("", encoding="utf-8")
    hebrew_zip.write_text("", encoding="utf-8")

    def fake_build_quotes_eval_pack(*, llm, **kwargs):
        captured["llm"] = llm
        return {"sample_size": 0}

    monkeypatch.setattr("data_proc.pipeline.build_quotes_eval_pack", fake_build_quotes_eval_pack)

    runner = CliRunner()
    result = runner.invoke(
        build_quotes_eval_command,
        [
            "--candidates",
            str(candidates_path),
            "--out-dir",
            str(out_dir),
            "--seed",
            str(TEST_SEED),
            "--english-xml",
            str(english_xml),
            "--hebrew-zip",
            str(hebrew_zip),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["llm"].request_options == {"seed": TEST_SEED}


def test_transport_timeout_retries_inside_single_outer_attempt(monkeypatch) -> None:
    seen_calls: list[tuple[str, float]] = []
    responses = iter(
        [
            httpx.ReadTimeout("timed out"),
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
        ]
    )

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_calls.append((model, timeout))
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(
        model="gemma3:4b",
        fallback_model=None,
        max_retries=1,
        request_timeout_seconds=7.5,
        transport_retries=1,
    )

    assert client.chat_json("timeout-retry", "system", "user") == {"ok": True}
    assert seen_calls == [("gemma3:4b", 7.5), ("gemma3:4b", 7.5)]


def test_transport_timeouts_still_flow_through_outer_model_attempts(monkeypatch) -> None:
    seen_models: list[str] = []

    def fake_chat(*, model: str, messages, format, timeout: float, think=None, options=None):
        seen_models.append(model)
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("data_proc.llm._ollama_chat", fake_chat)
    client = OllamaJsonClient(
        model="gemma3:4b",
        fallback_model="gemma4:26b",
        max_retries=3,
        fallback_retries=2,
        request_timeout_seconds=1.0,
        transport_retries=1,
    )

    with pytest.raises(JsonResponseError, match="Failed to get valid JSON"):
        client.chat_json("timeout-failure", "system", "user")

    assert seen_models == [
        "gemma3:4b",
        "gemma3:4b",
        "gemma3:4b",
        "gemma3:4b",
        "gemma3:4b",
        "gemma3:4b",
        "gemma4:26b",
        "gemma4:26b",
        "gemma4:26b",
        "gemma4:26b",
    ]


def test_chapter_grouping_and_output_naming_are_stable(candidate_map, tmp_path) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    item = FinalQuoteItem(
        id=candidate.id,
        source=FinalSource(
            method="llm",
            book_code="GEN",
            book="Genesis",
            book_he="בראשית",
            chapter=3,
            quote_verse_start=9,
            quote_verse_end=9,
        ),
        en=FinalLangText(
            quote=candidate.en.quote,
            riddle=candidate.en.riddle,
            speaker=candidate.en.speaker,
            listener=candidate.en.listener,
            book=candidate.en.book,
            options=ChoicePools.empty(),
            bonus="serpent",
            bonus_hint=BonusHint(
                quote="And the LORD sent fiery serpents among the people, and they bit the people.",
                source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
            ),
        ),
        he=FinalLangText(
            quote=candidate.he.quote,
            riddle=candidate.he.riddle,
            speaker=candidate.he.speaker,
            listener=candidate.he.listener,
            book=candidate.he.book,
            options=ChoicePools.empty(),
            bonus="הַנָּחָשׁ",
            bonus_hint=BonusHint(
                quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים הַשְּׂרָפִים וַיְנַשְּׁכוּ אֶת הָעָם",
                source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
            ),
        ),
        raw_quote_source=candidate.raw_quote_source,
        ref=RefRange(chapter=3, start=13, end=13),
        meta=FinalMeta(
            mode="llm",
            source="data-proc",
            template_item_id="",
            bonus_source="llm",
            bonus_hint_source="aligned-bible-search",
        ),
    )

    payloads = build_chapter_payloads([item])

    assert len(payloads) == 1
    assert chapter_output_path(tmp_path, payloads[0]).name == "genesis-003.json"


def test_build_character_bank_recursively_splits_invalid_batches(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[
            FinalQuoteItem(
                id="synthetic-1",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=13,
                    quote_verse_end=13,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="the LORD",
                    listener="woman",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="יְהוָה",
                    listener="הָאִשָּׁה",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
                    ),
                ),
                raw_quote_source=candidate.raw_quote_source,
                ref=RefRange(chapter=3, start=13, end=13),
                meta=FinalMeta(
                    mode="llm",
                    source="data-proc",
                    template_item_id="",
                    bonus_source="llm",
                    bonus_hint_source="aligned-bible-search",
                ),
            ),
            FinalQuoteItem(
                id="synthetic-2",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=9,
                    quote_verse_end=9,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="Moses",
                    listener="the people",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="מֹשֶׁה",
                    listener="הָעָם",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
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
            ),
        ],
    )

    class StubLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            self.calls += 1
            if prompt_name == "character-bank-keep-single":
                return {"keep": True}
            if prompt_name == "character-bank-classification-single":
                if '"en": "the LORD"' in user_prompt:
                    return {"category": "divine"}
                if '"en": "Moses"' in user_prompt:
                    return {"category": "leader"}
                if '"en": "the people"' in user_prompt:
                    return {"category": "people_group"}
                return {"category": "woman"}
            entries_json = user_prompt.split("entries: ", 1)[1].split("\n", 1)[0]
            entries = json.loads(entries_json)
            names = {entry["en"] for entry in entries}
            if {"the LORD", "Moses"} <= names:
                return {"items": [{"id": "bad-id", "category": "divine"}]}
            items = []
            for entry in entries:
                category = {
                    "the LORD": "divine",
                    "Moses": "leader",
                    "the people": "people_group",
                    "woman": "woman",
                }[entry["en"]]
                items.append({"id": entry["id"], "category": category})
            return {"items": items}

    llm = StubLLM()
    bank = build_character_bank([payload], llm, batch_size=4)

    assert {entry.en: entry.category for entry in bank.items} == {
        "the LORD": "divine",
        "Moses": "leader",
        "the people": "people_group",
        "woman": "woman",
    }
    assert llm.calls >= 3


def test_build_character_bank_canonicalizes_divine_aliases(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[
            FinalQuoteItem(
                id="synthetic-divine-1",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=13,
                    quote_verse_end=13,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="LORD",
                    listener="woman",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="יְהוָה",
                    listener="הָאִשָּׁה",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
                    ),
                ),
                raw_quote_source=candidate.raw_quote_source,
                ref=RefRange(chapter=3, start=13, end=13),
                meta=FinalMeta(mode="llm", source="data-proc", template_item_id="", bonus_source="llm", bonus_hint_source="aligned-bible-search"),
            ),
            FinalQuoteItem(
                id="synthetic-divine-2",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=13,
                    quote_verse_end=13,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="LORD God of Israel",
                    listener="woman",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="יְהוָה אֱלֹהֵי יִשְׂרָאֵל",
                    listener="הָאִשָּׁה",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
                    ),
                ),
                raw_quote_source=candidate.raw_quote_source,
                ref=RefRange(chapter=3, start=13, end=13),
                meta=FinalMeta(mode="llm", source="data-proc", template_item_id="", bonus_source="llm", bonus_hint_source="aligned-bible-search"),
            ),
        ],
    )

    class StubLLM:
        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            if prompt_name == "character-bank-classification":
                entries_json = user_prompt.split("entries: ", 1)[1].split("\n", 1)[0]
                entries = json.loads(entries_json)
                return {
                    "items": [
                        {"id": entry["id"], "category": "divine" if "lord" in entry["en"].casefold() else "woman"}
                        for entry in entries
                    ]
                }
            if prompt_name == "character-bank-classification-single":
                return {"category": "divine" if '"LORD' in user_prompt else "woman"}
            if prompt_name == "character-bank-keep-single":
                return {"keep": True}
            raise AssertionError(f"unexpected prompt {prompt_name}")

    bank = build_character_bank([payload], StubLLM(), batch_size=4)

    divine_entries = [entry for entry in bank.items if entry.category == "divine"]
    assert len(divine_entries) == 1
    assert divine_entries[0].en == "the LORD"
    assert divine_entries[0].he == "יְהוָה"
    assert "lord" in divine_entries[0].normalized_en_aliases
    assert "lord god of israel" in divine_entries[0].normalized_en_aliases
    assert "יהוה" in divine_entries[0].normalized_he_aliases
    assert "יהוה אלהי ישראל" in divine_entries[0].normalized_he_aliases
    assert divine_entries[0].count == 2


def test_filter_overlapping_chapter_items_keeps_overlapping_turns(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    first = FinalQuoteItem(
        id="synthetic-1",
        source=FinalSource(
            method="llm",
            book_code="GEN",
            book="Genesis",
            book_he="בראשית",
            chapter=3,
            quote_verse_start=13,
            quote_verse_end=13,
        ),
        en=FinalLangText(
            quote=candidate.en.quote,
            riddle=candidate.en.riddle,
            speaker=candidate.en.speaker,
            listener=candidate.en.listener,
            book=candidate.en.book,
            options=ChoicePools.empty(),
            bonus="serpent",
            bonus_hint=BonusHint(
                quote="And the LORD God called unto Adam, and said unto him, Where art thou?",
                source=HintSourceRef(book="Genesis", chapter=3, start=9, end=9),
            ),
        ),
        he=FinalLangText(
            quote=candidate.he.quote,
            riddle=candidate.he.riddle,
            speaker=candidate.he.speaker,
            listener=candidate.he.listener,
            book=candidate.he.book,
            options=ChoicePools.empty(),
            bonus="הנחש",
            bonus_hint=BonusHint(
                quote="וַיִּקְרָא יְהוָה אֱלֹהִים אֶל־הָאָדָם וַיֹּאמֶר לוֹ אַיֶּכָּה",
                source=HintSourceRef(book="בראשית", chapter=3, start=9, end=9),
            ),
        ),
        raw_quote_source=candidate.raw_quote_source,
        ref=RefRange(chapter=3, start=13, end=13),
        meta=FinalMeta(
            mode="llm",
            source="data-proc",
            template_item_id="",
            bonus_source="llm",
            bonus_hint_source="aligned-bible-search",
        ),
    )
    second = replace(
        first,
        id="synthetic-2",
        source=replace(first.source, quote_verse_start=13, quote_verse_end=14),
        ref=RefRange(chapter=3, start=13, end=14),
    )
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[first, second],
    )

    kept, dropped = _filter_overlapping_chapter_items(payload)

    assert [item.id for item in kept] == ["synthetic-1", "synthetic-2"]
    assert dropped == []


def test_read_character_bank_normalizes_stale_divine_aliases(tmp_path) -> None:
    path = tmp_path / "bank.json"
    path.write_text(
        json.dumps(
            {
                "taxonomy": list(),
                "items": [
                    {
                        "id": "old-1",
                        "en": "LORD",
                        "he": "יְהוָה",
                        "normalized_en_aliases": ["lord"],
                        "normalized_he_aliases": ["יהוה"],
                        "books": ["GEN"],
                        "observed_fields": ["speaker"],
                        "count": 2,
                        "category": "divine",
                    },
                    {
                        "id": "old-2",
                        "en": "LORD God of Israel",
                        "he": "יְהוָה אֱלֹהֵי יִשְׂרָאֵל",
                        "normalized_en_aliases": ["lord god of israel"],
                        "normalized_he_aliases": ["יהוה אלהי ישראל"],
                        "books": ["2KI"],
                        "observed_fields": ["speaker"],
                        "count": 1,
                        "category": "divine",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bank = read_character_bank(path)

    assert len(bank.items) == 1
    assert bank.items[0].en == "the LORD"
    assert bank.items[0].he == "יְהוָה"
    assert bank.items[0].count == 3


def test_options_builder_skips_unresolved_individual_roles_without_llm(generated_payloads) -> None:
    payload = next(payload for payload in generated_payloads if payload.book_code == "JOB" and payload.chapter == 13)
    item = next(item for item in payload.items if item.id == "job-13-11-11")
    item = replace(
        item,
        en=replace(item.en, speaker="he", listener="him"),
        he=replace(item.he, speaker="הוא", listener="אותו"),
    )
    bank = read_character_bank(CHARACTER_BANK_PATH)

    class StubLLM:
        def chat_json(self, *args, **kwargs):
            raise AssertionError("LLM should not be called for unresolved individual roles")

    updated, issues, _ = OptionsBuilder(bank=bank, llm=StubLLM()).apply_options(item)

    assert updated.en.options.speaker == []
    assert updated.en.options.listener == []
    assert updated.he.options.speaker == []
    assert updated.he.options.listener == []
    assert {issue.reason for issue in issues} == {"speaker_options_failed", "listener_options_failed"}
    assert any(issue.detail == "unresolved true speaker role" for issue in issues)
    assert any(issue.detail == "unresolved true listener role" for issue in issues)


def test_build_character_bank_uses_single_entry_category_prompt_after_split(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[
            FinalQuoteItem(
                id="synthetic-single",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=13,
                    quote_verse_end=13,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="Lot",
                    listener="Abram",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="לוט",
                    listener="אברם",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
                    ),
                ),
                raw_quote_source=candidate.raw_quote_source,
                ref=RefRange(chapter=3, start=13, end=13),
                meta=FinalMeta(
                    mode="llm",
                    source="data-proc",
                    template_item_id="",
                    bonus_source="llm",
                    bonus_hint_source="aligned-bible-search",
                ),
            )
        ],
    )

    class StubLLM:
        def __init__(self) -> None:
            self.prompt_names: list[str] = []

        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            self.prompt_names.append(prompt_name)
            if prompt_name == "character-bank-classification-single":
                return {"category": "family"}
            if prompt_name == "character-bank-keep-single":
                return {"keep": True}
            raise AssertionError(f"unexpected prompt {prompt_name}")

    llm = StubLLM()
    bank = build_character_bank([payload], llm, batch_size=1)

    assert {entry.en: entry.category for entry in bank.items} == {"Lot": "family", "Abram": "family"}
    assert llm.prompt_names == [
        "character-bank-classification-single",
        "character-bank-classification-single",
        "character-bank-keep-single",
        "character-bank-keep-single",
    ]


def test_build_character_bank_repairs_invalid_single_entry_category(candidate_map) -> None:
    candidate = candidate_map["genesis-03-13-13"]
    payload = ChapterPayload(
        book_code="GEN",
        book="Genesis",
        book_he="בראשית",
        chapter=3,
        mode="llm",
        items=[
            FinalQuoteItem(
                id="synthetic-single-repair",
                source=FinalSource(
                    method="llm",
                    book_code="GEN",
                    book="Genesis",
                    book_he="בראשית",
                    chapter=3,
                    quote_verse_start=13,
                    quote_verse_end=13,
                ),
                en=FinalLangText(
                    quote=candidate.en.quote,
                    riddle=candidate.en.riddle,
                    speaker="Lot",
                    listener="Abram",
                    book="Genesis",
                    options=ChoicePools.empty(),
                    bonus="serpent",
                    bonus_hint=BonusHint(
                        quote="And the LORD sent fiery serpents among the people.",
                        source=HintSourceRef(book="Numbers", chapter=21, start=6, end=6),
                    ),
                ),
                he=FinalLangText(
                    quote=candidate.he.quote,
                    riddle=candidate.he.riddle,
                    speaker="לוט",
                    listener="אברם",
                    book="בראשית",
                    options=ChoicePools.empty(),
                    bonus="הַנָּחָשׁ",
                    bonus_hint=BonusHint(
                        quote="וַיְשַׁלַּח יְהוָה בָּעָם אֵת הַנְּחָשִׁים.",
                        source=HintSourceRef(book="במדבר", chapter=21, start=6, end=6),
                    ),
                ),
                raw_quote_source=candidate.raw_quote_source,
                ref=RefRange(chapter=3, start=13, end=13),
                meta=FinalMeta(
                    mode="llm",
                    source="data-proc",
                    template_item_id="",
                    bonus_source="llm",
                    bonus_hint_source="aligned-bible-search",
                ),
            )
        ],
    )

    class StubLLM:
        def __init__(self) -> None:
            self.prompt_names: list[str] = []

        def chat_json(self, prompt_name: str, system_prompt: str, user_prompt: str, *, required_keys=()):
            self.prompt_names.append(prompt_name)
            if prompt_name == "character-bank-classification-single":
                return {"category": "{}"}
            if prompt_name == "character-bank-classification-single-repair":
                return {"category": "family"}
            if prompt_name == "character-bank-keep-single":
                return {"keep": True}
            raise AssertionError(f"unexpected prompt {prompt_name}")

    llm = StubLLM()
    bank = build_character_bank([payload], llm, batch_size=1)

    assert {entry.en: entry.category for entry in bank.items} == {"Lot": "family", "Abram": "family"}
    assert llm.prompt_names == [
        "character-bank-classification-single",
        "character-bank-classification-single-repair",
        "character-bank-classification-single",
        "character-bank-classification-single-repair",
        "character-bank-keep-single",
        "character-bank-keep-single",
    ]
