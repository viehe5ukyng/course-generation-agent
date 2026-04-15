from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_decision_model_service, get_service
from app.core.schemas import (
    ApiEnvelope,
    DecisionModelStatusResponse,
    DecisionRecordsResponse,
    ReviewBatchResponse,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
)
from app.services.course_agent import CourseAgentService
from app.services.decision_model import DecisionModelService
from app.storage.thread_store import ThreadNotFoundError


router = APIRouter()


def envelope(*, data: dict, thread_id: str | None = None, request_id: str | None = None) -> ApiEnvelope:
    return ApiEnvelope(request_id=request_id or uuid4().hex, thread_id=thread_id, data=data)


@router.get("/threads/{thread_id}/review-batches/{batch_id}", response_model=ApiEnvelope[ReviewBatchResponse])
async def get_review_batch(thread_id: str, batch_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        batch = await service.store.get_review_batch(thread_id, batch_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "review_batch_not_found", "message": str(exc)},
        ) from exc
    return envelope(thread_id=thread_id, data={"review_batch": batch.model_dump(mode="json")})


@router.post("/threads/{thread_id}/review-batches/{batch_id}/submit", response_model=ApiEnvelope[ReviewSubmitResponse])
async def submit_review(
    thread_id: str,
    batch_id: str,
    request: ReviewSubmitRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        await service.submit_review(thread_id, batch_id, request)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"submitted": True, "review_batch_id": batch_id})


@router.get("/decision-records", response_model=ApiEnvelope[DecisionRecordsResponse])
async def list_decision_records(service: CourseAgentService = Depends(get_service)):
    records = await service.export_decision_records()
    return envelope(data={"records": records})


@router.get("/threads/{thread_id}/decision-records", response_model=ApiEnvelope[DecisionRecordsResponse])
async def list_thread_decision_records(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        records = await service.export_decision_records(thread_id=thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"records": records})


@router.get("/decision-model/status", response_model=ApiEnvelope[DecisionModelStatusResponse])
async def decision_model_status(decision_model_service: DecisionModelService = Depends(get_decision_model_service)):
    return envelope(data={"status": decision_model_service.status()})
