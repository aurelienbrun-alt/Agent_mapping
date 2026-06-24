from __future__ import annotations

import json
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .azure_openai_client import AzureOpenAIClient
from .config import AppConfig
from .logging_utils import JsonlRunLogger
from .models import MappingDecision
from .utils import render_prompt, stable_hash, resolve_language_name


PARENT_GAP_SYNTHESIS_CACHE_SCHEMA = "parent_gap_synthesis_cache_v2_parent_final_judge"


DEFAULT_PARENT_GAP_SYNTHESIS_PROMPT = """
You are the parent-level final judge for a cybersecurity regulatory mapping.

Your task is to synthesize the residual gap at parent requirement level and classify the parent gap using the controlled taxonomy below. This is a coverage mapping task, not a textual similarity task. Different wording, different legal drafting, and different structure do not prevent coverage.

Allowed parent_gap_type values only:
- none
- implementation_detail_gap
- partial_gap
- indirect_support_gap
- true_gap
- conflict_gap

Definitions:
- none: the target framework fully covers the parent source requirement. No material residual gap remains.
- implementation_detail_gap: the target covers the main obligation, but lacks implementation details such as evidence, documentation, traceability, frequency, deadline, testing method, accountability, proof, or explicit procedural wording.
- partial_gap: the target covers the same regulatory objective or obligation family, but material actor/action/object/scope/condition/evidence elements remain missing, narrower, implicit, or only partly addressed.
- indirect_support_gap: the target contains related or supportive provisions, but they do not impose the same direct parent obligation.
- true_gap: no selected target requirement provides meaningful coverage of the parent source obligation.
- conflict_gap: the target framework contradicts or prevents the source obligation.

Classification rules:
1. Do not classify as partial_gap by default.
2. If the main obligation is covered and remaining differences are mostly proof, evidence, documentation, deadline, frequency, traceability, governance, or explicitness, prefer implementation_detail_gap.
3. If material actor/action/object/scope elements are missing but the same objective is covered, use partial_gap.
4. If most atomic decisions are only supportive or 25-level coverage, use indirect_support_gap.
5. Use true_gap only when there is no meaningful coverage after considering selected target requirements.
6. If the atomic decisions include meaningful 50 or 75 coverage, do not use true_gap unless those atomic decisions are clearly wrong.
7. Keep every materially distinct residual gap. Do not artificially limit the number of bullets.
8. Merge duplicates and near-duplicates.
9. Do not mention atoms, atomic requirements, embeddings, scores, candidates, gates, prompts, LLM behavior, or technical internals.
10. Do not repeat the full source requirement.
11. Write in the requested output language: {output_language}.

A deterministic classifier suggested this parent_gap_type: {suggested_gap_classification}.
You may override it only if the evidence clearly supports a different controlled value.

Return JSON only:
{
  "parent_relation_type": "direct_full_coverage|mostly_covered|partial|implementation_detail_gap|indirect_support|true_gap|conflict",
  "parent_gap_type": "none|implementation_detail_gap|partial_gap|indirect_support_gap|true_gap|conflict_gap",
  "coverage_synthesis": "One concise sentence summarizing the overall coverage by the target framework.",
  "residual_gaps": [
    {
      "dimension": "actor|action|object|scope|condition|deadline|evidence|governance|explicitness|implementation",
      "gap": "Concise but specific residual gap.",
      "severity": "minor|moderate|material"
    }
  ],
  "overall_impact": "One concise sentence explaining the practical implication for the mapping."
}

Source parent ID:
{source_parent_id}

Source parent requirement:
{source_parent_requirement}

Target framework:
{target_framework}

Selected target parent requirements:
{target_parent_requirements_json}

Atomic coverage decisions and residual gap evidence:
{atomic_decisions_json}
""".strip()


class ParentGapSynthesisCache:
    """Thread-safe JSONL cache for parent-level LLM gap synthesis."""

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}
        if self.enabled:
            self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            key = str(payload.get("key") or "")
            result = payload.get("result")
            if key and isinstance(result, dict):
                self._items[key] = result

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        return self._items.get(key)

    def set(self, key: str, result: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            if key in self._items:
                return
            self._items[key] = result
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "result": result}, ensure_ascii=False, default=str) + "\n")


def run_parent_gap_synthesis(
    decisions: list[MappingDecision],
    *,
    direction: str,
    target_framework: str,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[MappingDecision]:
    """Use an LLM to synthesize parent-level gap text from atomic decisions.

    The function mutates each MappingDecision by setting parent_gap_summary on all
    decisions belonging to the same source parent. output_writer.py then uses that
    summary for the parent row instead of deterministic concatenation.
    """
    if not getattr(app_cfg, "enable_parent_gap_llm_synthesis", False):
        logger.event("parent_gap_synthesis.skip", direction=direction, reason="disabled")
        return decisions
    if app_cfg.dry_run_without_llm:
        logger.event("parent_gap_synthesis.skip", direction=direction, reason="dry_run")
        return decisions

    groups = _group_parent_decisions(decisions)
    todo: list[tuple[str, list[MappingDecision]]] = []
    for parent_id, items in groups.items():
        if not items:
            continue
        if getattr(app_cfg, "parent_gap_synthesis_only_for_non_full_coverage", True):
            avg = sum(d.coverage_level for d in items) / max(len(items), 1)
            if avg >= 99.5:
                _apply_parent_summary(items, _format_full_coverage_summary(target_framework))
                continue
        todo.append((parent_id, items))

    logger.event("parent_gap_synthesis.start", direction=direction, parents=len(todo))
    if not todo:
        logger.event("parent_gap_synthesis.done", direction=direction, parents=0)
        return decisions

    print(f"[4/6] Parent gap synthesis: reviewing {len(todo)} parent requirement(s)...", flush=True)
    cache_path = app_cfg.docs_cache_dir / "parent_gap_synthesis" / app_cfg.parent_gap_synthesis_cache_file
    cache = ParentGapSynthesisCache(cache_path, enabled=app_cfg.enable_parent_gap_synthesis_cache)
    max_workers = max(1, int(getattr(app_cfg, "parent_gap_synthesis_max_concurrent_calls", 0) or app_cfg.max_concurrent_llm_calls or 1))

    def work(item: tuple[str, list[MappingDecision]]) -> tuple[str, str, str, bool]:
        parent_id, parent_items = item
        try:
            cache_key = build_parent_gap_cache_key(
                app_cfg=app_cfg,
                direction=direction,
                target_framework=target_framework,
                parent_id=parent_id,
                items=parent_items,
            )
            cached = cache.get(cache_key)
            if cached:
                return parent_id, format_parent_gap_result(cached), str(cached.get("parent_gap_type") or ""), True

            prompt = build_parent_gap_prompt(
                app_cfg=app_cfg,
                target_framework=target_framework,
                parent_id=parent_id,
                items=parent_items,
            )
            result = llm.judge_json(prompt)
            normalized = normalize_parent_gap_result(result)
            cache.set(cache_key, normalized)
            return parent_id, format_parent_gap_result(normalized), str(normalized.get("parent_gap_type") or ""), False
        except Exception as exc:
            logger.error("parent_gap_synthesis.parent", exc, direction=direction, parent_id=parent_id)
            return parent_id, "", "", False

    summaries: dict[str, str] = {}
    gap_types: dict[str, str] = {}
    cache_hits = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(work, x) for x in todo]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Parent gap synthesis", unit="parent"):
            parent_id, summary, gap_type, was_cached = future.result()
            if summary:
                summaries[parent_id] = summary
            if gap_type:
                gap_types[parent_id] = gap_type
            if was_cached:
                cache_hits += 1

    for parent_id, items in groups.items():
        if parent_id in summaries:
            _apply_parent_summary(items, summaries[parent_id], gap_types.get(parent_id, ""))

    logger.event("parent_gap_synthesis.done", direction=direction, parents=len(todo), cache_hits=cache_hits, generated=len(summaries))
    return decisions


def _group_parent_decisions(decisions: list[MappingDecision]) -> dict[str, list[MappingDecision]]:
    groups: dict[str, list[MappingDecision]] = defaultdict(list)
    for d in decisions:
        parent_id = d.source_parent_id or _parent_id(d.source_id)
        groups[parent_id].append(d)
    return dict(groups)


def _parent_id(value: str) -> str:
    text = str(value or "")
    if "#" in text:
        return text.split("#", 1)[0]
    if "__atom" in text:
        return text.split("__atom", 1)[0]
    return text


def _apply_parent_summary(items: list[MappingDecision], summary: str, gap_type: str = "") -> None:
    for d in items:
        d.parent_gap_summary = summary
        if gap_type:
            d.parent_gap_type = gap_type



def classify_parent_gap_deterministic(items: list[MappingDecision]) -> str:
    if not items:
        return "true_gap"
    scores = [float(getattr(d, "coverage_level", 0) or 0) for d in items]
    total = max(len(scores), 1)
    avg = sum(scores) / total
    direct_ratio = sum(1 for s in scores if s >= 40) / total
    high_ratio = sum(1 for s in scores if s >= 80) / total
    indirect_ratio = sum(1 for s in scores if 0 < s < 40) / total
    gap_ratio = sum(1 for s in scores if s <= 0) / total
    gap_types = {_normalize_parent_gap_type(str(getattr(d, "gap_type", "") or ""), []) for d in items}
    dims = {_normalize_dimension(str(g.get("dimension", ""))) for d in items for g in (getattr(d, "gap_items", []) or []) if isinstance(g, dict)}
    implementation_dims = {"evidence", "deadline", "condition", "governance", "explicitness"}
    material_dims = {"actor", "action", "object", "scope"}

    if "conflict_gap" in gap_types:
        return "conflict_gap"
    if avg >= 99.5 and gap_ratio == 0:
        return "none"
    if gap_ratio >= 0.70 and direct_ratio == 0:
        return "true_gap"
    if direct_ratio == 0 and indirect_ratio > 0:
        return "indirect_support_gap"
    if avg >= 70 and high_ratio >= 0.50 and dims and dims.issubset(implementation_dims):
        return "implementation_detail_gap"
    if avg >= 60 and direct_ratio >= 0.60 and not (dims & material_dims):
        return "implementation_detail_gap"
    if avg >= 40 and direct_ratio >= 0.25:
        return "partial_gap"
    if avg > 0 or indirect_ratio > 0:
        return "indirect_support_gap"
    return "true_gap"

def build_parent_gap_prompt(
    *,
    app_cfg: AppConfig,
    target_framework: str,
    parent_id: str,
    items: list[MappingDecision],
) -> str:
    source_parent_requirement = next((d.source_parent_requirement for d in items if d.source_parent_requirement), items[0].source_requirement if items else "")
    target_parent_reqs = _unique_target_parent_requirements(items)
    atomic_decisions = [_decision_payload(d) for d in sorted(items, key=lambda x: (x.coverage_level, x.source_id))]
    template = app_cfg.prompt_parent_gap_synthesis or DEFAULT_PARENT_GAP_SYNTHESIS_PROMPT
    return render_prompt(
        template,
        output_language=resolve_language_name(app_cfg.output_language),
        source_parent_id=parent_id,
        source_parent_requirement=_truncate(source_parent_requirement, app_cfg.parent_gap_synthesis_max_text_chars),
        target_framework=target_framework,
        suggested_gap_classification=classify_parent_gap_deterministic(items),
        target_parent_requirements_json=json.dumps(target_parent_reqs, ensure_ascii=False, indent=2),
        atomic_decisions_json=json.dumps(atomic_decisions, ensure_ascii=False, indent=2),
    )


def _decision_payload(d: MappingDecision) -> dict[str, Any]:
    return {
        "source_id": d.source_id,
        "source_obligation": _truncate(d.source_requirement, 700),
        "coverage_level": d.coverage_level,
        "equivalence_level": d.equivalence_level,
        "relation_type": d.relation_type,
        "gap_type": getattr(d, "gap_type", ""),
        "match_type": d.match_type,
        "selected_target_ids": d.target_ids,
        "selected_target_obligations": [_truncate(x, 700) for x in d.target_requirements],
        "gap": _truncate(d.gap, 900),
        "gap_dimensions": d.gap_dimensions,
        "gap_items": d.gap_items,
    }


def _unique_target_parent_requirements(items: list[MappingDecision]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for d in items:
        ids = d.target_parent_ids or []
        reqs = d.target_parent_requirements or []
        if not ids and d.target_ids:
            ids = d.target_ids
            reqs = d.target_requirements
        for idx, target_id in enumerate(ids):
            req = reqs[idx] if idx < len(reqs) else ""
            key = str(target_id or req)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"target_id": str(target_id), "requirement": _truncate(req, 1000)})
    return out


def normalize_parent_gap_result(result: dict[str, Any]) -> dict[str, Any]:
    coverage_synthesis = str(result.get("coverage_synthesis") or result.get("summary") or "").strip()
    overall_impact = str(result.get("overall_impact") or result.get("impact") or "").strip()
    raw_gaps = result.get("residual_gaps") or result.get("gap_items") or []
    residual_gaps: list[dict[str, str]] = []
    if isinstance(raw_gaps, list):
        for raw in raw_gaps:
            if not isinstance(raw, dict):
                continue
            gap = str(raw.get("gap") or raw.get("missing_element") or raw.get("residual_gap") or "").strip()
            if not gap:
                continue
            residual_gaps.append({
                "dimension": _normalize_dimension(str(raw.get("dimension") or "explicitness")),
                "gap": _clean_sentence(gap),
                "severity": _normalize_severity(str(raw.get("severity") or "moderate")),
            })
    parent_gap_type = _normalize_parent_gap_type(str(result.get("parent_gap_type") or result.get("gap_type") or ""), residual_gaps)
    parent_relation_type = str(result.get("parent_relation_type") or result.get("relation_type") or "").strip() or _relation_from_parent_gap_type(parent_gap_type)
    return {
        "schema": PARENT_GAP_SYNTHESIS_CACHE_SCHEMA,
        "parent_relation_type": parent_relation_type,
        "parent_gap_type": parent_gap_type,
        "coverage_synthesis": _clean_sentence(coverage_synthesis) if coverage_synthesis else "The target framework provides partial or indirect coverage, but residual obligations remain.",
        "residual_gaps": _dedupe_residual_gaps(residual_gaps),
        "overall_impact": _clean_sentence(overall_impact) if overall_impact else "The mapping should be reviewed to determine whether additional interpretation or implementation evidence is required.",
    }


def format_parent_gap_result(result: dict[str, Any]) -> str:
    synthesis = str(result.get("coverage_synthesis") or "").strip() or "The target framework provides partial or indirect coverage."
    gaps = result.get("residual_gaps") or []
    lines = [synthesis]
    if isinstance(gaps, list) and gaps:
        bullets = []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            text = _clean_sentence(str(gap.get("gap") or ""))
            if text:
                bullets.append(f"• {text}")
        if bullets:
            lines.append("")
            lines.extend(bullets)
    return "\n".join(lines)


def _format_full_coverage_summary(target_framework: str) -> str:
    return f"{target_framework} fully covers this requirement."


def build_parent_gap_cache_key(
    *,
    app_cfg: AppConfig,
    direction: str,
    target_framework: str,
    parent_id: str,
    items: list[MappingDecision],
) -> str:
    payload = {
        "schema": PARENT_GAP_SYNTHESIS_CACHE_SCHEMA,
        "direction": direction,
        "target_framework": target_framework,
        "parent_id": parent_id,
        "source_parent_requirement": next((d.source_parent_requirement for d in items if d.source_parent_requirement), ""),
        "decisions": [_decision_payload(d) for d in sorted(items, key=lambda x: x.source_id)],
        "model": app_cfg.azure_openai_judge_deployment,
        "prompt_hash": stable_hash(app_cfg.prompt_parent_gap_synthesis or DEFAULT_PARENT_GAP_SYNTHESIS_PROMPT),
        "output_language": app_cfg.output_language,
    }
    return stable_hash(payload)


def _dedupe_residual_gaps(items: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        gap = item.get("gap", "")
        if not gap:
            continue
        key = _dedupe_key(item.get("dimension", ""), gap)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_key(dimension: str, gap: str) -> str:
    tokens = [x for x in " ".join(str(gap).casefold().replace(".", " ").split()).split() if len(x) > 2]
    return f"{_normalize_dimension(dimension)}|{' '.join(tokens[:18])}"



def _normalize_parent_gap_type(value: str, gaps: list[dict[str, str]]) -> str:
    text = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "none": "none",
        "no_gap": "none",
        "true_gap": "true_gap",
        "gap": "true_gap",
        "partial_gap": "partial_gap",
        "partial": "partial_gap",
        "implementation_gap": "implementation_detail_gap",
        "implementation_detail": "implementation_detail_gap",
        "implementation_detail_gap": "implementation_detail_gap",
        "indirect": "indirect_support_gap",
        "indirect_support": "indirect_support_gap",
        "indirect_support_gap": "indirect_support_gap",
        "conflict": "conflict_gap",
        "conflict_gap": "conflict_gap",
    }
    if text in aliases:
        return aliases[text]
    if not gaps:
        return "none"
    if any(g.get("dimension") in {"evidence", "explicitness", "deadline", "condition"} for g in gaps):
        return "implementation_detail_gap"
    return "partial_gap"


def _relation_from_parent_gap_type(gap_type: str) -> str:
    return {
        "none": "direct_full_coverage",
        "partial_gap": "partial",
        "implementation_detail_gap": "implementation_detail_gap",
        "indirect_support_gap": "indirect_support",
        "conflict_gap": "conflict",
        "true_gap": "true_gap",
    }.get(gap_type, "partial")

def _normalize_dimension(value: str) -> str:
    text = str(value or "").strip().casefold()
    allowed = {"actor", "action", "object", "scope", "condition", "deadline", "evidence", "governance", "explicitness", "implementation"}
    aliases = {
        "actors": "actor",
        "role": "actor",
        "roles": "actor",
        "process": "governance",
        "procedure": "implementation",
        "responsibility": "governance",
        "implementation": "implementation",
        "responsibilities": "governance",
        "frequency": "deadline",
        "timing": "deadline",
        "proof": "evidence",
        "documentation": "evidence",
        "explicit": "explicitness",
        "clarity": "explicitness",
        "specificity": "explicitness",
    }
    text = aliases.get(text, text)
    return text if text in allowed else "explicitness"


def _normalize_severity(value: str) -> str:
    text = str(value or "").strip().casefold()
    if text in {"high", "major", "material", "critical"}:
        return "material"
    if text in {"low", "minor"}:
        return "minor"
    return "moderate"


def _clean_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" -;\n\t")
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _truncate(text: str, max_chars: int = 1000) -> str:
    max_chars = int(max_chars or 1000)
    value = str(text or "")
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"
