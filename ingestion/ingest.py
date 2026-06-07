"""Read policy.md, split into chunks, embed, write to pgvector."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bedrock import embed
from app.store import init_db, upsert_chunks

POLICY_PATH = os.path.join(os.path.dirname(__file__), "policy.md")
CHUNK_SIZE = 900  # characters — ~1 section per chunk, ~10-15 chunks total
OVERLAP = 80


def split_by_section(text: str) -> list[dict]:
    """Split on level-2 headings (## N.) first, then by size."""
    sections = re.split(r"(?=^## \d+\.)", text, flags=re.MULTILINE)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Extract heading for source label
        heading_match = re.match(r"^(##[^\n]+)", section)
        heading = heading_match.group(1).strip("# ").strip() if heading_match else "header"

        # Sub-split large sections
        if len(section) <= CHUNK_SIZE:
            chunks.append({"source": heading, "text": section})
        else:
            start = 0
            while start < len(section):
                end = start + CHUNK_SIZE
                chunk_text = section[start:end]
                chunks.append({"source": heading, "text": chunk_text})
                start += CHUNK_SIZE - OVERLAP

    return chunks


def main():
    print("Initialising DB...")
    init_db()

    print(f"Reading {POLICY_PATH}...")
    with open(POLICY_PATH) as f:
        text = f.read()

    print("Splitting into chunks...")
    chunks = split_by_section(text)
    print(f"  {len(chunks)} chunks")

    print("Embedding...")
    for i, chunk in enumerate(chunks):
        chunk["embedding"] = embed(chunk["text"])
        print(f"  {i+1}/{len(chunks)} embedded")
        time.sleep(0.5)  # avoid Bedrock throttling

    print("Writing to pgvector...")
    upsert_chunks(chunks)
    print("Done.")


if __name__ == "__main__":
    main()
