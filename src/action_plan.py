"""Action plan synthesis.

Generates a short, actionable remediation plan (1 to N bullet points) for each
parent requirement of the final output, based on the gap text already shown in
the Gap column. This runs after the parent rows are assembled, so the action
plan reflects the complete gap (including the entity-criticality note when the
entity-criticality feature is enabled).

The plan focuses on the key actions required to close the most important
residual gaps. Fully covered requirements (no material gap) receive no plan.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from .config import AppConfig
from .parent_gap_synthesis import ParentGapSynthesisCache
from .utils import render_prompt, stable_hash, resolve_language_name


ACTION_PLAN_CACHE_SCHEMA = "action_plan_cache_v1"


DEFAULT_ACTION_PLAN_PROMPT = """
You are a cybersecurity regulatory remediation expert.

For each item below, write a concise ACTION PLAN: the key actions an organization
must take to close the most important residual gaps described in the gap text.

Rules:
1. Return between 1 and {max_bullets} bullet points. Never exceed {max_bullets}.
2. Prioritize the most material gaps first; omit minor or cosmetic points.
3. Each action must be specific, imperative and operational (what to do), max 25 words.
4. Do not restate the requirement or the gap; state the action to remediate it.
5. If the gap text indicates full coverage or contains no material gap, return an empty list.
6. Do not mention scores, mappings, atoms, prompts or any technical internals.
7. Write every action in {output_language}.

Return JSON only:
{"results": [{"id": "<id>", "actions": ["action 1", "action 2"]}]}

Items:
{items_json}
""".strip()


def run_action_plan_synthesis(
    rows: list[dict[str, Any]],
    app_cfg: AppConfig,
    llm: Any,
    logger: Any = None,
) -> list[dict[str, Any]]:
    """Populate row['action_plan'] for every parent row that has a material gap.

    Mutates the rows in place and also returns them. Rows that are fully covered
    or have no gap text receive an empty action plan.
    """
    if not getattr(app_cfg, "enable_action_plan", False):
        _log(logger, "action_plan.skip", reason="disabled")
        return rows
    if getattr(app_cfg, "dry_run_without_llm", False) or llm is None:
        _log(logger, "action_plan.skip", reason="dry_run_or_no_llm")
        return rows

    for r in rows:
        r.setdefault("action_plan", "")

    output_language = resolve_language_name(app_cfg.output_language)
    max_bullets = max(1, int(getattr(app_cfg, "action_plan_max_bullets", 4) or 4))
    batch_size = max(1, int(getattr(app_cfg, "action_plan_batch_size", 20) or 20))
    prompt_template = getattr(app_cfg, "prompt_action_plan", "") or DEFAULT_ACTION_PLAN_PROMPT

    cache_path = app_cfg.docs_cache_dir / "action_plan" / getattr(app_cfg, "action_plan_cache_file", "action_plan_cache.jsonl")
    cache = ParentGapSynthesisCache(cache_path, enabled=getattr(app_cfg, "enable_action_plan_cache", True))

    # Select rows that need a plan and resolve cache hits first.
    pending: list[dict[str, Any]] = []
    cache_hits = 0
    for r in rows:
        if not _needs_action_plan(r):
            continue
        key = _cache_key(app_cfg, r, prompt_template, max_bullets)
        cached = cache.get(key)
        if cached is not None:
            r["action_plan"] = _format_actions(cached.get("actions") or [], max_bullets)
            cache_hits += 1
        else:
            r["_action_plan_key"] = key
            pending.append(r)

    _log(logger, "action_plan.start", pending=len(pending), cache_hits=cache_hits)
    if not pending:
        _log(logger, "action_plan.done", generated=0, cache_hits=cache_hits)
        return rows

    print(f"[5/6] Action plan: generating for {len(pending)} requirement(s)...", flush=True)
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    max_workers = max(1, int(getattr(app_cfg, "max_concurrent_llm_calls", 1) or 1))

    def work(batch: list[dict[str, Any]]) -> dict[str, list[str]]:
        items = [_row_payload(r) for r in batch]
        prompt = render_prompt(
            prompt_template,
            output_language=output_language,
            max_bullets=str(max_bullets),
            items_json=json.dumps(items, ensure_ascii=False, indent=2),
        )
        try:
            raw = llm.judge_json(prompt)
        except Exception as exc:
            _error(logger, "action_plan.batch", exc, items=len(items))
            return {}
        out: dict[str, list[str]] = {}
        for entry in (raw.get("results") or []):
            if isinstance(entry, dict) and entry.get("id") is not None:
                out[str(entry["id"])] = _clean_actions(entry.get("actions"), max_bullets)
        return out

    generated = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(work, b): b for b in batches}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Action plan", unit="batch"):
            result_map = future.result()
            for r in futures[future]:
                pid = str(r["source_parent_id"])
                actions = result_map.get(pid, [])
                r["action_plan"] = _format_actions(actions, max_bullets)
                key = r.pop("_action_plan_key", "")
                if key:
                    cache.set(key, {"schema": ACTION_PLAN_CACHE_SCHEMA, "actions": actions})
                if actions:
                    generated += 1

    # Clean up any leftover helper keys (rows whose batch failed entirely).
    for r in pending:
        r.pop("_action_plan_key", None)

    _log(logger, "action_plan.done", generated=generated, cache_hits=cache_hits)
    return rows


def _needs_action_plan(r: dict[str, Any]) -> bool:
    try:
        coverage = float(r.get("coverage_level", 0) or 0)
    except Exception:
        coverage = 0.0
    if coverage >= 99.5:
        return False
    gap = str(r.get("gap") or "").strip()
    if not gap:
        return False
    # A "fully covers" synthesis is not a material gap.
    if "fully covers this requirement" in gap.casefold():
        return False
    return True


def _row_payload(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r["source_parent_id"]),
        "category": str(r.get("domain") or ""),
        "requirement": _truncate(r.get("source_parent_requirement"), 600),
        "coverage_level": int(round(float(r.get("coverage_level", 0) or 0))),
        "gap": _truncate(r.get("gap"), 1400),
    }


def _cache_key(app_cfg: AppConfig, r: dict[str, Any], prompt_template: str, max_bullets: int) -> str:
    payload = {
        "schema": ACTION_PLAN_CACHE_SCHEMA,
        "parent_id": str(r["source_parent_id"]),
        "gap": str(r.get("gap") or ""),
        "requirement": str(r.get("source_parent_requirement") or ""),
        "coverage_level": int(round(float(r.get("coverage_level", 0) or 0))),
        "max_bullets": max_bullets,
        "model": getattr(app_cfg, "azure_openai_judge_deployment", ""),
        "prompt_hash": stable_hash(prompt_template),
        "output_language": app_cfg.output_language,
    }
    return stable_hash(payload)


def _clean_actions(value: Any, max_bullets: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split()).strip(" -•*;\n\t")
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        out.append(text)
        if len(out) >= max_bullets:
            break
    return out


def _format_actions(actions: list[str], max_bullets: int) -> str:
    actions = _clean_actions(actions, max_bullets)
    return "\n".join(f"• {a}" for a in actions)


def _truncate(text: Any, max_chars: int) -> str:
    value = str(text or "")
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _log(logger: Any, event: str, **fields: Any) -> None:
    if logger is not None:
        try:
            logger.event(event, **fields)
        except Exception:
            pass


def _error(logger: Any, event: str, exc: Exception, **fields: Any) -> None:
    if logger is not None:
        try:
            logger.error(event, exc, **fields)
        except Exception:
            pass
