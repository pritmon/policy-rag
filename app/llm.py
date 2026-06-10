"""
llm.py — All communication with the AI provider (AWS Bedrock or Google Gemini).

This file handles two things:
  1. llm()   — Send a prompt to the LLM, get a text answer back
  2. embed() — Send text to the embedding model, get a vector of numbers back

Provider switch (set in .env):
  LLM_PROVIDER=bedrock → AWS Nova Micro      LLM_PROVIDER=gemini → Google Gemini Flash
  EMBED_PROVIDER=bedrock → AWS Titan Embed   EMBED_PROVIDER=gemini → Google text-embedding-004

The rest of the app never knows which provider is active — it just calls
llm() and embed(). That's why switching providers needs zero changes elsewhere.

Why the retry logic?
  All AI APIs have rate limits (throttling). If you send too many requests
  too fast, they return an error. Instead of crashing, we wait and try
  again — doubling the wait each time. This is called exponential backoff.
"""

import json
import re
import time

import boto3
import httpx
from botocore.exceptions import ClientError

from app.config import settings

# Base URL for all Google Gemini API calls
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Speed governor for the free tier: remember when we last called the
# Gemini LLM, and never call it faster than once every _MIN_GAP seconds.
# This prevents bursts (critic + synthesizer back-to-back) from slamming
# into the requests-per-minute wall in the first place.
_MIN_GAP = 10.0  # seconds between LLM calls
_last_llm_call = 0.0


def _gemini_post(url: str, body: dict, max_retries: int = 10) -> dict:
    """
    Call the Gemini REST API with retry on rate-limit (HTTP 429) errors.

    Gemini's free tier allows ~20 requests per minute — if we go faster,
    Google replies 429 and even tells us how long to wait ("retry in 37s").
    We read that hint and wait exactly that long (plus a small buffer).
    """
    for attempt in range(max_retries):
        resp = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json=body,
            timeout=60,
        )
        if resp.status_code == 429 and attempt < max_retries - 1:
            # Google's error message includes "Please retry in 37.5s" —
            # use that if present, otherwise wait a safe 45 seconds.
            wait = 45.0
            match = re.search(r"retry in ([\d.]+)s", resp.text)
            if match:
                wait = float(match.group(1)) + 2  # small safety buffer
            print(f"  Gemini rate-limited, waiting {wait:.0f}s "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Gemini API: ran out of retries")

# Cached Bedrock client — created once and reused for every call
_bedrock = None


def _client():
    """Return a Bedrock client, creating it once on first call."""
    global _bedrock
    if _bedrock is None:
        from botocore.config import Config
        # Disable botocore's own internal retry (max_attempts=1) so that
        # our custom backoff loop below is the only retry mechanism.
        # Without this, botocore retries 4x internally before we even see the error.
        cfg = Config(retries={"max_attempts": 1, "mode": "legacy"})
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=cfg,
        )
    return _bedrock


def _invoke_with_retry(model_id: str, body: dict, max_retries: int = 8) -> dict:
    """
    Call Bedrock with automatic retry on throttling errors.

    Waits 5s after first failure, 10s after second, 20s after third, etc.
    Raises the error immediately for non-throttling failures (e.g. bad request).
    """
    delay = 5.0  # starting wait in seconds
    throttle_codes = {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
    }
    for attempt in range(max_retries):
        try:
            resp = _client().invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            return json.loads(resp["body"].read())
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in throttle_codes and attempt < max_retries - 1:
                # Exponential backoff: 5s, 10s, 20s, 40s ...
                wait = delay * (2 ** attempt)
                print(f"  Throttled ({code}), waiting {wait:.0f}s "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                # Not a throttle error, or ran out of retries — raise immediately
                raise


def llm(prompt: str, system: str = "") -> str:
    """
    Send a prompt to the LLM and return the text response.

    Supports two model families:
    - Amazon Nova  → uses 'messages' + 'inferenceConfig' format
    - Anthropic Claude → uses 'anthropic_version' format

    The model family is detected automatically from the model ID in settings.
    """
    # --- OpenAI path (paid, no free-tier speed limits) ---
    if settings.llm_provider == "openai":
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": settings.openai_model, "messages": messages, "max_tokens": 1024},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # --- Gemini path (free Google API) ---
    if settings.llm_provider == "gemini":
        # Speed governor: wait if the last LLM call was under _MIN_GAP ago
        global _last_llm_call
        gap = time.time() - _last_llm_call
        if gap < _MIN_GAP:
            time.sleep(_MIN_GAP - gap)
        _last_llm_call = time.time()

        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 1024},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = _gemini_post(f"{_GEMINI_BASE}/{settings.gemini_model}:generateContent", body)
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # --- Bedrock path (AWS) ---
    model = settings.bedrock_llm_model_id

    if "nova" in model or "amazon" in model.split(".")[0]:
        # Amazon Nova format: messages array with content blocks
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        body: dict = {"messages": messages, "inferenceConfig": {"maxTokens": 1024}}
        if system:
            # System prompt goes in a separate top-level key for Nova
            body["system"] = [{"text": system}]
        data = _invoke_with_retry(model, body)
        return data["output"]["message"]["content"][0]["text"]
    else:
        # Anthropic Claude format: anthropic_version header required
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        data = _invoke_with_retry(model, body)
        return data["content"][0]["text"]


def embed(text: str) -> list[float]:
    """
    Convert a piece of text (document chunk) into a vector of 1024 numbers.

    Used during ingestion — each policy chunk gets embedded and stored in pgvector.
    Uses 'search_document' input type for Cohere, standard format for Titan.
    """
    # --- Gemini path: RETRIEVAL_DOCUMENT tells Google this is a stored chunk ---
    if settings.embed_provider == "gemini":
        body = {
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_DOCUMENT",
            # Gemini's default is 3072 numbers; we ask for embed_dim (768)
            "outputDimensionality": settings.embed_dim,
        }
        data = _gemini_post(
            f"{_GEMINI_BASE}/{settings.gemini_embed_model}:embedContent", body)
        return data["embedding"]["values"]

    model = settings.bedrock_embed_model_id

    if model.startswith("cohere.embed"):
        # Cohere format: list of texts with input_type
        body = {"texts": [text], "input_type": "search_document"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        # Titan Embed v2 format
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]


def embed_query(text: str) -> list[float]:
    """
    Convert a user's question into a vector for similarity search.

    Same as embed() but uses 'search_query' input type for Cohere —
    this tells the model the text is a search query, not a document,
    which improves retrieval accuracy.
    """
    # --- Gemini path: RETRIEVAL_QUERY tells Google this is a search question ---
    if settings.embed_provider == "gemini":
        body = {
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_QUERY",
            "outputDimensionality": settings.embed_dim,
        }
        data = _gemini_post(
            f"{_GEMINI_BASE}/{settings.gemini_embed_model}:embedContent", body)
        return data["embedding"]["values"]

    model = settings.bedrock_embed_model_id

    if model.startswith("cohere.embed"):
        body = {"texts": [text], "input_type": "search_query"}
        data = _invoke_with_retry(model, body)
        return data["embeddings"][0]
    else:
        # Titan treats queries and documents the same way
        body = {"inputText": text, "dimensions": settings.embed_dim, "normalize": True}
        data = _invoke_with_retry(model, body)
        return data["embedding"]
