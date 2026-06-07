from langfuse import Langfuse

from app.config import settings

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
    global _langfuse
    if _langfuse is None and settings.langfuse_public_key:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    return _langfuse


class Trace:
    def __init__(self, name: str, input: str):
        lf = get_langfuse()
        self._trace = lf.trace(name=name, input=input) if lf else None

    def span(self, name: str, input: dict) -> "Span":
        return Span(self._trace, name, input)

    def update(self, output: str):
        if self._trace:
            self._trace.update(output=output)


class Span:
    def __init__(self, trace, name: str, input: dict):
        self._span = trace.span(name=name, input=input) if trace else None

    def end(self, output: dict):
        if self._span:
            self._span.end(output=output)
