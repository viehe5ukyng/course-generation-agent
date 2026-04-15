# Data Model

## Core Entities
- `ThreadState`
  - 线程聚合根，包含消息、需求槽位、约束、当前草稿、版本链、评审批次、生成运行记录和结构化 runtime state。
- `ConversationConstraint`
  - 用户显式要求或显式禁止的内容。
  - 典型例子：`不要咖啡馆案例`、`必须基于真实案例`。
- `DraftArtifact`
  - 当前版本课程稿。
  - 关键字段：`version`、`source_version`、`revision_goal`、`generation_run_id`。
- `ArtifactVersionDetail`
  - 某一历史版本的完整可读快照。
- `GenerationRun`
  - 一次生成或修订运行记录。
- `TimelineEvent`
  - 用户可读时间线事件。
- `DecisionRecord`
  - 人工审核反馈形成的训练样本，独立持久化。
- `ThreadRuntimeState`
  - 结构化运行时状态，替代旧的 `run_metadata` 字典。

## Persistence Strategy
- SQLite 中存六类持久化对象：
  - `threads`
  - `artifact_versions`
  - `review_batches`
  - `timeline_events`
  - `audit_events`
  - `decision_records`

## Versioning Rules
- 当前草稿始终挂在 `draft_artifact`。
- 历史版本进入 `artifact_versions` 仓储。
- `version_chain` 只存轻量索引，供线程聚合和前端快速展示版本列表。
