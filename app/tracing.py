"""
tracing.py — Langfuse observability wrapper.

Langfuse records every query as a Trace with child Spans so you can see
exactly what the agent did, how long each step took, and what it returned.

Trace  = one full user query (the outer container)
Span   = one step inside that query (retriever / critic / synthesizer)

How to view traces:
  1. Sign up at cloud.langfuse.com
  2. Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to your .env
  3. Run the app and ask a question
  4. Open cloud.langfuse.com → you will see the trace appear

If no keys are set, this module does nothing — every method is a safe no-op.
The app works exactly the same, just without tracing.
"""

from langfuse import Langfuse

from app.config import settings

# Cached Langfuse client — None if keys are not configured
_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
    """
    Return the Langfuse client, creating it on first call.
    Returns None if LANGFUSE_PUBLIC_KEY is not set in .env.
    """
    global _langfuse
    if _langfuse is None and settings.langfuse_public_key:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


class Trace:
    """
    Represents one full user query in Langfuse.

    Usage:
        trace = Trace(name="policy-rag", input="What is the hotel limit?")
        span = trace.span("retriever", {"query": "..."})
        span.end({"chunks": 4})
        trace.update("The hotel limit is $250 per night.")
    """

    def __init__(self, name: str, input: str):
        lf = get_langfuse()
        # Create a real Langfuse trace, or None if tracing is disabled
        self._trace = lf.trace(name=name, input=input) if lf else None

    def span(self, name: str, input: dict) -> "Span":
        """Create a child span for one step of the pipeline."""
        return Span(self._trace, name, input)

    def update(self, output: str):
        """Record the final answer on the trace when the query is complete."""
        if self._trace:
            self._trace.update(output=output)


class Span:
    """
    Represents one step (node) inside a Trace.

    Call end() when the step is complete to record its output and duration.
    """

    def __init__(self, trace, name: str, input: dict):
        # Create a real span attached to the trace, or None if tracing is off
        self._span = trace.span(name=name, input=input) if trace else None

    def end(self, output: dict):
        """Mark this step as complete and record what it produced."""
        if self._span:
            self._span.end(output=output)
