import re

from app.bedrock import llm

INJECTION_PATTERNS = [
    r"ignore (previous|prior|all) instructions",
    r"system prompt",
    r"disregard (your|the) (instructions|rules|guidelines)",
    r"you are now",
    r"act as (a |an )?(different|new|another)",
    r"jailbreak",
    r"forget (your|all) (instructions|training|rules)",
    r"bypass",
    r"override (your|the) (instructions|rules|safety)",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b")
PHONE_RE = re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")


def check_input(text: str) -> str | None:
    """Return refusal message if input should be blocked, else None."""
    stripped = text.strip()
    if not stripped or len(stripped) < 3:
        return "Please provide a valid question."
    if _INJECTION_RE.search(stripped):
        return "I'm unable to process that request."
    return None


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[EMAIL REDACTED]", text)
    text = PHONE_RE.sub("[PHONE REDACTED]", text)
    return text


def check_groundedness(answer: str, chunks: list[dict]) -> bool:
    """Quick LLM check: is the answer supported by the retrieved chunks?"""
    if not chunks:
        return False
    context = "\n\n".join(c["text"] for c in chunks[:4])
    prompt = (
        f"Context:\n{context}\n\n"
        f"Answer:\n{answer}\n\n"
        "Is this answer fully supported by the context above? "
        "Reply with only YES or NO."
    )
    result = llm(prompt).strip().upper()
    return result.startswith("YES")
