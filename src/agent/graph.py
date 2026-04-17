"""LangGraph runtime with explicit skill-loading and execution gates."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.graph_runtime import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    GraphToolRuntime,
    GraphNodes,
    State,
    build_llm,
    get_env_int,
    set_optional_env,
)

load_dotenv()

PROJECT_ROOT = Path.cwd()
DEBUGGER_DIR = PROJECT_ROOT / "debugger"
WORKDIR = PROJECT_ROOT / "workspace"
set_optional_env("DEEPSEEK_API_KEY")

LLM_TIMEOUT_SECONDS = get_env_int("AGENT_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)
LLM_MAX_RETRIES = get_env_int("AGENT_LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES)

llm = build_llm(timeout_seconds=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES)

tool_runtime = GraphToolRuntime(debugger_dir=DEBUGGER_DIR, model_name=llm.model)
tools = tool_runtime.tools
llm_with_tools = llm.bind_tools(tools)

nodes = GraphNodes(
    debugger_dir=DEBUGGER_DIR,
    workdir=WORKDIR,
    llm=llm,
    llm_with_tools=llm_with_tools,
    tool_runtime=tool_runtime,
    llm_timeout_seconds=LLM_TIMEOUT_SECONDS,
)


def build_graph_config(thread_id: str, **configurable: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, **configurable}}


graph_builder = StateGraph(State)
memory = InMemorySaver()

graph_builder.add_node("prepare_context", nodes.prepare_context)
graph_builder.add_node("call_model", nodes.call_model)
graph_builder.add_node("load_skills", nodes.load_skills)
graph_builder.add_node("execute_tools", nodes.execute_tools)
graph_builder.add_node("review_completion", nodes.review_completion)

graph_builder.add_edge(START, "prepare_context")
graph_builder.add_edge("prepare_context", "call_model")
graph_builder.add_conditional_edges(
    "call_model",
    nodes.route_after_model,
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
    nodes.route_after_review,
    {
        "call_model": "call_model",
        END: END,
    },
)

graph = graph_builder.compile(checkpointer=memory)
