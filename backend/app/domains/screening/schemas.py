from uuid import UUID

from pydantic import BaseModel, Field


class TaskStep(BaseModel):
    step_no: int
    script: str
    wait_sec: int


class TaskOption(BaseModel):
    option_no: int
    label: str


class Task(BaseModel):
    task_code: str
    title: str
    tool: str | None                 # 준비물. None 이면 맨몸으로 가능
    skippable: bool
    observes: str                    # "무엇을 보는 과제인지" — 부모에게 그대로 보여준다
    steps: list[TaskStep]
    options: list[TaskOption]


class TaskSet(BaseModel):
    child_age_months: int
    tools: list[str]                 # 미리 안내할 준비물 목록 (없으면 건너뛰면 된다)
    tasks: list[Task]


class Answer(BaseModel):
    task_code: str
    option_no: int = Field(ge=1, le=4)


class ResultIn(BaseModel):
    child_age_months: int = Field(ge=18, le=48)
    answers: list[Answer] = []
    skipped: list[str] = []          # 준비물이 없어 건너뛴 과제


class Observation(BaseModel):
    """과제 하나를 어떻게 관찰했는지. 점수가 아니라 문장이다."""
    task_code: str
    title: str
    observes: str
    label: str                       # 부모가 고른 선택지 그대로
    needs_attention: bool            # 전문가에게 보여줄 만한 반응이었는지


class ResultOut(BaseModel):
    result_token: UUID
    child_age_months: int
    done_count: int
    skipped_count: int
    observations: list[Observation]
    attention: list[str]             # 반응이 약했던 과제 제목
    area_codes: list[str]            # 기관 필터용
    headline: str                    # 결과 한 줄
    note: str                        # 참고용이라는 안내
    suggest_visit: bool              # 전문기관 확인을 권할지
    expires_at: str
