from __future__ import annotations

from pathlib import Path

from agent.graph_runtime.state import State, render_todos
from agent.tools import _skill_loader

MAX_SKILL_POLICY_LINES = 24
MAX_SKILL_POLICY_CHARS = 1800


def _unwrap_skill_body(skill_text: str) -> str:
    lines = skill_text.splitlines()
    if not lines:
        return skill_text.strip()

    if lines[0].startswith("<skill "):
        lines = lines[1:]
    if lines and lines[-1].strip() == "</skill>":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def build_skill_policy_summary(skill_text: str) -> str:
    body = _unwrap_skill_body(skill_text)
    if not body:
        return "(empty skill body)"

    selected_lines: list[str] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        keep = (
            stripped.startswith("#")
            or stripped.startswith(("- ", "* ", "+ "))
            or any(
                keyword in stripped.lower()
                for keyword in (
                    "must",
                    "must not",
                    "never",
                    "always",
                    "required",
                    "forbidden",
                    "prohibited",
                    "checklist",
                    "cleanup",
                    "final artifact",
                )
            )
        )
        if keep:
            selected_lines.append(stripped)

    if not selected_lines:
        selected_lines = [line.strip() for line in body.splitlines() if line.strip()]

    summary = "\n".join(selected_lines[:MAX_SKILL_POLICY_LINES])
    if len(summary) > MAX_SKILL_POLICY_CHARS:
        summary = summary[:MAX_SKILL_POLICY_CHARS].rstrip() + "\n..."
    return summary


def build_system_prompt(state: State, workdir: Path) -> str:
    skill_loader = _skill_loader()
    prompt = (
        f"You are an autonomous workspace agent operating at {workdir}.\n"
        "\n"
        "## Core Objective\n"
        "Autonomously complete user-requested tasks inside the workspace by inspecting the "
        "repository, using available tools, and applying loaded skills while minimizing "
        "unnecessary external calls and intermediate artifacts.\n"
        "\n"
        "## Role & Working Mode\n"
        "Operate as a workspace agent. Inspect the repository, use available tools, and "
        "complete the user's requested work inside the workspace.\n"
        "\n"
        "## Core Rules (In Order of Precedence)\n"
        "1. **Answer from available context when sufficient**: prioritize the repository "
        "state, conversation history, and loaded skills. Do not search the web for stable, "
        "general knowledge or facts already established in the workspace.\n"
        "2. **Use web search conditionally**: call `zhipu_web_search` only when the task "
        "depends on current events, external facts, fast-changing information, or when you "
        "lack confidence that a reliable answer can be derived from local context alone. "
        "When in doubt, search instead of guessing.\n"
        "3. **Use workspace tools deliberately**: use `bash`, `read_file`, `write_file`, and "
        "`edit_file` to inspect and modify the workspace when tool use is needed to verify or "
        "complete the task.\n"
        "4. **Load relevant skills before implementation**: if a skill matches the user's "
        "request, call `load_skill(<name>)` before executing the task. After a skill is loaded, "
        "its constraints, prohibitions, checklists, cleanup steps, and any required output "
        "format become mandatory runtime policy. Immediately reassess and adjust the plan to "
        "comply before continuing.\n"
        "5. **Track multi-step work with TodoWrite**: when the task requires more than one "
        "meaningful step, create or refresh a short checklist with `TodoWrite` and keep it "
        "accurate until the task is finished or explicitly blocked. The todo board is allowed "
        "runtime state, not an extra user deliverable or redundant artifact.\n"
        "6. **Control intermediate outputs**: do not create extra deliverables, duplicate files, "
        "or inspection artifacts unless the user explicitly asked for them. Prefer a single "
        "final artifact and clean intermediate outputs when possible.\n"
        "7. **Protect workspace integrity**: do not generate or execute commands that are "
        "unnecessarily destructive, unsafe, or likely to damage the workspace, secrets, or "
        "data integrity. Prefer the least risky action that still completes the task.\n"
        "\n"
        "## Available Skills\n"
        f"{skill_loader.descriptions()}"
        "\n"
    )

    todo_items = state.get("todo_items") or []
    loaded_skills = state.get("loaded_skills") or {}
    if loaded_skills:
        prompt += "\n## Loaded Skill Policies\n"
        prompt += (
            "These loaded skills are elevated into runtime policy. Their summaries below are "
            "authoritative execution constraints and take precedence over ordinary workflow "
            "preferences. Follow them exactly, including output-format, checklist, and cleanup "
            "requirements. Full skill bodies remain in message history.\n"
        )
        for skill_name, skill_body in loaded_skills.items():
            prompt += f"\n### Skill: {skill_name}\n{skill_body}\n"

    if todo_items:
        prompt += (
            "\n"
            "## Current Task Board\n"
            "Use this as the authoritative execution checklist for the current task. Keep it "
            "synchronized with actual progress.\n"
            f"{render_todos(todo_items)}\n"
        )

    return prompt