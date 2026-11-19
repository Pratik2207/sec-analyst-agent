# Eval dataset — review sheet

Generated from `evals/dataset.jsonl` (120 questions, pilot companies, FY2023-2025). Gold values for number and multi-hop questions are computed from the XBRL facts; text golds are taken from the filing chunks (their key phrases are verified to exist).

To change a question: edit `evals/dataset.jsonl` (or tell Claude the id and the change). Edited questions are re-run automatically.

## Number (single fact) (40)

| id | question | gold answer | sources |
|---|---|---|---|
| num-001 | How much did NVIDIA spend on research and development in fiscal 2023? | NVIDIA's R&D expense in FY2023 was $7.34 billion (fiscal year ended 2023-01-29). | NVDA FY2023 Item 8 |
| num-002 | What was Nvidia's net income for FY24? | NVIDIA's net income in FY2024 was $29.76 billion (fiscal year ended 2024-01-28). | NVDA FY2024 Item 8 |
| num-003 | What was NVIDIA's operating income in fiscal year 2025? | NVIDIA's operating income in FY2025 was $81.45 billion (fiscal year ended 2025-01-26). | NVDA FY2025 Item 8 |
| num-004 | What were Nvidia's total assets at the end of fiscal 2024? | NVIDIA's total assets at the end of FY2024 were $65.73 billion (fiscal year ended 2024-01-28). | NVDA FY2024 Item 8 |
| num-005 | What was AMD's revenue in 2023? | AMD's revenue in FY2023 was $22.68 billion. | AMD FY2023 Item 8 |
| num-006 | What was AMD's gross profit for fiscal year 2024? | AMD's gross profit in FY2024 was $12.72 billion. | AMD FY2024 Item 8 |
| num-007 | How much operating income did AMD report in FY2025? | AMD's operating income in FY2025 was $3.69 billion. | AMD FY2025 Item 8 |
| num-008 | What was Advanced Micro Devices' R&D expense in FY25? | AMD's R&D expense in FY2025 was $8.09 billion. | AMD FY2025 Item 8 |
| num-009 | What was Intel's net income (or loss) in fiscal year 2024? | Intel reported a net loss of $18.76 billion in FY2024. | INTC FY2024 Item 8 |
| num-010 | What was Intel's total revenue in 2025? | Intel's revenue in FY2025 was $52.85 billion. | INTC FY2025 Item 8 |
| num-011 | What were Intel's total assets at the end of FY2023? | Intel's total assets at the end of FY2023 were $191.57 billion. | INTC FY2023 Item 8 |
| num-012 | What gross profit did Intel report for fiscal 2025? | Intel's gross profit in FY2025 was $18.38 billion. | INTC FY2025 Item 8 |
| num-013 | What were Qualcomm's revenues in fiscal 2024? | Qualcomm's revenue in FY2024 was $38.96 billion (fiscal year ended 2024-09-29). | QCOM FY2024 Item 8 |
| num-014 | How much did Qualcomm spend on R&D in FY2025? | Qualcomm's R&D expense in FY2025 was $9.04 billion (fiscal year ended 2025-09-28). | QCOM FY2025 Item 8 |
| num-015 | What was Qualcomm's net income for fiscal year 2023? | Qualcomm's net income in FY2023 was $7.23 billion (fiscal year ended 2023-09-24). | QCOM FY2023 Item 8 |
| num-016 | What was QCOM's operating income in FY24? | Qualcomm's operating income in FY2024 was $10.07 billion (fiscal year ended 2024-09-29). | QCOM FY2024 Item 8 |
| num-017 | What was JPMorgan Chase's net income in 2024? | JPMorgan Chase's net income in FY2024 was $58.47 billion. | JPM FY2024 Item 8 |
| num-018 | What was JPMorgan's total net revenue for fiscal year 2025? | JPMorgan Chase's revenue in FY2025 was $182.45 billion. | JPM FY2025 Item 8 |
| num-019 | What were JPMorgan Chase's total assets at year-end 2023? | JPMorgan Chase's total assets at the end of FY2023 were $3.88 trillion. | JPM FY2023 Item 8 |
| num-020 | How much net income did JPMorgan earn in FY2023? | JPMorgan Chase's net income in FY2023 was $49.55 billion. | JPM FY2023 Item 8 |
| num-021 | What was Bank of America's total revenue in 2023? | Bank of America's revenue in FY2023 was $98.58 billion. | BAC FY2023 Item 8 |
| num-022 | What were Bank of America's total assets at the end of FY2025? | Bank of America's total assets at the end of FY2025 were $3.41 trillion. | BAC FY2025 Item 8 |
| num-023 | What was BofA's net income in fiscal 2025? | Bank of America's net income in FY2025 was $30.51 billion. | BAC FY2025 Item 8 |
| num-024 | What was Bank of America's revenue for FY24? | Bank of America's revenue in FY2024 was $101.89 billion. | BAC FY2024 Item 8 |
| num-025 | What was Goldman Sachs' net income in 2023? | Goldman Sachs's net income in FY2023 was $8.52 billion. | GS FY2023 Item 8 |
| num-026 | What were Goldman Sachs's total net revenues in fiscal year 2025? | Goldman Sachs's revenue in FY2025 was $58.28 billion. | GS FY2025 Item 8 |
| num-027 | What were Goldman Sachs' total assets at the end of 2024? | Goldman Sachs's total assets at the end of FY2024 were $1.68 trillion. | GS FY2024 Item 8 |
| num-028 | How much net income did Goldman report for FY2025? | Goldman Sachs's net income in FY2025 was $17.18 billion. | GS FY2025 Item 8 |
| num-029 | What was Pfizer's total revenue in fiscal 2024? | Pfizer's revenue in FY2024 was $63.63 billion. | PFE FY2024 Item 8 |
| num-030 | What was Pfizer's research and development expense in 2023? | Pfizer's R&D expense in FY2023 was $10.87 billion. | PFE FY2023 Item 8 |
| num-031 | What was Pfizer's net income for FY2025? | Pfizer's net income in FY2025 was $7.77 billion. | PFE FY2025 Item 8 |
| num-032 | What were Pfizer's total assets at the end of FY24? | Pfizer's total assets at the end of FY2024 were $213.40 billion. | PFE FY2024 Item 8 |
| num-033 | What was Eli Lilly's revenue in fiscal year 2025? | Eli Lilly's revenue in FY2025 was $65.18 billion. | LLY FY2025 Item 8 |
| num-034 | How much did Lilly spend on R&D in 2024? | Eli Lilly's R&D expense in FY2024 was $14.27 billion. | LLY FY2024 Item 8 |
| num-035 | What was Eli Lilly's net income in FY2023? | Eli Lilly's net income in FY2023 was $5.24 billion. | LLY FY2023 Item 8 |
| num-036 | What were Eli Lilly's total assets at the end of 2025? | Eli Lilly's total assets at the end of FY2025 were $112.48 billion. | LLY FY2025 Item 8 |
| num-037 | What was Merck's R&D expense in fiscal 2023? | Merck's R&D expense in FY2023 was $30.53 billion. | MRK FY2023 Item 8 |
| num-038 | What was Merck's net income in 2024? | Merck's net income in FY2024 was $17.12 billion. | MRK FY2024 Item 8 |
| num-039 | What was Merck's gross profit in FY2025? | Merck's gross profit in FY2025 was $48.63 billion (revenue minus cost of sales). | MRK FY2025 Item 8 |
| num-040 | What were Merck's total sales in FY23? | Merck's revenue in FY2023 was $60.12 billion. | MRK FY2023 Item 8 |

## Text / explanation (40)

| id | question | gold answer | sources |
|---|---|---|---|
| txt-001 | What drove the increase in NVIDIA's gross margin in fiscal 2024? | Gross margin rose to 72.7% in FY2024 from 56.9% in FY2023, primarily due to strong Data Center revenue growth of 217% and lower net inventory provisions as a share of revenue. | NVDA FY2024 Item 7 |
| txt-002 | Why did NVIDIA's deal to buy Arm fall through, and what did the termination cost in FY2023? | NVIDIA and SoftBank terminated the agreement in February 2022 because of significant regulatory challenges; NVIDIA recorded a $1.35 billion acquisition termination cost in fiscal 2023, writing off the prepayment made at signing. | NVDA FY2023 Item 7 |
| txt-003 | According to Nvidia's FY2025 10-K, how did sanctions after the war in Ukraine affect its business in Russia? | Sanctions and export controls blocked its products, services and support into Russia, Belarus and parts of Ukraine; in fiscal 2023 NVIDIA stopped direct sales to Russia and closed its business operations there. | NVDA FY2025 Item 1A |
| txt-004 | How does NVIDIA manufacture its products, per its fiscal 2025 annual report? | NVIDIA uses a fabless and contracting manufacturing strategy, partnering with key suppliers for all phases of manufacturing (wafer fabrication, assembly, testing and packaging), which lets it avoid the costs and risks of owning fabs. | NVDA FY2025 Item 1 |
| txt-005 | What agreement did AMD sign with OpenAI in 2025? | In October 2025 AMD agreed with OpenAI to deploy 6 gigawatts of AMD GPUs, starting with MI450 series products, and issued OpenAI a warrant to buy up to 160 million AMD shares at $0.01 per share, vesting on purchase milestones and stock price targets. | AMD FY2025 Item 7 |
| txt-006 | Why did AMD's gross margin change in 2025? | Gross margin rose to 50% from 49% in 2024, primarily due to product mix, partially offset by about $440 million of inventory and related charges from the U.S. export control on Instinct MI308 GPUs. | AMD FY2025 Item 7 |
| txt-007 | Which foundries make AMD's wafers, according to its FY2024 10-K? | AMD uses TSMC for wafers for its HPC, FPGA and Adaptive SoC products and GLOBALFOUNDRIES for HPC wafers at the 12 nm and 14 nm nodes; TSMC, UMC and Samsung produce its programmable logic ICs. | AMD FY2024 Item 1 |
| txt-008 | What competitive risk does AMD describe regarding Intel in its 2023 risk factors? | Intel's microprocessor dominance, financial resources and OEM relationships let it price aggressively and use practices such as rebates, bundling and exclusivity payments, which have lowered AMD's unit sales, average selling prices and margins. | AMD FY2023 Item 1A |
| txt-009 | Why did Intel's revenue decline in 2023? | 2023 revenue was $54.2 billion, down $8.8 billion or 14% from 2022: CCG fell 8% on lower notebook and desktop volume, DCAI fell 20% on lower server volume, and NEX fell 31% as customers reduced inventories. | INTC FY2023 Item full |
| txt-010 | Why did Intel stop paying dividends in 2024? | Intel suspended its quarterly dividend starting in Q4 2024; under its commercial CHIPS Act agreement it agreed to forgo dividends for the next two years and to limit them for the three years after that. | INTC FY2024 Item full |
| txt-011 | What caused Intel's gross margin to fall in fiscal 2024? | Consolidated gross margin fell $4.4 billion (20%) mainly due to higher impairment charges and accelerated depreciation: Intel 7 manufacturing assets exceeded capacity needs, leading to $3.3 billion of charges; lower revenue also contributed. | INTC FY2024 Item full |
| txt-012 | What did Intel do with Altera in 2025? | On September 12, 2025 Intel completed the divestiture of 51% of Altera; Altera's results are no longer included in Intel's consolidated or segment results after that date. | INTC FY2025 Item full |
| txt-013 | Why did Qualcomm's net income fall in fiscal 2025 even though revenue grew? | Revenue rose 14% to $44.3 billion but net income fell 45% to $5.5 billion, because Qualcomm recorded a $5.7 billion tax charge to set up a valuation allowance on federal deferred tax assets after the One Big Beautiful Bill Act. | QCOM FY2025 Item 7 |
| txt-014 | What happened to Qualcomm's licensing royalties from Huawei in fiscal 2025? | Starting in the second quarter of fiscal 2025, QTL revenues no longer included royalties from Huawei because Huawei's license agreement expired. | QCOM FY2025 Item 7 |
| txt-015 | What risk does Qualcomm see in a conflict between China and Taiwan (FY2023 10-K)? | Qualcomm depends on chipset supply from foundry partners, particularly in Taiwan; a significant or prolonged conflict involving China and Taiwan could severely limit or prevent that supply and materially harm its business. | QCOM FY2023 Item 1A |
| txt-016 | What are Qualcomm's reportable segments, per its fiscal 2024 10-K? | Qualcomm has three reportable segments: it does business primarily through QCT (integrated circuits and system software) and QTL, while QSI makes strategic investments. | QCOM FY2024 Item 1 |
| txt-017 | What drove the jump in JPMorgan Chase's noninterest revenue in 2024? | Noninterest revenue was $85.0 billion, up 23%, predominantly driven by a $7.9 billion net gain related to Visa shares, plus higher asset management and investment banking fees and lower investment securities losses. | JPM FY2024 Item 7 |
| txt-018 | How did JPMorgan reorganize its business segments in 2024? | In Q2 2024 it combined Corporate & Investment Bank and Commercial Banking into one segment, the Commercial & Investment Bank, leaving three reportable segments: CCB, CIB and AWM, with other activities in Corporate. | JPM FY2024 Item 7 |
| txt-019 | What risks does JPMorgan describe about its First Republic acquisition? | Results of the May 1, 2023 acquisition of First Republic Bank assets and liabilities from the FDIC may differ from expectations, including the final purchase price, the cost and time of integration, and the performance of the acquired assets and liabilities. | JPM FY2023 Item 1A |
| txt-020 | How many employees did JPMorgan Chase have at the end of 2025? | JPMorganChase had 318,512 employees globally as of December 31, 2025, located in 66 countries, with 58% in the U.S. | JPM FY2025 Item 1 |
| txt-021 | Why did Bank of America's net interest income increase in 2023? | Net interest income rose $4.5 billion to $56.9 billion, mainly from higher interest rates and loan growth, partly offset by higher funding costs, lower deposits and lower Global Markets net interest income. | BAC FY2023 Item 7 |
| txt-022 | How would Federal Reserve rate cuts affect Bank of America, according to its FY2024 risk factors? | Lower interest rates from a Federal Reserve policy change would typically reduce revenue through lower net interest income, which could hurt its results of operations. | BAC FY2024 Item 1A |
| txt-023 | Where does Bank of America say it has concentrations of credit risk (FY2024)? | Its concentrations include consumer real estate and consumer credit card exposure, plus commercial real estate and asset managers and funds portfolios, which are a significant share of its credit portfolio. | BAC FY2024 Item 1A |
| txt-024 | What business segments does Bank of America report in its 2025 10-K? | Four segments: Consumer Banking, Global Wealth & Investment Management (GWIM), Global Banking and Global Markets, with remaining operations in All Other. | BAC FY2025 Item 1 |
| txt-025 | Why did Goldman Sachs' operating expenses rise in 2023? | Operating expenses were $34.49 billion, up 11%, mainly due to $1.46 billion of commercial real estate impairments in consolidated investment entities, a $506 million GreenSky intangibles write-down, a $504 million goodwill impairment for Consumer platforms and a $529 million FDIC special assessment. | GS FY2023 Item 7 |
| txt-026 | What did Goldman Sachs decide about the Apple Card program in 2025? | In December 2025 Goldman agreed to transition the Apple Card program to another issuer, expected to take about 24 months; it also sold the GM credit card program during 2025. | GS FY2025 Item 7 |
| txt-027 | What are Goldman Sachs' business segments as described in its 2024 10-K? | Three segments: Global Banking & Markets, Asset & Wealth Management, and Platform Solutions (consumer platforms and transaction banking). | GS FY2024 Item 1 |
| txt-028 | How could a credit rating downgrade hurt Goldman Sachs, per its FY2024 risk factors? | A downgrade could hurt its liquidity and competitive position, raise borrowing costs, limit access to capital markets, and let counterparties terminate trading and collateralized financing contracts or require additional collateral. | GS FY2024 Item 1A |
| txt-029 | Why did Pfizer's revenue fall so sharply in 2023? | Total revenues fell $41.8 billion (42%) to $58.5 billion, mainly because of significant declines in Comirnaty and Paxlovid, including a $3.5 billion non-cash Paxlovid revenue reversal in Q4 2023. | PFE FY2023 Item 7 |
| txt-030 | How dependent was Pfizer on its biggest products in 2024? | 11 products with more than $1 billion of revenue each made up 66% of total revenues in 2024; Eliquis alone was 12%. | PFE FY2024 Item 1A |
| txt-031 | Which Pfizer drugs were selected for Medicare price setting under the IRA, per its FY2024 10-K? | Ibrance and Xtandi were among the 15 drugs selected for the IRA's Medicare price negotiation program. | PFE FY2024 Item 1A |
| txt-032 | What are Pfizer's key priorities for 2026? | Maximize the value of key transactions, deliver on critical R&D milestones, invest to maximize post-2028 growth, and scale AI across the business. | PFE FY2025 Item 1 |
| txt-033 | What supply problems did Eli Lilly have with its incretin drugs in 2023? | Strong demand for Mounjaro, the Zepbound launch and continued Trulicity demand led to intermittent delays in filling some incretin orders; Lilly expects tight supply until new manufacturing capacity, such as its Research Triangle Park site, comes online. | LLY FY2023 Item 7 |
| txt-034 | What drove Lilly's revenue growth in 2024? | Revenue grew on higher volume and, to a lesser extent, higher realized prices, primarily from Mounjaro, Zepbound and Verzenio, partially offset by Trulicity. | LLY FY2024 Item 7 |
| txt-035 | What share of Eli Lilly's 2025 revenue came from Mounjaro and Zepbound? | Mounjaro and Zepbound made up 56 percent of Lilly's total revenues in 2025; six products with over $3 billion each made up 82 percent. | LLY FY2025 Item 1A |
| txt-036 | How many business segments does Eli Lilly operate in (FY2023 10-K)? | Lilly operates in a single business segment: human pharmaceutical products. | LLY FY2023 Item 1 |
| txt-037 | Why did Merck's R&D expenses jump in 2023? | R&D expenses rose to $30.5 billion from $13.5 billion, mainly from business development charges: $10.2 billion for the Prometheus acquisition, $5.5 billion for the Daiichi Sankyo collaboration and $1.2 billion for the Imago acquisition. | MRK FY2023 Item 7 |
| txt-038 | What percentage of Merck's 2024 sales came from Keytruda? | Keytruda represented 46% of Merck's total sales in 2024, and the oncology portfolio led by Keytruda was substantially all of its revenue growth. | MRK FY2024 Item 1A |
| txt-039 | How does Merck expect IRA price setting to affect Keytruda? | Merck expects HHS to select Keytruda in 2026 for IRA price setting, with the price effective January 1, 2028, and expects U.S. Keytruda sales to decline after that. | MRK FY2024 Item 1A |
| txt-040 | How many employees did Merck have at the end of 2025? | About 75,000 employees worldwide as of December 31, 2025, including about 30,000 in the U.S. and Puerto Rico. | MRK FY2025 Item 1 |

## Multi-hop / comparison (30)

| id | question | gold answer | sources |
|---|---|---|---|
| mh-001 | Which bank had the highest net income in FY2025? | JPMorgan Chase (JPM) had the highest FY2025 net income: JPM $57.05 billion, BAC $30.51 billion, GS $17.18 billion. | BAC FY2025 Item 8; GS FY2025 Item 8; JPM FY2025 Item 8 |
| mh-002 | How much did Eli Lilly's revenue grow from FY2023 to FY2025, in percent? | Lilly's revenue grew 91.0%, from $34.12 billion in FY2023 to $65.18 billion in FY2025. | LLY FY2023 Item 8; LLY FY2025 Item 8 |
| mh-003 | Rank the semiconductor companies by FY2024 gross margin. | FY2024 gross margin (gross profit / revenue), highest to lowest: NVDA 72.7%, QCOM 56.2%, AMD 49.4%, INTC 32.7%. | AMD FY2024 Item 8; INTC FY2024 Item 8; NVDA FY2024 Item 8; QCOM FY2024 Item 8 |
| mh-004 | Which pharma company spent the most on R&D relative to revenue in FY2024? | Eli Lilly had the highest R&D-to-revenue ratio in FY2024: LLY 31.7%, MRK 28.0%, PFE 17.2%. | LLY FY2024 Item 8; MRK FY2024 Item 8; PFE FY2024 Item 8 |
| mh-005 | By how many percentage points did AMD's gross margin change from FY2023 to FY2024? | AMD's gross margin changed by +3.23 pp, from 46.12% in FY2023 to 49.35% in FY2024. | AMD FY2023 Item 8; AMD FY2024 Item 8 |
| mh-006 | By what percentage did Nvidia's revenue grow from fiscal 2024 to fiscal 2025? | NVIDIA's revenue grew 114.2%, from $60.92 billion in FY2024 to $130.50 billion in FY2025. | NVDA FY2024 Item 8; NVDA FY2025 Item 8 |
| mh-007 | By how much did Intel's net income decline from 2023 to 2024? | Intel's net income fell by $20.45 billion, from $1.69 billion in FY2023 to a net loss of $18.76 billion in FY2024. | INTC FY2023 Item 8; INTC FY2024 Item 8 |
| mh-008 | Which semiconductor company had the highest operating margin in FY2025? | NVIDIA had the highest FY2025 operating margin (operating income / revenue): NVDA 62.4%, QCOM 27.9%, AMD 10.7%, INTC -4.2%. | AMD FY2025 Item 8; INTC FY2025 Item 8; NVDA FY2025 Item 8; QCOM FY2025 Item 8 |
| mh-009 | How much larger were JPMorgan Chase's total assets than Bank of America's at the end of 2024? | JPMorgan's total assets ($4.00 trillion) exceeded Bank of America's ($3.26 trillion) by $741.29 billion at year-end 2024. | BAC FY2024 Item 8; JPM FY2024 Item 8 |
| mh-010 | What was Goldman Sachs' percentage growth in net income from FY23 to FY25? | Goldman's net income grew 101.7%, from $8.52 billion in FY2023 to $17.18 billion in FY2025. | GS FY2023 Item 8; GS FY2025 Item 8 |
| mh-011 | Which of the three banks converted the largest share of its revenue into net income in 2024? | JPMorgan Chase had the highest net margin (net income / revenue) in FY2024: JPM 32.93%, GS 26.68%, BAC 26.63%. | BAC FY2024 Item 8; GS FY2024 Item 8; JPM FY2024 Item 8 |
| mh-012 | How did Qualcomm's R&D as a percentage of revenue change between fiscal 2023 and fiscal 2025, in percentage points? | Qualcomm's R&D-to-revenue ratio changed by -4.20 pp, from 24.62% in FY2023 to 20.42% in FY2025. | QCOM FY2023 Item 8; QCOM FY2025 Item 8 |
| mh-013 | How much did Merck's net income increase in dollars from 2023 to 2024? | Merck's net income rose by $16.75 billion, from $365 million in FY2023 to $17.12 billion in FY2024. | MRK FY2023 Item 8; MRK FY2024 Item 8 |
| mh-014 | What was the combined FY2025 revenue of JPMorgan, Bank of America and Goldman Sachs? | Combined FY2025 revenue was $353.83 billion (BAC $113.10 billion, GS $58.28 billion, JPM $182.45 billion). | BAC FY2025 Item 8; GS FY2025 Item 8; JPM FY2025 Item 8 |
| mh-015 | Which pharmaceutical company had the largest revenue in 2025? | Eli Lilly had the largest FY2025 revenue, narrowly: LLY $65.18 billion, MRK $65.01 billion, PFE $62.58 billion. | LLY FY2025 Item 8; MRK FY2025 Item 8; PFE FY2025 Item 8 |
| mh-016 | Rank Pfizer, Merck and Eli Lilly by net income in FY2025. | FY2025 net income, highest to lowest: LLY $20.64 billion, MRK $18.25 billion, PFE $7.77 billion. | LLY FY2025 Item 8; MRK FY2025 Item 8; PFE FY2025 Item 8 |
| mh-017 | By what percent did AMD's R&D spending grow between FY2023 and FY2025? | AMD's R&D expense grew 37.8%, from $5.87 billion in FY2023 to $8.09 billion in FY2025. | AMD FY2023 Item 8; AMD FY2025 Item 8 |
| mh-018 | By how many percentage points did Intel's gross margin change from 2023 to 2025? | Intel's gross margin changed by -5.27 pp, from 40.04% in FY2023 to 34.77% in FY2025. | INTC FY2023 Item 8; INTC FY2025 Item 8 |
| mh-019 | Which semiconductor company spent the most on R&D in FY2025, in dollars? | Intel spent the most on R&D in FY2025: INTC $13.77 billion, NVDA $12.91 billion, QCOM $9.04 billion, AMD $8.09 billion (each company's own fiscal year). | AMD FY2025 Item 8; INTC FY2025 Item 8; NVDA FY2025 Item 8; QCOM FY2025 Item 8 |
| mh-020 | How many percentage points did NVIDIA's net profit margin change from FY24 to FY25? | NVIDIA's net margin changed by +7.00 pp, from 48.85% in FY2024 to 55.85% in FY2025. | NVDA FY2024 Item 8; NVDA FY2025 Item 8 |
| mh-021 | What was Pfizer's revenue growth rate from 2023 to 2024? | Pfizer's revenue grew 8.8%, from $58.50 billion in FY2023 to $63.63 billion in FY2024. | PFE FY2023 Item 8; PFE FY2024 Item 8 |
| mh-022 | Which had the higher return on assets in FY2025 (net income divided by year-end total assets): JPMorgan Chase or Bank of America? | JPMorgan Chase: 1.29% vs Bank of America 0.89% (JPM $57.05 billion / $4.42 trillion; BAC $30.51 billion / $3.41 trillion). | BAC FY2025 Item 8; JPM FY2025 Item 8 |
| mh-023 | By what percentage did Qualcomm's net income change from fiscal 2024 to fiscal 2025? | Qualcomm's net income changed -45.4%, from $10.14 billion in FY2024 to $5.54 billion in FY2025. | QCOM FY2024 Item 8; QCOM FY2025 Item 8 |
| mh-024 | Which had the higher gross margin in FY2025, Eli Lilly or Merck, and by how many percentage points? | Eli Lilly, by 8.24 pp: 83.04% vs Merck 74.80% (gross profit = revenue minus cost of sales). | LLY FY2025 Item 8; MRK FY2025 Item 8 |
| mh-025 | What was the total R&D expense of Pfizer, Merck and Lilly combined in 2023? | Combined FY2023 R&D expense was $54.52 billion (LLY $13.11 billion, MRK $30.53 billion, PFE $10.87 billion; includes acquired IPR&D). | LLY FY2023 Item 8; MRK FY2023 Item 8; PFE FY2023 Item 8 |
| mh-026 | Which chipmaker had the largest total assets at the end of FY2025? | Intel had the largest FY2025 total assets: INTC $211.43 billion, NVDA $111.60 billion, AMD $76.93 billion, QCOM $50.14 billion. | AMD FY2025 Item 8; INTC FY2025 Item 8; NVDA FY2025 Item 8; QCOM FY2025 Item 8 |
| mh-027 | How much did Goldman Sachs' net revenues grow in 2025 versus 2024, in percent? | Goldman's net revenues grew 8.9%, from $53.51 billion in FY2024 to $58.28 billion in FY2025. | GS FY2024 Item 8; GS FY2025 Item 8 |
| mh-028 | What was AMD's operating income growth from FY2024 to FY2025? | AMD's operating income grew 94.4%, from $1.90 billion in FY2024 to $3.69 billion in FY2025. | AMD FY2024 Item 8; AMD FY2025 Item 8 |
| mh-029 | How much more revenue did NVIDIA report than Intel for fiscal 2025? | NVIDIA's FY2025 revenue ($130.50 billion, year ended 2025-01-26) exceeded Intel's ($52.85 billion, year ended 2025-12-27) by $77.64 billion. | INTC FY2025 Item 8; NVDA FY2025 Item 8 |
| mh-030 | By how many percentage points did Merck's R&D-to-revenue ratio change from 2023 to 2024? | Merck's R&D as a share of revenue changed by -22.83 pp, from 50.79% in FY2023 to 27.95% in FY2024 (FY2023 R&D included large acquired IPR&D charges). | MRK FY2023 Item 8; MRK FY2024 Item 8 |

## Unanswerable (must say not found) (10)

| id | question | gold answer | sources |
|---|---|---|---|
| na-001 | What was Pfizer's revenue in FY2030? | Not found in the filings. | — |
| na-002 | What was AMD's net income in fiscal 2019? | Not found in the filings. | — |
| na-003 | What was Apple's revenue in fiscal 2024? | Not found in the filings. | — |
| na-004 | How much did Tesla spend on R&D in 2023? | Not found in the filings. | — |
| na-005 | What were Microsoft's total assets at the end of FY2025? | Not found in the filings. | — |
| na-006 | What was Bank of America's research and development expense in 2024? | Not found in the filings. | — |
| na-007 | What was Goldman Sachs' R&D spending in FY2025? | Not found in the filings. | — |
| na-008 | What was NVIDIA's closing stock price on March 15, 2024? | Not found in the filings. | — |
| na-009 | What was Merck's closing share price on December 31, 2024? | Not found in the filings. | — |
| na-010 | What revenue does Eli Lilly forecast for 2028? | Not found in the filings. | — |
