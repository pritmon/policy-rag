"""
ingest.py — Loads the policy document into the database (one-time setup).

Think of this as a librarian preparing a library:
  1. Read the big policy book (policy.md)
  2. Tear it into small pages (chunks) so each page covers one topic
  3. Give every page a "magic number tag" (embedding) that describes its meaning
  4. File all pages into the database (pgvector) so they can be found fast

Run it with:  make ingest
Re-run it whenever policy.md changes, or when the embedding model changes.
"""
import os
import re
import sys
import time

# Allow "from app.xxx import ..." even though this file lives in ingestion/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.llm import embed
from app.store import init_db, upsert_chunks

# Where the policy document lives
POLICY_PATH = os.path.join(os.path.dirname(__file__), "policy.md")
# How big each chunk (page) is — 900 characters ≈ one policy section
CHUNK_SIZE = 900
# Neighbouring chunks share 80 characters so no sentence gets cut in half
OVERLAP = 80


def split_by_section(text: str) -> list[dict]:
    """
    Cut the document into chunks, the smart way.

    First we cut at section headings (## 1., ## 2., ...) so each chunk
    stays about ONE topic. If a section is still too long, we cut it
    again by size, with a small overlap so nothing is lost at the edges.
    """
    # Cut wherever a line starts with "## <number>." (a section heading)
    sections = re.split(r"(?=^## \d+\.)", text, flags=re.MULTILINE)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Remember the section heading — it becomes the citation label
        # shown to users (e.g. "6. Meals and Entertainment")
        heading_match = re.match(r"^(##[^\n]+)", section)
        heading = heading_match.group(1).strip("# ").strip() if heading_match else "header"

        if len(section) <= CHUNK_SIZE:
            # Small section → keep it as one chunk
            chunks.append({"source": heading, "text": section})
        else:
            # Big section → slice it into CHUNK_SIZE pieces with overlap
            start = 0
            while start < len(section):
                end = start + CHUNK_SIZE
                chunk_text = section[start:end]
                chunks.append({"source": heading, "text": chunk_text})
                # Step forward, but leave OVERLAP characters shared
                start += CHUNK_SIZE - OVERLAP

    return chunks


def main():
    # Step 1: make sure the database table exists (creates it if missing)
    print("Initialising DB...")
    init_db()

    # Step 2: read the whole policy document into memory
    print(f"Reading {POLICY_PATH}...")
    with open(POLICY_PATH) as f:
        text = f.read()

    # Step 3: cut it into topic-sized chunks
    print("Splitting into chunks...")
    chunks = split_by_section(text)
    print(f"  {len(chunks)} chunks")

    # Step 4: get the "magic number tag" (embedding) for every chunk.
    # The small sleep keeps us under the AI provider's speed limit.
    print("Embedding...")
    for i, chunk in enumerate(chunks):
        chunk["embedding"] = embed(chunk["text"])
        print(f"  {i+1}/{len(chunks)} embedded")
        time.sleep(0.5)  # be polite — avoid rate-limit errors

    # Step 5: save everything into pgvector (old rows are replaced)
    print("Writing to pgvector...")
    upsert_chunks(chunks)
    print("Done.")


if __name__ == "__main__":
    main()
