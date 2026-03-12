from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

ROOT_DOCS = [
    ROOT / "README.md",
    ROOT / "SKILL.md",
]

SUBSKILL_NAMES = {
    "mail": "Почта",
    "calendar": "Календарь",
    "contacts": "Контакты",
    "directory": "Директория",
    "disk": "Диск",
    "telemost": "Телемост",
    "search": "Поиск",
    "cloud": "Облако",
    "forms": "Формы",
    "tracker": "Трекер",
}

SUBSKILL_DOCS = {
    "mail": ROOT / "mail" / "mail.md",
    "calendar": ROOT / "calendar" / "calendar.md",
    "contacts": ROOT / "contacts" / "contacts.md",
    "directory": ROOT / "directory" / "directory.md",
    "disk": ROOT / "disk" / "disk.md",
    "telemost": ROOT / "telemost" / "telemost.md",
    "search": ROOT / "search" / "search.md",
    "cloud": ROOT / "cloud" / "cloud.md",
    "forms": ROOT / "forms" / "forms.md",
    "tracker": ROOT / "tracker" / "tracker.md",
}


def test_root_docs_list_all_subskills() -> None:
    contents = "\n".join(path.read_text(encoding="utf-8") for path in ROOT_DOCS)
    for subskill in SUBSKILL_NAMES:
        assert f"[{subskill}]({subskill}/)" in contents


def test_root_docs_include_russian_skill_names() -> None:
    contents = "\n".join(path.read_text(encoding="utf-8") for path in ROOT_DOCS)
    for russian_name in SUBSKILL_NAMES.values():
        assert russian_name in contents


def test_each_subskill_doc_contains_english_and_russian_name() -> None:
    for subskill, russian_name in SUBSKILL_NAMES.items():
        content = SUBSKILL_DOCS[subskill].read_text(encoding="utf-8")
        assert russian_name in content
        assert subskill in content.lower()
