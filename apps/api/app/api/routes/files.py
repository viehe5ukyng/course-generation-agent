from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import get_service
from app.core.schemas import (
    ApiEnvelope,
    ArtifactDiffResponse,
    ArtifactResponse,
    ArtifactUpdateRequest,
    ThreadFilesResponse,
    UploadCategory,
    UploadFileResponse,
)
from app.services.course_agent import CourseAgentService
from app.storage.thread_store import ThreadNotFoundError


router = APIRouter()


def envelope(*, data: dict, thread_id: str | None = None, request_id: str | None = None) -> ApiEnvelope:
    return ApiEnvelope(request_id=request_id or uuid4().hex, thread_id=thread_id, data=data)


@router.post("/threads/{thread_id}/files", response_model=ApiEnvelope[UploadFileResponse])
async def upload_file(
    thread_id: str,
    file: UploadFile = File(...),
    category: UploadCategory = Query(default=UploadCategory.CONTEXT),
    service: CourseAgentService = Depends(get_service),
):
    try:
        content = await file.read()
        await service.upload_file(thread_id, file.filename, file.content_type or "application/octet-stream", content, category)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"uploaded": True, "filename": file.filename, "category": category.value})


@router.get("/threads/{thread_id}/files", response_model=ApiEnvelope[ThreadFilesResponse])
async def list_files(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        files = await service.store.list_files(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"files": [file.model_dump(mode="json") for file in files]})


@router.get("/threads/{thread_id}/artifacts/latest", response_model=ApiEnvelope[ArtifactResponse])
async def latest_artifact(thread_id: str, service: CourseAgentService = Depends(get_service)):
    try:
        artifact = await service.store.latest_artifact(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"artifact": artifact.model_dump(mode="json") if artifact else None})


@router.get("/threads/{thread_id}/artifacts/{version}", response_model=ApiEnvelope[ArtifactResponse])
async def get_artifact_version(thread_id: str, version: int, service: CourseAgentService = Depends(get_service)):
    try:
        artifact = await service.get_artifact_version(thread_id, version)
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


@router.patch("/threads/{thread_id}/artifacts/latest", response_model=ApiEnvelope[ArtifactResponse])
async def update_latest_artifact(
    thread_id: str,
    request: ArtifactUpdateRequest,
    service: CourseAgentService = Depends(get_service),
):
    try:
        artifact = await service.update_artifact(thread_id, request.markdown)
    except ThreadNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "thread_not_found", "message": f"Thread not found: {exc.thread_id}"},
        ) from exc
    return envelope(thread_id=thread_id, data={"artifact": artifact.model_dump(mode="json")})


@router.get("/threads/{thread_id}/artifacts/{version}/diff/{prev_version}", response_model=ApiEnvelope[ArtifactDiffResponse])
async def artifact_diff(thread_id: str, version: int, prev_version: int, service: CourseAgentService = Depends(get_service)):
    try:
        diff = await service.store.diff_versions(thread_id, version, prev_version)
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
    return envelope(thread_id=thread_id, data={"diff": diff, "version": version, "prev_version": prev_version})
