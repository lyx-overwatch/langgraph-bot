from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_deepseek import ChatDeepSeek
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END

from agent.debugger import write_interaction_log as log_interaction
from agent.graph_runtime.config import format_runtime_error
from agent.graph_runtime.prompting import build_skill_policy_summary, build_system_prompt
from agent.graph_runtime.state import (
    MAX_CONTINUATION_ATTEMPTS,
    State,
    build_continuation_gate_message,
    build_continuation_message,
    get_finish_reason,
    has_open_todos,
)
from agent.graph_runtime.tools import GraphToolRuntime


class GraphNodes:
    def __init__(
        self,
        *,
        debugger_dir: Path,
        workdir: Path,
        llm: ChatDeepSeek,
        llm_with_tools: Any,
        tool_runtime: GraphToolRuntime,
        llm_timeout_seconds: int,
    ) -> None:
        self._debugger_dir = debugger_dir
        self._workdir = workdir
        self._llm = llm
        self._llm_with_tools = llm_with_tools
        self._tool_runtime = tool_runtime
        self._llm_timeout_seconds = llm_timeout_seconds

    def prepare_context(self, state: State) -> State:
        loaded_skills = {
            skill_name: build_skill_policy_summary(skill_text)
            for skill_name, skill_text in dict(state.get("loaded_skills") or {}).items()
        }
        todo_items = list(state.get("todo_items") or [])
        rounds_without_todo = state.get("rounds_without_todo", 0)
        continuation_required = state.get("continuation_required", False)
        continuation_attempts = state.get("continuation_attempts", 0)
        updates: State = {
            "messages": [],
            "loaded_skills": loaded_skills,
            "todo_items": todo_items,
            "rounds_without_todo": rounds_without_todo,
            "completion_blocked": False,
            "continuation_required": continuation_required,
            "continuation_attempts": continuation_attempts,
            "last_model_finish_reason": state.get("last_model_finish_reason"),
        }

        reminder_messages: list[BaseMessage] = []

        if continuation_required and continuation_attempts < MAX_CONTINUATION_ATTEMPTS:
            reminder_messages.append(
                HumanMessage(content=build_continuation_message(continuation_attempts + 1))
            )
            updates["continuation_attempts"] = continuation_attempts + 1

        if has_open_todos(todo_items) and rounds_without_todo >= 3:
            reminder_messages.append(
                HumanMessage(
                    content=(
                        "<todo-reminder>There are unfinished task items. Refresh `TodoWrite` "
                        "before ending if the plan has changed, and keep executing until the "
                        "board is complete or explicitly blocked.</todo-reminder>"
                    )
                )
            )
            updates["rounds_without_todo"] = 0

        if reminder_messages:
            updates["messages"] = reminder_messages

        return updates

    def call_model(self, state: State, config: Optional[RunnableConfig] = None) -> State:
        runtime_config = self._with_default_thread_id(config)
        system_prompt = build_system_prompt(state, self._workdir)
        messages = [SystemMessage(content=system_prompt), *state["messages"]]

        try:
            response = self._llm_with_tools.invoke(messages, config=runtime_config)
        except Exception as error:
            fallback_message = AIMessage(
                content=format_runtime_error(error, timeout_seconds=self._llm_timeout_seconds)
            )
            log_interaction(
                debugger_dir=self._debugger_dir,
                event_type="llm",
                model_name=self._llm.model,
                messages=messages,
                output_payload=fallback_message,
                config=runtime_config,
                error=error,
            )
            return {
                "messages": [fallback_message],
                "continuation_required": False,
                "continuation_attempts": 0,
                "last_model_finish_reason": None,
            }

        log_interaction(
            debugger_dir=self._debugger_dir,
            event_type="llm",
            model_name=self._llm.model,
            messages=messages,
            output_payload=response,
            config=runtime_config,
        )
        finish_reason = get_finish_reason(response)
        updates: State = {
            "messages": [response],
            "continuation_required": finish_reason == "length",
            "continuation_attempts": state.get("continuation_attempts", 0),
            "last_model_finish_reason": finish_reason,
            "completion_blocked": False,
            "loaded_skills": state.get("loaded_skills", {}),
            "todo_items": state.get("todo_items", []),
            "rounds_without_todo": state.get("rounds_without_todo", 0),
        }
        if finish_reason != "length":
            updates["continuation_attempts"] = 0
        return updates

    def route_after_model(self, state: State) -> str:
        tool_calls = self._latest_ai_tool_calls(state)
        if any(tool_call.get("name") == "load_skill" for tool_call in tool_calls):
            return "load_skills"
        if tool_calls:
            return "execute_tools"
        return "review_completion"

    def load_skills(self, state: State, config: Optional[RunnableConfig] = None) -> State:
        runtime_config = self._with_default_thread_id(config)
        tool_calls = self._latest_ai_tool_calls(state)
        loaded_skills = dict(state.get("loaded_skills") or {})
        new_messages: list[BaseMessage] = []

        for tool_call in tool_calls:
            if tool_call.get("name") != "load_skill":
                continue

            result = self._invoke_regular_tool_call(state, runtime_config, tool_call)
            new_messages.append(result)

            skill_name = str((tool_call.get("args", {}) or {}).get("name", "")).strip()
            if skill_name and isinstance(result.content, str) and not result.content.startswith("Error:"):
                loaded_skills[skill_name] = build_skill_policy_summary(result.content)

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

    def execute_tools(self, state: State, config: Optional[RunnableConfig] = None) -> State:
        runtime_config = self._with_default_thread_id(config)
        tool_calls = self._latest_ai_tool_calls(state)
        todo_items = list(state.get("todo_items") or [])
        new_messages: list[BaseMessage] = []
        used_todo = False

        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            if tool_name == "load_skill":
                continue
            if tool_name == "TodoWrite":
                result, todo_items, used_todo = self._tool_runtime.handle_todo_call(
                    state,
                    runtime_config,
                    tool_call,
                )
                new_messages.append(result)
                continue

            result = self._invoke_regular_tool_call(state, runtime_config, tool_call)
            new_messages.append(result)

        rounds_without_todo = 0 if used_todo else state.get("rounds_without_todo", 0) + 1
        return {
            "messages": new_messages,
            "todo_items": todo_items,
            "rounds_without_todo": rounds_without_todo,
        }

    def review_completion(self, state: State) -> State:
        todo_items = list(state.get("todo_items") or [])
        if state.get("continuation_required"):
            next_attempt = min(
                state.get("continuation_attempts", 0) + 1,
                MAX_CONTINUATION_ATTEMPTS,
            )
            return {
                "messages": [
                    HumanMessage(content=build_continuation_gate_message(next_attempt))
                ],
                "completion_blocked": True,
                "continuation_attempts": next_attempt,
            }

        if not has_open_todos(todo_items):
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

    def route_after_review(self, state: State) -> str:
        return "call_model" if state.get("completion_blocked") else END

    def _with_default_thread_id(self, config: Optional[RunnableConfig]) -> RunnableConfig:
        runtime_config = dict(config or {})
        configurable = dict(runtime_config.get("configurable", {}))
        configurable.setdefault("thread_id", 1)
        runtime_config["configurable"] = configurable
        return runtime_config

    def _latest_ai_message(self, state: State) -> AIMessage | None:
        for message in reversed(state["messages"]):
            if isinstance(message, AIMessage):
                return message
        return None

    def _latest_ai_tool_calls(self, state: State) -> list[dict[str, Any]]:
        latest = self._latest_ai_message(state)
        return latest.tool_calls or [] if latest else []

    def _invoke_regular_tool_call(
        self,
        state: State,
        config: RunnableConfig,
        tool_call: dict[str, Any],
    ) -> ToolMessage:
        tool_name = tool_call.get("name")
        tool_call_id = tool_call.get("id", "")

        try:
            return self._tool_runtime.invoke_regular_tool_call(state, config, tool_call)
        except GraphBubbleUp:
            raise
        except Exception as error:
            result = ToolMessage(
                content=format_runtime_error(error),
                name=str(tool_name),
                tool_call_id=tool_call_id,
                status="error",
            )
            self._tool_runtime.log_tool_result(
                state=state,
                config=config,
                tool_call=tool_call,
                result=result,
                error=error,
            )
            return result