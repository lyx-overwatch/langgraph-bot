from __future__ import annotations

from pathlib import Path

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from agent.debugger import write_interaction_log as log_interaction
from agent.graph_runtime.state import State, normalize_todo_items, render_todos
from agent.tools import CUSTOM_TOOLS


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


class GraphToolRuntime:
    def __init__(self, *, debugger_dir: Path, model_name: str) -> None:
        self._debugger_dir = debugger_dir
        self._model_name = model_name
        self.tools = [human_assistance, todo_write, *CUSTOM_TOOLS]
        self.tool_registry = {tool_.name: tool_ for tool_ in self.tools}

    def log_tool_result(
        self,
        *,
        state: State,
        config: RunnableConfig,
        tool_call: dict[str, object],
        result: ToolMessage,
        error: Exception | None = None,
    ) -> None:
        log_interaction(
            debugger_dir=self._debugger_dir,
            event_type="tool",
            model_name=self._model_name,
            messages=state["messages"],
            output_payload=[result],
            config=config,
            error=error,
            extra_input={"tool_calls": [tool_call]},
        )

    def invoke_regular_tool_call(
        self,
        state: State,
        config: RunnableConfig,
        tool_call: dict[str, object],
    ) -> ToolMessage:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {}) or {}
        tool_call_id = str(tool_call.get("id", ""))
        tool_instance = self.tool_registry.get(tool_name)

        if tool_instance is None:
            result = ToolMessage(
                content=f"Error: Unknown tool '{tool_name}'",
                name=str(tool_name),
                tool_call_id=tool_call_id,
                status="error",
            )
            self.log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
            return result

        try:
            output = tool_instance.invoke(tool_args, config=config)
        except GraphBubbleUp:
            raise
        except Exception as error:
            raise error

        if isinstance(output, ToolMessage):
            result = output
        else:
            result = ToolMessage(
                content=str(output),
                name=str(tool_name),
                tool_call_id=tool_call_id,
            )

        self.log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
        return result

    def handle_todo_call(
        self,
        state: State,
        config: RunnableConfig,
        tool_call: dict[str, object],
    ) -> tuple[ToolMessage, list[dict[str, str]], bool]:
        tool_call_id = str(tool_call.get("id", ""))
        tool_args = tool_call.get("args", {}) or {}

        try:
            items = normalize_todo_items(tool_args.get("items", []))
            result = ToolMessage(
                content=render_todos(items),
                name="TodoWrite",
                tool_call_id=tool_call_id,
            )
            self.log_tool_result(state=state, config=config, tool_call=tool_call, result=result)
            return result, items, True
        except Exception as error:
            result = ToolMessage(
                content=f"Error: {error}",
                name="TodoWrite",
                tool_call_id=tool_call_id,
                status="error",
            )
            self.log_tool_result(
                state=state,
                config=config,
                tool_call=tool_call,
                result=result,
                error=error,
            )
            return result, state.get("todo_items", []), False