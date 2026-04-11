from __future__ import annotations

import json
import zipfile

from click.testing import CliRunner

from data_proc.source_reader import build_source_reader_archive, build_source_reader_command
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


def test_build_source_reader_archive_writes_index_and_chapters(tmp_path) -> None:
    archive_path = tmp_path / "source.zip"
    chapters_written, index_payload = build_source_reader_archive(build_stub_tandem(), archive_path)

    assert chapters_written == 2
    assert [book["slug"] for book in index_payload["books"]] == ["genesis", "exodus"]
    assert [book["chapter_count"] for book in index_payload["books"]] == [1, 33]

    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["exodus/", "exodus/chapter33.json", "genesis/", "genesis/chapter1.json", "index.json"]

        written_index = json.loads(archive.read("index.json").decode("utf-8"))
        assert written_index["books"][0]["chapter_count"] == 1
        assert written_index["books"][1]["chapter_count"] == 33

        exodus_payload = json.loads(archive.read("exodus/chapter33.json").decode("utf-8"))

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
    archive_path = tmp_path / "filtered.zip"
    monkeypatch.setattr("data_proc.source_reader.TandemBible.load", lambda english_xml, hebrew_zip: build_stub_tandem())

    result = CliRunner().invoke(
        build_source_reader_command,
        ["--out-file", str(archive_path), "--book", "Exodus", "--chapter", "33"],
    )

    assert result.exit_code == 0

    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["exodus/", "exodus/chapter33.json", "index.json"]
        written_index = json.loads(archive.read("index.json").decode("utf-8"))

    assert written_index == {
        "books": [
            {
                "code": "EXO",
                "slug": "exodus",
                "en": "Exodus",
                "he": "שמות",
                "chapter_count": 33,
            }
        ]
    }
