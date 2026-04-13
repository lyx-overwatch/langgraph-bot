from __future__ import annotations

import argparse
from typing import cast

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, GraphOutput, Interrupt

from agent.graph import DEFAULT_THREAD_ID, build_graph_config, graph


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LangGraph agent from a script.")
    parser.add_argument("prompt", nargs="?", help="Optional single prompt to run once.")
    parser.add_argument(
        "--thread-id",
        default=DEFAULT_THREAD_ID,
        help="Thread id used to persist conversation state.",
    )
    return parser.parse_args()


def _last_ai_message(messages: list) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _format_interrupt(interrupt: Interrupt) -> str:
    value = interrupt.value
    if isinstance(value, dict) and value.get("query"):
        return f"[human_assistance] {value['query']}\n> "
    return "[human_assistance] Please provide input\n> "


def _resume_value(interrupt: Interrupt) -> dict[str, str]:
    answer = input(_format_interrupt(interrupt)).strip()
    return {"data": answer}


def _unwrap_invoke_result(result: GraphOutput | dict) -> tuple[tuple[Interrupt, ...], dict]:
    if isinstance(result, GraphOutput):
        return result.interrupts, cast(dict, result.value)

    interrupts = tuple(result.get("__interrupt__", ()))
    if interrupts:
        state = {key: value for key, value in result.items() if key != "__interrupt__"}
        return interrupts, state

    return (), result


def _run_turn(user_input: str, thread_id: str) -> None:
    config = build_graph_config(thread_id=thread_id)
    payload: dict | Command = {"messages": [HumanMessage(content=user_input)]}

    while True:
        result = graph.invoke(payload, config=config)
        interrupts, state = _unwrap_invoke_result(result)

        if interrupts:
            if len(interrupts) == 1:
                payload = Command(resume=_resume_value(interrupts[0]))
            else:
                payload = Command(
                    resume={
                        interrupt.id: _resume_value(interrupt)
                        for interrupt in interrupts
                    }
                )
            continue

        assistant_message = _last_ai_message(state["messages"])
        if assistant_message is not None:
            print(f"Assistant: {assistant_message.text}")
        return


def main() -> None:
    args = _parse_args()

    if args.prompt:
        _run_turn(args.prompt, args.thread_id)
        return

    print("LangGraph CLI started. Type 'exit' to quit.")
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            return
        _run_turn(user_input, args.thread_id)


if __name__ == "__main__":
    main()