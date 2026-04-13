from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.load import dumpd
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

DEFAULT_THREAD_ID = "1"

def write_debugger_log(
    *,
    debugger_dir: Path,
    event_type: str,
    model_name: str,
    input_payload: object,
    output_payload: object | None,
    config: RunnableConfig,
    error: Exception | None = None,
) -> None:
    debugger_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    thread_id = config.get("configurable", {}).get("thread_id", DEFAULT_THREAD_ID)
    record = {
        "id": str(uuid4()),
        "timestamp": timestamp.isoformat(),
        "thread_id": thread_id,
        "event_type": event_type,
        "model": model_name,
        "input": dumpd(input_payload),
        "output": dumpd(output_payload) if output_payload is not None else None,
        "error": str(error) if error is not None else None,
    }
    log_file = debugger_dir / (
        f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{thread_id}_{event_type}_{record['id']}.json"
    )
    with log_file.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)


def message_payload(messages: list[BaseMessage]) -> list[object]:
    return [dumpd(message) for message in messages]


def write_interaction_log(
    *,
    debugger_dir: Path,
    event_type: str,
    model_name: str,
    messages: list[BaseMessage],
    output_payload: object | None,
    config: RunnableConfig,
    error: Exception | None = None,
    extra_input: dict[str, object] | None = None,
) -> None:
    input_payload = {
        "messages": message_payload(messages),
        "config": config,
    }
    if extra_input:
        input_payload.update(extra_input)

    write_debugger_log(
        debugger_dir=debugger_dir,
        event_type=event_type,
        model_name=model_name,
        input_payload=input_payload,
        output_payload=output_payload,
        config=config,
        error=error,
    )