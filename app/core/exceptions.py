from fastapi import HTTPException, status


class VideoNotFoundError(HTTPException):
    def __init__(self, video_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' was not found."
        )


class VideoNotReadyError(HTTPException):
    def __init__(self, video_id: str, status_val: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video '{video_id}' is not ready for chat. Current status: '{status_val}'."
        )


class InvalidFileFormatError(HTTPException):
    def __init__(self, filename: str, allowed: set[str]):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid format for '{filename}'. Allowed formats: {', '.join(sorted(allowed))}."
        )


class FileTooLargeError(HTTPException):
    def __init__(self, size_mb: float, max_mb: int):
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {size_mb:.2f}MB exceeds limit of {max_mb}MB."
        )
