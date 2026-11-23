from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.schemas import ApiResponse, DocumentResponse, DocumentUpdate
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    name: Annotated[str, Form(min_length=1, max_length=255)],
    file: Annotated[UploadFile, File()],
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[DocumentResponse]:
    """Save an uploaded file locally and queue its background processing."""
    document = document_service.upload_document(db, user, name, file)
    return ApiResponse(
        status=status.HTTP_202_ACCEPTED,
        message="Document uploaded and queued for processing",
        data=DocumentResponse.model_validate(document),
    )


@router.get("")
def list_documents(
    db: DbSession,
    user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> ApiResponse[list[DocumentResponse]]:
    documents = document_service.list_documents(db, user, skip, limit)
    return ApiResponse(
        message="Documents fetched",
        data=[DocumentResponse.model_validate(document) for document in documents],
    )


@router.get("/{document_id}")
def read_document(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[DocumentResponse]:
    document = document_service.get_owned_document(db, document_id, user.id)
    return ApiResponse(message="Document fetched", data=DocumentResponse.model_validate(document))


@router.get("/{document_id}/events")
def document_progress_events(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
) -> StreamingResponse:
    events = document_service.progress_events(db, document_id, user)
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{document_id}")
def rename_document(
    document_id: int,
    payload: DocumentUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[DocumentResponse]:
    document = document_service.rename_document(db, document_id, user, payload)
    return ApiResponse(message="Document updated", data=DocumentResponse.model_validate(document))


@router.delete("/{document_id}")
def remove_document(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[None]:
    document_service.remove_document(db, document_id, user)
    return ApiResponse(message="Document deleted", data=None)
