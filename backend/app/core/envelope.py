"""성공 응답 봉투 — 라우터의 반환값(response_model 검증 후)을 {"success": true, "data": ...} 로 감싼다.
각 도메인 APIRouter 에 route_class=EnvelopeRoute 로 붙인다. 오류는 errors.py 핸들러가 같은 규격으로 낸다."""
import json
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class EnvelopeRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            resp = await original(request)
            if not isinstance(resp, JSONResponse) or resp.status_code >= 400:
                return resp
            data = json.loads(resp.body) if resp.body else None
            wrapped = JSONResponse(status_code=resp.status_code, content={"success": True, "data": data})
            for k, v in resp.headers.items():                  # CORS 등 헤더 유지 (길이는 새로 계산)
                if k.lower() not in ("content-length", "content-type"):
                    wrapped.headers[k] = v
            return wrapped

        return handler
