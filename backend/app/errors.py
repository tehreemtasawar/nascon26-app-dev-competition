from typing import Any, Dict
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Dict[str, Any] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details if details is not None else {}

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_content_length: int = 1024 * 1024):
        super().__init__(app)
        self.max_content_length = max_content_length

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_content_length:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Body exceeds 1 MB limit",
                        "details": {}
                    }
                }
            )
        return await call_next(request)

def setup_error_handlers(app: FastAPI):
    app.add_middleware(MaxBodySizeMiddleware)

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields = []
        for error in exc.errors():
            loc = error.get("loc", [])
            # filter out 'body' prefix if present
            field_name = str(loc[-1]) if loc else "unknown"
            fields.append(field_name)
        
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Validation failed: " + str(exc),
                    "details": {
                        "fields": list(dict.fromkeys(fields))
                    }
                }
            }
        )
