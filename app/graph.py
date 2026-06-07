"""
graph.py — The LangGraph self-correction loop (the brain of the agent).

This file defines and runs the 3-node pipeline:

  [retriever] → [critic] → [synthesizer]
       ↑              |
       └──────────────┘  (loop back if context is not sufficient)

Node responsibilities:
  retriever   — embed the query and find similar chunks from pgvector
  critic      — ask the LLM "are these chunks good enough to answer?"
  synthesizer — write the final cited answer using the retrieved chunks

The loop:
  - If the critic says NO (not sufficient) AND retries < max_retries:
      rewrite the query to be more specific, then go back to retriever
  - If the critic says YES, or retries are exhausted:
      go to synthesizer and write the answer

State flows through all nodes as a single dict (TypedDict).
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.bedrock import embed_query, llm
from app.config import settings
from app.guards import check_groundedness, redact_pii
from app.store import similarity_search
from app.tracing import Trace


class State(TypedDict):
    """
    The shared state passed between all nodes in the graph.
    Each node receives the full state and returns an updated copy.
    """
    query: str           # the user's current question (may be rewritten by critic)
    retrieved: list[dict]  # chunks found by the retriever [{source, text, score}]
    grade: dict          # critic's verdict e.g. {"sufficient": True}
    retries: int         # how many times the loop has retried so far
    answer: str          # the final answer written by the synthesizer
    citations: list[str] # list of section names cited in the answer
    flags: list[str]     # warning flags e.g. ["ungrounded", "pii_redacted"]
    _trace: object       # Langfuse Trace instance (not serialised, internal only)


def retriever_node(state: State) -> State:
    """
    Node 1 — Retriever.

    Converts the query into a vector using Titan Embed, then searches
    pgvector for the top-K most similar policy chunks.

    Returns the state with 'retrieved' filled in.
    """
    trace: Trace = state.get("_trace")
    span = trace.span("retriever", {"query": state["query"]}) if trace else None

    # Step 1: embed the query into a 1024-dim vector
    vec = embed_query(state["query"])

    # Step 2: find the most similar chunks in pgvector
    chunks = similarity_search(vec, k=settings.top_k)

    if span:
        span.end({
            "chunks": len(chunks),
            "top_score": chunks[0]["score"] if chunks else 0,
        })

    return {**state, "retrieved": chunks}


def critic_node(state: State) -> State:
    """
    Node 2 — Critic.

    Shows the retrieved chunks to the LLM and asks: "Are these good enough
    to answer the question?" Expects a YES or NO response.

    If NO and retries are available:
      - Asks the LLM to rewrite the query to be more specific
      - Increments the retry counter
      - Returns updated state so should_loop() sends us back to retriever

    If YES (or retries exhausted):
      - Returns state unchanged so should_loop() proceeds to synthesizer
    """
    trace: Trace = state.get("_trace")

    # Format the retrieved chunks for the LLM to read
    chunks_text = "\n\n".join(
        f"[Chunk {i+1} | {c['source']} | score={c['score']:.2f}]\n{c['text']}"
        for i, c in enumerate(state["retrieved"])
    )

    # Ask the LLM: are these chunks sufficient?
    prompt = (
        f"Question: {state['query']}\n\n"
        f"Retrieved chunks:\n{chunks_text}\n\n"
        "Are these chunks sufficient to answer the question accurately and completely? "
        "Reply with only YES or NO."
    )
    span = (
        trace.span("critic", {
            "query": state["query"],
            "num_chunks": len(state["retrieved"]),
        })
        if trace else None
    )
    result = llm(prompt).strip().upper()
    sufficient = result.startswith("YES")

    if span:
        span.end({"sufficient": sufficient, "retries": state["retries"]})

    grade = {"sufficient": sufficient}

    # If not sufficient and we still have retries left — rewrite the query
    if not sufficient and state["retries"] < settings.max_retries:
        rewrite_prompt = (
            f"The following question did not retrieve sufficient context:\n{state['query']}\n\n"
            "Rewrite it as a more specific search query (one sentence, no preamble)."
        )
        new_query = llm(rewrite_prompt).strip()
        # Return with incremented retries and new query — should_loop() will
        # send us back to the retriever node
        return {
            **state,
            "grade": grade,
            "retries": state["retries"] + 1,
            "query": new_query,
        }

    return {**state, "grade": grade}


def synthesizer_node(state: State) -> State:
    """
    Node 3 — Synthesizer.

    Uses the retrieved chunks to write a final, cited answer.
    Also runs PII redaction and groundedness check on the answer before returning.

    Returns the state with 'answer', 'citations', and 'flags' filled in.
    """
    trace: Trace = state.get("_trace")
    span = trace.span("synthesizer", {"query": state["query"]}) if trace else None

    # Edge case: no chunks were retrieved at all
    if not state["retrieved"]:
        answer = "I don't have enough information in the policy document to answer that question."
        return {**state, "answer": answer, "citations": [], "flags": ["no_context"]}

    # Format the chunks for the LLM with numbered references [1], [2], etc.
    chunks_text = "\n\n".join(
        f"[{i+1}] ({c['source']}) {c['text']}"
        for i, c in enumerate(state["retrieved"])
    )

    # System prompt: strict instruction to only answer from the given excerpts
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

    # Safety: redact any PII that may have appeared in the answer
    flags: list[str] = list(state.get("flags", []))
    redacted = redact_pii(answer)
    if redacted != answer:
        flags.append("pii_redacted")
        answer = redacted

    # Safety: verify the answer is actually grounded in the retrieved chunks
    grounded = check_groundedness(answer, state["retrieved"])
    if not grounded:
        flags.append("ungrounded")  # warn the caller but still return the answer

    # Citations = the section names of all retrieved chunks
    citations = [c["source"] for c in state["retrieved"]]

    if span:
        span.end({"answer_len": len(answer), "flags": flags})

    return {**state, "answer": answer, "citations": citations, "flags": flags}


def should_loop(state: State) -> str:
    """
    Conditional edge — decides what happens after the critic node.

    Returns "retriever" → go back and try again (critic said NO, retries left)
    Returns "synthesizer" → write the answer (critic said YES, or retries exhausted)
    """
    grade = state.get("grade", {})
    if not grade.get("sufficient") and state["retries"] < settings.max_retries:
        return "retriever"
    return "synthesizer"


def build_graph():
    """
    Assemble the LangGraph StateGraph with 3 nodes and the conditional loop edge.

    Graph structure:
      START → retriever → critic → (should_loop) → retriever (loop) OR synthesizer → END
    """
    g = StateGraph(State)

    # Register the 3 nodes
    g.add_node("retriever", retriever_node)
    g.add_node("critic", critic_node)
    g.add_node("synthesizer", synthesizer_node)

    # Define the edges
    g.set_entry_point("retriever")          # always start at retriever
    g.add_edge("retriever", "critic")       # retriever always goes to critic
    g.add_conditional_edges(               # critic goes to retriever or synthesizer
        "critic",
        should_loop,
        {"retriever": "retriever", "synthesizer": "synthesizer"},
    )
    g.add_edge("synthesizer", END)          # synthesizer is always the last step

    return g.compile()


# Compiled graph — built once on first use, then reused
_graph = None


def get_graph():
    """Return the compiled graph, building it once on first call."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_query(question: str) -> dict:
    """
    Main entry point — run a question through the full self-correction pipeline.

    1. Creates a Langfuse Trace for this query
    2. Runs the LangGraph pipeline (retriever → critic → synthesizer)
    3. Updates the Trace with the final answer
    4. Returns {answer, citations, flags}
    """
    trace = Trace(name="policy-rag", input=question)

    # Initial state — everything starts empty except the question
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
    trace.update(result["answer"])  # record final answer in Langfuse

    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "flags": result["flags"],
    }
