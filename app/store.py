import psycopg
from pgvector.psycopg import register_vector

from app.config import settings

CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding vector({dim})
)
""".format(dim=settings.embed_dim)
CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
ON chunks USING hnsw (embedding vector_cosine_ops)
"""


def get_conn(register_vec: bool = True):
    conn = psycopg.connect(settings.database_url)
    if register_vec:
        register_vector(conn)
    return conn


def init_db():
    # First pass: create extension without vector registered
    with get_conn(register_vec=False) as conn:
        conn.execute(CREATE_EXTENSION)
        conn.commit()
    # Second pass: now register vector and create table/index
    with get_conn() as conn:
        conn.execute(CREATE_TABLE)
        conn.execute(CREATE_INDEX)
        conn.commit()


def upsert_chunks(chunks: list[dict]):
    """chunks: list of {source, text, embedding}"""
    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE chunks")
        with conn.cursor() as cur:
            for c in chunks:
                cur.execute(
                    "INSERT INTO chunks (source, text, embedding) VALUES (%s, %s, %s)",
                    (c["source"], c["text"], c["embedding"]),
                )
        conn.commit()


def similarity_search(query_embedding: list[float], k: int = 4) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, text, 1 - (embedding <=> %s::vector) AS score
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, query_embedding, k),
            )
            rows = cur.fetchall()
    return [{"source": r[0], "text": r[1], "score": float(r[2])} for r in rows]


def health_check() -> bool:
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
