from __future__ import annotations

import argparse
import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt, StateSnapshot

from agent.graph import build_graph_config, graph

# LangGraph 流式事件分三层：
# 1. messages: 模型 token 级输出，适合看回答是如何实时生成的。
# 2. updates: 节点执行完成后的状态增量，适合看每一步写回了什么。
# 3. tasks: 运行时任务调度事件，适合看底层执行、完成和报错过程。
STREAM_MODES = ["messages", "updates"]
DIVIDER = "=" * 80
SECTION_DIVIDER = "-" * 80


def _parse_args(thread_id: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LangGraph agent from a script.")
    parser.add_argument("prompt", nargs="?", help="Optional single prompt to run once.")
    parser.add_argument(
        "--thread-id",
        default=thread_id,
        help="Thread id used to persist conversation state.",
    )
    return parser.parse_args()


def _format_interrupt(interrupt: Interrupt) -> str:
    value = interrupt.value
    if isinstance(value, dict) and value.get("query"):
        return f"[human_assistance] {value['query']}\n> "
    return "[human_assistance] Please provide input\n> "


def _interrupt_debug_lines(interrupt: Interrupt) -> list[str]:
    lines = [f"  id   : {interrupt.id}"]
    lines.append("  value:")
    for value_line in _to_pretty_json(interrupt.value).splitlines():
        lines.append(f"    {value_line}")
    return lines


def _resume_value(interrupt: Interrupt) -> dict[str, str]:
    answer = input(_format_interrupt(interrupt)).strip()
    payload = {"data": answer}
    _print_block(
        "人工恢复输入",
        [
            f"  interrupt_id: {interrupt.id}",
            "  payload:",
            *[f"    {line}" for line in _to_pretty_json(payload).splitlines()],
        ],
    )
    return payload


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _to_pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _summarize(value: Any, *, limit: int = 280) -> str:
    if isinstance(value, BaseMessage):
        text = _extract_text(value.content)
    elif isinstance(value, (dict, list, tuple)):
        text = _to_pretty_json(value)
    else:
        text = str(value)

    text = text.strip()
    if not text:
        return "<empty>"
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _print_block(title: str, lines: list[str]) -> None:
    print(SECTION_DIVIDER, flush=True)
    print(title, flush=True)
    for line in lines:
        print(line, flush=True)


def _message_lines(messages: Any) -> list[str]:
    if not isinstance(messages, list):
        return [f"  raw: {_summarize(messages)}"]

    lines: list[str] = []
    for message in messages:
        message_type = getattr(message, "type", type(message).__name__)
        if isinstance(message, ToolMessage) or message_type == "tool":
            status = getattr(message, "status", "success")
            lines.append(f"  tool result: {message.name} [{status}]")
            lines.append(f"    {_summarize(message.content, limit=500)}")
            continue

        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            lines.append("  tool calls:")
            for index, tool_call in enumerate(tool_calls, start=1):
                name = tool_call.get("name", "<unknown>")
                args = _to_pretty_json(tool_call.get("args", {}))
                lines.append(f"    {index}. {name}")
                for arg_line in args.splitlines():
                    lines.append(f"       {arg_line}")
            continue

        text = _extract_text(getattr(message, "content", "")).strip()
        if text:
            lines.append(f"  {message_type}: {_summarize(text, limit=500)}")

    return lines or ["  messages: <empty>"]


class StreamDebugPrinter:
    def __init__(self) -> None:
        self._active_stream_node: str | None = None
        self._stream_open = False

    def start_phase(self, payload: dict[str, Any] | Command, thread_id: str) -> None:
        self._close_stream()
        print(DIVIDER, flush=True)
        print(f"调试流 | thread={thread_id}", flush=True)
        if isinstance(payload, dict):
            prompt = payload.get("messages", [None])[0]
            content = _extract_text(getattr(prompt, "content", prompt))
            print(f"用户输入 : {content}", flush=True)
        else:
            print("恢复执行 : 接续人工介入后的图运行", flush=True)
        print(DIVIDER, flush=True)

    def finish_phase(self, snapshot: StateSnapshot) -> None:
        self._close_stream()
        if snapshot.interrupts:
            lines: list[str] = []
            for index, interrupt in enumerate(snapshot.interrupts, start=1):
                lines.append(f"  {index}. {_format_interrupt(interrupt).strip()}")
                lines.extend(_interrupt_debug_lines(interrupt))
            _print_block("人工介入", lines)
            return

        print(SECTION_DIVIDER, flush=True)
        print("本轮结束", flush=True)

    def emit(self, mode: str, data: Any) -> None:
        if mode == "messages":
            self._emit_message_token(data)
            return

        self._close_stream()
        if mode == "updates":
            self._emit_update(data)
            return
        if mode == "tasks":
            self._emit_task(data)
            return

        _print_block(f"未分类事件: {mode}", [f"  {_summarize(data, limit=500)}"])

    def _emit_message_token(self, data: Any) -> None:
        if not isinstance(data, tuple) or len(data) != 2:
            return

        token, metadata = data
        node_name = "llm"
        if isinstance(metadata, dict):
            node_name = str(metadata.get("langgraph_node") or metadata.get("node_name") or node_name)

        text = _extract_text(getattr(token, "content", token))
        if not text:
            return

        if not self._stream_open or self._active_stream_node != node_name:
            self._close_stream()
            print(SECTION_DIVIDER, flush=True)
            print(f"模型流式输出 | 节点={node_name}", flush=True)
            print("", end="", flush=True)
            self._stream_open = True
            self._active_stream_node = node_name

        print(text, end="", flush=True)

    def _emit_update(self, data: Any) -> None:
        if not isinstance(data, dict):
            _print_block("状态更新", [f"  {_summarize(data, limit=500)}"])
            return

        for node_name, update in data.items():
            lines = [f"  node: {node_name}"]
            if isinstance(update, dict):
                messages = update.get("messages")
                if messages is not None:
                    lines.extend(_message_lines(messages))
                remaining = {key: value for key, value in update.items() if key != "messages"}
                if remaining:
                    lines.append("  state:")
                    for state_line in _to_pretty_json(remaining).splitlines():
                        lines.append(f"    {state_line}")
            else:
                lines.append(f"  payload: {_summarize(update, limit=500)}")
            _print_block("节点状态更新", lines)

    def _emit_task(self, data: Any) -> None:
        if not isinstance(data, dict):
            _print_block("任务事件", [f"  {_summarize(data, limit=500)}"])
            return

        name = data.get("name") or data.get("task") or data.get("id") or "<unknown>"
        event = data.get("event") or data.get("type") or "task"
        lines = [f"  event: {event}", f"  name : {name}"]

        if "input" in data:
            lines.append(f"  input: {_summarize(data['input'], limit=300)}")
        if "result" in data:
            lines.append(f"  result: {_summarize(data['result'], limit=300)}")
        if data.get("error"):
            lines.append(f"  error: {_summarize(data['error'], limit=300)}")

        extra = {
            key: value
            for key, value in data.items()
            if key not in {"name", "task", "id", "event", "type", "input", "result", "error"}
        }
        if extra:
            lines.append("  meta:")
            for extra_line in _to_pretty_json(extra).splitlines():
                lines.append(f"    {extra_line}")

        _print_block("任务调度事件", lines)

    def _close_stream(self) -> None:
        if self._stream_open:
            print("", flush=True)
            self._stream_open = False
            self._active_stream_node = None


def _run_turn(user_input: str, thread_id: str) -> None:
    config = build_graph_config(thread_id=thread_id)
    payload: dict | Command = {"messages": [HumanMessage(content=user_input)]}
    printer = StreamDebugPrinter()

    while True:
        printer.start_phase(payload, thread_id)
        try:
            for mode, data in graph.stream(payload, config=config, stream_mode=STREAM_MODES):
                printer.emit(mode, data)
        except KeyboardInterrupt:
            print("\n[cancelled] Interrupted by user.", flush=True)
            return
        except Exception as error:
            print(f"[runtime error] {type(error).__name__}: {error}", flush=True)
            return

        snapshot = graph.get_state(config)
        interrupts = snapshot.interrupts
        printer.finish_phase(snapshot)

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

        return


def main() -> None:
    thread_id = 'cli-results-01'
    args = _parse_args(thread_id)

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