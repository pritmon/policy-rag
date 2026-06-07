from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.bedrock import embed_query, llm
from app.config import settings
from app.guards import check_groundedness, redact_pii
from app.store import similarity_search
from app.tracing import Trace


class State(TypedDict):
    query: str
    retrieved: list[dict]
    grade: dict
    retries: int
    answer: str
    citations: list[str]
    flags: list[str]
    _trace: object  # Trace instance, not serialised


def retriever_node(state: State) -> State:
    trace: Trace = state.get("_trace")
    span = trace.span("retriever", {"query": state["query"]}) if trace else None

    vec = embed_query(state["query"])
    chunks = similarity_search(vec, k=settings.top_k)

    if span:
        span.end({"chunks": len(chunks), "top_score": chunks[0]["score"] if chunks else 0})

    return {**state, "retrieved": chunks}


def critic_node(state: State) -> State:
    trace: Trace = state.get("_trace")
    chunks_text = "\n\n".join(
        f"[Chunk {i+1} | {c['source']} | score={c['score']:.2f}]\n{c['text']}"
        for i, c in enumerate(state["retrieved"])
    )
    prompt = (
        f"Question: {state['query']}\n\n"
        f"Retrieved chunks:\n{chunks_text}\n\n"
        "Are these chunks sufficient to answer the question accurately and completely? "
        "Reply with only YES or NO."
    )
    span = (
        trace.span("critic", {"query": state["query"], "num_chunks": len(state["retrieved"])})
        if trace else None
    )
    result = llm(prompt).strip().upper()
    sufficient = result.startswith("YES")

    if span:
        span.end({"sufficient": sufficient, "retries": state["retries"]})

    grade = {"sufficient": sufficient}

    if not sufficient and state["retries"] < settings.max_retries:
        # Reformulate the query to retrieve better chunks
        rewrite_prompt = (
            f"The following question did not retrieve sufficient context:\n{state['query']}\n\n"
            "Rewrite it as a more specific search query (one sentence, no preamble)."
        )
        new_query = llm(rewrite_prompt).strip()
        return {**state, "grade": grade, "retries": state["retries"] + 1, "query": new_query}

    return {**state, "grade": grade}


def synthesizer_node(state: State) -> State:
    trace: Trace = state.get("_trace")
    span = trace.span("synthesizer", {"query": state["query"]}) if trace else None

    if not state["retrieved"]:
        answer = "I don't have enough information in the policy document to answer that question."
        return {**state, "answer": answer, "citations": [], "flags": ["no_context"]}

    chunks_text = "\n\n".join(
        f"[{i+1}] ({c['source']}) {c['text']}"
        for i, c in enumerate(state["retrieved"])
    )
    system = (
        "You are a policy assistant. Answer ONLY from the provided policy excerpts. "
        "Cite sources using [N] notation matching the excerpt numbers. "
        "If the excerpts do not contain the answer, say so — never fabricate."
    )
    prompt = (
        f"Policy excerpts:\n{chunks_text}\n\n"
        f"Question: {state['query']}\n\n"
        "Answer with inline citations [N]:"
    )
    answer = llm(prompt, system=system)

    # PII redaction
    flags: list[str] = list(state.get("flags", []))
    redacted = redact_pii(answer)
    if redacted != answer:
        flags.append("pii_redacted")
        answer = redacted

    # Groundedness check
    grounded = check_groundedness(answer, state["retrieved"])
    if not grounded:
        flags.append("ungrounded")

    citations = [c["source"] for c in state["retrieved"]]

    if span:
        span.end({"answer_len": len(answer), "flags": flags})

    return {**state, "answer": answer, "citations": citations, "flags": flags}


def should_loop(state: State) -> str:
    grade = state.get("grade", {})
    if not grade.get("sufficient") and state["retries"] < settings.max_retries:
        return "retriever"
    return "synthesizer"


def build_graph():
    g = StateGraph(State)
    g.add_node("retriever", retriever_node)
    g.add_node("critic", critic_node)
    g.add_node("synthesizer", synthesizer_node)

    g.set_entry_point("retriever")
    g.add_edge("retriever", "critic")
    g.add_conditional_edges(
        "critic", should_loop, {"retriever": "retriever", "synthesizer": "synthesizer"}
    )
    g.add_edge("synthesizer", END)

    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_query(question: str) -> dict:
    trace = Trace(name="policy-rag", input=question)
    initial: State = {
        "query": question,
        "retrieved": [],
        "grade": {},
        "retries": 0,
        "answer": "",
        "citations": [],
        "flags": [],
        "_trace": trace,
    }
    result = get_graph().invoke(initial)
    trace.update(result["answer"])
    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "flags": result["flags"],
    }
