"""Request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Citation(BaseModel):
    ticker: str
    form: str
    fiscal_year: int
    section: str
    accession_no: str
    url: str


class Step(BaseModel):
    name: str
    detail: dict


class Tokens(BaseModel):
    prompt: int = 0
    completion: int = 0


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    steps: list[Step]
    tokens: Tokens
    latency_ms: int
