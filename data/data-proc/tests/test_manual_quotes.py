from __future__ import annotations

from dataclasses import dataclass

from data_proc.manual_quotes import (
    DEFAULT_SPEC_DIR,
    build_manual_chapter_payloads,
    load_manual_specs,
    manual_chapter_output_path,
)


@dataclass(frozen=True)
class StubRangeQuote:
    book_en: str = "Numbers"
    book_he: str = "במדבר"
    en_quote: str = (
        "And Moses said unto Hobab, the son of Raguel the Midianite, Moses' father in law, "
        "We are journeying unto the place of which the LORD said, I will give it you: "
        "come thou with us, and we will do thee good: for the LORD hath spoken good concerning Israel."
    )
    he_quote: str = (
        "וַיֹּאמֶר מֹשֶׁה לְחֹבָב בֶּן־רְעוּאֵל הַמִּדְיָנִי חֹתֵן מֹשֶׁה "
        "נֹסְעִים אֲנַחְנוּ אֶל־הַמָּקוֹם אֲשֶׁר אָמַר יְהוָה אֹתוֹ אֶתֵּן לָכֶם "
        "לְכָה אִתָּנוּ וְהֵטַבְנוּ לָךְ כִּֽי־יְהוָה דִּבֶּר־טוֹב עַל־יִשְׂרָאֵֽל"
    )
    raw_quote_source: dict[str, dict[str, str]] | None = None
    missing: list[int] | None = None


class StubCorpus:
    def collect_range(self, book_code: str, chapter: int, start: int, end: int) -> StubRangeQuote:
        if (book_code, chapter, start, end) == ("GEN", 33, 12, 12):
            return StubRangeQuote(
                book_en="Genesis",
                book_he="בראשית",
                en_quote="And he said, Let us take our journey, and let us go, and I will go before thee.",
                he_quote="וַיֹּאמֶר נִסְעָה וְנֵלֵכָה וְאֵלְכָה לְנֶגְדֶּֽךָ",
                raw_quote_source=None,
                missing=[],
            )

        assert (book_code, chapter, start, end) == ("NUM", 10, 29, 29)
        return StubRangeQuote(
            raw_quote_source={
                "en": {
                    "29": "And Moses said unto Hobab, the son of Raguel the Midianite, Moses' father in law, We are journeying unto the place of which the LORD said, I will give it you: come thou with us, and we will do thee good: for the LORD hath spoken good concerning Israel."
                },
                "he": {
                    "29": "וַיֹּאמֶר מֹשֶׁה לְחֹבָב בֶּן־רְעוּאֵל הַמִּדְיָנִי חֹתֵן מֹשֶׁה נֹסְעִים ׀ אֲנַחְנוּ אֶל־הַמָּקוֹם אֲשֶׁר אָמַר יְהוָה אֹתוֹ אֶתֵּן לָכֶם לְכָה אִתָּנוּ וְהֵטַבְנוּ לָךְ כִּֽי־יְהוָה דִּבֶּר־טוֹב עַל־יִשְׂרָאֵֽל׃"
                },
            },
            missing=[],
        )


def test_numbers_manual_spec_builds_expected_payload(tmp_path) -> None:
    spec = next(spec for spec in load_manual_specs(DEFAULT_SPEC_DIR) if spec.id == "manual-numbers-10-29-29-d5882096")

    payloads = build_manual_chapter_payloads([spec], StubCorpus())

    assert len(payloads) == 1
    payload = payloads[0]
    assert manual_chapter_output_path(tmp_path, payload).name == "numbers-010.json"
    assert payload["book_code"] == "NUM"
    assert payload["mode"] == "manual"

    item = payload["items"][0]
    assert item["id"] == "manual-numbers-10-29-29-d5882096"
    assert item["source"]["method"] == "manual"
    assert item["source"]["quote_verse_start"] == 29
    assert item["source"]["quote_verse_end"] == 29
    assert item["he"]["riddle"] == "לְכָה אִתָּנוּ וְהֵטַבְנוּ לָךְ"
    assert item["he"]["speaker"] == "מֹשֶׁה"
    assert item["he"]["listener"] == "יִתְרוֹ חֹתְנוֹ"
    assert item["he"]["bonus"] == "נֹסְעִים"
    assert item["en"]["listener"] == "Jethro, Moses' father-in-law"
    assert item["en"]["bonus"] == "journeying"
    assert item["en"]["bonus_hint"]["quote"] == "Let us take our journey"
    assert item["en"]["bonus_hint"]["source"] == {"book": "Genesis", "chapter": 33, "start": 12, "end": 12}
    assert item["he"]["bonus_hint"]["quote"] == "נִסְעָה וְנֵלֵכָה"
    assert item["he"]["bonus_hint"]["source"] == {"book": "בראשית", "chapter": 33, "start": 12, "end": 12}
    assert item["raw_quote_source"]["he"]["29"].startswith("וַיֹּאמֶר מֹשֶׁה")
    assert item["meta"]["source"] == "manual-spec"
