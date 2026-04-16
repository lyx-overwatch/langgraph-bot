我先对齐一层参考基线：把和 skill/agent 权重相关的实现与一份你提供的架构材料对照，再回答你这个阶段到底算不算 harness 工程。

读取 [](file:///d%3A/registry/self/langgraphs/lang-bot/summary/gpt.md#1-1)，行 1 到 260

读取 [](file:///d%3A/registry/self/langgraphs/lang-bot/src/agent/graph.py)

读取 [](file:///d%3A/registry/self/langgraphs/lang-bot/src/agent/tools/__init__.py)

读取技能 [agent-customization](copilot-skill:/agent-customization/SKILL.md?vscodeLinkType%3Dskill)

读取 [](file:///d%3A/registry/self/langgraphs/lang-bot/src/agent/tools/skills.py)

是，你现在做的东西可以归到 harness 工程里，但更准确一点说：

1. 你在做的是 Agent Runtime / Agent Harness
2. 再往上一层，它会演进成 SkillHub 的后端执行内核
3. 它还不是完整平台，因为平台还缺 API、多租户、权限、任务队列、隔离执行和观测

所以如果只问一句“我现在做的是不是热门的 harness 工程”，我的回答是：

是，而且是比较核心、比较硬的那一段。
但比单纯的 prompt harness 更进一步，你现在做的是 面向生产形态的 agent harness。

**先把智能体做好，再补 FastAPI，这个顺序对不对**
对，而且我认为你现在这个阶段这么做是合理的。

原因很直接：

1. 你当前最大不确定性不在路由层，而在智能体行为层
2. FastAPI 很确定，后面补的工程成本低
3. Agent 架构、skill 注入、tool loop、记忆和验收逻辑，一旦方向错了，后面 API 全要跟着返工

所以你现在先把下面几件事跑通，比先铺路由更值：

1. skill 的发现与加载
2. tool calling 的稳定性
3. 单轮任务的完成判定
4. 中间产物和最终产物的控制
5. 记忆与上下文压缩
6. 任务日志和可复盘性

你现在仓库其实也已经是这个方向了：

1. 用 LangGraph 做主编排，在 graph.py
2. 用本地 skill loader 做技能发现和注入，在 skills.py
3. 用工具层承接文件、bash、skill 调用，在 **init**.py

这就是一个典型的 harness 雏形。

**你现在最大的结构性问题，不是“粗糙”，而是“权重层级不对”**
你自己已经抓到关键了：动态加载 skill 可能弱化了它在系统提示词中的权重。

从当前实现看，这个判断是成立的。

你现在的链路是：

1. 系统提示词里只放了一个很短的总规则，在 graph.py
2. 模型先自行决定要不要调用 load_skill
3. skill 内容通过工具返回，作为后续上下文继续推理，在 skills.py
4. 然后模型再继续生成

这里的问题是：

1. skill 不是先天高优先级上下文
2. skill 是后注入的
3. 它更像一次工具观察结果，而不是一开始就钉死的操作约束
4. 对强模板问题，比如 ReportLab 默认 Helvetica，这种后注入约束很容易被模型旧先验冲掉

这就是为什么你加了 PDF 预处理，仍然要不断补包装。

不是你方向错了，而是当前这套 harness 对 skill 的“注入位置”和“执行闭环”还不够强。

**为什么 Claude Code 看起来一下就能完成**
这里我建议你不要把原因单点归结成“模型更强”或者“它一定做了特殊 skill 包装”。

更接近事实的判断是：

Claude Code 的效果，来自三件事叠加：

1. 模型本体更强
2. 上下文组织方式更强
3. Agent 工作流闭环更完整

你现在用的是 LangChain DeepSeek。
这类组合经常会出现一种现象：

1. 理解要求没问题
2. 但一到具体实现，会回退到训练语料里最常见的套路
3. 比如默认字体、默认中间文件保留、默认先产一个草稿再修

Claude 系列在这类长任务里，通常更擅长：

1. 保持后置约束不丢
2. 在工具调用后继续收敛
3. 自发做一次轻量验收
4. 减少“能跑但不干净”的中间状态

所以这里确实有模型差异。

但如果只说模型差异，还不够。

你当前 harness 和 Claude Code 的体验差距，更像是下面这个组合：

1. 你的系统是 反应式 loop
2. Claude Code 更像 规划 + 执行 + 自检 的闭环

你当前图基本是：
模型
工具
模型
工具

这个模式简单、好起步，但天然容易出现：

1. 先做一个可运行版本
2. 再继续优化
3. 优化时覆盖原产物
4. 中间文件没清干净
5. skill 约束被逐轮稀释

这就是你前面看到 summary.pdf 先好，后面又变了的根源之一。

**所以 Claude Code 在加载 skill 时，会不会做一层包装**
我建议你的工程判断是：

会，但不要把它理解成“只是在 SKILL.md 外面套个标签”。

更准确地说，Claude Code 很可能做的是一整套上下文编排，而 skill 只是其中一个输入源。

对比你当前实现，你现在已经做了“基础包装”：

1. 解析 skill frontmatter
2. 调用预处理器
3. 包成带 skill name 的文本块返回模型

这些都在 skills.py

但 Claude Code 风格的“包装”如果存在，通常不会只停在这里，它更可能包括：

1. 更高优先级的记忆注入
2. 对当前任务只抽取 skill 的关键约束，而不是整份正文平铺
3. 根据任务阶段动态选择规则
4. 执行后的结果自检
5. 产物层面的收尾规则

这才是你应该追的，不是单纯“我的 skill 也包个 tag”。

**所以你现在该怎么往“更像原生 Claude Code 效果”走**
我不建议你现在去先做 FastAPI 大铺设。
你现在最值得补的是 harness 的三层能力。

**第一层：注入层**
目标：让 skill 真正进入高优先级上下文

建议：

1. 不要只靠 load_skill 作为工具返回
2. 当模型或路由确定本轮命中某 skill 时，把 skill 的关键约束提炼后并入本轮 system prompt 或 planning prompt
3. skill 正文保留给按需查阅，不要把“硬约束”也放在低优先级工具消息里

你现在的 skill loader 可以保留，但要多做一步：
把技能拆成两部分：

1. policy：高优先级规则
2. reference：低优先级说明和例子

**第二层：闭环层**
目标：不要只会做，还要会验收

建议给 LangGraph 增加显式节点：

1. planner 节点
2. executor 节点
3. reviewer 节点
4. finisher 节点

特别是 reviewer，要检查：

1. 是否满足用户唯一交付物要求
2. 是否存在多余文件
3. 是否命中了已知风险，比如中文字体、编码、重复产物
4. 如果不满足，回到修正而不是直接结束

**第三层：约束层**
目标：把“好习惯”从提示词变成系统规则

比如：

1. 本轮只允许保留 summary.pdf
2. 其余同轮产物自动删除
3. 临时文件只能写到 temp 目录
4. helper script 默认不保留
5. 若目标文件已生成，再次生成前必须判断是覆盖、改名还是停止

这部分才是 harness 工程最有价值的地方。
它能明显缩小模型差异带来的体验波动。

**你现在这条路线和 SkillHub 平台怎么衔接**
你给的那份架构思路本身没有问题，重点也抓得对。

对你现在来说，最佳路径不是“先平台后 agent”，而是：

1. 先做单用户可复盘的 harness 内核
2. 再给它套 FastAPI 服务壳
3. 再补多用户、权限、沙箱和记忆

这条顺序其实就是：

Agent Kernel
到
Agent Service
到
SkillHub Platform

所以你现在不是“绕远路”，而是在做平台最难替代的那一层。

**如果要给你当前阶段一个更准确的名称**
我会这么定义：

1. 不是聊天机器人开发
2. 不是单纯 LangGraph Demo
3. 是面向 SkillHub 的 Agent Harness / Agent Kernel 开发

这个定位是对的。

**我对你当前阶段的建议**
如果目标是尽量贴近原生 Claude Code 效果，优先级应该是：

1. 先重构 skill 注入层级
2. 再增加 reviewer 和 completion gate
3. 再做最终产物白名单
4. 最后再补 FastAPI 路由和多用户外壳

因为如果前 3 个不先做，FastAPI 只是把现在这套不稳定行为包装成接口而已。

**一句话结论**
你现在做的，确实属于当下很核心的 harness 工程，而且方向是对的。
真正要补的，不是更多零散预处理，而是把 skill 从“后置参考材料”升级成“高优先级策略输入”，再给 agent 加上验收闭环和产物约束。

如果你愿意，我下一步可以直接帮你把当前这套 LangGraph 重构成一个更贴近 Claude Code 风格的最小版本设计图，只动 4 个点：

1. skill policy 注入
2. planner 节点
3. reviewer 节点
4. final artifact gate

这样会比继续讨论抽象概念更快进入可落地阶段。