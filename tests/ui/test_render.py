import re

from ui.render import citation_markdown, format_answer, step_label


def label(name, **detail):
    return step_label({"name": name, "detail": detail})


def test_route_labels():
    assert label("route", kind="fast") == ("Routing: fast path", True)
    assert label("route", kind="agent") == ("Routing: agent", True)


def test_plan_label():
    assert label("plan", steps=[{}, {}, {}]) == ("Planned 3 steps", True)
    assert label("plan", steps=[{}])[0] == "Planned 1 step"


def test_tool_call_labels():
    assert label("tool_call", tool="sql_query", ok=True, rows=24) == ("sql_query: 24 rows", True)
    assert label("tool_call", tool="search_filings", ok=True, chunks=8) == (
        "search_filings: 8 passages", True)
    assert label("tool_call", tool="calculate", ok=True, results=[{}] * 4) == (
        "calculate: 4 results", True)
    assert label("tool_call", tool="list_companies", ok=True, rows=4) == (
        "list_companies: 4 rows", True)


def test_tool_call_failure_is_marked():
    text, ok = label("tool_call", tool="sql_query", ok=False, error="bad SQL", rows=0)
    assert not ok and "failed" in text and "bad SQL" in text


def test_fast_path_sql_step_counts_row_list():
    assert label("sql_query", sql="SELECT", ok=True, rows=[{"a": 1}], error=None) == (
        "sql_query: 1 rows", True)


def test_grade_answer_verify_flags_labels():
    assert label("grade", step=0, ok=True, reason="", retry=False) == ("Grade step 1: ok", True)
    assert label("grade", step=1, ok=False, retry=True) == ("Grade step 2: weak, retrying", False)
    assert label("answer", claims=3, not_found=False, attempt=1) == (
        "Answer drafted: 3 claims", True)
    assert label("answer", not_found=True, attempt=1)[1] is False
    assert label("verify", ok=3, failed=[]) == ("Verify: 3 claims ok, 0 failed", True)
    assert label("verify", ok=2, failed=[{"claim": "x"}]) == (
        "Verify: 2 claims ok, 1 failed", False)
    assert label("flags", flags=[], stop_reason="done") == ("Finished (done)", True)
    assert label("flags", flags=["x"], stop_reason="tool cap")[1] is False


def test_unknown_step_uses_its_name():
    assert step_label({"name": "retrieve", "detail": {}}) == ("retrieve", True)


def test_answer_markers_bold_and_dollar_escaped():
    out = format_answer("Revenue was $60.9 billion [1]. Margin rose [1][2].")
    assert "**[1]**" in out and "**[2]**" in out
    assert r"\$60.9" in out


def test_citation_numbers_match_answer_markers_and_link():
    cites = [{"ticker": "NVDA", "form": "10-K", "fiscal_year": 2024, "section": "Item 7",
              "accession_no": "a", "url": "https://www.sec.gov/Archives/edgar/data/1/a.htm"},
             {"ticker": "INTC", "form": "10-K", "fiscal_year": 2025, "section": "Item 8",
              "accession_no": "b", "url": "https://www.sec.gov/b.htm"}]
    markers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", "x [1]. y [2].")})
    lines = [citation_markdown(n, c) for n, c in enumerate(cites, 1)]
    assert [int(re.match(r"\*\*\[(\d+)\]", ln).group(1)) for ln in lines] == markers
    assert lines[0] == ("**[1]** NVDA 10-K FY2024, Item 7 - "
                        "[EDGAR filing](https://www.sec.gov/Archives/edgar/data/1/a.htm)")
    assert lines[1].startswith("**[2]** INTC 10-K FY2025, Item 8")


def test_citation_non_https_url_not_linked():
    line = citation_markdown(1, {"ticker": "X", "fiscal_year": 2024, "section": "Item 1",
                                 "url": "javascript:alert(1)"})
    assert "](" not in line
