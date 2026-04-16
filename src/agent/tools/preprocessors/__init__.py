"""Preprocessor registry and built-in preprocessors.

Register new preprocessors with the `@register("skill-name")` decorator.
All preprocessors are imported here so that importing this package
has the side-effect of registering them.
"""

# Import all built-in preprocessors (triggers @register decorators).
from agent.tools.preprocessors.pdf_preprocessor import pdf_preprocessor  # noqa: F401
from agent.tools.preprocessors.registry import register, run_preprocessors

__all__ = ["register", "run_preprocessors", "pdf_preprocessor"]
