---
name: wrds-research
description: Find, check and extract data from WRDS (Wharton Research Data Services) — Compustat, CRSP, Capital IQ, Worldscope/Datastream, I/B/E/S, Orbis, Audit Analytics, etc. Use whenever the user asks whether some company/financial/market data exists, or wants firm-level or aggregated data pulled from WRDS.
---

# WRDS research

Tools come from the `wrds` MCP server. Always work in this order.

## 1. Find it (metadata only, always allowed)
- `list_libraries(contains=...)` — what this account can access. `sample_or_trial=true` libraries
  (names with samp/smp/trial) hold only a handful of firms: never present them as full coverage.
- `search_catalog(keyword)` — search table/column names and descriptions (e.g. `revt`, `sales`, `nace`, `sic`, `loc`).
- `list_tables(library)`, `describe_table(library, table)` — structure and column meanings.

## 2. Say whether it's available
Use `check_availability` with a single-row aggregate: row count, distinct firms, min/max year,
filtered to what the user asked for. Report to the user **before** pulling data:
source, table, coverage (firms, years, countries), missing pieces, and whether it's AI-allowed.

## 3. Extract
- `query(sql, limit)` for small results / aggregates you analyse in chat (AI-allowed sources only).
- `export_query(sql, filename, fmt)` for full datasets (csv/parquet/xlsx) saved to the output folder.
  For non-AI-allowed sources the file is saved without a preview: tell the user to analyse it
  locally, and do not read the file yourself.
- Always schema-qualify tables (`comp.g_funda`); unqualified names fail by design.

## WRDS AI policy (enforced by the server, respect it in spirit)
Row-level data may reach the model only from CRSP, S&P (Compustat, Capital IQ, SNL), LSEG
(Worldscope, Datastream, I/B/E/S, DealScan), MSCI, Audit Analytics, Revelio and WRDS-created data,
and only on a protected (no-training) AI plan. Everything else (e.g. Orbis/BvD, TRACE, FactSet
libraries) is metadata and counts only. Never try to work around a block.

## Key knowledge
**Compustat North America** `comp.funda` / **Global** `comp.g_funda` (annual), `comp.fundq` / `comp.g_fundq` (quarterly), company info `comp.company` / `comp.g_company`.
- Standard filters — NA: `indfmt='INDL' and datafmt='STD' and popsrc='D' and consol='C'`;
  Global: `indfmt='INDL' and datafmt='HIST_STD' and popsrc='I' and consol='C'`.
- Keys: `gvkey`, `datadate`, `fyear`. Country: `loc` (HQ) / `fic` (incorporation), ISO-3 codes.
- Industry: `sic`, `naics`, GICS `gsector`/`ggroup`/`gind`/`gsubind` (in company tables).
- Currency: `curcd` — Global values are in local currency; convert (e.g. `comp.g_exrt_mth` or ECB rates) before aggregating across countries.
- Income statement: `revt` revenue, `sale` net sales, `cogs`, `xsga` SG&A, `oibdp` EBITDA, `dp` D&A,
  `oiadp` EBIT, `xint` interest, `pi` pre-tax income, `txt` tax, `ib` income before extraordinary items,
  net income = `ni` in NA but `nicon` in Global. Verify column names with `describe_table` before querying.

**CRSP** `crsp.msf`/`crsp.dsf` (monthly/daily stock), key `permno`. Link to Compustat via `crsp.ccmxpf_lnkhist`
(`linktype in ('LU','LC')`, `linkprim in ('P','C')`, date-bounded by `linkdt`/`linkenddt`).

**Europe caveats**: EU listed firms moved to IFRS in 2005 (2004 not fully comparable);
Compustat/Worldscope cover listed firms only — private firms need Orbis/Amadeus (BvD), which is not AI-allowed.

## Output
Lead with the answer (available? where? how much?), then the table or file path.
Large pulls: filter server-side and aggregate in SQL rather than exporting millions of rows.
