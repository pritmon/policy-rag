"""
guards.py — Security and safety checks for user inputs and LLM outputs.

Three types of protection:
  1. check_input()        — Block prompt injection attacks before they reach the LLM
  2. redact_pii()         — Remove emails and phone numbers from text
  3. check_groundedness() — Verify the answer is actually supported by the retrieved chunks

Why these matter:
  - Prompt injection: a user could try to hijack the LLM by saying "ignore your instructions"
  - PII: the policy document or answer might accidentally contain personal data
  - Groundedness: the LLM might hallucinate an answer not supported by the policy text
"""

import re

from app.bedrock import llm

# List of regex patterns that indicate a prompt injection attempt.
# If any of these match the user's input, we block the request immediately.
INJECTION_PATTERNS = [
    r"ignore (previous|prior|all) instructions",   # classic jailbreak opener
    r"system prompt",                               # trying to expose the system prompt
    r"disregard (your|the) (instructions|rules|guidelines)",
    r"you are now",                                 # trying to assign a new persona
    r"act as (a |an )?(different|new|another)",
    r"jailbreak",
    r"forget (your|all) (instructions|training|rules)",
    r"bypass",
    r"override (your|the) (instructions|rules|safety)",
]

# Compile all patterns into a single regex for efficiency (case-insensitive)
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# Regex to find email addresses (e.g. john@acme.com)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b")

# Regex to find US/international phone numbers (e.g. +1-800-555-1234)
PHONE_RE = re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")


def check_input(text: str) -> str | None:
    """
    Check if the user's input should be blocked.

    Returns a refusal message string if the input is invalid or suspicious.
    Returns None if the input is clean and should proceed normally.
    """
    stripped = text.strip()

    # Reject empty or very short inputs
    if not stripped or len(stripped) < 3:
        return "Please provide a valid question."

    # Reject prompt injection attempts
    if _INJECTION_RE.search(stripped):
        return "I'm unable to process that request."

    return None  # Input is clean — allow it through


def redact_pii(text: str) -> str:
    """
    Replace any email addresses or phone numbers in the text with placeholders.

    Called on the LLM's answer before returning it to the user —
    ensures no personal data leaks through even if the policy document
    or the LLM accidentally includes it.

    Example:
      "Contact john@acme.com at 555-123-4567"
      → "Contact [EMAIL REDACTED] at [PHONE REDACTED]"
    """
    text = EMAIL_RE.sub("[EMAIL REDACTED]", text)
    text = PHONE_RE.sub("[PHONE REDACTED]", text)
    return text


def check_groundedness(answer: str, chunks: list[dict]) -> bool:
    """
    Use the LLM itself to verify the answer is supported by the retrieved chunks.

    This is called LLM-as-judge — we ask Nova: "Is this answer actually
    supported by these chunks?" and expect a YES or NO.

    Returns True if grounded (answer supported by context).
    Returns False if not grounded (answer may be hallucinated).

    If the answer is not grounded, graph.py adds "ungrounded" to the flags list
    so the caller knows to treat the answer with caution.
    """
    if not chunks:
        return False  # No context at all — cannot be grounded

    # Build a combined context string from the top retrieved chunks
    context = "\n\n".join(c["text"] for c in chunks[:4])

    prompt = (
        f"Context:\n{context}\n\n"
        f"Answer:\n{answer}\n\n"
        "Is this answer fully supported by the context above? "
        "Reply with only YES or NO."
    )
    result = llm(prompt).strip().upper()
    return result.startswith("YES")
