"""LangGraph runtime with explicit skill-loading and execution gates."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent.debugger import write_interaction_log as log_interaction
from agent.tools import CUSTOM_TOOLS, _skill_loader

load_dotenv()

PROJECT_ROOT = Path.cwd()
DEBUGGER_DIR = PROJECT_ROOT / "debugger"
WORKDIR = PROJECT_ROOT / "workspace"
DEFAULT_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_MAX_RETRIES = 2


TODO_PENDING = "pending"
TODO_IN_PROGRESS = "in_progress"
TODO_COMPLETED = "completed"
TODO_STATUSES = {TODO_PENDING, TODO_IN_PROGRESS, TODO_COMPLETED}
MAX_SKILL_POLICY_LINES = 24
MAX_SKILL_POLICY_CHARS = 1800

def _set_optional_env(name: str) -> None:
    value = os.getenv(name)
    if value:
        os.environ[name] = value


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _format_runtime_error(error: Exception, *, timeout_seconds: int | None = None) -> str:
    error_name = type(error).__name__
    message = str(error).strip()
    lowered = f"{error_name} {message}".lower()

    if "timeout" in lowered:
        return (
            f"请求超时，已在 {timeout_seconds or DEFAULT_LLM_TIMEOUT_SECONDS} 秒后中止本轮调用。"
            "请稍后重试，或缩小问题范围后再试。"
        )
    if "connection" in lowered or "api_connection" in lowered:
        return "模型服务连接失败，本轮已安全结束。请检查网络或稍后重试。"
    return f"调用失败：{error_name}。本轮已安全结束，请稍后重试。"


_set_optional_env("DEEPSEEK_API_KEY")

def _render_todos(items: list[dict[str, str]]) -> str:
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


def _normalize_todo_items(raw_items: Any) -> list[dict[str, str]]:
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


def _has_open_todos(items: list[dict[str, str]]) -> bool:
    return any(item["status"] != TODO_COMPLETED for item in items)


def _unwrap_skill_body(skill_text: str) -> str:
    lines = skill_text.splitlines()
    if not lines:
        return skill_text.strip()

    if lines[0].startswith("<skill "):
        lines = lines[1:]
    if lines and lines[-1].strip() == "</skill>":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_skill_policy_summary(skill_text: str) -> str:
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


def build_system_prompt(state: "State") -> str:
    skill_loader = _skill_loader()
    prompt = (
        f"You are a agent at {WORKDIR}.\n"
        "\n"
        "## Working Priority\n"
        "1. **Web search first**: before answering any factual, up-to-date, or "
        "otherwise unknown question, use `zhipu_web_search` to search the internet. "
        "Do NOT guess or rely on training data alone.\n"
        "2. **Tools**: use `bash`, `read_file`, `write_file`, `edit_file` to "
        "inspect and modify the workspace.\n"
        "3. **Task execution**: for any work that takes more than one meaningful step, "
        "first create or refresh a short task list with `TodoWrite`. Keep it accurate "
        "until all work is done.\n"
        "4. **Skills**: if a skill matches the user's request, call "
        "`load_skill(<name>)` before implementation. After a skill is loaded, treat its "
        "constraints, prohibitions, checklists, and cleanup steps as mandatory policy. "
        "Do not continue implementation until you have replanned against the loaded skill.\n"
        "5. **Execution discipline**: do not create extra deliverables, duplicate files, "
        "or inspection artifacts unless the user explicitly asked for them. Prefer a "
        "single final artifact and clean intermediate outputs.\n"
        "\n"
        f"Skills:\n{skill_loader.descriptions()}"
        "\n"
    )

    todo_items = state.get("todo_items") or []
    if todo_items:
        prompt += (
            "\n"
            "## Current Task Board\n"
            "Use this as the authoritative execution checklist for the current task.\n"
            f"{_render_todos(todo_items)}\n"
        )

    loaded_skills = state.get("loaded_skills") or {}
    if loaded_skills:
        prompt += "\n## Loaded Skill Policies\n"
        prompt += (
            "The following loaded skills are now elevated into runtime policy as compact "
            "summaries. Full skill bodies remain in message history, while the summaries "
            "below are the authoritative system-level constraints for execution.\n"
        )
        for skill_name, skill_body in loaded_skills.items():
            prompt += f"\n### Skill: {skill_name}\n{skill_body}\n"

    return prompt


LLM_TIMEOUT_SECONDS = _get_env_int("AGENT_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)
LLM_MAX_RETRIES = _get_env_int("AGENT_LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES)

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=None,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=LLM_MAX_RETRIES,
)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    loaded_skills: dict[str, str]
    todo_items: list[dict[str, str]]
    rounds_without_todo: int
    completion_blocked: bool


@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    human_response = interrupt({"query": query})
    return human_response["data"]


@tool("TodoWrite")
def todo_write(items: list[dict[str, str]]) -> str:
    """Update the short execution checklist for the current task.

    Each item must include `content`, `status`, and `activeForm`.
    Allowed statuses: pending, in_progress, completed.
    """
    return "TodoWrite is handled by the graph runtime."


tools = [human_assistance, todo_write, *CUSTOM_TOOLS]
tool_registry = {tool_.name: tool_ for tool_ in tools}

llm_with_tools = llm.bind_tools(tools)


def build_graph_config(thread_id: str, **configurable: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, **configurable}}


def _with_default_thread_id(config: Optional[RunnableConfig]) -> RunnableConfig:
    runtime_config = dict(config or {})
    configurable = dict(runtime_config.get("configurable", {}))
    configurable.setdefault("thread_id", 1)
    runtime_config["configurable"] = configurable
    return runtime_config


def _latest_ai_message(state: State) -> AIMessage | None:
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            return message
    return None


def _latest_ai_tool_calls(state: State) -> list[dict[str, Any]]:
    latest = _latest_ai_message(state)
    return latest.tool_calls or [] if latest else []


def _log_tool_result(
    *,
    state: State,
    config: RunnableConfig,
    tool_call: dict[str, Any],
    result: ToolMessage,
    error: Exception | None = None,
) -> None:
    log_interaction(
        debugger_dir=DEBUGGER_DIR,
        event_type="tool",
        model_name=llm.model,
        messages=state["messages"],
        output_payload=[result],
        config=config,
        error=error,
        extra_input={"tool_calls": [tool_call]},
    )


def _invoke_regular_tool_call(
    state: State,
    config: RunnableConfig,
    tool_call: dict[str, Any],
) -> ToolMessage:
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {}) or {}
    tool_call_id = tool_call.get("id", "")
    tool_instance = tool_registry.get(tool_name)

    if tool_instance is None:
        result = ToolMessage(
            content=f"Error: Unknown tool '{tool_name}'",
            name=tool_name,
            tool_call_id=tool_call_id,
            status="error",
        )
        _log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
        return result

    try:
        output = tool_instance.invoke(tool_args, config=config)
    except GraphBubbleUp:
        raise
    except Exception as error:
        result = ToolMessage(
            content=_format_runtime_error(error),
            name=tool_name,
            tool_call_id=tool_call_id,
            status="error",
        )
        _log_tool_result(
            state=state,
            config=config,
            tool_call=tool_call,
            result=result,
            error=error,
        )
        return result

    if isinstance(output, ToolMessage):
        result = output
    else:
        result = ToolMessage(
            content=str(output),
            name=tool_name,
            tool_call_id=tool_call_id,
        )

    _log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
    return result


def _handle_todo_call(
    state: State,
    config: RunnableConfig,
    tool_call: dict[str, Any],
) -> tuple[ToolMessage, list[dict[str, str]], bool]:
    tool_call_id = tool_call.get("id", "")
    tool_args = tool_call.get("args", {}) or {}

    try:
        items = _normalize_todo_items(tool_args.get("items", []))
        result = ToolMessage(
            content=_render_todos(items),
            name="TodoWrite",
            tool_call_id=tool_call_id,
        )
        _log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
        return result, items, True
    except Exception as error:
        result = ToolMessage(
            content=f"Error: {error}",
            name="TodoWrite",
            tool_call_id=tool_call_id,
            status="error",
        )
        _log_tool_result(
            state=state,
            config=config,
            tool_call=tool_call,
            result=result,
            error=error,
        )
        return result, state.get("todo_items", []), False


def prepare_context(state: State) -> State:
    loaded_skills = {
        skill_name: _build_skill_policy_summary(skill_text)
        for skill_name, skill_text in dict(state.get("loaded_skills") or {}).items()
    }
    todo_items = list(state.get("todo_items") or [])
    rounds_without_todo = state.get("rounds_without_todo", 0)
    updates: State = {
        "messages": [],
        "loaded_skills": loaded_skills,
        "todo_items": todo_items,
        "rounds_without_todo": rounds_without_todo,
        "completion_blocked": False,
    }

    if _has_open_todos(todo_items) and rounds_without_todo >= 3:
        updates["messages"] = [
            HumanMessage(
                content=(
                    "<todo-reminder>There are unfinished task items. Refresh `TodoWrite` "
                    "before ending if the plan has changed, and keep executing until the "
                    "board is complete or explicitly blocked.</todo-reminder>"
                )
            )
        ]
        updates["rounds_without_todo"] = 0

    return updates


def call_model(state: State, config: Optional[RunnableConfig] = None) -> State:
    runtime_config = _with_default_thread_id(config)
    system_prompt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prompt), *state["messages"]]

    try:
        response = llm_with_tools.invoke(messages, config=runtime_config)
    except Exception as error:
        fallback_message = AIMessage(
            content=_format_runtime_error(error, timeout_seconds=LLM_TIMEOUT_SECONDS)
        )
        log_interaction(
            debugger_dir=DEBUGGER_DIR,
            event_type="llm",
            model_name=llm.model,
            messages=messages,
            output_payload=fallback_message,
            config=runtime_config,
            error=error,
        )
        return {"messages": [fallback_message]}

    log_interaction(
        debugger_dir=DEBUGGER_DIR,
        event_type="llm",
        model_name=llm.model,
        messages=messages,
        output_payload=response,
        config=runtime_config,
    )
    return {"messages": [response]}


def route_after_model(state: State) -> str:
    tool_calls = _latest_ai_tool_calls(state)
    if any(tool_call.get("name") == "load_skill" for tool_call in tool_calls):
        return "load_skills"
    if tool_calls:
        return "execute_tools"
    return "review_completion"


def load_skills(state: State, config: Optional[RunnableConfig] = None) -> State:
    runtime_config = _with_default_thread_id(config)
    tool_calls = _latest_ai_tool_calls(state)
    loaded_skills = dict(state.get("loaded_skills") or {})
    new_messages: list[BaseMessage] = []

    for tool_call in tool_calls:
        if tool_call.get("name") != "load_skill":
            continue

        result = _invoke_regular_tool_call(state, runtime_config, tool_call)
        new_messages.append(result)

        skill_name = str((tool_call.get("args", {}) or {}).get("name", "")).strip()
        if skill_name and isinstance(result.content, str) and not result.content.startswith("Error:"):
            loaded_skills[skill_name] = _build_skill_policy_summary(result.content)

    if any(tool_call.get("name") != "load_skill" for tool_call in tool_calls):
        new_messages.append(
            HumanMessage(
                content=(
                    "<skill-gate>A skill was just loaded. Re-plan against the loaded skill "
                    "before using other tools.</skill-gate>"
                )
            )
        )

    return {
        "messages": new_messages,
        "loaded_skills": loaded_skills,
    }


def execute_tools(state: State, config: Optional[RunnableConfig] = None) -> State:
    runtime_config = _with_default_thread_id(config)
    tool_calls = _latest_ai_tool_calls(state)
    todo_items = list(state.get("todo_items") or [])
    new_messages: list[BaseMessage] = []
    used_todo = False

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        if tool_name == "load_skill":
            continue
        if tool_name == "TodoWrite":
            result, todo_items, used_todo = _handle_todo_call(
                state,
                runtime_config,
                tool_call,
            )
            new_messages.append(result)
            continue

        result = _invoke_regular_tool_call(state, runtime_config, tool_call)
        new_messages.append(result)

    rounds_without_todo = 0 if used_todo else state.get("rounds_without_todo", 0) + 1
    return {
        "messages": new_messages,
        "todo_items": todo_items,
        "rounds_without_todo": rounds_without_todo,
    }


def review_completion(state: State) -> State:
    todo_items = list(state.get("todo_items") or [])
    if not _has_open_todos(todo_items):
        return {"messages": [], "completion_blocked": False}

    return {
        "messages": [
            HumanMessage(
                content=(
                    "<completion-gate>There are unfinished todo items. Do not finish yet. "
                    "Continue execution, or call `TodoWrite` to mark remaining items "
                    "completed before giving the final answer.</completion-gate>"
                )
            )
        ],
        "completion_blocked": True,
    }


def route_after_review(state: State) -> str:
    return "call_model" if state.get("completion_blocked") else END


graph_builder = StateGraph(State)
memory = InMemorySaver()

graph_builder.add_node("prepare_context", prepare_context)
graph_builder.add_node("call_model", call_model)
graph_builder.add_node("load_skills", load_skills)
graph_builder.add_node("execute_tools", execute_tools)
graph_builder.add_node("review_completion", review_completion)

graph_builder.add_edge(START, "prepare_context")
graph_builder.add_edge("prepare_context", "call_model")
graph_builder.add_conditional_edges(
    "call_model",
    route_after_model,
    {
        "load_skills": "load_skills",
        "execute_tools": "execute_tools",
        "review_completion": "review_completion",
    },
)
graph_builder.add_edge("load_skills", "prepare_context")
graph_builder.add_edge("execute_tools", "prepare_context")
graph_builder.add_conditional_edges(
    "review_completion",
    route_after_review,
    {
        "call_model": "call_model",
        END: END,
    },
)

graph = graph_builder.compile(checkpointer=memory)
