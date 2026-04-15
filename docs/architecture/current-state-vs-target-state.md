# Current State vs Target State

## Current State

### 当前真实主链路

当前主链路实际由 `CourseAgentService.ingest_message()` 驱动，先把用户消息写入线程状态，再直接触发 `CourseGraph.run_thread()`。真实执行链是：

1. `POST /api/v1/threads/{thread_id}/messages`
2. `CourseAgentService.ingest_message()`
3. `CourseGraph.run_thread()`
4. `intake_message -> requirement_gap_check`
5. 分流到 `clarify_question` / `confirm_requirements` / `apply_manual_feedback` / `decision_update`
6. `source_parse -> outline_generate -> case_design_generate -> script_generate -> draft_assemble -> critique_score`
7. 如果低分则 `auto_improve`，否则 `human_review_interrupt`
8. 人工提交后 `approved_feedback_merge -> revise_draft -> completion_gate`

代码证据：

- `apps/api/app/services/course_agent.py`
- `apps/api/app/workflows/course_graph.py`

### 当前持久化边界

当前持久化边界并不清晰，主要依赖三处：

1. `threads.state_json`
   - 整个 `ThreadState` 直接 JSON 序列化进 SQLite。
   - 消息、需求槽位、约束、当前稿件、版本索引、评审批次、生成运行记录、运行时临时变量都混在一个聚合里。
2. `timeline_events`
   - 用户可见时间线单独存表。
3. `audit_events`
   - 审计事件单独存表。

但真正的 artifact history、decision records、pause/resume 状态、当前 generation session 上下文并没有独立仓储，而是继续塞进 `ThreadState.run_metadata`。

### 当前 workflow 与 service 的职责重叠点

当前 `CourseAgentService` 与 `CourseGraph` 都在同时承担应用编排职责：

- `CourseAgentService`
  - 决定何时触发 graph
  - 直接修改线程状态
  - 直接维护 pause/resume 语义
  - 直接维护 decision records 与 artifact history
  - 直接调用 LLM 做 `regenerate()`
- `CourseGraph`
  - 既做 workflow routing，又持有大量业务状态拼装逻辑
  - 直接写 `run_metadata`
  - 直接创建 `GenerationRun`
  - 直接拼装评审、修订、完成条件

这导致：

- 版本生成逻辑分散在 graph 节点和 service `regenerate()` 两套路径里。
- review completion 逻辑只在 graph 内成立，service 端的再生成和评审写入又绕开了一部分状态约束。
- interrupt/resume 既依赖 LangGraph，又依赖 service 自己维护的暂停状态和 payload。

### 当前 API 文档与代码实现不一致的地方

`docs/api/http-api.md` 只列了部分接口，且没有反映实际新增的能力：

- 文档缺少：
  - `PATCH /api/v1/threads/{thread_id}/mode`
  - `POST /api/v1/threads/{thread_id}/confirm-step`
  - `GET /api/v1/threads/{thread_id}/history`
  - `POST /api/v1/threads/{thread_id}/pause`
  - `POST /api/v1/threads/{thread_id}/resume`
  - `DELETE /api/v1/threads/{thread_id}/messages/last`
  - `PUT /api/v1/threads/{thread_id}/messages/last`
  - `DELETE /api/v1/threads/{thread_id}`
  - `PATCH /api/v1/threads/{thread_id}/artifacts/latest`
  - `GET /api/v1/decision-records`
  - `GET /api/v1/threads/{thread_id}/decision-records`
  - `GET /api/v1/decision-model/status`
- 文档没有反映真实 envelope 结构与错误结构。
- 代码没有用 OpenAPI schema 作为唯一真相，前端类型是手写的，导致漂移必然发生。

### 当前前端单体组件的问题

`frontend/src/App.vue` 约 1800+ 行，问题非常明确：

- Workspace shell、thread sidebar、message list、artifact viewer、review panel、timeline 数据拉取都塞在一个组件里。
- 网络请求、SSE 订阅、线程状态管理、artifact/version 管理、文件查看器状态全部混在 `<script setup>` 中。
- `frontend/src/lib/api.ts` 仍然大量使用 `any`。
- `frontend/src/types.ts` 是手写模型，不受后端 schema 约束。
- `apps/web/` 与 `frontend/` 同时存在，但真实运行入口只有 `frontend/`，目录语义漂移。

## Target State

### 目标主链路

目标链路应收敛为：

1. HTTP 路由只负责协议与 schema
2. Application use-case 负责线程、消息、评审、版本、文件的业务编排
3. Workflow orchestration 只负责 LangGraph 节点路由与 interrupt/resume
4. Repository 层分别管理：
   - Thread
   - ArtifactVersion
   - ReviewBatch
   - TimelineEvent
   - DecisionRecord
5. OpenAPI 成为前后端唯一契约源

### 目标持久化边界

- `ThreadRepository`
  - 只负责线程聚合根与当前运行态快照
- `ArtifactVersionRepository`
  - 负责版本列表、历史内容、diff 源数据
- `ReviewBatchRepository`
  - 负责评审批次与建议
- `TimelineEventRepository`
  - 负责用户可见时间线
- `DecisionRecordRepository`
  - 负责人工评审训练样本
- `LangGraph Durable Checkpointer`
  - 负责 interrupt/resume 所需 checkpoint

### 目标职责划分

- `CourseAgentService`
  - 收缩为 facade，只暴露应用用例入口
- `application/*`
  - 按线程、对话、artifact、review、file 拆分 use-cases
- `CourseGraph`
  - 只做 orchestration，不再承担业务数据库职责
- `run_metadata`
  - 不再承载主业务；临时运行态转为结构化 runtime state

### 目标 API 契约

- `FastAPI OpenAPI` 为唯一真相
- `docs/api/openapi.json` 由后端导出
- `frontend` 类型与 client 从 OpenAPI 自动生成
- 手写 `frontend/src/types.ts` 退场或只保留纯 UI 层 view models

### 目标前端结构

- `App.vue`
  - 只负责组合页面与顶层装配
- `components/`
  - `WorkspaceShell`
  - `ThreadSidebar`
  - `MessageList`
  - `ArtifactPanel`
  - `ReviewPanel`
  - `TimelinePanel`
- `composables/`
  - `useThreadWorkspace`
  - `useThreadStream`
  - `useArtifacts`
  - `useApiClient`

## 本次分阶段改造方案

### Phase 1

- 固化 current-state vs target-state 文档
- 导出真实 OpenAPI 基线
- 补齐 API 文档缺口

### Phase 2

- 引入结构化 runtime state，替代 `run_metadata`
- 拆出独立 repositories
- 把 `CourseAgentService` 收缩为 use-case facade
- 把 `CourseGraph` 收到 workflow orchestration
- 切换 durable LangGraph checkpointer

### Phase 3

- 建立 OpenAPI -> frontend types/client 生成链路
- 拆 `App.vue`
- 抽 composables
- 保持现有交互不回退

### Phase 4

- 明确唯一前端目录
- 明确 Python 依赖入口角色
- 补状态流转、interrupt/resume、artifact versioning、review completion 测试
- 更新最终目录结构、时序图、状态机与验证清单
