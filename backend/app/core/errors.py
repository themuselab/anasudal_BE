"""응답 규격.

성공:  {"success": true,  "data": ...}
실패:  {"success": false, "error": {"code": "SESSION_NOT_FOUND", "message": "...", "details": ...}}

HTTP 상태만으로는 부족한 경우(400 안에 여러 사유)를 code로 구분한다. 프론트는 code로 분기하고 message는 그대로 보여줘도 된다.
"""
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(str, Enum):
    # 400 — 요청이 잘못됨 (여러 사유)
    VALIDATION_ERROR         = "VALIDATION_ERROR"          # 필드 누락·형식 오류 (details에 필드별 사유)
    FEEDBACK_REASON_REQUIRED = "FEEDBACK_REASON_REQUIRED"  # 👎 인데 사유 없음
    INVALID_REASON_CODE      = "INVALID_REASON_CODE"       # 사유 코드가 목록에 없음
    MESSAGE_EMPTY            = "MESSAGE_EMPTY"             # 질문이 비어 있음
    MESSAGE_TOO_LONG         = "MESSAGE_TOO_LONG"
    # 404
    SESSION_NOT_FOUND        = "SESSION_NOT_FOUND"         # 없거나 만료
    ANSWER_NOT_FOUND         = "ANSWER_NOT_FOUND"
    REGION_NOT_FOUND         = "REGION_NOT_FOUND"
    INSTITUTION_NOT_FOUND    = "INSTITUTION_NOT_FOUND"
    CHUNK_NOT_FOUND          = "CHUNK_NOT_FOUND"
    NOT_FOUND                = "NOT_FOUND"                 # 라우트 자체가 없음
    # 409
    ANSWER_NOT_GROUNDED      = "ANSWER_NOT_GROUNDED"       # tier 1이 아닌 답변으로 추천 요청
    ANSWER_SESSION_MISMATCH  = "ANSWER_SESSION_MISMATCH"   # 다른 세션의 답변
    # 429
    RATE_LIMITED             = "RATE_LIMITED"
    # 5xx
    LLM_FAILED               = "LLM_FAILED"                # Gemini 생성/임베딩 실패
    LLM_RATE_LIMITED         = "LLM_RATE_LIMITED"          # Gemini 분당 한도 (503, 몇 초 뒤 재시도)
    INTERNAL_ERROR           = "INTERNAL_ERROR"


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _fail(status: int, code: ErrorCode | str, message: str, details=None) -> JSONResponse:
    body = {"success": False, "error": {"code": str(getattr(code, "value", code)), "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


_STATUS_DEFAULT = {404: ErrorCode.NOT_FOUND, 429: ErrorCode.RATE_LIMITED, 500: ErrorCode.INTERNAL_ERROR}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return _fail(e.status, e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        # pydantic 오류를 필드별로 압축. 422 대신 400 + VALIDATION_ERROR
        details = [{"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"),
                    "reason": err.get("msg", "")} for err in e.errors()]
        return _fail(400, ErrorCode.VALIDATION_ERROR, "요청 형식이 올바르지 않습니다", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = _STATUS_DEFAULT.get(e.status_code, ErrorCode.INTERNAL_ERROR if e.status_code >= 500 else ErrorCode.VALIDATION_ERROR)
        return _fail(e.status_code, code, str(e.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        return _fail(500, ErrorCode.INTERNAL_ERROR, "서버 오류가 발생했습니다")
