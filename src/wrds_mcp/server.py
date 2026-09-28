"""WRDS MCP server: catalog search, availability checks, and policy-guarded queries.

Credentials come from the PostgreSQL password file written by `wrds-mcp-setup`, or from
the WRDS_USERNAME / WRDS_PASSWORD environment variables. Data rows
are only returned to the model for vendors the WRDS AI policy allows with protected AI
tools; everything else is metadata-only, or exported to a local file without a preview.
"""

import datetime as dt
import json
import os
import re
from pathlib import Path

import pandas as pd
import psycopg2
from mcp.server.mcpserver import MCPServer

from wrds_mcp.setup import HOST, PORT, DB, pgpass_path

OUTPUT_DIR = Path(os.environ.get("WRDS_OUTPUT_DIR") or "~/wrds-data").expanduser()
DATA_DIR = OUTPUT_DIR
LOG_FILE = OUTPUT_DIR / "logs" / "queries.log"

# WRDS AI policy: CRSP, S&P, LSEG, MSCI, Audit Analytics, Revelio, WRDS-created data.
# Matched on library-name prefix; anything not listed is metadata-only.
AI_ALLOWED_PREFIXES = {
    "crsp": "CRSP",
    "comp": "S&P (Compustat)",
    "ciq": "S&P (Capital IQ)",
    "snl": "S&P (Market Intelligence)",
    "tr": "LSEG (Refinitiv/Thomson)",
    "lseg": "LSEG",
    "msci": "MSCI",
    "audit": "Audit Analytics",
    "revelio": "Revelio",
    "revsamp": "Revelio",
    "wrdsapps": "WRDS-created",
    "wrdssec": "WRDS-created",
}
# Prefix collisions that are NOT allowed vendors (e.g. TRACE is FINRA, not LSEG).
AI_DENIED_PREFIXES = ("trace",)
MAX_ROWS = 500

mcp = MCPServer(
    "wrds",
    instructions=(
        "WRDS research data. Workflow: list_libraries / search_catalog / describe_table to find data, "
        "check_availability to report coverage (firms, years) to the user before pulling, then query "
        "(small results) or export_query (full datasets). Libraries with samp/smp/trial in the name are "
        "tiny samples. Row-level data is only returned for WRDS-AI-policy-allowed vendors; never work "
        "around a block. Always schema-qualify tables, e.g. comp.g_funda."
    ),
)
_conn = None


def wrds_username():
    if os.environ.get("WRDS_USERNAME"):
        return os.environ["WRDS_USERNAME"]
    path = pgpass_path()
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split(":")
            if parts[0] == HOST and len(parts) >= 4:
                return parts[3]
    raise RuntimeError("No WRDS username: set it in the plugin config or run `wrds-mcp-setup`.")


def conn():
    global _conn
    if _conn is None or _conn.closed:
        kwargs = {"password": os.environ["WRDS_PASSWORD"]} if os.environ.get("WRDS_PASSWORD") else {}
        _conn = psycopg2.connect(
            host=HOST, port=PORT, dbname=DB, user=wrds_username(),
            sslmode="require", connect_timeout=60, **kwargs,
        )
        _conn.set_session(readonly=True, autocommit=True)
        with _conn.cursor() as cur:
            cur.execute("SET statement_timeout = '300s'")
            # Force schema-qualified names so the policy check sees every library used.
            cur.execute("SET search_path = pg_catalog")
    return _conn


def fetch(sql, params=None):
    try:
        with conn().cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    except psycopg2.OperationalError:
        global _conn
        _conn = None
        raise
    except psycopg2.Error as e:
        raise ValueError(f"SQL error: {str(e).strip()}") from None


def log(kind, detail):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps({"t": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, **detail}) + "\n")


def vendor(lib):
    if lib.lower().startswith(AI_DENIED_PREFIXES):
        return None
    for prefix, name in AI_ALLOWED_PREFIXES.items():
        if lib.lower().startswith(prefix):
            return name
    return None


# Same access rule as the official `wrds` package: schemas with USAGE that hold real tables,
# or only views that point at tables in such schemas.
LIBRARIES_SQL = """
WITH pgobjs AS (
    SELECT oid, relnamespace, relkind FROM pg_class
    WHERE relkind = ANY (ARRAY['r'::"char", 'v'::"char", 'f'::"char", 'p'::"char"])
),
schemas AS (
    SELECT nspname AS schemaname, pg_namespace.oid, array_agg(DISTINCT relkind) AS relkind_a
    FROM pg_namespace JOIN pgobjs ON pg_namespace.oid = relnamespace
    WHERE nspname !~ '(^pg_)|(_old$)|(_new$)|(information_schema)'
        AND has_schema_privilege(nspname, 'USAGE') = TRUE
    GROUP BY nspname, pg_namespace.oid
)
SELECT schemaname FROM schemas WHERE relkind_a != ARRAY['v'::"char"]
UNION
SELECT nv.schemaname
FROM schemas nv
JOIN pgobjs v ON nv.oid = v.relnamespace AND v.relkind = 'v'::"char"
JOIN pg_depend dv ON v.oid = dv.refobjid AND dv.refclassid = 'pg_class'::regclass::oid
    AND dv.classid = 'pg_rewrite'::regclass::oid AND dv.deptype = 'i'::"char"
JOIN pg_depend dt ON dv.objid = dt.objid AND dv.refobjid <> dt.refobjid
    AND dt.classid = 'pg_rewrite'::regclass::oid AND dt.refclassid = 'pg_class'::regclass::oid
JOIN pgobjs t ON dt.refobjid = t.oid
JOIN schemas nt ON t.relnamespace = nt.oid
GROUP BY nv.schemaname
ORDER BY 1
"""
_libs_cache = None


def accessible_libraries():
    global _libs_cache
    if _libs_cache is None:
        _libs_cache = fetch(LIBRARIES_SQL).schemaname.tolist()
    return _libs_cache


def referenced_libraries(sql):
    libs = set(accessible_libraries())
    return {m.lower() for m in re.findall(r"\b([A-Za-z_][\w]*)\s*\.\s*[A-Za-z_\"]", sql) if m.lower() in libs}


def check_select(sql):
    s = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.S | re.M).strip().rstrip(";")
    if ";" in s:
        raise ValueError("Only a single statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", s, re.I):
        raise ValueError("Only SELECT / WITH queries are allowed.")
    return s


def to_text(df):
    return df.to_csv(index=False) if len(df) else "(no rows)"


@mcp.tool()
def list_libraries(contains: str = "") -> str:
    """List WRDS libraries this account can access, with the vendor and whether data rows
    may be returned to the AI under the WRDS AI policy. Optional substring filter."""
    rows = [
        {"library": l, "ai_data_allowed": bool(vendor(l)), "vendor": vendor(l) or "",
         "sample_or_trial": bool(re.search(r"samp|smp|trial|sample", l))}
        for l in accessible_libraries() if contains.lower() in l.lower()
    ]
    return to_text(pd.DataFrame(rows))


@mcp.tool()
def list_tables(library: str) -> str:
    """List tables in a WRDS library with approximate row counts."""
    df = fetch(
        "SELECT c.relname AS table, NULLIF(c.reltuples, -1)::bigint AS approx_rows "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relkind IN ('r','v','m','p','f') ORDER BY 1",
        (library.lower(),),
    )
    return to_text(df)


@mcp.tool()
def describe_table(library: str, table: str) -> str:
    """Show columns, types and WRDS column descriptions (where available) for a table."""
    df = fetch(
        "SELECT a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type, "
        "col_description(c.oid, a.attnum) AS description "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum",
        (library.lower(), table.lower()),
    )
    return to_text(df)


@mcp.tool()
def search_catalog(keyword: str, library_contains: str = "", max_results: int = 200) -> str:
    """Search table names, column names and column descriptions across all accessible
    libraries for a keyword (e.g. 'revenue', 'nace', 'sic', 'orbis'). Use this first to
    answer 'is X available?' questions."""
    libs = [l for l in accessible_libraries() if library_contains.lower() in l.lower()]
    df = fetch(
        "SELECT n.nspname AS library, c.relname AS table, a.attname AS column, "
        "col_description(c.oid, a.attnum) AS description "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','v','m','p','f') "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "AND (c.relname ILIKE %s OR a.attname ILIKE %s OR col_description(c.oid, a.attnum) ILIKE %s) "
        "ORDER BY 1, 2, 3 LIMIT %s",
        (libs, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", max_results),
    )
    if len(df):
        df.insert(1, "ai_data_allowed", df.library.map(lambda l: bool(vendor(l))))
    return to_text(df)


@mcp.tool()
def check_availability(sql: str) -> str:
    """Run an aggregate-only availability check (counts, distinct counts, min/max years)
    on any accessible library, including ones where row-level data is not AI-allowed.
    The query must return a single summary row, e.g.
    SELECT count(*), count(distinct gvkey), min(fyear), max(fyear) FROM comp.g_funda WHERE ..."""
    s = check_select(sql)
    df = fetch(f"SELECT * FROM ({s}) q LIMIT 2")
    if len(df) > 1:
        return "Rejected: availability checks must return a single summary row. Use GROUP BY only via query() on AI-allowed sources."
    blocked = [l for l in referenced_libraries(s) if not vendor(l)]
    non_numeric = [c for i, c in enumerate(df.columns) if df.iloc[:, i].map(lambda v: isinstance(v, str)).any()]
    if blocked and non_numeric:
        return f"Rejected: for non-AI-allowed sources ({', '.join(blocked)}) availability checks may only return numbers (counts, min/max years)."
    log("availability", {"sql": s})
    return to_text(df)


@mcp.tool()
def query(sql: str, limit: int = 200) -> str:
    """Run a read-only SELECT and return up to `limit` rows (max 500) as CSV. Only
    allowed when every referenced library is AI-allowed under the WRDS policy."""
    s = check_select(sql)
    libs = referenced_libraries(s)
    blocked = sorted(l for l in libs if not vendor(l))
    if blocked:
        return (f"Blocked by WRDS AI policy: {', '.join(blocked)} is not an AI-allowed vendor. "
                "Use check_availability for counts, or export_query to save the data locally without preview.")
    df = fetch(f"SELECT * FROM ({s}) q LIMIT {min(max(limit, 1), MAX_ROWS)}")
    log("query", {"sql": s, "rows": len(df), "libraries": sorted(libs)})
    return to_text(df)


@mcp.tool()
def export_query(sql: str, filename: str, fmt: str = "csv") -> str:
    """Run a read-only SELECT with no row limit and save it to the output folder (default ~/wrds-data).
    fmt: csv, parquet or xlsx. Returns the path, row count and columns; a 5-row preview
    is included only for AI-allowed sources."""
    s = check_select(sql)
    libs = referenced_libraries(s)
    allowed = all(vendor(l) for l in libs)
    if fmt not in {"csv", "parquet", "xlsx"}:
        return "fmt must be csv, parquet or xlsx."
    df = fetch(s)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{Path(filename).stem}.{fmt}"
    {"csv": df.to_csv, "parquet": df.to_parquet, "xlsx": df.to_excel}[fmt](path, index=False)
    log("export", {"sql": s, "rows": len(df), "path": str(path), "libraries": sorted(libs)})
    out = f"Saved {len(df):,} rows x {len(df.columns)} cols to {path}\nColumns: {', '.join(df.columns)}\n"
    if allowed:
        out += "\nPreview:\n" + to_text(df.head(5))
    else:
        out += "\nNo preview: source is not AI-allowed under the WRDS policy; process this file locally."
    return out


def main():
    mcp.run()


if __name__ == "__main__":
    main()
