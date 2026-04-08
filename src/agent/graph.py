"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Annotated
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_community.chat_models import MiniMaxChat

load_dotenv()

os.environ["MINIMAX_GROUP_ID"] = os.getenv("MINIMAX_GROUP_ID")
os.environ["MINIMAX_API_KEY"] = os.getenv("MINIMAX_API_KEY")

llm = MiniMaxChat(streaming=False, base_url="https://api.minimaxi.com/v1/text/chatcompletion_v2", model="M2-her")

class State(TypedDict):
    messages: Annotated[list, add_messages]

def chatbot(state: State):
    return {"messages": llm.invoke(state["messages"])}

graph_builder = StateGraph(State)

graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph_builder.add_edge("chatbot", END)

graph = graph_builder.compile()

# class Context(TypedDict):
#     """Context parameters for the agent.

#     Set these when creating assistants OR when invoking the graph.
#     See: https://langchain-ai.github.io/langgraph/cloud/how-tos/configuration_cloud/
#     """

#     my_configurable_param: str


# @dataclass
# class State:
#     """Input state for the agent.

#     Defines the initial structure of incoming data.
#     See: https://langchain-ai.github.io/langgraph/concepts/low_level/#state
#     """

#     changeme: str = "example"


# async def call_model(state: State, runtime: Runtime[Context]) -> Dict[str, Any]:
#     """Process input and returns output.

#     Can use runtime context to alter behavior.
#     """
#     return {
#         "changeme": "output from call_model. "
#         f"Configured with {(runtime.context or {}).get('my_configurable_param')}"
#     }


# # Define the graph
# graph = (
#     StateGraph(State, context_schema=Context)
#     .add_node(call_model)
#     .add_edge("__start__", "call_model")
#     .compile(name="New Graph")
# )