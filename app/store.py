"""
store.py — All database operations for the policy chunks.

This file manages the pgvector Postgres database:
  - init_db()          — Create the vector extension, table, and index
  - upsert_chunks()    — Delete old chunks and insert new ones
  - similarity_search()— Find the chunks most similar to a query vector
  - health_check()     — Confirm the database is reachable

The chunks table stores 3 things per chunk:
  - source    : the section name (e.g. "Section 4: Hotel Expenses")
  - text      : the actual policy text
  - embedding : 1024 numbers representing the meaning of the text
"""

import psycopg
from pgvector.psycopg import register_vector

from app.config import settings

# SQL to install the pgvector extension into Postgres (run once)
CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"

# SQL to create the chunks table that stores policy text + embeddings
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS chunks (
    id        SERIAL PRIMARY KEY,
    source    TEXT NOT NULL,          -- section name, e.g. "Section 4: Hotel Expenses"
    text      TEXT NOT NULL,          -- the actual policy text chunk
    embedding vector({dim})           -- 1024-dimensional vector from Titan Embed
)
""".format(dim=settings.embed_dim)

# SQL to create an HNSW index for fast approximate nearest-neighbour search
# vector_cosine_ops means we search by cosine similarity (angle between vectors)
CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
ON chunks USING hnsw (embedding vector_cosine_ops)
"""


def get_conn(register_vec: bool = True):
    """
    Open a connection to Postgres.

    register_vec=True  → also registers the vector type (needed for read/write)
    register_vec=False → plain connection, no vector type (used for health check
                         and the first pass of init_db before the extension exists)
    """
    conn = psycopg.connect(settings.database_url)
    if register_vec:
        register_vector(conn)
    return conn


def init_db():
    """
    Set up the database on first run. Safe to call multiple times (IF NOT EXISTS).

    Two-pass approach:
    Pass 1 — Create the pgvector extension WITHOUT registering the vector type.
             (We can't register the type before the extension exists.)
    Pass 2 — Now the extension exists, so register the vector type and create
             the table and index.
    """
    # Pass 1: install the extension (no vector type registered yet)
    with get_conn(register_vec=False) as conn:
        conn.execute(CREATE_EXTENSION)
        conn.commit()

    # Pass 2: extension is ready, now create table and index
    with get_conn() as conn:
        conn.execute(CREATE_TABLE)
        conn.execute(CREATE_INDEX)
        conn.commit()


def upsert_chunks(chunks: list[dict]):
    """
    Replace all existing chunks with a fresh set.

    Why TRUNCATE first? So re-running ingest.py gives a clean slate
    instead of duplicating chunks.

    Each chunk dict must have: source (str), text (str), embedding (list[float])
    """
    with get_conn() as conn:
        # Delete all existing rows — start fresh on every ingest
        conn.execute("TRUNCATE TABLE chunks")
        with conn.cursor() as cur:
            for c in chunks:
                cur.execute(
                    "INSERT INTO chunks (source, text, embedding) VALUES (%s, %s, %s)",
                    (c["source"], c["text"], c["embedding"]),
                )
        conn.commit()


def similarity_search(query_embedding: list[float], k: int = 4) -> list[dict]:
    """
    Find the k chunks whose embeddings are most similar to the query embedding.

    Uses cosine distance (<=> operator) — smaller distance = more similar.
    Score = 1 - cosine_distance, so higher score = better match.

    Returns a list of dicts: [{source, text, score}, ...]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, text, 1 - (embedding <=> %s::vector) AS score
                FROM chunks
                ORDER BY embedding <=> %s::vector   -- closest first
                LIMIT %s
                """,
                (query_embedding, query_embedding, k),
            )
            rows = cur.fetchall()
    return [{"source": r[0], "text": r[1], "score": float(r[2])} for r in rows]


def health_check() -> bool:
    """
    Return True if the database is reachable, False otherwise.

    Used by GET /health endpoint. Uses register_vec=False because the
    vector extension may not be installed yet (before first ingest).
    We just need to confirm Postgres itself is up.
    """
    try:
        with get_conn(register_vec=False) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False
