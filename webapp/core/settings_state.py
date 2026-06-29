"""Azure connection settings.

The API key is held in the user's browser (see the UI layer) and passed in per
request — never persisted on the server. This module only models the credentials
and validates a connection; it keeps no global state.

v1 is Azure-only by decision. To add more providers later, generalize `AzureCreds`
into a provider union and branch in `as_overrides` / `test_connection`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AzureCreds:
    api_key: str
    endpoint: str = ""       # falls back to .env default when empty
    api_version: str = ""    # falls back to .env default when empty

    def as_overrides(self) -> dict[str, str]:
        """Map credentials onto load_config() override keys (empty values ignored)."""
        ov: dict[str, str] = {}
        if self.api_key:
            ov["AZURE_OPENAI_API_KEY"] = self.api_key
        if self.endpoint:
            ov["AZURE_OPENAI_ENDPOINT"] = self.endpoint.rstrip("/")
        if self.api_version:
            ov["AZURE_OPENAI_API_VERSION"] = self.api_version
        return ov

    @property
    def is_set(self) -> bool:
        return bool(self.api_key.strip())


def test_connection(creds: AzureCreds) -> tuple[bool, str]:
    """Validate the Azure credentials with one cheap embeddings call.

    Returns (ok, message). Endpoint/api-version/deployment names fall back to the
    server `.env` defaults when not supplied in `creds`.
    """
    # Local imports keep this module free of heavy pipeline imports at load time.
    from src.config import load_config
    from src.azure_openai_client import AzureOpenAIClient

    if not creds.is_set:
        return False, "Clé API manquante."
    try:
        cfg = load_config(overrides=creds.as_overrides())
        llm = AzureOpenAIClient(
            api_key=cfg.azure_openai_api_key,
            endpoint=cfg.azure_openai_endpoint,
            api_version=cfg.azure_openai_api_version,
            text_deployment=cfg.azure_openai_text_deployment,
            judge_deployment=cfg.azure_openai_judge_deployment,
            embedding_deployment=cfg.azure_openai_embedding_deployment,
            temperature=cfg.azure_openai_temperature,
            embedding_dimensions=cfg.azure_openai_embedding_dimensions,
            dry_run=False,
        )
        vectors = llm.embed_texts(["ping"])
        if vectors and vectors[0]:
            return True, "Connexion réussie à Azure OpenAI."
        return False, "Réponse vide d'Azure OpenAI."
    except Exception as exc:  # noqa: BLE001 - surface any provider/SDK error to the user
        return False, _friendly_error(str(exc))


def _friendly_error(raw: str) -> str:
    low = raw.lower()
    if "401" in raw or "unauthorized" in low or "access denied" in low:
        return "Échec d'authentification : clé API invalide ou non autorisée."
    if "404" in raw or "not found" in low or "deploymentnotfound" in low:
        return "Ressource introuvable : vérifiez l'endpoint et le nom de déploiement."
    if "getaddrinfo" in low or "connection" in low or "timed out" in low:
        return "Connexion impossible : vérifiez l'endpoint Azure et le réseau."
    return f"Échec de la connexion : {raw}"
