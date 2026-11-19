"""Pure formatting helpers for the UI: step labels, answer markers, source lines."""

import re

MARKER = re.compile(r"\[(\d+)\]")


def step_label(step: dict) -> tuple[str, bool]:
    """Short human label for one agent step, and whether the step went fine."""
    name, d = step.get("name", "?"), step.get("detail") or {}
    if name == "route":
        return f"Routing: {'fast path' if d.get('kind') == 'fast' else 'agent'}", True
    if name == "plan":
        n = len(d.get("steps") or [])
        return f"Planned {n} step{'' if n == 1 else 's'}", n > 0
    if name in ("tool_call", "sql_query"):
        tool = d.get("tool", name)
        if not d.get("ok", True):
            return f"{tool}: failed ({str(d.get('error') or 'error')[:120]})", False
        if tool in ("search_filings", "get_section"):
            return f"{tool}: {_count(d.get('chunks'))} passages", True
        if tool == "calculate":
            return f"calculate: {_count(d.get('results'))} results", True
        return f"{tool}: {_count(d.get('rows'))} rows", True
    if name == "grade":
        step_no = f" step {d['step'] + 1}" if isinstance(d.get("step"), int) else ""
        if d.get("ok"):
            kept = f", kept {d['kept']} passages" if "kept" in d else ""
            return f"Grade{step_no}: ok{kept}", True
        return f"Grade{step_no}: weak{', retrying' if d.get('retry') else ''}", False
    if name == "answer":
        if d.get("not_found"):
            return "Answer: not found in the filings", False
        retry = " (retry)" if (d.get("attempt") or 1) > 1 else ""
        return f"Answer drafted: {d.get('claims', 0)} claims{retry}", True
    if name == "verify":
        failed = len(d.get("failed") or [])
        return f"Verify: {d.get('ok', 0)} claims ok, {failed} failed", failed == 0
    if name == "flags":
        flags = d.get("flags") or []
        stop = d.get("stop_reason") or "done"
        if flags:
            return f"Finished ({stop}), {len(flags)} flag{'' if len(flags) == 1 else 's'}", False
        return f"Finished ({stop})", True
    return name, True


def _count(v) -> int:
    if isinstance(v, int):
        return v
    return len(v) if isinstance(v, list | tuple) else 0


def format_answer(text: str) -> str:
    """Markdown for the answer: `$` escaped (Streamlit would read it as LaTeX) and each [n]
    citation marker in bold."""
    return MARKER.sub(r"**[\1]**", text.replace("$", r"\$"))


def citation_markdown(n: int, c: dict) -> str:
    """One numbered source line, matching the answer's [n] marker, with the EDGAR link."""
    form = c.get("form") or "10-K"
    head = f"**[{n}]** {c.get('ticker', '?')} {form} FY{c.get('fiscal_year', '?')}"
    section = c.get("section")
    if section:
        head += f", {section}"
    url = c.get("url") or ""
    if url.startswith("https://"):
        head += f" - [EDGAR filing]({url})"
    return head
