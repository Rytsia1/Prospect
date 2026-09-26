from starlette.exceptions import HTTPException


class ApiError(HTTPException):
    """HTTP error with a stable machine-readable `code` for the error response body."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code, message)
        self.code = code
