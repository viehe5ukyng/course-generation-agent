from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_service
from app.core.schemas import (
    ApiEnvelope,
    BooleanResultResponse,
    ConfirmStepRequest,
    CreateThreadResponse,
    ModeUpdateRequest,
    RegenerateRequest,
    SendMessageRequest,
    ThreadDetailResponse,
    ThreadHistoryResponse,
    ThreadListResponse,
    ThreadStateResponse,
    ThreadTimelineResponse,
    ThreadVersionsResponse,
    ArtifactResponse,
)
from app.services.course_agent import CourseAgentService
from app.storage.thread_store import ThreadNotFoundError


router = APIRouter()


def envelope(*, data: dict, thread_id: str | None = None, request_id: str | None = None) -> ApiEnvelope:
    return ApiEnvelope(request_id=request_id or uuid4().hex, thread_id=thread_id, data=data)


@router.post("/threads", response_model=ApiEnvelope[CreateThreadResponse])
async def create_thread(service: CourseAgentService = Depends(get_service)):
    thread = await service.create_thread()
    return envelope(data={"thread": thread.model_dump(mode="json")}, thread_id=thread.thread_id)


@router.get("/threads", response_model=ApiEnvelope[ThreadListResponse])
async def list_threads(service: CourseAgentService = Depends(get_service)):
    threads = await service.list_threads()
    return envelope(data={"threads": [item.model_dump(mode="json") for item in threads]})


@router.patch("/threads/{thread_id}/mode", response_model=ApiEnvelope[ThreadStateResponse])
async def update_thread_mode(
    thread_id: str,
    request: ModeUpdateRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        state = await service.update_mode(thread_id, request)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"state": state.model_dump(mode="json")})


@router.post("/threads/{thread_id}/confirm-step", response_model=ApiEnvelope[ThreadStateResponse])
async def confirm_thread_step(
    thread_id: str,
    request: ConfirmStepRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        state = await service.confirm_step(thread_id, request)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "step_confirmation_rejected", "message": str(exc)},
        ) from exc
    return envelope(thread_id=thread_id, data={"state": state.model_dump(mode="json")})


@router.get("/threads/{thread_id}", response_model=ApiEnvelope[ThreadDetailResponse])
async def get_thread(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        summary = await service.store.build_summary(thread_id)
        state = await service.store.get_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(
        thread_id=thread_id,
        data={
            "thread": summary.model_dump(mode="json"),
            "state": state.model_dump(mode="json"),
        },
    )


@router.get("/threads/{thread_id}/timeline", response_model=ApiEnvelope[ThreadTimelineResponse])
async def get_thread_timeline(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        timeline = await service.get_timeline(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"timeline": [item.model_dump(mode="json") for item in timeline]})


@router.get("/threads/{thread_id}/versions", response_model=ApiEnvelope[ThreadVersionsResponse])
async def get_thread_versions(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        versions = await service.list_versions(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"versions": [item.model_dump(mode="json") for item in versions]})


@router.get("/threads/{thread_id}/history", response_model=ApiEnvelope[ThreadHistoryResponse])
async def get_thread_history(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        history = await service.get_history(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"history": [item.model_dump(mode="json") for item in history]})


@router.post("/threads/{thread_id}/pause", response_model=ApiEnvelope[BooleanResultResponse])
async def pause_thread(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        await service.pause_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"paused": True})


@router.post("/threads/{thread_id}/resume", response_model=ApiEnvelope[BooleanResultResponse])
async def resume_thread(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        await service.resume_paused_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"resumed": True})


@router.delete("/threads/{thread_id}/messages/last", response_model=ApiEnvelope[BooleanResultResponse])
async def retract_last_message(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        await service.retract_last_message(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"retracted": True})


@router.put("/threads/{thread_id}/messages/last", response_model=ApiEnvelope[BooleanResultResponse])
async def replace_last_message(
    thread_id: str,
    request: SendMessageRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        await service.replace_last_message(thread_id, request.content, request.user_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"replaced": True})


@router.delete("/threads/{thread_id}", response_model=ApiEnvelope[BooleanResultResponse])
async def delete_thread(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        await service.delete_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"deleted": True})


@router.post("/threads/{thread_id}/messages", response_model=ApiEnvelope[BooleanResultResponse])
async def send_message(
    thread_id: str,
    request: SendMessageRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        await service.ingest_message(thread_id, request.content, request.user_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"accepted": True})


@router.post("/threads/{thread_id}/regenerate", response_model=ApiEnvelope[ArtifactResponse])
async def regenerate_thread_artifact(
    thread_id: str,
    request: RegenerateRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        artifact = await service.regenerate(thread_id, request)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "artifact_not_found", "message": str(exc)},
        ) from exc
    return envelope(thread_id=thread_id, data={"artifact": artifact.model_dump(mode="json")})
