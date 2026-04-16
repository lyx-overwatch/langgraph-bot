import re
from pathlib import Path
from typing import Any


class SkillLoader:
	def __init__(self, skills_dir: Path):
		self.skills: dict[str, dict[str, Any]] = {}
		if skills_dir.exists():
			for f in sorted(skills_dir.rglob("SKILL.md")):
				text = f.read_text(encoding="utf-8")
				match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
				meta: dict[str, str] = {}
				body = text
				if match:
					for line in match.group(1).strip().splitlines():
						if ":" in line:
							k, v = line.split(":", 1)
							meta[k.strip()] = v.strip()
					body = match.group(2).strip()
				name = meta.get("name", f.parent.name)
				self.skills[name] = {"meta": meta, "body": body}

	def descriptions(self) -> str:
		if not self.skills:
			return "(no skills)"
		return "\n".join(
			f"  - {n}: {s['meta'].get('description', '-')}"
			for n, s in self.skills.items()
		)

	def load(self, name: str, *, workspace: Path | None = None, task_hint: str | None = None) -> str:
		skill = self.skills.get(name)
		if not skill:
			return (
				f"Error: Unknown skill '{name}'. "
				f"Available: {', '.join(self.skills.keys())}"
			)
		# Import here so preprocessors are lazily registered (avoids circular imports).
		from agent.tools.preprocessors.registry import run_preprocessors

		body = run_preprocessors(name, skill["body"], workspace=workspace, task_hint=task_hint)
		return f"<skill name=\"{name}\">\n{body}\n</skill>"