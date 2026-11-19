"""Build evals/dataset.jsonl (Phase 5, track-a).

Usage: uv run python -m evals.build_dataset

Number and multihop gold values are computed from evals/data/facts_pilot.json, so the file
can be regenerated exactly. Text questions were written by reading the chunk files
(data/processed/chunks); their gold_contains phrases are checked by evals.validate_dataset.
"""

import json
from pathlib import Path

from evals.schema import DATASET, DatasetItem, GoldSource

FACTS = Path(__file__).resolve().parent / "data" / "facts_pilot.json"

SEMIS = ["AMD", "INTC", "NVDA", "QCOM"]
BANKS = ["BAC", "GS", "JPM"]
PHARMA = ["LLY", "MRK", "PFE"]
NAMES = {
    "NVDA": "NVIDIA", "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm", "JPM": "JPMorgan Chase",
    "BAC": "Bank of America", "GS": "Goldman Sachs", "PFE": "Pfizer", "LLY": "Eli Lilly",
    "MRK": "Merck",
}
METRIC_WORDS = {
    "revenue": "revenue", "gross_profit": "gross profit", "rd_expense": "R&D expense",
    "operating_income": "operating income", "net_income": "net income",
    "total_assets": "total assets",
}


def load_facts(path: Path = FACTS) -> dict[tuple[str, int, str], dict]:
    with open(path, encoding="utf-8") as f:
        return {(r["ticker"], r["fiscal_year"], r["metric"]): r for r in json.load(f)}


F = load_facts() if FACTS.exists() else {}


def v(t: str, y: int, m: str) -> float:
    return F[(t, y, m)]["value"]


def src(t: str, y: int) -> GoldSource:
    acc = next(r["accession_no"] for (tt, yy, _), r in F.items() if tt == t and yy == y)
    return GoldSource(ticker=t, fiscal_year=y, item="8", accession_no=acc)


def srcs(pairs) -> list[GoldSource]:
    seen = []
    for p in pairs:
        if p not in seen:
            seen.append(p)
    return [src(t, y) for t, y in sorted(seen)]


def usd(x: float) -> str:
    """$130.50 billion, $3.18 trillion, $365 million."""
    a = abs(x)
    if a >= 1e12:
        s = f"${a / 1e12:.2f} trillion"
    elif a >= 1e9:
        s = f"${a / 1e9:.2f} billion"
    else:
        s = f"${a / 1e6:,.0f} million"
    return ("-" if x < 0 else "") + s


def pct(a: float, b: float) -> float:
    """a / b in percent."""
    return a / b * 100


def growth(new: float, old: float) -> float:
    return (new / old - 1) * 100


def r2(x: float) -> float:
    return round(x, 2)


def period_note(t: str, y: int) -> str:
    if t in ("NVDA", "QCOM"):
        return f" (fiscal year ended {F[(t, y, 'revenue')]['period_end']})"
    return ""


# ---------------------------------------------------------------- number (40)
# (ticker, fiscal_year, metric, question)
NUMBER = [
    ("NVDA", 2023, "rd_expense",
     "How much did NVIDIA spend on research and development in fiscal 2023?"),
    ("NVDA", 2024, "net_income", "What was Nvidia's net income for FY24?"),
    ("NVDA", 2025, "operating_income", "What was NVIDIA's operating income in fiscal year 2025?"),
    ("NVDA", 2024, "total_assets", "What were Nvidia's total assets at the end of fiscal 2024?"),
    ("AMD", 2023, "revenue", "What was AMD's revenue in 2023?"),
    ("AMD", 2024, "gross_profit", "What was AMD's gross profit for fiscal year 2024?"),
    ("AMD", 2025, "operating_income", "How much operating income did AMD report in FY2025?"),
    ("AMD", 2025, "rd_expense", "What was Advanced Micro Devices' R&D expense in FY25?"),
    ("INTC", 2024, "net_income", "What was Intel's net income (or loss) in fiscal year 2024?"),
    ("INTC", 2025, "revenue", "What was Intel's total revenue in 2025?"),
    ("INTC", 2023, "total_assets", "What were Intel's total assets at the end of FY2023?"),
    ("INTC", 2025, "gross_profit", "What gross profit did Intel report for fiscal 2025?"),
    ("QCOM", 2024, "revenue", "What were Qualcomm's revenues in fiscal 2024?"),
    ("QCOM", 2025, "rd_expense", "How much did Qualcomm spend on R&D in FY2025?"),
    ("QCOM", 2023, "net_income", "What was Qualcomm's net income for fiscal year 2023?"),
    ("QCOM", 2024, "operating_income", "What was QCOM's operating income in FY24?"),
    ("JPM", 2024, "net_income", "What was JPMorgan Chase's net income in 2024?"),
    ("JPM", 2025, "revenue", "What was JPMorgan's total net revenue for fiscal year 2025?"),
    ("JPM", 2023, "total_assets", "What were JPMorgan Chase's total assets at year-end 2023?"),
    ("JPM", 2023, "net_income", "How much net income did JPMorgan earn in FY2023?"),
    ("BAC", 2023, "revenue", "What was Bank of America's total revenue in 2023?"),
    ("BAC", 2025, "total_assets", "What were Bank of America's total assets at the end of FY2025?"),
    ("BAC", 2025, "net_income", "What was BofA's net income in fiscal 2025?"),
    ("BAC", 2024, "revenue", "What was Bank of America's revenue for FY24?"),
    ("GS", 2023, "net_income", "What was Goldman Sachs' net income in 2023?"),
    ("GS", 2025, "revenue", "What were Goldman Sachs's total net revenues in fiscal year 2025?"),
    ("GS", 2024, "total_assets", "What were Goldman Sachs' total assets at the end of 2024?"),
    ("GS", 2025, "net_income", "How much net income did Goldman report for FY2025?"),
    ("PFE", 2024, "revenue", "What was Pfizer's total revenue in fiscal 2024?"),
    ("PFE", 2023, "rd_expense", "What was Pfizer's research and development expense in 2023?"),
    ("PFE", 2025, "net_income", "What was Pfizer's net income for FY2025?"),
    ("PFE", 2024, "total_assets", "What were Pfizer's total assets at the end of FY24?"),
    ("LLY", 2025, "revenue", "What was Eli Lilly's revenue in fiscal year 2025?"),
    ("LLY", 2024, "rd_expense", "How much did Lilly spend on R&D in 2024?"),
    ("LLY", 2023, "net_income", "What was Eli Lilly's net income in FY2023?"),
    ("LLY", 2025, "total_assets", "What were Eli Lilly's total assets at the end of 2025?"),
    ("MRK", 2023, "rd_expense", "What was Merck's R&D expense in fiscal 2023?"),
    ("MRK", 2024, "net_income", "What was Merck's net income in 2024?"),
    ("MRK", 2025, "gross_profit", "What was Merck's gross profit in FY2025?"),
    ("MRK", 2023, "revenue", "What were Merck's total sales in FY23?"),
]


def number_items() -> list[DatasetItem]:
    out = []
    for i, (t, y, m, q) in enumerate(NUMBER, 1):
        val = v(t, y, m)
        if m == "net_income" and val < 0:
            ans = f"{NAMES[t]} reported a net loss of {usd(-val)} in FY{y}{period_note(t, y)}."
        elif m == "total_assets":
            ans = (f"{NAMES[t]}'s total assets at the end of FY{y} were {usd(val)}"
                   f"{period_note(t, y)}.")
        else:
            ans = f"{NAMES[t]}'s {METRIC_WORDS[m]} in FY{y} was {usd(val)}{period_note(t, y)}."
        if m == "gross_profit" and t in ("PFE", "LLY", "MRK", "QCOM"):
            ans = ans[:-1] + " (revenue minus cost of sales)."
        out.append(DatasetItem(
            id=f"num-{i:03d}", type="number", question=q, gold_answer=ans, gold_value=val,
            unit="USD", gold_sources=[src(t, y)], notes=f"metric={m}",
        ))
    return out


# ---------------------------------------------------------------- text (40)
# (ticker, fiscal_year, item, section, question, gold_answer, gold_contains)
TEXT = [
    ("NVDA", 2024, "7", "Gross Profit and Gross Margin",
     "What drove the increase in NVIDIA's gross margin in fiscal 2024?",
     "Gross margin rose to 72.7% in FY2024 from 56.9% in FY2023, primarily due to strong Data "
     "Center revenue growth of 217% and lower net inventory provisions as a share of revenue.",
     ["72.7%", "Data Center revenue growth of 217%"]),
    ("NVDA", 2023, "7", "Termination of the Arm Share Purchase Agreement",
     "Why did NVIDIA's deal to buy Arm fall through, and what did the termination cost in FY2023?",
     "NVIDIA and SoftBank terminated the agreement in February 2022 because of significant "
     "regulatory challenges; NVIDIA recorded a $1.35 billion acquisition termination cost in "
     "fiscal 2023, writing off the prepayment made at signing.",
     ["significant regulatory challenges", "$1.35 billion"]),
    ("NVDA", 2025, "1A",
     "We are subject to complex laws, rules, regulations, and political and other actions, "
     "including restrictions on the export of our products, which may ...",
     "According to Nvidia's FY2025 10-K, how did sanctions after the war in Ukraine affect its "
     "business in Russia?",
     "Sanctions and export controls blocked its products, services and support into Russia, "
     "Belarus and parts of Ukraine; in fiscal 2023 NVIDIA stopped direct sales to Russia and "
     "closed its business operations there.",
     ["stopped direct sales to Russia", "closed business operations in Russia"]),
    ("NVDA", 2025, "1", "Manufacturing",
     "How does NVIDIA manufacture its products, per its fiscal 2025 annual report?",
     "NVIDIA uses a fabless and contracting manufacturing strategy, partnering with key "
     "suppliers for all phases of manufacturing (wafer fabrication, assembly, testing and "
     "packaging), which lets it avoid the costs and risks of owning fabs.",
     ["fabless and contracting manufacturing strategy"]),
    ("AMD", 2025, "7", "Overview",
     "What agreement did AMD sign with OpenAI in 2025?",
     "In October 2025 AMD agreed with OpenAI to deploy 6 gigawatts of AMD GPUs, starting with "
     "MI450 series products, and issued OpenAI a warrant to buy up to 160 million AMD shares "
     "at $0.01 per share, vesting on purchase milestones and stock price targets.",
     ["6 gigawatts", "160 million shares"]),
    ("AMD", 2025, "7", "Gross Margin",
     "Why did AMD's gross margin change in 2025?",
     "Gross margin rose to 50% from 49% in 2024, primarily due to product mix, partially offset "
     "by about $440 million of inventory and related charges from the U.S. export control on "
     "Instinct MI308 GPUs.",
     ["product mix", "MI308"]),
    ("AMD", 2024, "1", "Third-Party Wafer Foundry Facilities",
     "Which foundries make AMD's wafers, according to its FY2024 10-K?",
     "AMD uses TSMC for wafers for its HPC, FPGA and Adaptive SoC products and GLOBALFOUNDRIES "
     "for HPC wafers at the 12 nm and 14 nm nodes; TSMC, UMC and Samsung produce its "
     "programmable logic ICs.",
     ["Taiwan Semiconductor Manufacturing Company", "GLOBALFOUNDRIES"]),
    ("AMD", 2023, "1A",
     "Intel Corporation’s dominance of the microprocessor market and its aggressive business "
     "practices may limit our ability to compete effectively on a ...",
     "What competitive risk does AMD describe regarding Intel in its 2023 risk factors?",
     "Intel's microprocessor dominance, financial resources and OEM relationships let it price "
     "aggressively and use practices such as rebates, bundling and exclusivity payments, which "
     "have lowered AMD's unit sales, average selling prices and margins.",
     ["aggressive business practices", "exclusivity payments"]),
    ("INTC", 2023, "full", "A Year in Review",
     "Why did Intel's revenue decline in 2023?",
     "2023 revenue was $54.2 billion, down $8.8 billion or 14% from 2022: CCG fell 8% on lower "
     "notebook and desktop volume, DCAI fell 20% on lower server volume, and NEX fell 31% as "
     "customers reduced inventories.",
     ["down $8.8 billion, or 14%", "DCAI revenue decreased 20%"]),
    ("INTC", 2024, "full", "Our Financial Capital Allocation Strategy",
     "Why did Intel stop paying dividends in 2024?",
     "Intel suspended its quarterly dividend starting in Q4 2024; under its commercial CHIPS Act "
     "agreement it agreed to forgo dividends for the next two years and to limit them for the "
     "three years after that.",
     ["suspended the declaration of quarterly dividends", "CHIPS Act"]),
    ("INTC", 2024, "full", "Consolidated Gross Margin",
     "What caused Intel's gross margin to fall in fiscal 2024?",
     "Consolidated gross margin fell $4.4 billion (20%) mainly due to higher impairment charges "
     "and accelerated depreciation: Intel 7 manufacturing assets exceeded capacity needs, "
     "leading to $3.3 billion of charges; lower revenue also contributed.",
     ["$4.4 billion", "accelerated depreciation"]),
    ("INTC", 2025, "full", "Our Priorities",
     "What did Intel do with Altera in 2025?",
     "On September 12, 2025 Intel completed the divestiture of 51% of Altera; Altera's results "
     "are no longer included in Intel's consolidated or segment results after that date.",
     ["divestiture of 51% of Altera"]),
    ("QCOM", 2025, "7", "Fiscal 2025 Overview",
     "Why did Qualcomm's net income fall in fiscal 2025 even though revenue grew?",
     "Revenue rose 14% to $44.3 billion but net income fell 45% to $5.5 billion, because "
     "Qualcomm recorded a $5.7 billion tax charge to set up a valuation allowance on federal "
     "deferred tax assets after the One Big Beautiful Bill Act.",
     ["$5.7 billion", "valuation allowance"]),
    ("QCOM", 2025, "7", "2025 vs. 2024",
     "What happened to Qualcomm's licensing royalties from Huawei in fiscal 2025?",
     "Starting in the second quarter of fiscal 2025, QTL revenues no longer included royalties "
     "from Huawei because Huawei's license agreement expired.",
     ["Huawei", "license agreement has expired"]),
    ("QCOM", 2023, "1A",
     "Geopolitical conflicts, natural disasters, pandemics and other health crises, and other "
     "factors outside of our control, could significantly disrupt ...",
     "What risk does Qualcomm see in a conflict between China and Taiwan (FY2023 10-K)?",
     "Qualcomm depends on chipset supply from foundry partners, particularly in Taiwan; a "
     "significant or prolonged conflict involving China and Taiwan could severely limit or "
     "prevent that supply and materially harm its business.",
     ["China and Taiwan", "chipset supply"]),
    ("QCOM", 2024, "1", "Operating Segments",
     "What are Qualcomm's reportable segments, per its fiscal 2024 10-K?",
     "Qualcomm has three reportable segments: it does business primarily through QCT "
     "(integrated circuits and system software) and QTL, while QSI makes strategic investments.",
     ["three reportable segments", "QSI makes strategic investments"]),
    ("JPM", 2024, "7", "Firmwide overview",
     "What drove the jump in JPMorgan Chase's noninterest revenue in 2024?",
     "Noninterest revenue was $85.0 billion, up 23%, predominantly driven by a $7.9 billion net "
     "gain related to Visa shares, plus higher asset management and investment banking fees and "
     "lower investment securities losses.",
     ["$7.9 billion net gain related to Visa shares"]),
    ("JPM", 2024, "7", "INTRODUCTION",
     "How did JPMorgan reorganize its business segments in 2024?",
     "In Q2 2024 it combined Corporate & Investment Bank and Commercial Banking into one segment, "
     "the Commercial & Investment Bank, leaving three reportable segments: CCB, CIB and AWM, "
     "with other activities in Corporate.",
     ["Commercial & Investment Bank", "three reportable business segments"]),
    ("JPM", 2023, "1A",
     "JPMorgan Chase’s acquisition of certain assets and liabilities of First Republic Bank may "
     "not result in all of the benefits anticipated.",
     "What risks does JPMorgan describe about its First Republic acquisition?",
     "Results of the May 1, 2023 acquisition of First Republic Bank assets and liabilities from "
     "the FDIC may differ from expectations, including the final purchase price, the cost and "
     "time of integration, and the performance of the acquired assets and liabilities.",
     ["First Republic", "total cost of integration"]),
    ("JPM", 2025, "1", "Human capital",
     "How many employees did JPMorgan Chase have at the end of 2025?",
     "JPMorganChase had 318,512 employees globally as of December 31, 2025, located in 66 "
     "countries, with 58% in the U.S.",
     ["318,512 employees"]),
    ("BAC", 2023, "7", "Net Interest Income",
     "Why did Bank of America's net interest income increase in 2023?",
     "Net interest income rose $4.5 billion to $56.9 billion, mainly from higher interest rates "
     "and loan growth, partly offset by higher funding costs, lower deposits and lower Global "
     "Markets net interest income.",
     ["$56.9 billion", "higher interest rates and loan growth"]),
    ("BAC", 2024, "1A",
     "We may be adversely affected by the financial markets, fiscal, monetary, and regulatory "
     "policies, and economic conditions.",
     "How would Federal Reserve rate cuts affect Bank of America, according to its FY2024 risk "
     "factors?",
     "Lower interest rates from a Federal Reserve policy change would typically reduce revenue "
     "through lower net interest income, which could hurt its results of operations.",
     ["lower revenue through lower net interest income"]),
    ("BAC", 2024, "1A",
     "Our concentrations of credit risk could adversely affect our credit losses, results of "
     "operations and financial condition.",
     "Where does Bank of America say it has concentrations of credit risk (FY2024)?",
     "Its concentrations include consumer real estate and consumer credit card exposure, plus "
     "commercial real estate and asset managers and funds portfolios, which are a significant "
     "share of its credit portfolio.",
     ["concentrations of credit risk", "consumer credit card"]),
    ("BAC", 2025, "1", "Segments",
     "What business segments does Bank of America report in its 2025 10-K?",
     "Four segments: Consumer Banking, Global Wealth & Investment Management (GWIM), Global "
     "Banking and Global Markets, with remaining operations in All Other.",
     ["four business segments", "Global Wealth & Investment Management"]),
    ("GS", 2023, "7", "Executive Overview",
     "Why did Goldman Sachs' operating expenses rise in 2023?",
     "Operating expenses were $34.49 billion, up 11%, mainly due to $1.46 billion of commercial "
     "real estate impairments in consolidated investment entities, a $506 million GreenSky "
     "intangibles write-down, a $504 million goodwill impairment for Consumer platforms and a "
     "$529 million FDIC special assessment.",
     ["$34.49 billion", "GreenSky"]),
    ("GS", 2025, "7", "Platform Solutions",
     "What did Goldman Sachs decide about the Apple Card program in 2025?",
     "In December 2025 Goldman agreed to transition the Apple Card program to another issuer, "
     "expected to take about 24 months; it also sold the GM credit card program during 2025.",
     ["transition the Apple Card program to another issuer", "24 months"]),
    ("GS", 2024, "1", "Our Business Segments",
     "What are Goldman Sachs' business segments as described in its 2024 10-K?",
     "Three segments: Global Banking & Markets, Asset & Wealth Management, and Platform "
     "Solutions (consumer platforms and transaction banking).",
     ["three business segments", "Platform Solutions"]),
    ("GS", 2024, "1A",
     "Reductions in our credit ratings or an increase in our credit spreads may adversely "
     "affect our liquidity and cost of funding.",
     "How could a credit rating downgrade hurt Goldman Sachs, per its FY2024 risk factors?",
     "A downgrade could hurt its liquidity and competitive position, raise borrowing costs, "
     "limit access to capital markets, and let counterparties terminate trading and "
     "collateralized financing contracts or require additional collateral.",
     ["credit ratings are important to our liquidity", "additional collateral"]),
    ("PFE", 2023, "7", "Our 2023 Performance",
     "Why did Pfizer's revenue fall so sharply in 2023?",
     "Total revenues fell $41.8 billion (42%) to $58.5 billion, mainly because of significant "
     "declines in Comirnaty and Paxlovid, including a $3.5 billion non-cash Paxlovid revenue "
     "reversal in Q4 2023.",
     ["Comirnaty and Paxlovid", "$3.5 billion non-cash revenue reversal"]),
    ("PFE", 2024, "1A", "CONCENTRATION",
     "How dependent was Pfizer on its biggest products in 2024?",
     "11 products with more than $1 billion of revenue each made up 66% of total revenues in "
     "2024; Eliquis alone was 12%.",
     ["11 products", "66% of Total revenues"]),
    ("PFE", 2024, "1A", "PRICING AND REIMBURSEMENT",
     "Which Pfizer drugs were selected for Medicare price setting under the IRA, per its FY2024 "
     "10-K?",
     "Ibrance and Xtandi were among the 15 drugs selected for the IRA's Medicare price "
     "negotiation program.",
     ["Ibrance and Xtandi"]),
    ("PFE", 2025, "1", "ABOUT PFIZER",
     "What are Pfizer's key priorities for 2026?",
     "Maximize the value of key transactions, deliver on critical R&D milestones, invest to "
     "maximize post-2028 growth, and scale AI across the business.",
     ["2026 key priorities", "Scale AI across our business"]),
    ("LLY", 2023, "7", "Product Supply",
     "What supply problems did Eli Lilly have with its incretin drugs in 2023?",
     "Strong demand for Mounjaro, the Zepbound launch and continued Trulicity demand led to "
     "intermittent delays in filling some incretin orders; Lilly expects tight supply until new "
     "manufacturing capacity, such as its Research Triangle Park site, comes online.",
     ["incretin products", "intermittent delays"]),
    ("LLY", 2024, "7", "Financial Results",
     "What drove Lilly's revenue growth in 2024?",
     "Revenue grew on higher volume and, to a lesser extent, higher realized prices, primarily "
     "from Mounjaro, Zepbound and Verzenio, partially offset by Trulicity.",
     ["Mounjaro, Zepbound, and Verzenio", "partially offset by Trulicity"]),
    ("LLY", 2025, "1A",
     "We derive a significant percentage of our total revenue from relatively few products and "
     "sell our products through consolidated supply chain ...",
     "What share of Eli Lilly's 2025 revenue came from Mounjaro and Zepbound?",
     "Mounjaro and Zepbound made up 56 percent of Lilly's total revenues in 2025; six products "
     "with over $3 billion each made up 82 percent.",
     ["56 percent of our total revenues", "Mounjaro and Zepbound"]),
    ("LLY", 2023, "1", None,
     "How many business segments does Eli Lilly operate in (FY2023 10-K)?",
     "Lilly operates in a single business segment: human pharmaceutical products.",
     ["single business segment", "human pharmaceutical products"]),
    ("MRK", 2023, "7", "Costs, Expenses and Other",
     "Why did Merck's R&D expenses jump in 2023?",
     "R&D expenses rose to $30.5 billion from $13.5 billion, mainly from business development "
     "charges: $10.2 billion for the Prometheus acquisition, $5.5 billion for the Daiichi Sankyo "
     "collaboration and $1.2 billion for the Imago acquisition.",
     ["$10.2 billion for the acquisition of Prometheus", "Daiichi Sankyo"]),
    ("MRK", 2024, "1A",
     "Key products generate a significant amount of the Company’s profits and cash flows, and "
     "any events that adversely affect the markets for its leading ...",
     "What percentage of Merck's 2024 sales came from Keytruda?",
     "Keytruda represented 46% of Merck's total sales in 2024, and the oncology portfolio led by "
     "Keytruda was substantially all of its revenue growth.",
     ["Keytruda represented 46%"]),
    ("MRK", 2024, "1A",
     "The health care industry in the U.S. has been, and will continue to be, subject to "
     "increasing regulation and political action.",
     "How does Merck expect IRA price setting to affect Keytruda?",
     "Merck expects HHS to select Keytruda in 2026 for IRA price setting, with the price "
     "effective January 1, 2028, and expects U.S. Keytruda sales to decline after that.",
     ["Keytruda", "January 1, 2028"]),
    ("MRK", 2025, "1", "Human Capital",
     "How many employees did Merck have at the end of 2025?",
     "About 75,000 employees worldwide as of December 31, 2025, including about 30,000 in the "
     "U.S. and Puerto Rico.",
     ["approximately 75,000 employees"]),
]


def text_items() -> list[DatasetItem]:
    return [
        DatasetItem(
            id=f"txt-{i:03d}", type="text", question=q, gold_answer=a,
            gold_sources=[GoldSource(ticker=t, fiscal_year=y, item=it, section=s)],
            gold_contains=c,
        )
        for i, (t, y, it, s, q, a, c) in enumerate(TEXT, 1)
    ]


# ---------------------------------------------------------------- multihop (30)
def gm(t, y):
    return pct(v(t, y, "gross_profit"), v(t, y, "revenue"))


def om(t, y):
    return pct(v(t, y, "operating_income"), v(t, y, "revenue"))


def nm(t, y):
    return pct(v(t, y, "net_income"), v(t, y, "revenue"))


def rdi(t, y):
    return pct(v(t, y, "rd_expense"), v(t, y, "revenue"))


def roa(t, y):
    return pct(v(t, y, "net_income"), v(t, y, "total_assets"))


def p(x: float) -> str:
    return f"{x:.1f}%"


def pp(x: float) -> str:
    return f"{x:+.2f} pp"


def mh(q, answer, value, unit, pairs, notes=""):
    return dict(question=q, gold_answer=answer, gold_value=value, unit=unit,
                gold_sources=srcs(pairs), notes=notes)


def ranked(tickers, fn, y, fmt):
    order = sorted(tickers, key=lambda t: fn(t, y), reverse=True)
    return order, ", ".join(f"{t} {fmt(fn(t, y))}" for t in order)


def multihop_specs() -> list[dict]:
    out = []

    def add(*a, **k):
        out.append(mh(*a, **k))

    # 1 highest bank net income
    o, s = ranked(BANKS, lambda t, y: v(t, y, "net_income"), 2025, usd)
    add("Which bank had the highest net income in FY2025?",
        f"{NAMES[o[0]]} ({o[0]}) had the highest FY2025 net income: {s}.",
        v(o[0], 2025, "net_income"), "USD", [(t, 2025) for t in BANKS])
    # 2 LLY revenue growth 23->25
    g = growth(v("LLY", 2025, "revenue"), v("LLY", 2023, "revenue"))
    add("How much did Eli Lilly's revenue grow from FY2023 to FY2025, in percent?",
        f"Lilly's revenue grew {p(g)}, from {usd(v('LLY', 2023, 'revenue'))} in FY2023 to "
        f"{usd(v('LLY', 2025, 'revenue'))} in FY2025.",
        r2(g), "%", [("LLY", 2023), ("LLY", 2025)])
    # 3 rank semis by FY2024 gross margin
    o, s = ranked(SEMIS, gm, 2024, p)
    add("Rank the semiconductor companies by FY2024 gross margin.",
        f"FY2024 gross margin (gross profit / revenue), highest to lowest: {s}.",
        None, None, [(t, 2024) for t in SEMIS], notes="ranking; no single gold_value")
    # 4 pharma R&D intensity FY2024
    o, s = ranked(PHARMA, rdi, 2024, p)
    add("Which pharma company spent the most on R&D relative to revenue in FY2024?",
        f"{NAMES[o[0]]} had the highest R&D-to-revenue ratio in FY2024: {s}.",
        r2(rdi(o[0], 2024)), "%", [(t, 2024) for t in PHARMA])
    # 5 AMD GM change 23->24
    d = gm("AMD", 2024) - gm("AMD", 2023)
    add("By how many percentage points did AMD's gross margin change from FY2023 to FY2024?",
        f"AMD's gross margin changed by {pp(d)}, from {gm('AMD', 2023):.2f}% in FY2023 to "
        f"{gm('AMD', 2024):.2f}% in FY2024.",
        r2(d), "pp", [("AMD", 2023), ("AMD", 2024)])
    # 6 NVDA revenue growth 24->25
    g = growth(v("NVDA", 2025, "revenue"), v("NVDA", 2024, "revenue"))
    add("By what percentage did Nvidia's revenue grow from fiscal 2024 to fiscal 2025?",
        f"NVIDIA's revenue grew {p(g)}, from {usd(v('NVDA', 2024, 'revenue'))} in FY2024 to "
        f"{usd(v('NVDA', 2025, 'revenue'))} in FY2025.",
        r2(g), "%", [("NVDA", 2024), ("NVDA", 2025)])
    # 7 INTC net income drop 23->24
    d = v("INTC", 2023, "net_income") - v("INTC", 2024, "net_income")
    add("By how much did Intel's net income decline from 2023 to 2024?",
        f"Intel's net income fell by {usd(d)}, from {usd(v('INTC', 2023, 'net_income'))} in "
        f"FY2023 to a net loss of {usd(-v('INTC', 2024, 'net_income'))} in FY2024.",
        d, "USD", [("INTC", 2023), ("INTC", 2024)])
    # 8 highest semis operating margin FY2025
    o, s = ranked(SEMIS, om, 2025, p)
    add("Which semiconductor company had the highest operating margin in FY2025?",
        f"{NAMES[o[0]]} had the highest FY2025 operating margin (operating income / revenue): "
        f"{s}.",
        r2(om(o[0], 2025)), "%", [(t, 2025) for t in SEMIS])
    # 9 JPM vs BAC total assets FY2024
    d = v("JPM", 2024, "total_assets") - v("BAC", 2024, "total_assets")
    add("How much larger were JPMorgan Chase's total assets than Bank of America's at the end of "
        "2024?",
        f"JPMorgan's total assets ({usd(v('JPM', 2024, 'total_assets'))}) exceeded Bank of "
        f"America's ({usd(v('BAC', 2024, 'total_assets'))}) by {usd(d)} at year-end 2024.",
        d, "USD", [("JPM", 2024), ("BAC", 2024)])
    # 10 GS NI growth 23->25
    g = growth(v("GS", 2025, "net_income"), v("GS", 2023, "net_income"))
    add("What was Goldman Sachs' percentage growth in net income from FY23 to FY25?",
        f"Goldman's net income grew {p(g)}, from {usd(v('GS', 2023, 'net_income'))} in FY2023 "
        f"to {usd(v('GS', 2025, 'net_income'))} in FY2025.",
        r2(g), "%", [("GS", 2023), ("GS", 2025)])
    # 11 bank net margin FY2024
    o, s = ranked(BANKS, nm, 2024, lambda x: f"{x:.2f}%")
    add("Which of the three banks converted the largest share of its revenue into net income in "
        "2024?",
        f"{NAMES[o[0]]} had the highest net margin (net income / revenue) in FY2024: {s}.",
        r2(nm(o[0], 2024)), "%", [(t, 2024) for t in BANKS])
    # 12 QCOM R&D intensity change 23->25
    d = rdi("QCOM", 2025) - rdi("QCOM", 2023)
    add("How did Qualcomm's R&D as a percentage of revenue change between fiscal 2023 and fiscal "
        "2025, in percentage points?",
        f"Qualcomm's R&D-to-revenue ratio changed by {pp(d)}, from {rdi('QCOM', 2023):.2f}% in "
        f"FY2023 to {rdi('QCOM', 2025):.2f}% in FY2025.",
        r2(d), "pp", [("QCOM", 2023), ("QCOM", 2025)])
    # 13 MRK NI increase 23->24
    d = v("MRK", 2024, "net_income") - v("MRK", 2023, "net_income")
    add("How much did Merck's net income increase in dollars from 2023 to 2024?",
        f"Merck's net income rose by {usd(d)}, from {usd(v('MRK', 2023, 'net_income'))} in "
        f"FY2023 to {usd(v('MRK', 2024, 'net_income'))} in FY2024.",
        d, "USD", [("MRK", 2023), ("MRK", 2024)])
    # 14 combined bank revenue FY2025
    tot = sum(v(t, 2025, "revenue") for t in BANKS)
    add("What was the combined FY2025 revenue of JPMorgan, Bank of America and Goldman Sachs?",
        "Combined FY2025 revenue was " + usd(tot) + " (" + ", ".join(
            f"{t} {usd(v(t, 2025, 'revenue'))}" for t in BANKS) + ").",
        tot, "USD", [(t, 2025) for t in BANKS])
    # 15 largest pharma revenue FY2025
    o, s = ranked(PHARMA, lambda t, y: v(t, y, "revenue"), 2025, usd)
    add("Which pharmaceutical company had the largest revenue in 2025?",
        f"{NAMES[o[0]]} had the largest FY2025 revenue, narrowly: {s}.",
        v(o[0], 2025, "revenue"), "USD", [(t, 2025) for t in PHARMA])
    # 16 rank pharma by FY2025 net income
    o, s = ranked(PHARMA, lambda t, y: v(t, y, "net_income"), 2025, usd)
    add("Rank Pfizer, Merck and Eli Lilly by net income in FY2025.",
        f"FY2025 net income, highest to lowest: {s}.",
        None, None, [(t, 2025) for t in PHARMA], notes="ranking; no single gold_value")
    # 17 AMD R&D growth 23->25
    g = growth(v("AMD", 2025, "rd_expense"), v("AMD", 2023, "rd_expense"))
    add("By what percent did AMD's R&D spending grow between FY2023 and FY2025?",
        f"AMD's R&D expense grew {p(g)}, from {usd(v('AMD', 2023, 'rd_expense'))} in FY2023 to "
        f"{usd(v('AMD', 2025, 'rd_expense'))} in FY2025.",
        r2(g), "%", [("AMD", 2023), ("AMD", 2025)])
    # 18 INTC GM change 23->25
    d = gm("INTC", 2025) - gm("INTC", 2023)
    add("By how many percentage points did Intel's gross margin change from 2023 to 2025?",
        f"Intel's gross margin changed by {pp(d)}, from {gm('INTC', 2023):.2f}% in FY2023 to "
        f"{gm('INTC', 2025):.2f}% in FY2025.",
        r2(d), "pp", [("INTC", 2023), ("INTC", 2025)])
    # 19 largest semis R&D FY2025 (absolute)
    o, s = ranked(SEMIS, lambda t, y: v(t, y, "rd_expense"), 2025, usd)
    add("Which semiconductor company spent the most on R&D in FY2025, in dollars?",
        f"{NAMES[o[0]]} spent the most on R&D in FY2025: {s} (each company's own fiscal year).",
        v(o[0], 2025, "rd_expense"), "USD", [(t, 2025) for t in SEMIS])
    # 20 NVDA net margin change 24->25
    d = nm("NVDA", 2025) - nm("NVDA", 2024)
    add("How many percentage points did NVIDIA's net profit margin change from FY24 to FY25?",
        f"NVIDIA's net margin changed by {pp(d)}, from {nm('NVDA', 2024):.2f}% in FY2024 to "
        f"{nm('NVDA', 2025):.2f}% in FY2025.",
        r2(d), "pp", [("NVDA", 2024), ("NVDA", 2025)])
    # 21 PFE revenue growth 23->24
    g = growth(v("PFE", 2024, "revenue"), v("PFE", 2023, "revenue"))
    add("What was Pfizer's revenue growth rate from 2023 to 2024?",
        f"Pfizer's revenue grew {p(g)}, from {usd(v('PFE', 2023, 'revenue'))} in FY2023 to "
        f"{usd(v('PFE', 2024, 'revenue'))} in FY2024.",
        r2(g), "%", [("PFE", 2023), ("PFE", 2024)])
    # 22 ROA JPM vs BAC FY2025
    add("Which had the higher return on assets in FY2025 (net income divided by year-end total "
        "assets): JPMorgan Chase or Bank of America?",
        f"JPMorgan Chase: {roa('JPM', 2025):.2f}% vs Bank of America {roa('BAC', 2025):.2f}% "
        f"(JPM {usd(v('JPM', 2025, 'net_income'))} / {usd(v('JPM', 2025, 'total_assets'))}; "
        f"BAC {usd(v('BAC', 2025, 'net_income'))} / {usd(v('BAC', 2025, 'total_assets'))}).",
        r2(roa("JPM", 2025)), "%", [("JPM", 2025), ("BAC", 2025)])
    # 23 QCOM NI change 24->25
    g = growth(v("QCOM", 2025, "net_income"), v("QCOM", 2024, "net_income"))
    add("By what percentage did Qualcomm's net income change from fiscal 2024 to fiscal 2025?",
        f"Qualcomm's net income changed {p(g)}, from {usd(v('QCOM', 2024, 'net_income'))} in "
        f"FY2024 to {usd(v('QCOM', 2025, 'net_income'))} in FY2025.",
        r2(g), "%", [("QCOM", 2024), ("QCOM", 2025)])
    # 24 LLY vs MRK gross margin FY2025
    d = gm("LLY", 2025) - gm("MRK", 2025)
    add("Which had the higher gross margin in FY2025, Eli Lilly or Merck, and by how many "
        "percentage points?",
        f"Eli Lilly, by {d:.2f} pp: {gm('LLY', 2025):.2f}% vs Merck {gm('MRK', 2025):.2f}% "
        f"(gross profit = revenue minus cost of sales).",
        r2(d), "pp", [("LLY", 2025), ("MRK", 2025)])
    # 25 total pharma R&D FY2023
    tot = sum(v(t, 2023, "rd_expense") for t in PHARMA)
    add("What was the total R&D expense of Pfizer, Merck and Lilly combined in 2023?",
        "Combined FY2023 R&D expense was " + usd(tot) + " (" + ", ".join(
            f"{t} {usd(v(t, 2023, 'rd_expense'))}" for t in PHARMA) + "; includes acquired "
        "IPR&D).",
        tot, "USD", [(t, 2023) for t in PHARMA])
    # 26 largest semis total assets FY2025
    o, s = ranked(SEMIS, lambda t, y: v(t, y, "total_assets"), 2025, usd)
    add("Which chipmaker had the largest total assets at the end of FY2025?",
        f"{NAMES[o[0]]} had the largest FY2025 total assets: {s}.",
        v(o[0], 2025, "total_assets"), "USD", [(t, 2025) for t in SEMIS])
    # 27 GS revenue growth 24->25
    g = growth(v("GS", 2025, "revenue"), v("GS", 2024, "revenue"))
    add("How much did Goldman Sachs' net revenues grow in 2025 versus 2024, in percent?",
        f"Goldman's net revenues grew {p(g)}, from {usd(v('GS', 2024, 'revenue'))} in FY2024 to "
        f"{usd(v('GS', 2025, 'revenue'))} in FY2025.",
        r2(g), "%", [("GS", 2024), ("GS", 2025)])
    # 28 AMD operating income growth 24->25
    g = growth(v("AMD", 2025, "operating_income"), v("AMD", 2024, "operating_income"))
    add("What was AMD's operating income growth from FY2024 to FY2025?",
        f"AMD's operating income grew {p(g)}, from {usd(v('AMD', 2024, 'operating_income'))} in "
        f"FY2024 to {usd(v('AMD', 2025, 'operating_income'))} in FY2025.",
        r2(g), "%", [("AMD", 2024), ("AMD", 2025)])
    # 29 NVDA vs INTC revenue FY2025
    d = v("NVDA", 2025, "revenue") - v("INTC", 2025, "revenue")
    add("How much more revenue did NVIDIA report than Intel for fiscal 2025?",
        f"NVIDIA's FY2025 revenue ({usd(v('NVDA', 2025, 'revenue'))}, year ended "
        f"{F[('NVDA', 2025, 'revenue')]['period_end']}) exceeded Intel's "
        f"({usd(v('INTC', 2025, 'revenue'))}, year ended "
        f"{F[('INTC', 2025, 'revenue')]['period_end']}) by {usd(d)}.",
        d, "USD", [("NVDA", 2025), ("INTC", 2025)])
    # 30 MRK R&D intensity change 23->24
    d = rdi("MRK", 2024) - rdi("MRK", 2023)
    add("By how many percentage points did Merck's R&D-to-revenue ratio change from 2023 to "
        "2024?",
        f"Merck's R&D as a share of revenue changed by {pp(d)}, from {rdi('MRK', 2023):.2f}% in "
        f"FY2023 to {rdi('MRK', 2024):.2f}% in FY2024 (FY2023 R&D included large acquired "
        "IPR&D charges).",
        r2(d), "pp", [("MRK", 2023), ("MRK", 2024)])
    return out


def multihop_items() -> list[DatasetItem]:
    return [DatasetItem(id=f"mh-{i:03d}", type="multihop", **s)
            for i, s in enumerate(multihop_specs(), 1)]


# ---------------------------------------------------------------- unanswerable (10)
UNANSWERABLE = [
    ("What was Pfizer's revenue in FY2030?", "year outside the data"),
    ("What was AMD's net income in fiscal 2019?", "year outside the data"),
    ("What was Apple's revenue in fiscal 2024?", "company not in the corpus"),
    ("How much did Tesla spend on R&D in 2023?", "company not in the corpus"),
    ("What were Microsoft's total assets at the end of FY2025?", "company not in the corpus"),
    ("What was Bank of America's research and development expense in 2024?",
     "banks do not report R&D expense"),
    ("What was Goldman Sachs' R&D spending in FY2025?", "banks do not report R&D expense"),
    ("What was NVIDIA's closing stock price on March 15, 2024?", "stock price on a date"),
    ("What was Merck's closing share price on December 31, 2024?", "stock price on a date"),
    ("What revenue does Eli Lilly forecast for 2028?", "future-year forecast"),
]


def unanswerable_items() -> list[DatasetItem]:
    return [DatasetItem(id=f"na-{i:03d}", type="unanswerable", question=q,
                        gold_answer="Not found in the filings.", notes=n)
            for i, (q, n) in enumerate(UNANSWERABLE, 1)]


def build() -> list[DatasetItem]:
    return number_items() + text_items() + multihop_items() + unanswerable_items()


def main() -> None:
    items = build()
    with open(DATASET, "w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps(it.model_dump(exclude_defaults=True) | {"author": it.author},
                               ensure_ascii=False) + "\n")
    print(f"wrote {len(items)} items to {DATASET}")


if __name__ == "__main__":
    main()
