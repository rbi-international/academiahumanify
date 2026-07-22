"""Tests for the zero-dependency .env loader."""

from __future__ import annotations

from pathlib import Path

from app.config import load_env


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_keys_skipping_comments_and_blanks(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '# a comment\nOPENROUTER_API_KEY=sk-abc123\n\nHF_TOKEN="hf_xyz"\nEMPTY=\n',
    )
    env: dict[str, str] = {}
    applied = load_env(path, environ=env)
    assert applied == {"OPENROUTER_API_KEY": "sk-abc123", "HF_TOKEN": "hf_xyz"}
    assert env["OPENROUTER_API_KEY"] == "sk-abc123"
    assert env["HF_TOKEN"] == "hf_xyz"  # surrounding quotes stripped
    assert "EMPTY" not in env  # empty values are skipped


def test_existing_environment_wins_unless_override(tmp_path: Path) -> None:
    path = _write(tmp_path, "OPENAI_API_KEY=from-file\n")
    env = {"OPENAI_API_KEY": "from-shell"}
    load_env(path, environ=env)
    assert env["OPENAI_API_KEY"] == "from-shell"  # shell value kept
    load_env(path, environ=env, override=True)
    assert env["OPENAI_API_KEY"] == "from-file"  # override forces the file value


def test_missing_file_is_harmless() -> None:
    assert load_env("no/such/.env", environ={}) == {}
