from typing import Any

from fastapi import status


class AppException(Exception):
    def __init__(
        self,
        message: str = "Something went wrong",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        error: Any = "",
        headers: dict[str, str] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error = error
        self.headers = headers
        super().__init__(message)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request", error: Any = ""):
        super().__init__(message, status.HTTP_400_BAD_REQUEST, error)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized", error: Any = ""):
        super().__init__(
            message,
            status.HTTP_401_UNAUTHORIZED,
            error,
            headers={"WWW-Authenticate": "Bearer"},
        )


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", error: Any = ""):
        super().__init__(message, status.HTTP_404_NOT_FOUND, error)


class ConflictException(AppException):
    def __init__(self, message: str = "Conflict", error: Any = ""):
        super().__init__(message, status.HTTP_409_CONFLICT, error)


class UnprocessableException(AppException):
    def __init__(self, message: str = "Unprocessable request", error: Any = ""):
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_CONTENT, error)


class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "Service unavailable", error: Any = ""):
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE, error)
