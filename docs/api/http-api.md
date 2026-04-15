# HTTP API

## Source of Truth

当前 API 契约以 FastAPI 导出的 OpenAPI 为准：

- 机器可读契约：`docs/api/openapi.json`
- 导出命令：`./.venv/bin/python scripts/export_openapi.py`
- 前端类型生成：`cd frontend && npm run generate:api`

本文档只保留面向人的路由总览，不再维护第二份字段级真相。

## Threads

- `POST /api/v1/threads`
- `GET /api/v1/threads`
- `GET /api/v1/threads/{thread_id}`
- `PATCH /api/v1/threads/{thread_id}/mode`
- `POST /api/v1/threads/{thread_id}/confirm-step`
- `POST /api/v1/threads/{thread_id}/messages`
- `PUT /api/v1/threads/{thread_id}/messages/last`
- `DELETE /api/v1/threads/{thread_id}/messages/last`
- `POST /api/v1/threads/{thread_id}/pause`
- `POST /api/v1/threads/{thread_id}/resume`
- `POST /api/v1/threads/{thread_id}/regenerate`
- `DELETE /api/v1/threads/{thread_id}`

## Artifacts and Files

- `GET /api/v1/threads/{thread_id}/files`
- `POST /api/v1/threads/{thread_id}/files`
- `GET /api/v1/threads/{thread_id}/artifacts/latest`
- `PATCH /api/v1/threads/{thread_id}/artifacts/latest`
- `GET /api/v1/threads/{thread_id}/artifacts/{version}`
- `GET /api/v1/threads/{thread_id}/artifacts/{version}/diff/{prev_version}`
- `GET /api/v1/threads/{thread_id}/versions`

## Reviews and Decisions

- `GET /api/v1/threads/{thread_id}/review-batches/{batch_id}`
- `POST /api/v1/threads/{thread_id}/review-batches/{batch_id}/submit`
- `GET /api/v1/decision-records`
- `GET /api/v1/threads/{thread_id}/decision-records`
- `GET /api/v1/decision-model/status`

## Events and Timeline

- `GET /api/v1/threads/{thread_id}/stream`
- `GET /api/v1/threads/{thread_id}/events`
- `GET /api/v1/threads/{thread_id}/timeline`
- `GET /api/v1/threads/{thread_id}/history`

## Experiments

- `POST /api/v1/experiments/deepagents/plan`
- `POST /api/v1/experiments/deepagents/review`
- `POST /api/v1/experiments/deepagents/research`
