from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

from agent.tools.bash import run_bash_command
from agent.tools.file import WORKDIR, run_edit, run_read, run_write
from agent.tools.skills import SkillLoader

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_DIR_NAME = ".skills"


def _resolve_skills_dir() -> Path:
	configured = os.getenv("AGENT_SKILLS_DIR")
	if configured:
		configured_path = Path(configured)
		if not configured_path.is_absolute():
			configured_path = PROJECT_ROOT / configured_path
		return configured_path.resolve()
	return (AGENT_ROOT / DEFAULT_SKILLS_DIR_NAME).resolve()


@lru_cache(maxsize=1)
def _skill_loader() -> SkillLoader:
	return SkillLoader(_resolve_skills_dir())


@tool("bash")
def bash_tool(command: str, timeout: int = 30) -> str:
	"""Inspect the workspace with short read-only shell commands. Prefer rg, ls, cat, git status, git diff, head, tail, sed, and wc."""
	return run_bash_command(command=command, cwd=WORKDIR, timeout=timeout)


@tool("read_file")
def read_file_tool(path: str, limit: int | None = None) -> str:
	"""Read a small UTF-8 text file from the workspace. Use this before editing and keep paths inside the workspace."""
	return run_read(path=path, limit=limit)


@tool("write_file")
def write_file_tool(path: str, content: str) -> str:
	"""Create or overwrite a small text file inside the workspace. Prefer for markdown, json, toml, yaml, and python files."""
	return run_write(path=path, content=content)


@tool("edit_file")
def edit_file_tool(path: str, old_text: str, new_text: str) -> str:
	"""Make a targeted single replacement in a small workspace text file when you already know the exact old text."""
	return run_edit(path=path, old_text=old_text, new_text=new_text)



@tool("load_skill")
def load_skill_tool(name: str) -> str:
	"""Load one local skill by exact name after checking list_skills. Returns the SKILL.md content wrapped in a skill tag."""
	return _skill_loader().load(name)


CUSTOM_TOOLS = [
	bash_tool,
	read_file_tool,
	write_file_tool,
	edit_file_tool,
	load_skill_tool,
]


__all__ = ["CUSTOM_TOOLS"]
