"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Optional

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent.debugger import write_interaction_log as log_interaction
from agent.tools import CUSTOM_TOOLS
from agent.tools import _skill_loader

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBUGGER_DIR = PROJECT_ROOT / "debugger"
DEFAULT_THREAD_ID = "1"
WORKDIR = Path.cwd() / "workspace"

os.environ["DEEPSEEK_API_KEY"] = os.getenv("DEEPSEEK_API_KEY")
os.environ["TAVILY_API_KEY"] = os.getenv("TAVILY_API_KEY")

def build_system_prompt() -> str:
	return (
		f"You are a agent at {WORKDIR}. Use tools to solve tasks.\n "
		f"Skills:\n{_skill_loader().descriptions()}"
	)

SYSTEM = build_system_prompt()

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)


class State(TypedDict):
    messages: Annotated[list, add_messages]


@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    human_response = interrupt({"query": query})
    return human_response["data"]

search_tool = TavilySearch(max_results=2)
tools = [search_tool, human_assistance, *CUSTOM_TOOLS]

llm_with_tools = llm.bind_tools(tools)


def build_graph_config(thread_id: str = DEFAULT_THREAD_ID, **configurable: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, **configurable}}


def _with_default_thread_id(config: RunnableConfig | None) -> RunnableConfig:
    runtime_config = dict(config or {})
    configurable = dict(runtime_config.get("configurable", {}))
    configurable.setdefault("thread_id", DEFAULT_THREAD_ID)
    runtime_config["configurable"] = configurable
    return runtime_config


def _wrap_tool_call(request, execute):
    messages = request.state["messages"]
    config = request.runtime.config
    latest_message = messages[-1] if messages else None
    tool_calls = getattr(latest_message, "tool_calls", []) if latest_message else []

    try:
        result = execute(request)
    except Exception as error:
        log_interaction(
            debugger_dir=DEBUGGER_DIR,
            event_type="tool",
            model_name=llm.model,
            messages=messages,
            output_payload=None,
            config=config,
            error=error,
            extra_input={"tool_calls": tool_calls},
        )
        raise

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
        log_interaction(
            debugger_dir=DEBUGGER_DIR,
            event_type="llm",
            model_name=llm.model,
            messages=messages,
            output_payload=None,
            config=runtime_config,
            error=error,
        )
        raise

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
