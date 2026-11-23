from fastapi import APIRouter

from app.core import settings
from app.schemas import ApiResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check() -> ApiResponse[dict[str, str]]:
    return ApiResponse(
        message=f"{settings.APP_NAME} is running",
        data={"status": "ok"},
    )
