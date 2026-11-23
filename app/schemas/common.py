from typing import Any

from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    status: int = 200
    message: str
    data: T
    error: Any = ""
