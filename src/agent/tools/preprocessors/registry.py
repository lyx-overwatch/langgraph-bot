"""Skill preprocessors: transform skill content before it is injected into the system prompt.

Each preprocessor is a callable `(skill_name: str, body: str, context: dict) -> str`.
The context dict currently includes `workspace` (Path) and `task_hint` (str | None).

Usage
-----
```python
from agent.tools.preprocessors import register, run_preprocessors

# Register a preprocessor for a specific skill
@register("my-skill")
def optimize_my_skill(name: str, body: str, context: dict) -> str:
    # patch the body ...
    return body

# During skill loading the SkillLoader calls this automatically.
```
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

# Registry: skill name -> preprocessor function
_REGISTRY: dict[str, Callable[[str, str, dict[str, Any]], str]] = {}


def register(name: str) -> Callable:
    """Register a preprocessor for `name`.

    ```python
    @register("pdf")
    def pdf_preprocessor(name, body, ctx): ...
    ```
    """

    def decorator(fn: Callable[[str, str, dict[str, Any]], str]) -> Callable:
        _REGISTRY[name] = fn
        return fn

    return decorator


def run_preprocessors(
    skill_name: str, body: str, *, workspace: Path | None = None, task_hint: str | None = None
) -> str:
    """Apply all registered preprocessors for `skill_name` (if any) to `body`."""
    processor = _REGISTRY.get(skill_name)
    if processor is None:
        return body
    context: dict[str, Any] = {}
    if workspace is not None:
        context["workspace"] = workspace
    if task_hint is not None:
        context["task_hint"] = task_hint
    return processor(skill_name, body, context)
