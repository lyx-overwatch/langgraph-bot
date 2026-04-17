from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

TODO_PENDING = "pending"
TODO_IN_PROGRESS = "in_progress"
TODO_COMPLETED = "completed"
TODO_STATUSES = {TODO_PENDING, TODO_IN_PROGRESS, TODO_COMPLETED}
MAX_CONTINUATION_ATTEMPTS = 8


class State(TypedDict):
    messages: Annotated[list, add_messages]
    loaded_skills: dict[str, str]
    todo_items: list[dict[str, str]]
    rounds_without_todo: int
    completion_blocked: bool
    continuation_required: bool
    continuation_attempts: int
    last_model_finish_reason: str | None


def render_todos(items: list[dict[str, str]]) -> str:
    if not items:
        return "No todos."

    lines: list[str] = []
    for item in items:
        mark = {
            TODO_COMPLETED: "[x]",
            TODO_IN_PROGRESS: "[>]",
            TODO_PENDING: "[ ]",
        }.get(item["status"], "[?]")
        suffix = f" <- {item['activeForm']}" if item["status"] == TODO_IN_PROGRESS else ""
        lines.append(f"{mark} {item['content']}{suffix}")

    completed = sum(1 for item in items if item["status"] == TODO_COMPLETED)
    lines.append(f"\n({completed}/{len(items)} completed)")
    return "\n".join(lines)


def normalize_todo_items(raw_items: Any) -> list[dict[str, str]]:
    if not isinstance(raw_items, list):
        raise ValueError("`items` must be a list")

    validated: list[dict[str, str]] = []
    in_progress_count = 0
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index}: must be an object")

        content = str(item.get("content", "")).strip()
        status = str(item.get("status", TODO_PENDING)).strip().lower()
        active_form = str(item.get("activeForm", "")).strip()

        if not content:
            raise ValueError(f"Item {index}: content required")
        if status not in TODO_STATUSES:
            raise ValueError(
                f"Item {index}: status must be one of {sorted(TODO_STATUSES)}"
            )
        if not active_form:
            raise ValueError(f"Item {index}: activeForm required")
        if status == TODO_IN_PROGRESS:
            in_progress_count += 1

        validated.append(
            {
                "content": content,
                "status": status,
                "activeForm": active_form,
            }
        )

    if len(validated) > 20:
        raise ValueError("At most 20 todo items are allowed")
    if in_progress_count > 1:
        raise ValueError("Only one todo item can be in_progress")
    return validated


def has_open_todos(items: list[dict[str, str]]) -> bool:
    return any(item["status"] != TODO_COMPLETED for item in items)


def get_finish_reason(message: AIMessage) -> str | None:
    metadata = getattr(message, "response_metadata", None)
    if not isinstance(metadata, dict):
        return None

    finish_reason = metadata.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason.strip():
        return finish_reason.strip().lower()
    return None


def build_continuation_message(attempt: int) -> str:
    return (
        "<continuation-reminder>"
        f"The previous model response ended because of the output length limit. This is continuation attempt {attempt}. "
        "Continue the same task from the exact stopping point. Do not restart the answer, do not create an alternate shorter version, "
        "and do not overwrite completed sections. If a file was partially written, inspect the file tail and append only the missing content. "
        "Prefer smaller chunks and finish the current missing section before doing anything else."
        "</continuation-reminder>"
    )


def build_continuation_gate_message(attempt: int) -> str:
    prefix = (
        "The previous response was cut off by the model length limit. "
        if attempt < MAX_CONTINUATION_ATTEMPTS
        else "The model has hit the length limit repeatedly. Continue in much smaller chunks. "
    )
    return (
        "<continuation-gate>"
        f"{prefix}Do not conclude the task yet. Continue from the exact stopping point, avoid restarting from the beginning, "
        "and avoid creating alternate versions unless the user explicitly asked for them."
        "</continuation-gate>"
    )