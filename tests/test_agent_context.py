from pathlib import Path

from sago.utils.agent_context import load_agent_context


def test_load_agent_context_detects_supported_files(tmp_path: Path) -> None:
    (tmp_path / "IMPORTANT.md").write_text("# Important\nFollow the constraints.\n")
    (tmp_path / "SKILLS.md").write_text("# Skills\n- Strong at refactors\n")
    (tmp_path / ".cursorrules").write_text("Always read PLAN.md first.\n")

    snapshot = load_agent_context(tmp_path)

    assert snapshot.present is True
    assert snapshot.file_paths == ["IMPORTANT.md", "SKILLS.md", ".cursorrules"]
    assert snapshot.errors == []


def test_agent_context_prompt_block_includes_metadata(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Agents\nShared instructions.\n")

    snapshot = load_agent_context(tmp_path)
    prompt_block = snapshot.to_prompt_block()

    assert "external coding agent contract" in prompt_block
    assert "AGENTS.md (shared_agent_instructions)" in prompt_block
    assert "Shared instructions." in prompt_block


def test_load_agent_context_records_read_errors(tmp_path: Path) -> None:
    broken = tmp_path / "SKILLS.md"
    broken.write_bytes(b"\x80\x81not-utf8")

    snapshot = load_agent_context(tmp_path)

    assert snapshot.present is False
    assert snapshot.errors
    assert "SKILLS.md" in snapshot.errors[0]
