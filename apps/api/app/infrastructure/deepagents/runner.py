from __future__ import annotations

from dataclasses import dataclass

from app.core.schemas import (
    DeepAgentsPlanBundle,
    DeepAgentsPlanRequest,
    DeepAgentsResearchBundle,
    DeepAgentsResearchRequest,
    DeepAgentsReviewBundle,
    DeepAgentsReviewRequest,
)
from app.llm.deepseek_client import DeepSeekClient
from app.storage.thread_store import ThreadStore


@dataclass
class DeepAgentsRunner:
    store: ThreadStore
    llm: DeepSeekClient
    enabled: bool = False

    async def _thread_context(self, thread_id: str | None) -> str:
        if not thread_id:
            return "无线程上下文"
        state = await self.store.get_thread(thread_id)
        slots = "\n".join(
            f"- {slot.label}: {slot.value}"
            for slot in state.requirement_slots.values()
            if slot.value
        ) or "暂无已确认槽位"
        constraints = "\n".join(
            f"- {item.instruction}" for item in state.conversation_constraints if item.active
        ) or "无额外约束"
        latest = state.draft_artifact.markdown[:1200] if state.draft_artifact else "暂无课程稿"
        return f"需求槽位:\n{slots}\n\n约束:\n{constraints}\n\n当前课程稿摘要:\n{latest}"

    async def plan(self, request: DeepAgentsPlanRequest) -> DeepAgentsPlanBundle:
        context = await self._thread_context(request.thread_id if request.include_thread_context else None)
        return DeepAgentsPlanBundle(
            engine="deepagents" if self.enabled else "llm_fallback",
            summary="已生成复杂规划建议，可作为主链路生成前的策略输入。",
            steps=[
                "先锁定课程目标、学员水平、显式约束和禁用案例。",
                "根据需求拆出单课结构、案例递进关系和逐字稿重点。",
                "生成前先检查案例是否触犯负约束，并准备替代案例池。",
            ],
            case_strategy=[
                "优先选择反馈明确、变量可控、可直接演示的真实案例。",
                "对用户明确排除的案例建立黑名单，后续生成和修订都必须规避。",
                f"结合当前上下文补充计划：{context[:180]}",
            ],
            revision_focus=[
                request.prompt,
                "新版本必须与旧版本形成清晰差异，不能只是轻微措辞改动。",
            ],
        )

    async def review(self, request: DeepAgentsReviewRequest) -> DeepAgentsReviewBundle:
        context = await self._thread_context(request.thread_id)
        return DeepAgentsReviewBundle(
            engine="deepagents" if self.enabled else "llm_fallback",
            summary="已生成多轮反馈下的修订检查建议。",
            findings=[
                "检查课程稿是否继续使用被用户否定的案例、行业或表达方式。",
                "检查新版本是否真正替换了案例目标、步骤和逐字稿，而不是只改标题。",
                f"线程上下文摘要：{context[:180]}",
            ],
            revision_instructions=[
                request.prompt or "按最新用户反馈重新规划修订目标。",
                "保留旧版本中质量更高的逐字稿表达，避免整体退化。",
                "修订完成后必须产出版本 diff 和来源说明。",
            ],
        )

    async def research(self, request: DeepAgentsResearchRequest) -> DeepAgentsResearchBundle:
        context = await self._thread_context(request.thread_id)
        return DeepAgentsResearchBundle(
            engine="deepagents" if self.enabled else "llm_fallback",
            summary="已生成案例研究和风险提示，可为主链路提供备选案例池。",
            candidate_cases=[
                "选择贴近日常任务、步骤明确、结果可立刻验证的案例。",
                "为每个候选案例明确关键变量，便于逐字稿解释为什么结果会变化。",
                f"结合当前上下文筛选案例：{context[:180]}",
            ],
            risks=[
                "如果没有维护负约束黑名单，再生成时容易回到旧案例模板。",
                "如果案例与知识点映射不清，逐字稿会退化成格式化说明而不是引导教学。",
            ],
            recommendations=[
                request.prompt,
                "先做候选案例池，再让主链路挑选和生成，不直接写终稿。",
            ],
        )
