# API Contract

## Source of Truth

- 机器契约：`docs/api/openapi.json`
- 导出入口：`scripts/export_openapi.py`
- 前端生成入口：`frontend/package.json -> generate:api`

## Threads
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/threads` | 创建线程 |
| GET | `/api/v1/threads` | 获取线程列表 |
| GET | `/api/v1/threads/{thread_id}` | 获取线程摘要与当前状态 |
| PATCH | `/api/v1/threads/{thread_id}/mode` | 切换单课/系列课 |
| POST | `/api/v1/threads/{thread_id}/confirm-step` | 确认当前步骤 |
| POST | `/api/v1/threads/{thread_id}/messages` | 发送消息 |
| PUT | `/api/v1/threads/{thread_id}/messages/last` | 编辑上一条用户消息 |
| DELETE | `/api/v1/threads/{thread_id}/messages/last` | 撤回上一条用户消息 |
| POST | `/api/v1/threads/{thread_id}/pause` | 暂停线程 |
| POST | `/api/v1/threads/{thread_id}/resume` | 恢复线程 |
| GET | `/api/v1/threads/{thread_id}/timeline` | 获取用户可读时间线 |
| GET | `/api/v1/threads/{thread_id}/versions` | 获取版本列表 |
| GET | `/api/v1/threads/{thread_id}/history` | 获取 workflow checkpoint 历史 |
| POST | `/api/v1/threads/{thread_id}/regenerate` | 基于指定版本重新生成 |
| DELETE | `/api/v1/threads/{thread_id}` | 删除线程 |

## Artifacts
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/threads/{thread_id}/files` | 获取上传文件列表 |
| POST | `/api/v1/threads/{thread_id}/files` | 上传上下文或素材包 |
| GET | `/api/v1/threads/{thread_id}/artifacts/latest` | 获取当前草稿 |
| GET | `/api/v1/threads/{thread_id}/artifacts/{version}` | 获取指定版本 |
| PATCH | `/api/v1/threads/{thread_id}/artifacts/latest` | 人工编辑最新草稿 |
| GET | `/api/v1/threads/{thread_id}/artifacts/{version}/diff/{prev_version}` | 查看版本差异 |

## Reviews and Decisions
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/threads/{thread_id}/review-batches/{batch_id}` | 获取评审批次 |
| POST | `/api/v1/threads/{thread_id}/review-batches/{batch_id}/submit` | 提交人工审核动作 |
| GET | `/api/v1/decision-records` | 导出全局决策记录 |
| GET | `/api/v1/threads/{thread_id}/decision-records` | 导出线程级决策记录 |
| GET | `/api/v1/decision-model/status` | 查看决策模型状态 |

## Experiments
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/experiments/deepagents/plan` | 复杂规划 bundle |
| POST | `/api/v1/experiments/deepagents/review` | 修订评审 bundle |
| POST | `/api/v1/experiments/deepagents/research` | 案例研究 bundle |

## SSE Events
- `clarification_started`
- `clarification_completed`
- `generation_started`
- `generation_chunk`
- `generation_completed`
- `review_ready`
- `revision_started`
- `revision_completed`
- `thread_paused`
- `thread_resumed`
- `thread_failed`
