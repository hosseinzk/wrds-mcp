# WRDS Research for Claude

Ask Claude in plain English whether data exists on WRDS, and have it pull it for you.

> *"Do we have P&L data for European companies 2004–2022 by country and industry? If so, export it."*

Claude searches the WRDS catalog, tells you what's available (source, firms, years, countries),
then queries or exports the data — with the
[WRDS AI policy](https://wrds-www.wharton.upenn.edu/pages/about/ai-policy-on-chatgpt-and-other-generative-ai-tools/) enforced.

Not affiliated with WRDS or the Wharton School. You need your own WRDS account; you only see the
libraries your institution subscribes to.

## Before you start: the WRDS AI policy

- Row-level data may only be sent to a **protected** AI tool (vendor contractually doesn't train on it).
  Check that your Claude plan qualifies (Team / Enterprise / API usually do; ask your WRDS representative if unsure).
- Only these sources are AI-allowed: **CRSP, S&P (Compustat, Capital IQ), LSEG (Worldscope, Datastream, I/B/E/S),
  MSCI, Audit Analytics, Revelio, WRDS-created data**.
- For every other library the server returns metadata and counts only; exports are saved to disk without a preview.

## Install

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS, or see the uv docs).

**1. Save your WRDS login** (once, in a terminal — the password is typed there, never into Claude):

```bash
uvx --from git+https://github.com/hosseinzk/wrds-mcp wrds-mcp-setup
```

It asks for your WRDS username and password, tests the connection (approve the Duo push if one
arrives) and saves them to `~/.pgpass` (Windows: `%APPDATA%\postgresql\pgpass.conf`).

**2a. Claude Code** — install the plugin (MCP server + a research skill):

```
/plugin marketplace add hosseinzk/wrds-mcp
/plugin install wrds@wrds-tools
```

Restart Claude Code, then ask *"Which WRDS databases do I have access to?"*

**2b. Claude Desktop / other MCP clients** — install the server and add it to your MCP config
(Claude Desktop: Settings → Developer → Edit config):

```bash
uv tool install git+https://github.com/hosseinzk/wrds-mcp
```

```json
{ "mcpServers": { "wrds": { "command": "wrds-mcp" } } }
```

Exports and the query log go to `~/wrds-data` (set `WRDS_OUTPUT_DIR` to change it).

## Tools

| Tool | What it does |
|---|---|
| `list_libraries` | Libraries your account can access, vendor, AI-allowed flag, sample/trial flag |
| `search_catalog` | Search table/column names and descriptions across all libraries |
| `list_tables`, `describe_table` | Tables, approximate row counts, columns and descriptions |
| `check_availability` | Single-row counts / year ranges on any library (numbers only for non-AI-allowed ones) |
| `query` | Read-only SELECT, up to 500 rows, AI-allowed sources only |
| `export_query` | Full result to CSV / Parquet / Excel in your output folder |

Every query is logged to `<output folder>/logs/queries.log`. Connections are read-only.

## Examples

- "Which databases do I have access to? Which are full and which are just samples?"
- "Is quarterly R&D spending available for Tesla 2015–2024?"
- "Export annual revenue, EBIT and net income for all German and French listed firms 2010–2022, with GICS sector."
- "Median EBITDA margin by country and GICS sector for Europe, 2004–2022, in EUR."
