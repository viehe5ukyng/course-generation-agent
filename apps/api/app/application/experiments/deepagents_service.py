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
from app.infrastructure.deepagents import DeepAgentsRunner


@dataclass
class DeepAgentsExperimentService:
    runner: DeepAgentsRunner

    async def plan(self, request: DeepAgentsPlanRequest) -> DeepAgentsPlanBundle:
        return await self.runner.plan(request)

    async def review(self, request: DeepAgentsReviewRequest) -> DeepAgentsReviewBundle:
        return await self.runner.review(request)

    async def research(self, request: DeepAgentsResearchRequest) -> DeepAgentsResearchBundle:
        return await self.runner.research(request)
