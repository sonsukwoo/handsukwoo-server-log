import hashlib
import uuid
import json
import logging
import os
from datetime import datetime, timezone

import requests
from openai import OpenAI

from sqlalchemy import text

from src.database.connection import engine


logger = logging.getLogger("SCHEMA_EMBED")


QDRANT_URL = os.getenv("QDRANT_URL", "http://192.168.219.100:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "table_index")

SCHEMA_NAMESPACES = ("ops_metrics", "ops_events", "ops_runtime")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def _qdrant_headers():
    headers = {"Content-Type": "application/json"}
    if QDRANT_API_KEY:
        headers["api-key"] = QDRANT_API_KEY
    return headers


def _ensure_meta_table(conn):
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ops_runtime.schema_meta (
                id INTEGER PRIMARY KEY,
                schema_hash TEXT,
                updated_at TIMESTAMPTZ,
                note TEXT
            );
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO ops_runtime.schema_meta (id, schema_hash, updated_at, note)
            VALUES (1, NULL, NULL, NULL)
            ON CONFLICT (id) DO NOTHING;
            """
        )
    )


def _get_stored_hash(conn):
    res = conn.execute(
        text("SELECT schema_hash FROM ops_runtime.schema_meta WHERE id = 1;")
    ).fetchone()
    return res[0] if res else None


def _set_stored_hash(conn, schema_hash):
    conn.execute(
        text(
            """
            UPDATE ops_runtime.schema_meta
            SET schema_hash = :schema_hash,
                updated_at = :updated_at
            WHERE id = 1;
            """
        ),
        {"schema_hash": schema_hash, "updated_at": datetime.now(timezone.utc)},
    )


def _fetch_schema_rows(conn):
    tables = conn.execute(
        text(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   c.relkind AS relkind,
                   d.description AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE c.relkind IN ('r','v')
              AND n.nspname = ANY(:schemas)
            ORDER BY 1,2;
            """
        ),
        {"schemas": list(SCHEMA_NAMESPACES)},
    ).fetchall()

    columns = conn.execute(
        text(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   c.relkind AS relkind,
                   a.attname AS column_name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   d.description AS column_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum
            WHERE c.relkind IN ('r','v')
              AND n.nspname = ANY(:schemas)
            ORDER BY 1,2,4;
            """
        ),
        {"schemas": list(SCHEMA_NAMESPACES)},
    ).fetchall()

    return tables, columns


def _build_schema_docs(tables, columns):
    docs = []
    col_map = {}
    for row in columns:
        key = (row.schema_name, row.table_name, row.relkind)
        col_map.setdefault(key, []).append(
            {
                "name": row.column_name,
                "type": row.data_type,
                "description": row.column_comment or "",
                "role": _infer_role(row.column_name),
                "category": _infer_category(row.column_name),
                "visible_to_llm": True,
            }
        )

    for row in tables:
        key = (row.schema_name, row.table_name, row.relkind)
        docs.append(
            {
                "doc_type": "view" if row.relkind == "v" else "table",
                "schema": row.schema_name,
                "table_name": row.table_name,
                "description": row.table_comment or "",
                "primary_time_col": _infer_primary_time(col_map.get(key, [])),
                "join_keys": _infer_join_keys(row.table_name),
                "columns": col_map.get(key, []),
                "source": "db_schema",
            }
        )
    return docs


def _infer_role(column_name):
    name = column_name.lower()
    if name in {"ts", "time", "timestamp", "created_at"}:
        return "time"
    if name.endswith("_id") or name in {"id", "name"}:
        return "dimension"
    if name.endswith("_pct") or name.endswith("_percent") or name.endswith("_rate_bps"):
        return "metric"
    if any(token in name for token in ("used", "total", "free", "count", "percent", "rate")):
        return "metric"
    return "dimension"


def _infer_category(column_name):
    name = column_name.lower()
    if "cpu" in name:
        return "cpu"
    if "mem" in name or "ram" in name or "swap" in name:
        return "memory"
    if "disk" in name or "mount" in name:
        return "disk"
    if "rx" in name or "tx" in name or "network" in name or "interface" in name:
        return "network"
    if "docker" in name or "container" in name:
        return "docker"
    if "tmux" in name or "session" in name:
        return "runtime"
    return "general"


def _infer_primary_time(columns):
    for col in columns:
        if col["name"] == "ts":
            return "ts"
    for col in columns:
        if col["role"] == "time":
            return col["name"]
    return None


def _infer_join_keys(table_name):
    if table_name in {"metrics_disk"}:
        return ["ts", "mount"]
    if table_name in {"metrics_network"}:
        return ["ts", "interface"]
    if table_name in {"docker_metrics"}:
        return ["ts", "container_id"]
    return ["ts"]


def _schema_hash(docs):
    payload = []
    for doc in docs:
        payload.append(
            {
                "doc_type": doc["doc_type"],
                "schema": doc["schema"],
                "table_name": doc["table_name"],
                "description": doc["description"],
                "columns": [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "description": c["description"],
                    }
                    for c in doc["columns"]
                ],
            }
        )
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _embed_texts(texts):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않아 임베딩을 생성할 수 없습니다.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        encoding_format="float",
    )
    return [item.embedding for item in resp.data]


def _ensure_collection(vector_size):
    url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}"
    res = requests.get(url, headers=_qdrant_headers(), timeout=10)
    if res.status_code == 200:
        info = res.json()
        try:
            existing_size = info["result"]["config"]["params"]["vectors"]["size"]
        except (KeyError, TypeError):
            existing_size = None
        if existing_size == vector_size:
            return
        # Recreate collection if vector size mismatch
        del_res = requests.delete(url, headers=_qdrant_headers(), timeout=10)
        del_res.raise_for_status()
    payload = {
        "vectors": {"size": vector_size, "distance": "Cosine"},
    }
    res = requests.put(url, headers=_qdrant_headers(), json=payload, timeout=10)
    res.raise_for_status()


def _delete_existing_points():
    url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/delete?wait=true"
    payload = {"filter": {"must": [{"key": "source", "match": {"value": "db_schema"}}]}}
    res = requests.post(url, headers=_qdrant_headers(), json=payload, timeout=30)
    if res.status_code >= 400:
        raise RuntimeError(f"Qdrant delete failed: {res.status_code} {res.text}")


def _upsert_points(vectors, docs):
    url = f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true"
    points = []
    for doc, vector in zip(docs, vectors):
        point_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{doc['schema']}.{doc['table_name']}:{doc['doc_type']}",
            )
        )
        points.append({"id": point_id, "vector": vector, "payload": doc})
    res = requests.put(url, headers=_qdrant_headers(), json={"points": points}, timeout=60)
    if res.status_code >= 400:
        raise RuntimeError(f"Qdrant upsert failed: {res.status_code} {res.text}")


def sync_schema_embeddings(force=False):
    if not QDRANT_API_KEY:
        logger.warning("QDRANT_API_KEY가 설정되지 않아 스키마 임베딩 업로드를 건너뜁니다.")
        return False
    try:
        with engine.begin() as conn:
            _ensure_meta_table(conn)
            tables, columns = _fetch_schema_rows(conn)
            docs = _build_schema_docs(tables, columns)
            schema_hash = _schema_hash(docs)
            stored_hash = _get_stored_hash(conn)

            if not force and stored_hash == schema_hash:
                logger.info("스키마 변경 없음: 임베딩 업로드 스킵")
                return False

            texts = []
            for doc in docs:
                columns_text = "\n".join(
                    f"- {c['name']} ({c['type']}): {c['description']}".strip()
                    for c in doc["columns"]
                )
                texts.append(
                    f"{doc['schema']}.{doc['table_name']} ({doc['doc_type']})\n"
                    f"{doc['description']}\n"
                    f"Columns:\n{columns_text}"
                )

            vectors = _embed_texts(texts)
            _ensure_collection(len(vectors[0]))
            _delete_existing_points()
            _upsert_points(vectors, docs)
            _set_stored_hash(conn, schema_hash)

        logger.info("스키마 임베딩 업로드 완료")
        return True
    except Exception as e:
        logger.error(f"스키마 임베딩 업로드 실패: {e}")
        return False
