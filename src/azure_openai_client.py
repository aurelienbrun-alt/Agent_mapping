from __future__ import annotations

import json
import math
import random
import time
from typing import Any, Callable, TypeVar

from .utils import stable_hash, tokenize

T = TypeVar("T")

# Erreurs Azure/OpenAI considérées comme transitoires (donc à retenter).
_TRANSIENT_ERROR_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "APIStatusError",  # filtré ensuite sur le status code
}


def _is_transient(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in _TRANSIENT_ERROR_NAMES:
        status = getattr(exc, "status_code", None)
        # Pour APIStatusError, ne retenter que 429 et 5xx.
        if name == "APIStatusError" and status is not None:
            try:
                status = int(status)
            except Exception:
                return True
            return status == 429 or 500 <= status < 600
        return True
    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    """Respecte l'en-tete Retry-After d'Azure quand il est present."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    try:
        headers = getattr(resp, "headers", {}) or {}
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except Exception:
        return None


class AzureOpenAIClient:
    """Azure OpenAI client with the same small interface as GeminiClient.

    Important Azure detail: the `model=` argument is the Azure deployment name,
    not necessarily the raw model id. For example, if you deployed gpt-4.1-nano
    with deployment name `gpt-4.1-nano`, use that value in .env.
    """

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        api_version: str,
        text_deployment: str,
        judge_deployment: str,
        embedding_deployment: str,
        temperature: float,
        embedding_dimensions: int = 0,
        dry_run: bool = False,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/") if endpoint else endpoint
        self.api_version = api_version
        self.text_deployment = text_deployment
        self.judge_deployment = judge_deployment or text_deployment
        self.embedding_deployment = embedding_deployment
        self.temperature = temperature
        self.embedding_dimensions = embedding_dimensions
        self.dry_run = dry_run
        self._client = None

        if not dry_run:
            if not api_key or api_key == "PASTE_YOUR_AZURE_OPENAI_API_KEY_HERE":
                raise ValueError("AZURE_OPENAI_API_KEY is missing. Set it in .env or enable DRY_RUN_WITHOUT_LLM=true.")
            if not endpoint or "https://" not in endpoint:
                raise ValueError("AZURE_OPENAI_ENDPOINT is missing or invalid. Example: https://my-resource.openai.azure.com/")
            from openai import AzureOpenAI

            self._client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=self.endpoint,
                api_version=api_version,
                timeout=60.0,      # evite les workers bloques indefiniment
                max_retries=0,     # on gere le retry nous-memes (backoff + Retry-After)
            )

    def _with_retries(self, fn: Callable[[], T], *, what: str, max_attempts: int = 5) -> T:
        """Retente un appel API en cas d'erreur transitoire (429, 5xx, timeout).

        Backoff exponentiel + jitter, en respectant l'en-tete Retry-After d'Azure
        quand il est present.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except Exception as exc:  # filtre via _is_transient juste apres
                last_exc = exc
                if not _is_transient(exc) or attempt == max_attempts:
                    raise
                wait = _retry_after_seconds(exc)
                if wait is None:
                    wait = min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 1))
                time.sleep(wait)
        assert last_exc is not None
        raise last_exc

    def generate_json(self, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True}
        assert self._client is not None
        deployment = model or self.text_deployment
        response = self._with_retries(
            lambda: self._client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": "Return valid JSON only. Do not include markdown fences."},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            ),
            what=f"chat.completions[{deployment}]",
        )
        text = response.choices[0].message.content or ""
        return self._parse_json(text)

    def judge_json(self, prompt: str) -> dict[str, Any]:
        return self.generate_json(prompt, model=self.judge_deployment)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.dry_run:
            dims = self.embedding_dimensions or 128
            return [self._hash_embedding(t, dims=dims) for t in texts]
        assert self._client is not None
        if not texts:
            return []

        # Azure OpenAI embeddings accept batched inputs. Keep batches modest to
        # avoid token/request limits and to make retry failures easier to isolate.
        embeddings: list[list[float]] = []
        batch_size = 64
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            kwargs: dict[str, Any] = {"model": self.embedding_deployment, "input": batch}
            if self.embedding_dimensions and self.embedding_dimensions > 0:
                kwargs["dimensions"] = self.embedding_dimensions
            result = self._with_retries(
                lambda kwargs=kwargs: self._client.embeddings.create(**kwargs),
                what=f"embeddings[{self.embedding_deployment}]",
            )
            ordered = sorted(result.data, key=lambda x: x.index)
            embeddings.extend([list(item.embedding) for item in ordered])
        return embeddings

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
            raise

    @staticmethod
    def _hash_embedding(text: str, dims: int = 128) -> list[float]:
        vec = [0.0] * dims
        for token in tokenize(text):
            h = int(stable_hash(token), 16)
            idx = h % dims
            sign = 1.0 if (h // dims) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
