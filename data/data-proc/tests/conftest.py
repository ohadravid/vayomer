from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_proc.corpus import BibleCorpus
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.schema import CandidateItem, ChapterPayload, iter_chapter_payloads

REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATES_PATH = REPO_ROOT / "data/processed/candidates.jsonl"
GENERATED_DIR = REPO_ROOT / "data/processed/generated"


@pytest.fixture(scope="session")
def candidate_map() -> dict[str, CandidateItem]:
    items: dict[str, CandidateItem] = {}
    with CANDIDATES_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            item = CandidateItem.from_dict(json.loads(stripped))
            items[item.id] = item
    return items


@pytest.fixture(scope="session")
def bible_corpus() -> BibleCorpus:
    return BibleCorpus(english_xml=DEFAULT_ENGLISH_XML, hebrew_zip=DEFAULT_HEBREW_ZIP)


@pytest.fixture(scope="session")
def generated_payloads() -> list[ChapterPayload]:
    return iter_chapter_payloads(GENERATED_DIR)
