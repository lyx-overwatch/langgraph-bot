"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent.debugger import write_interaction_log as log_interaction
from agent.tools import CUSTOM_TOOLS
from agent.tools import _skill_loader

load_dotenv()

PROJECT_ROOT = Path.cwd()
DEBUGGER_DIR = PROJECT_ROOT / "debugger"
WORKDIR = PROJECT_ROOT / "workspace"
DEFAULT_LLM_TIMEOUT_SECONDS = 60
DEFAULT_LLM_MAX_RETRIES = 2

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
_set_optional_env("TAVILY_API_KEY")

def build_system_prompt() -> str:
    skill_loader = _skill_loader()
    return (
        f"You are a agent at {WORKDIR}. Use tools to solve tasks.\n "
        f"Skills:\n{skill_loader.descriptions()}"
    )

SYSTEM = build_system_prompt()
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


@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    human_response = interrupt({"query": query})
    return human_response["data"]

search_tool = TavilySearch(max_results=2)
tools = [human_assistance, *CUSTOM_TOOLS]

llm_with_tools = llm.bind_tools(tools)


def build_graph_config(thread_id: str, **configurable: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, **configurable}}


def _with_default_thread_id(config: RunnableConfig | None) -> RunnableConfig:
    runtime_config = dict(config or {})
    configurable = dict(runtime_config.get("configurable", {}))
    configurable.setdefault("thread_id", 1)
    runtime_config["configurable"] = configurable
    return runtime_config


def _wrap_tool_call(request, execute):
    messages = request.state["messages"]
    config = request.runtime.config
    latest_message = messages[-1] if messages else None
    tool_calls = getattr(latest_message, "tool_calls", []) if latest_message else []
    tool_call = request.tool_call

    try:
        result = execute(request)
    except GraphBubbleUp:
        raise
    except Exception as error:
        result = ToolMessage(
            content=_format_runtime_error(error),
            name=tool_call.get("name"),
            tool_call_id=tool_call["id"],
            status="error",
        )
        log_interaction(
            debugger_dir=DEBUGGER_DIR,
            event_type="tool",
            model_name=llm.model,
            messages=messages,
            output_payload=[result],
            config=config,
            error=error,
            extra_input={"tool_calls": tool_calls},
        )
        return result

    log_interaction(
        debugger_dir=DEBUGGER_DIR,
        event_type="tool",
        model_name=llm.model,
        messages=messages,
        output_payload=[result] if isinstance(result, BaseMessage) else result,
        config=config,
        extra_input={"tool_calls": tool_calls},
    )
    return result


def call_model(state: State, config: Optional[RunnableConfig] = None) -> State:
    runtime_config = _with_default_thread_id(config)
    system_prompt = SYSTEM
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


graph_builder = StateGraph(State)
memory = InMemorySaver()
tool_node = ToolNode(tools=tools, wrap_tool_call=_wrap_tool_call)

graph_builder.add_node("call_model", call_model)
graph_builder.add_node("call_tools", tool_node)
graph_builder.add_edge(START, "call_model")
graph_builder.add_conditional_edges("call_model", tools_condition, {"tools": "call_tools", "__end__": END})
graph_builder.add_edge("call_tools", "call_model")

graph = graph_builder.compile(checkpointer=memory)
