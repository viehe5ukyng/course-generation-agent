#  Research Notes

## 结论
- 主对话运行时继续以 `LangGraph + LangChain` 为核心。
- `DeepAgents` 只作为实验性复杂规划层接入，不进入默认用户主链路。
- 线程、版本、约束、时间线必须持久化，不能继续依赖进程内内存。

## 官方文档结论
- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)
  - 适合长生命周期、可恢复、可人工介入的状态机工作流。
  - 官方强调 persistence、threads、checkpoint、human-in-the-loop。
- [LangChain Overview](https://docs.langchain.com/oss/python/langchain/overview)
  - 适合模型抽象、messages、结构化输出、提示模板与工具集成。
  - 结构化输出和 provider 抽象适合做模型切换和空值治理。
- [DeepAgents Overview](https://docs.langchain.com/oss/python/deepagents/overview)
  - 更适合研究、复杂规划、子代理分工、文件上下文管理。
  - 对当前制课产品，更适合做 planning/review/research 的实验层，而不是默认对话主链路。

## 当前项目问题映射
- 回答少、几乎无引导：澄清逻辑一次传入多个缺失项，缺少单槽位推进策略。
- 出现 `null`：内部结构化提取没有问题，但输出边界没有做“空值只转待澄清项”的规范。
- 历史丢失：旧实现只用内存 `ThreadStore` 和 `MemorySaver`。
- 再生成几乎不变：修订只把“整篇 markdown + 一句 instruction”交给模型，没有版本来源、约束黑名单和明确差异目标。
- 不听反馈：负约束没有进状态实体，只存在于临时消息或 prompt 文本里。
- 前端不知道是否生成完成：SSE 事件语义过粗，只能靠旧 token 流和 node_update 猜状态。

## V2 选型原则
- 稳定性优先于一次性大改。
- 主链路先修对，再给 DeepAgents 留实验入口。
- 配置切换模型，不改业务代码。
