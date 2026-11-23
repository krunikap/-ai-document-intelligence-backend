from typing import Any

from fastapi.responses import JSONResponse


def send_response(
    status_code: int,
    message: str,
    data: Any = "",
    error: Any = "",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status_code,
            "message": message,
            "data": data,
            "error": error,
        },
        headers=headers,
    )
