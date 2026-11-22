from pathlib import Path
from types import SimpleNamespace

from myloai.core.domain import ChatMessage, ChatSession, SkillRecord
from myloai.core.managers import SkillManager, apply_skill_to_session


def make_manager(tmp_path: Path) -> SkillManager:
    paths = SimpleNamespace(skills_dir=tmp_path / "skills")
    return SkillManager(SimpleNamespace(paths=paths))


def test_skill_roundtrip_and_apply(tmp_path):
    manager = make_manager(tmp_path)
    skill = SkillRecord(
        name="Code Reviewer",
        instructions="Review code for bugs.",
        description="Reviews code",
        version="1.2.0",
        tags=["code", "review"],
    )
    manager.upsert(skill)

    loaded = manager.get(skill.id)
    assert loaded is not None
    assert loaded.name == "Code Reviewer"
    assert loaded.instructions == "Review code for bugs."
    assert loaded.tags == ["code", "review"]
    assert len(manager.list()) == 1

    session = ChatSession()
    session.messages.append(ChatMessage("system", "old"))
    apply_skill_to_session(session, loaded)
    assert session.system_prompt == "Review code for bugs."
    assert session.messages[0].content == "Review code for bugs."

    manager.delete(skill.id)
    assert manager.list() == []


def test_skill_import_export(tmp_path):
    manager = make_manager(tmp_path)
    source = tmp_path / "imported.md"
    source.write_text(
        "---\nname: Writer\ndescription: Helps write\nversion: 2.0.0\ntags: writing\n---\n\nWrite clearly.\n",
        encoding="utf-8",
    )
    skill = manager.import_file(source)
    assert skill.name == "Writer"
    assert skill.instructions == "Write clearly."
    assert skill.version == "2.0.0"

    dest = tmp_path / "exported.md"
    manager.export(skill, dest)
    assert "name: Writer" in dest.read_text(encoding="utf-8")
