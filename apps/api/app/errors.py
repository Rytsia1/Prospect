from starlette.exceptions import HTTPException


class ApiError(HTTPException):
    """HTTP error with a stable machine-readable `code` for the error response body.

    The message is shown to clients: keep it generic, never an internal exception or path.
    """

    def __init__(
        self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(status_code, message, headers=headers)
        self.code = code
