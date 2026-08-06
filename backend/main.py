import re
import uuid

import duckdb
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Astrolabio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

con = duckdb.connect(database=":memory:")

TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def safe_ident(name: str) -> str:
    if not TABLE_NAME_RE.match(name):
        raise HTTPException(400, f"Nombre inválido: {name}")
    return name


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    raw_name = file.filename.rsplit(".", 1)[0]
    table_name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).lower()
    if not table_name or not table_name[0].isalpha():
        table_name = f"t_{table_name}"
    table_name = safe_ident(table_name)

    contents = await file.read()
    import io

    if file.filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents))

    df.columns = [re.sub(r"[^a-zA-Z0-9_]", "_", str(c)).lower() for c in df.columns]

    con.register("tmp_df", df)
    con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM tmp_df')
    con.unregister("tmp_df")

    return {
        "table": table_name,
        "rows": len(df),
        "columns": list(df.columns),
    }


@app.get("/api/tables")
def list_tables():
    tables = con.execute("SHOW TABLES").fetchall()
    result = []
    for (name,) in tables:
        cols = con.execute(f'DESCRIBE "{name}"').fetchall()
        count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        result.append(
            {
                "table": name,
                "rows": count,
                "columns": [{"name": c[0], "type": c[1]} for c in cols],
            }
        )
    return result


AGG_FUNCS = {"sum", "avg", "count", "min", "max", "count_distinct"}


class QuerySpec(BaseModel):
    table: str
    dimensions: list[str] = []
    metrics: list[dict] = []  # [{"column": "monto", "agg": "sum", "alias": "total"}]
    filters: list[dict] = []  # [{"column": "region", "op": "=", "value": "Norte"}]
    limit: int = 1000


OP_MAP = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "contiene": "ILIKE",
}


@app.post("/api/query")
def run_query(spec: QuerySpec):
    table = safe_ident(spec.table)

    select_parts = []
    group_parts = []
    for dim in spec.dimensions:
        col = safe_ident(dim)
        select_parts.append(f'"{col}"')
        group_parts.append(f'"{col}"')

    for m in spec.metrics:
        col = safe_ident(m["column"])
        agg = m.get("agg", "sum").lower()
        if agg not in AGG_FUNCS:
            raise HTTPException(400, f"Agregación no soportada: {agg}")
        alias = re.sub(r"[^a-zA-Z0-9_]", "_", m.get("alias") or f"{agg}_{col}")
        if agg == "count_distinct":
            select_parts.append(f'COUNT(DISTINCT "{col}") AS "{alias}"')
        else:
            select_parts.append(f'{agg.upper()}("{col}") AS "{alias}"')

    if not select_parts:
        select_parts.append("*")

    where_clauses = []
    params = []
    for f in spec.filters:
        col = safe_ident(f["column"])
        op = OP_MAP.get(f.get("op", "="))
        if op is None:
            raise HTTPException(400, f"Operador no soportado: {f.get('op')}")
        value = f.get("value")
        if op == "ILIKE":
            where_clauses.append(f'"{col}" ILIKE ?')
            params.append(f"%{value}%")
        else:
            where_clauses.append(f'"{col}" {op} ?')
            params.append(value)

    sql = f'SELECT {", ".join(select_parts)} FROM "{table}"'
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
    sql += f" LIMIT {int(spec.limit)}"

    try:
        result = con.execute(sql, params).fetchdf()
    except Exception as e:
        raise HTTPException(400, str(e))

    return {
        "sql": sql,
        "columns": list(result.columns),
        "rows": result.to_dict(orient="records"),
    }
