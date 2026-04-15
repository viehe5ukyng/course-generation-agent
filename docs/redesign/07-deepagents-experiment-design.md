# DeepAgents Experiment Design

## Positioning
- `DeepAgents` 不进入默认用户主链路。
- 只做复杂规划、研究、评审的实验入口。

## Why Experimental
- 当前产品的核心问题是状态、约束、版本和修订链路，而不是缺少通用代理能力。
- 先把主链路稳定下来，再让 DeepAgents 处理更复杂的 planning/review/research 场景。

## Bundles
- `DeepAgentsPlanBundle`
  - 输出复杂制课计划、案例策略、修订重点。
- `DeepAgentsReviewBundle`
  - 输出问题列表和修订指令。
- `DeepAgentsResearchBundle`
  - 输出候选案例池、风险、建议。

## Guardrails
- 不直接写最终课程稿。
- 不启用文件系统写入或 shell 执行。
- 主链路只消费结构化 bundle，不消费自由文本终稿。
