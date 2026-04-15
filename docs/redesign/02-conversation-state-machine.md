# Conversation State Machine

## Summary
- 对话状态机只解决一件事：把用户从需求模糊带到课程可交付，并且在每一步都有可解释状态。

```mermaid
stateDiagram-v2
    [*] --> collecting_requirements
    collecting_requirements --> collecting_requirements: 用户继续补充
    collecting_requirements --> confirming_requirements: 缺失槽位清空
    confirming_requirements --> generating: 用户确认开始
    generating --> review_pending: 主稿生成完成并评分
    review_pending --> revising: 用户采纳反馈或主动再生成
    revising --> review_pending: 新版本生成完成并重新评分
    review_pending --> completed: 达到完成条件
    collecting_requirements --> failed: 异常
    generating --> failed: 异常
    revising --> failed: 异常
```

## Core Rules
- 一次只追问一个缺失槽位。
- 用户明确的负约束在所有后续节点都必须生效。
- 每一次生成和修订都必须生成新版本。
- 评审前后都要写时间线事件，前端不直接读 LangGraph 原始 checkpoint。
