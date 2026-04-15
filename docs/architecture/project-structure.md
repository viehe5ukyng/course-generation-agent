# Project Structure

## Root

- `apps/api/`: FastAPI + LangGraph + LangChain 后端
- `frontend/`: 当前唯一有效的 Vue 前端工程
- `apps/web/`: 预留目录，当前不承载生产前端代码
- `config/`: 运行时配置文件
- `prompts/`: Prompt 模板
- `docs/`: 项目文档
- `apps/api/pyproject.toml`: Python 依赖与项目元数据的唯一权威入口
- `requirements.txt`: 兼容性安装清单，作为 `pyproject.toml` 的镜像而不是新的来源

## API Service

- `app/api/routes/`: 按线程、文件、审核、事件拆分的路由
- `app/application/`: 应用层 use-cases 与实验编排
- `app/core/`: settings、schemas、prompt registry
- `app/files/`: 文件解析
- `app/infrastructure/`: DeepAgents 等基础设施适配器
- `app/llm/`: DeepSeek 调用
- `app/review/`: 评分规则
- `app/services/`: 服务编排
- `app/storage/`: 仓储边界与 SQLite 持久化
- `app/workflows/`: LangGraph 工作流与节点

## Frontend Contract Flow

- `docs/api/openapi.json`
  - FastAPI 导出的 OpenAPI 契约
- `frontend/src/generated/api.d.ts`
  - 从 OpenAPI 自动生成的 TypeScript 类型
- `frontend/src/lib/api.ts`
  - 基于生成类型的请求封装

## Prompt Management

- `prompts/deepseek/clarify_requirements.md`
- `prompts/deepseek/generate_markdown.md`
- `prompts/deepseek/review_markdown.md`
- `prompts/deepseek/improve_markdown.md`

## Redesign Docs

- `docs/redesign/00-research.md`
- `docs/redesign/01-system-overview.md`
- `docs/redesign/02-conversation-state-machine.md`
- `docs/redesign/04-api-contract.md`
- `docs/redesign/07-deepagents-experiment-design.md`
