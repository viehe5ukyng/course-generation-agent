from uuid import uuid4

from fastapi import APIRouter, Depends

from app.api.deps import get_deepagents_service
from app.application.experiments import DeepAgentsExperimentService
from app.core.schemas import (
    ApiEnvelope,
    DeepAgentsPlanEnvelope,
    DeepAgentsPlanRequest,
    DeepAgentsResearchEnvelope,
    DeepAgentsResearchRequest,
    DeepAgentsReviewEnvelope,
    DeepAgentsReviewRequest,
)


router = APIRouter()


def envelope(*, data: dict, thread_id: str | None = None, request_id: str | None = None) -> ApiEnvelope:
    return ApiEnvelope(request_id=request_id or uuid4().hex, thread_id=thread_id, data=data)


@router.post("/experiments/deepagents/plan", response_model=ApiEnvelope[DeepAgentsPlanEnvelope])
async def deepagents_plan(
    request: DeepAgentsPlanRequest,
    service: DeepAgentsExperimentService = Depends(get_deepagents_service),
):
    bundle = await service.plan(request)
    return envelope(thread_id=request.thread_id, data={"bundle": bundle.model_dump(mode="json")})


@router.post("/experiments/deepagents/review", response_model=ApiEnvelope[DeepAgentsReviewEnvelope])
async def deepagents_review(
    request: DeepAgentsReviewRequest,
    service: DeepAgentsExperimentService = Depends(get_deepagents_service),
):
    bundle = await service.review(request)
    return envelope(thread_id=request.thread_id, data={"bundle": bundle.model_dump(mode="json")})


@router.post("/experiments/deepagents/research", response_model=ApiEnvelope[DeepAgentsResearchEnvelope])
async def deepagents_research(
    request: DeepAgentsResearchRequest,
    service: DeepAgentsExperimentService = Depends(get_deepagents_service),
):
    bundle = await service.research(request)
    return envelope(thread_id=request.thread_id, data={"bundle": bundle.model_dump(mode="json")})
