# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码仓库中工作时提供指导。

## 项目概述

一个基于 LangGraph 的 CLI 智能体，以 DeepSeek Chat 为 LLM、Tavily 为网页搜索后端。智能体运行在一个双节点状态机图上（`call_model` → `call_tools`），通过 `InMemorySaver` 实现按 `thread_id` 持久化对话历史。每次 LLM 调用和工具执行都会以 JSON 文件形式记录到 `debugger/` 目录。

## Commands

```bash
# Install dependencies
pip install -e .

# Run the agent (interactive REPL)
python -m agent

# Run a single prompt
python -m agent "你的问题"

# Continue a conversation with a specific thread
python -m agent --thread-id my-thread "你的问题"

# Run unit tests
make test

# Run a specific test file
make test TEST_FILE=tests/unit_tests/test_configuration.py

# Run integration tests
make integration_tests

# Lint and type-check
make lint

# Format code
make format

# Spell check
make spell_check
```

## 架构

### 图结构（`src/agent/graph.py`）

LangGraph 实现了一个简洁的状态机：

```
START → call_model → tools_condition → call_tools → call_model → END
                      ↓ (no tools)
                       END
```

- **State**：`{"messages": Annotated[list, add_messages]}`
- **LLM**：`ChatDeepSeek(model="deepseek-chat", temperature=0)` 绑定工具后使用
- **Tools**：`bash`、`read_file`、`write_file`、`edit_file`、`load_skill`（来自 `tools/`）、`TavilySearch`，以及 `human_assistance`（用于基于 `interrupt` 的人机协作）
- **工作流优先**：系统提示词中明确要求智能体优先使用 `tavily_search` 联网搜索 factual / 实时问题，再使用工具和技能
- **错误处理**：工具错误在 `_wrap_tool_call` 中捕获，返回带中文错误提示的 `ToolMessage`；LLM 错误在 `call_model` 中捕获，返回降级 `AIMessage`

### 工具层（`src/agent/tools/`）

- `bash.py` — 封装 `bash -lc` 子进程；30 秒硬性超时，拦截危险命令模式
- `file.py` — 在 `workspace/` 下读写编辑文件；强制 `MAX_FILE_SIZE_BYTES` 限制，支持多编码回退（utf-8/gb18030/gbk/latin-1）
- `skills.py` — `SkillLoader` 在 `.skills/` 下扫描 `SKILL.md`，解析 YAML frontmatter；`load_skill(name)` 在返回前会经过预处理器管道进行优化
- `__init__.py` — 注册 `bash_tool`、`read_file_tool`、`write_file_tool`、`edit_file_tool`、`load_skill_tool` 为 `CUSTOM_TOOLS`

### 预处理器（`src/agent/tools/preprocessors/`）

Skill 内容在注入系统提示词之前，会经过一个预处理器注册表。每个 skill 可以注册一个处理器函数 `(name, body, context) -> str`，用于注入补充指令或修正已知问题。

注册方式：
```python
from agent.tools.preprocessors.registry import register

@register("pdf")
def pdf_preprocessor(name, body, context):
    # 在 ReportLab 代码块前注入中文字体处理说明
    return inject_cjk_notice(body)
```

内置预处理器：
- `pdf_preprocessor` — 在 PDF skill 的 ReportLab 部分前插入 CJK/中文字体处理指南（Noto Sans CJK SC 等），禁止 Unicode 下标/上标字符，并提供 `ensure_cjk_font` 检测辅助函数

### 技能（`.skills/`）

每个技能是一个目录，其中包含 `SKILL.md`，采用 YAML frontmatter（`name`、`description`、可选 `license`）+ Markdown 正文的格式。当前可用技能：`pdf`、`pptx`、`mcp-builder`、`skill-creator`、`content-research-writer`。

技能依赖在 frontmatter 中声明：
```yaml
python_packages: ['reportlab', 'pymupdf']
external_tools: ['pdftotext']
```

启动时若存在 `uv.lock`，智能体会通过 `uv pip install` 自动安装缺失的 Python 包。可通过 `AGENT_AUTO_INSTALL_SKILL_DEPS=0` 禁用此行为。

### 调试器（`src/agent/debugger.py`）

每次 LLM 响应和工具执行结果都会写入 `debugger/`，文件名含时间戳，JSON 内容包含：`id`、`timestamp`、`thread_id`、`event_type`（`llm`/`tool`）、`model`、`input`、`output` 及可选的 `error`。

### CLI（`src/agent/cli.py`）

- 以三种模式流式输出 LangGraph 运行结果：`messages`（token 级）、`updates`（节点状态增量）、`tasks`（任务调度事件）
- `StreamDebugPrinter` 在每个节点内实时内联打印 token，用分隔线区分节点
- 通过 `Command(resume=...)` 处理 `Interrupt`，实现人机协作暂停与恢复
- 默认 thread ID 为 `cli-results-01`；可通过 `--thread-id` 覆盖

### 环境变量

```text
DEEPSEEK_API_KEY=...        # Required
TAVILY_API_KEY=...          # Required
LANGSMITH_API_KEY=...       # Optional; enables LangSmith tracing
AGENT_LLM_TIMEOUT_SECONDS=60  # LLM timeout (default 60)
AGENT_LLM_MAX_RETRIES=2      # Max retries (default 2)
AGENT_SKILLS_DIR=...          # Override skills directory
AGENT_AUTO_INSTALL_SKILL_DEPS=0  # Disable auto-install skill dependencies
```

## 关键入口

- `src/agent/graph.py` — 已编译的 LangGraph、LLM、工具集和图的构建逻辑
- `src/agent/cli.py` — CLI REPL、输出流式打印、人机协作处理
- `src/agent/tools/__init__.py` — `CUSTOM_TOOLS` 工具列表及 `_skill_loader()` 单例
- `src/agent/debugger.py` — `write_interaction_log` 负责将每次交互导出为 JSON
- `langgraph.json` — LangGraph Server 配置；图以 `agent` 为名注册在 `src/agent/graph.py:graph`
