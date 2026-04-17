# Agent 问题汇总与实施计划

日期：2026-04-17

## 背景

当前项目已经具备以下基础能力：

- 基于 LangGraph 的 agent 编排
- 基于 thread_id 的会话持久化
- 文件、bash、skill 等工具调用
- 基于 interrupt 的人工介入能力
- CLI 形态下的流式输出与恢复执行

当前需要统一收敛的核心问题有 3 类：

1. 长内容生成时，模型输出被截断后，没有继续生成，而是进入了重新生成或漂移到其他产物的路径。
2. 需要提供类似 Claude Code 的暂停确认机制，让用户对关键动作进行选择。
3. 后续要迁移到网页端，需要定义前端、后端、agent 之间统一的通信协议与交互模型。

## 问题 1：内容被截断后没有继续生成，而是重新生成

### 当前现象

- 模型单轮输出命中长度上限，内容在正文中间截断。
- agent 没有识别这是一次未完成输出。
- 后续没有进入“从上次中断处继续生成”的路径。
- 模型可能转而尝试重写全文、改写已有文件，或者生成一个简洁版替代产物。

### 根因拆解

1. 模型层

- 模型单轮输出存在长度上限。
- 当 finish_reason 为 length 时，输出实际并未完成。

2. 编排层

- 当前图没有针对 finish_reason=length 的专门分支。
- 当前图也没有“内容未完成检测”与“续写控制流”。

3. 工具层

- 续写目前主要依赖 edit_file 的精确 old_text 替换。
- 一旦匹配片段不稳定，续写失败后就容易出现漂移。

### 目标状态

- 模型输出被截断时，不应直接结束当前任务。
- agent 应明确进入“继续生成”或“请求用户确认是否继续生成”的流程。
- 续写应优先基于结构化定位，而不是脆弱的字符串片段替换。

### 计划

#### Phase 1：增加截断检测

- 在模型调用结果中读取 finish_reason。
- 若 finish_reason 为 length，则把本轮标记为 incomplete。
- 在状态中记录本轮是否因长度终止。

#### Phase 2：增加续写路由

- 在 route_after_model 之后增加一条“incomplete_output”分支。
- 该分支不走正常完成判定，而是进入续写处理。
- 续写处理优先尝试：
  - 基于文件尾部上下文续写
  - 基于章节标题续写
  - 基于用户确认后继续生成

#### Phase 3：规范长文生成策略

- 对长内容改为分段生成，不追求一次写完整篇。
- 按章节生成、按章节落盘、按章节校对。
- 最终汇总时只拼接最终产物，避免中途不断覆盖全量文件。

### 建议优先级

高优先级。

这是当前生成质量问题的首要来源，也是后续网页端“继续生成”交互的前提。

## 问题 2：提供类似 Claude Code 的暂停确认机制

### 目标能力

在执行高风险或关键动作前，让用户明确选择：

1. 是的，执行
2. 是的，执行，以后不再询问
3. 否

适用场景：

- 执行 bash 命令前
- 写文件、覆盖文件、批量编辑前
- 删除文件或高风险变更前
- 继续生成长内容前

### 当前基础

项目已具备 interrupt 能力：

- graph 中已有 human_assistance 工具
- CLI 已支持 interrupt 后暂停与 resume

这说明：

- “暂停并等待用户输入”在底层是可用的
- 但“结构化确认”还没有被正式建模

### 关键判断

这类功能可以通过 LangGraph 的 interrupt 实现。

但更推荐把它设计成结构化审批，而不是继续复用一个泛化的 human_assistance 文本输入。

### 计划

#### Phase 1：定义确认动作模型

定义统一的确认结果枚举，例如：

- approve_once
- approve_always
- deny
- continue_generation
- cancel_generation

#### Phase 2：增加确认节点或确认工具

建议新增明确语义的确认入口，例如：

- confirm_action
- request_approval

而不是把所有确认都塞给 human_assistance。

#### Phase 3：建立审批策略

按动作类型区分审批规则：

- bash 默认询问
- 写文件默认询问或按目录/后缀放行
- 只读工具默认不询问
- 长内容继续生成可询问，也可配置为自动继续

#### Phase 4：支持“以后不再询问”

需要明确作用域：

- 本次会话有效
- 当前 thread_id 有效
- 当前用户在当前 workspace 有效

建议先做“会话级”记忆，不直接做永久规则。

### 建议优先级

高优先级。

这是从 CLI 向网页端迁移前最重要的交互抽象之一。

## 问题 3：对接网页端与后端，统一通信协议

### 核心判断

网页端不会复用 CLI 的 input 心智。

网页端应改为：

- 前端展示事件流
- 后端驱动 graph 执行
- interrupt 变成一个中断事件
- 用户在前端完成确认或补充输入
- 后端拿到结果后 resume graph

### 设计目标

- 前端不理解 graph 内部节点，只消费标准事件
- 后端负责运行时管理、thread_id、resume 和权限控制
- agent 只负责推理、调工具和提出中断请求

### 协议原则

所有交互统一抽象成事件流。

建议至少有以下事件类型：

- message_delta
- message_completed
- tool_call_started
- tool_call_completed
- interrupt_requested
- interrupt_resolved
- run_completed
- run_failed

### interrupt 事件结构建议

interrupt_requested 至少包含：

- run_id
- thread_id
- interrupt_id
- interrupt_type
- title
- question
- options
- metadata

示例 interrupt_type：

- confirm_action
- continue_generation
- human_input

### resume 请求结构建议

前端提交后端的恢复请求至少包含：

- run_id
- thread_id
- interrupt_id
- action
- data

其中：

- action 用于表达结构化选择
- data 用于补充文本、选项或其他参数

### 计划

#### Phase 1：先定义事件协议

- 明确后端输出事件格式
- 明确前端提交 resume 的格式
- 不绑定具体前端框架实现

#### Phase 2：将 CLI 的流式事件抽象成通用 runtime 事件

- 把当前 CLI 中的 messages、updates、interrupts 抽象成统一协议
- CLI 只作为一个消费者
- 后续网页端作为第二个消费者

#### Phase 3：补后端服务层

后端负责：

- 创建 run
- 挂接 thread_id
- 推送事件流
- 接收 resume
- 控制权限和会话状态

#### Phase 4：补前端交互层

前端负责：

- 展示消息流
- 展示工具执行状态
- 展示 interrupt 卡片或审批弹窗
- 提交 resume

### 建议优先级

中高优先级。

它是网页端落地的基础，但应在“截断续写”和“确认机制”完成基础抽象后推进。

## 推荐实施顺序

### Step 1：先修复长内容截断后的续写路径

原因：

- 这是当前最直接影响生成质量的问题
- 后续“继续生成”交互也依赖这一层建模

### Step 2：再引入结构化确认机制

原因：

- 可以先在 CLI 中验证审批交互是否合理
- 这层抽象后续可以无缝迁移到网页端

### Step 3：最后统一网页端/后端通信协议

原因：

- 协议应建立在明确的 interrupt 和 runtime event 之上
- 否则容易把 CLI 特判直接复制到 Web，导致协议设计混乱

## 里程碑

### Milestone A：长内容生成稳定

完成标志：

- 模型截断后能进入续写流程
- 不再无故改写成简洁版或重复生成
- 长文改为分段生产

### Milestone B：审批交互统一

完成标志：

- bash / 写文件 / 长内容继续生成可统一走 interrupt
- 用户选择有结构化 action
- 支持会话级“以后不再询问”

### Milestone C：网页端协议可接入

完成标志：

- 有统一事件流协议
- 有统一 resume 协议
- 前端、后端、agent 职责边界清晰

## 风险与注意事项

### 风险 1：继续依赖全文重写

如果长文仍采用“一次写整篇、失败后再全量覆盖”的方式，后续仍会出现内容漂移。

### 风险 2：把审批做成纯文本问答

如果审批结果还是自由文本，后续网页端很难稳定解析，建议尽早结构化。

### 风险 3：前端理解 graph 内部节点

前端不应依赖 prepare_context、review_completion 这类内部节点名，否则后端 runtime 很难演进。

## 下一步建议

下一轮实现建议按下面顺序进行：

1. 在 graph 中补 finish_reason=length 的状态记录与续写路由。
2. 设计结构化 interrupt action，并补一个确认节点或确认工具。
3. 草拟网页端 runtime event / resume 协议，并让 CLI 先消费同一套协议。

## 跨对话引用说明

本文件用于后续跨对话引用，作为当前 agent 演进路线的统一上下文。

建议后续所有相关实现都围绕这三条主线展开：

1. 长内容续写
2. 结构化审批
3. Web 协议统一
