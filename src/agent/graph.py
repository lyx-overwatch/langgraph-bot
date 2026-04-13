"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.load import dumpd
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_deepseek import ChatDeepSeek
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBUGGER_DIR = PROJECT_ROOT / "debugger"

os.environ["DEEPSEEK_API_KEY"] = os.getenv("DEEPSEEK_API_KEY")
os.environ["TAVILY_API_KEY"] = os.getenv("TAVILY_API_KEY")

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    human_response = interrupt({"query": query})
    return human_response["data"]

search_tool = TavilySearch(max_results=2)
tools = [search_tool, human_assistance]
tools_by_name: dict[str, BaseTool] = {tool.name: tool for tool in tools}


llm_with_tools = llm.bind_tools(tools)


class State(TypedDict):
    messages: Annotated[list, add_messages]

DEFAULT_THREAD_ID = "1"


def build_graph_config(thread_id: str = DEFAULT_THREAD_ID, **configurable: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, **configurable}}


def _with_default_thread_id(config: RunnableConfig | None) -> RunnableConfig:
    runtime_config = dict(config or {})
    configurable = dict(runtime_config.get("configurable", {}))
    configurable.setdefault("thread_id", DEFAULT_THREAD_ID)
    runtime_config["configurable"] = configurable
    return runtime_config


def _merge_state(previous: State | None, current: State) -> State:
    previous_messages = previous.get("messages", []) if previous else []
    current_messages = current.get("messages", [])
    return {"messages": list(add_messages(previous_messages, current_messages))}


def _write_debugger_log(
    event_type: str,
    input_payload: object,
    output_payload: object | None,
    config: RunnableConfig,
    error: Exception | None = None,
) -> None:
    DEBUGGER_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    thread_id = config.get("configurable", {}).get("thread_id", DEFAULT_THREAD_ID)
    record = {
        "id": str(uuid4()),
        "timestamp": timestamp.isoformat(),
        "thread_id": thread_id,
        "event_type": event_type,
        "model": llm.model,
        "input": dumpd(input_payload),
        "output": dumpd(output_payload) if output_payload is not None else None,
        "error": str(error) if error is not None else None,
    }
    log_file = DEBUGGER_DIR / (
        f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{thread_id}_{event_type}_{record['id']}.json"
    )
    with log_file.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)


def _write_model_interaction_log(
    messages: list[BaseMessage],
    response: BaseMessage | None,
    config: RunnableConfig,
    error: Exception | None = None,
) -> None:
    _write_debugger_log(
        event_type="llm",
        input_payload={
            "messages": [dumpd(message) for message in messages],
            "config": config,
        },
        output_payload=response,
        config=config,
        error=error,
    )


def _write_tool_interaction_log(
    messages: list[BaseMessage],
    tool_messages: list[BaseMessage] | None,
    config: RunnableConfig,
    error: Exception | None = None,
) -> None:
    latest_message = messages[-1] if messages else None
    tool_calls = getattr(latest_message, "tool_calls", []) if latest_message else []
    _write_debugger_log(
        event_type="tool",
        input_payload={
            "messages": [dumpd(message) for message in messages],
            "tool_calls": tool_calls,
            "config": config,
        },
        output_payload=tool_messages,
        config=config,
        error=error,
    )


def _pending_tool_calls(messages: list[BaseMessage]) -> list[dict]:
    latest_message = messages[-1] if messages else None
    if isinstance(latest_message, AIMessage):
        return list(latest_message.tool_calls)
    return []


def _coerce_tool_message(tool_name: str, tool_call_id: str, response: object) -> ToolMessage:
    if isinstance(response, ToolMessage):
        return response

    if isinstance(response, str):
        content = response
    else:
        content = json.dumps(response, ensure_ascii=False)

    return ToolMessage(content=content, name=tool_name, tool_call_id=tool_call_id)


def _invoke_tool(tool: BaseTool, tool_call: dict, config: RunnableConfig) -> object:
    if tool.name == human_assistance.name and human_assistance.func is not None:
        return human_assistance.func(**tool_call["args"])
    return tool.invoke({**tool_call, "type": "tool_call"}, config=config)


@task
def call_model(messages: list[BaseMessage], config: RunnableConfig) -> BaseMessage:
    try:
        response = llm_with_tools.invoke(messages, config=config)
    except Exception as error:
        _write_model_interaction_log(messages, None, config, error)
        raise

    _write_model_interaction_log(messages, response, config)
    return response


@task
def call_tools(messages: list[BaseMessage], config: RunnableConfig) -> list[BaseMessage]:
    tool_messages: list[BaseMessage] = []

    try:
        for tool_call in _pending_tool_calls(messages):
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            tool = tools_by_name.get(tool_name)

            if tool is None:
                tool_messages.append(
                    ToolMessage(
                        content=f"Error: {tool_name} is not a valid tool.",
                        name=tool_name,
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                )
                continue

            response = _invoke_tool(tool, tool_call, config)
            tool_messages.append(_coerce_tool_message(tool_name, tool_call_id, response))
    except Exception as error:
        _write_tool_interaction_log(messages, None, config, error)
        raise

    _write_tool_interaction_log(messages, tool_messages, config)
    return tool_messages


memory = InMemorySaver()


@entrypoint(checkpointer=memory)
def graph(
    state: State,
    *,
    config: Optional[RunnableConfig] = None,
    previous: State | None = None,
) -> entrypoint.final[State, State]:
    runtime_config = _with_default_thread_id(config)
    current_state = _merge_state(previous, state)
    messages = current_state["messages"]

    while True:
        response = call_model(messages, config=runtime_config).result()
        messages = list(add_messages(messages, [response]))

        if tools_condition({"messages": messages}) == "__end__":
            final_state = {"messages": messages}
            return entrypoint.final(value=final_state, save=final_state)

        tool_messages = call_tools(messages, config=runtime_config).result()
        messages = list(add_messages(messages, tool_messages))
