from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from app.core.db import get_conn
from app.domains.screening import service
from app.domains.screening.schemas import ResultIn, ResultOut, TaskSet

router = APIRouter(prefix="/screening", tags=["screening"])


@router.get("/tasks", response_model=TaskSet, summary="연령에 맞는 관찰 과제")
async def tasks(child_age_months: int = Query(ge=0, le=216),
                conn: asyncpg.Connection = Depends(get_conn)):
    return await service.task_set(conn, child_age_months)


@router.post("/results", response_model=ResultOut, status_code=201,
             summary="관찰 기록 저장 → 공유 링크 토큰 발급")
async def create_result(body: ResultIn, conn: asyncpg.Connection = Depends(get_conn)):
    return await service.build_result(conn, body)


@router.get("/results/{token}", response_model=ResultOut, summary="공유 링크로 기록 열기")
async def read_result(token: UUID, response: Response,
                      conn: asyncpg.Connection = Depends(get_conn)):
    # 링크를 아는 사람만 볼 수 있는 기록이다. 검색엔진·중간 캐시에 남으면 안 된다.
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return await service.read_result(conn, token)


@router.delete("/results/{token}", status_code=204, summary="기록 삭제 (본인이 링크를 회수)")
async def delete_result(token: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    await service.remove_result(conn, token)
