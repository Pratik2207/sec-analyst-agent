"""Naive RAG baseline (FR-16): top-k dense search, then ONE LLM call. [track-b]

answer(question: str) -> AskResponse   # same response shape as POST /ask
No planner, no tools, no SQL, no reranker, no sparse vectors: hybrid_search(question,
k=settings.baseline_k, use_reranker=False, use_sparse=False). Model: settings.answer_model.
"""

from src.api.schemas import AskResponse


def answer(question: str) -> AskResponse:
    raise NotImplementedError("track-b")
