# New LangGraph Project

[![CI](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml)
[![Integration Tests](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml)

This template demonstrates a simple application implemented using [LangGraph](https://github.com/langchain-ai/langgraph), designed to run directly from a Python script without relying on LangGraph Server.

<div align="center">
  <img src="./static/studio_ui.png" alt="Graph view in LangGraph studio UI" width="75%" />
</div>

The core logic defined in `src/agent/graph.py`, showcases an single-step application that responds with a fixed string and the configuration provided.

You can extend this graph to orchestrate more complex agentic workflows that can be visualized and debugged in LangGraph Studio.

## Getting Started

1. Install dependencies.

```bash
cd path/to/your/app
pip install -e .
```

1. (Optional) Customize the code and project as needed. Create a `.env` file if you need to use secrets.

```bash
cp .env.example .env
```

If you want to enable LangSmith tracing, add your LangSmith API key to the `.env` file.

```text
# .env
LANGSMITH_API_KEY=lsv2...
```

1. Start the agent from a script.

```shell
python -m agent
```

You can also run a single prompt directly:

```shell
python -m agent "今天北京天气怎么样？"
```

Every LLM request/response pair and tool invocation is exported as a JSON file under the `debugger/` directory.

## Skill Dependencies

Local skills can declare runtime requirements in SKILL frontmatter:

```yaml
python_packages: ['reportlab', 'pymupdf']
python_modules: ['reportlab', 'fitz']
external_tools: ['pdftotext']
```

At startup, the agent checks these requirements, detects uv-managed projects via `uv.lock`, and prefers `uv pip install --python <current interpreter>` for missing Python packages. Non-uv projects fall back to `python -m pip`. The agent also adds an availability summary to the system prompt and `load_skill(...)` output. Set `AGENT_AUTO_INSTALL_SKILL_DEPS=0` to disable automatic installation.

## How to customize

1. **Define runtime context**: Modify the `Context` class in the `graph.py` file to expose the arguments you want to configure per assistant. For example, in a chatbot application you may want to define a dynamic system prompt or LLM to use. For more information on runtime context in LangGraph, [see here](https://langchain-ai.github.io/langgraph/agents/context/?h=context#static-runtime-context).

2. **Extend the graph**: The core logic of the application is defined in [graph.py](./src/agent/graph.py). You can modify this file to add new nodes, edges, or change the flow of information.

## Development

The script mode keeps conversation state by `thread_id`. Use `python -m agent --thread-id some-thread` to continue an existing conversation or start a new one with a different thread.

For more advanced features and examples, refer to the [LangGraph documentation](https://langchain-ai.github.io/langgraph/). These resources can help you adapt this template for your specific use case and build more sophisticated conversational agents.
