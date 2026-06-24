# Patch v2.6 - Azure OpenAI support

This patch adds Azure OpenAI as an alternative LLM provider while keeping the existing Gemini client.

## New .env variables

```env
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE-NAME.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_TEXT_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=512
AZURE_OPENAI_TEMPERATURE=0.2
```

Azure uses deployment names in API calls. If your Azure deployment is named `nis2-nano`, put `nis2-nano`, not `gpt-4.1-nano`.

## Files changed

- `requirements.txt`: adds `openai`
- `run_agent.py`: selects Gemini or Azure OpenAI depending on `LLM_PROVIDER`
- `src/config.py`: adds Azure OpenAI configuration
- `src/azure_openai_client.py`: new Azure OpenAI client
- `src/cache.py`: cache hash now includes provider/deployment information when `CACHE_KEY_MODE=hash`
- `src/preprocessing.py`: logs active embedding model/deployment
- `src/matching.py`, `src/final_judge.py`: use `judge_json()` so provider-specific judge deployment is used

## Recommended low-cost setup

```env
LLM_PROVIDER=azure_openai
AZURE_OPENAI_TEXT_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=512
TOP_K_CANDIDATES=3
RUN_FINAL_LLM_JUDGE=false
BIDIRECTIONAL_MAPPING=false
USE_CACHE=true
REBUILD_CACHE=false
CACHE_KEY_MODE=file_name
```
