from __future__ import annotations

import json

from click.testing import CliRunner

from data_proc.source_reader import build_source_reader_command, build_source_reader_outputs
from data_proc.utils.bible_tandem import TandemBible


def build_stub_tandem() -> TandemBible:
    english_map = {
        ("GEN", 1, 1): "In the beginning God created the heaven and the earth.",
        ("GEN", 1, 2): "And the earth was without form, and void.",
        ("EXO", 33, 5): "For the LORD had said unto Moses.",
    }
    hebrew_map = {
        ("GEN", 1, 1): "בְּרֵאשִׁית בָּרָא אֱלֹהִים",
        ("GEN", 1, 2): "וְהָאָרֶץ הָיְתָה תֹהוּ וָבֹהוּ",
        ("EXO", 33, 5): "וַיֹּאמֶר יְהוָה אֶל־מֹשֶׁה",
    }
    return TandemBible(english_map=english_map, hebrew_map=hebrew_map)


def test_build_source_reader_outputs_writes_index_and_chapters(tmp_path) -> None:
    chapters_written, index_payload = build_source_reader_outputs(build_stub_tandem(), tmp_path)

    assert chapters_written == 2
    assert [book["slug"] for book in index_payload["books"]] == ["genesis", "exodus"]

    written_index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert written_index["books"][0]["chapters"] == [1]
    assert written_index["books"][1]["chapters"] == [33]

    exodus_payload = json.loads((tmp_path / "exodus" / "chapter33.json").read_text(encoding="utf-8"))
    assert exodus_payload == {
        "book_code": "EXO",
        "slug": "exodus",
        "book": "Exodus",
        "book_he": "שמות",
        "chapter": 33,
        "verses": [
            {
                "verse": 5,
                "en": "For the LORD had said unto Moses.",
                "he": "וַיֹּאמֶר יְהוָה אֶל־מֹשֶׁה",
            }
        ],
    }


def test_build_source_reader_command_supports_filters(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("data_proc.source_reader.TandemBible.load", lambda english_xml, hebrew_zip: build_stub_tandem())

    result = CliRunner().invoke(
        build_source_reader_command,
        ["--out-dir", str(tmp_path), "--book", "Exodus", "--chapter", "33"],
    )

    assert result.exit_code == 0
    assert (tmp_path / "exodus" / "chapter33.json").exists()
    assert not (tmp_path / "genesis").exists()

    written_index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert written_index == {
        "books": [
            {
                "code": "EXO",
                "slug": "exodus",
                "en": "Exodus",
                "he": "שמות",
                "chapters": [33],
            }
        ]
    }
