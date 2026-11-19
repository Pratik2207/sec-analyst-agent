"""The LangGraph agent loop (PRD 6.2, FR-7/10/12/14, NFR-7). [track-a]

run_agent(question: str) -> AskResponse

Nodes: plan -> execute (dispatch the step's tool) -> grade -> (retry with the rewritten
step | next step | answer) -> verify -> (re-answer once with feedback | finish).
Owns the tool dispatcher: PlanStep -> tool call. sql_query steps become a code-built
SELECT over financial_facts (+ companies for sector), always selecting accession_no;
calculate steps run the expression once per ticker with variables <metric>_<year> taken
from earlier sql_query rows, and each calc data item gets "ticker", "name" and
"input_source_ids". Bad arguments from the LLM (TypeError, wrong types, float years) must
become a failed ToolResult, never an exception. Enforce MAX_TOOL_CALLS, MAX_RETRIES and
repeated-call detection; on a stop, answer from the evidence so far (partial) and flag it.
If there is no usable evidence at all, the answer is fast_path.NOT_FOUND.
Uses answerer.answer, verifier.verify and evidence.render_answer (track-b / contract).
"""

from src.api.schemas import AskResponse


def run_agent(question: str) -> AskResponse:
    raise NotImplementedError("track-a")
