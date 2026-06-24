from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import AppConfig, FrameworkConfig
from .models import AtomicRequirement, RequirementRow
from .utils import normalize_category, normalize_text, stable_hash, tokenize, render_prompt
from .cache import cache_dir, FULL_CACHE_FILE, FIELDS_CACHE_FILE, ATOMIZED_CACHE_FILE
from .logging_utils import JsonlRunLogger
from .azure_openai_client import AzureOpenAIClient


@dataclass(frozen=True)
class EnisaCategoryCard:
    category: str
    subcategories: list[str]
    key: str
    number: str
    definition: str = ""
    positive_keywords_en: list[str] | None = None
    positive_keywords_fr: list[str] | None = None
    negative_keywords: list[str] | None = None
    typical_actions: list[str] | None = None
    typical_objects: list[str] | None = None
    examples: list[str] | None = None
    counterexamples: list[str] | None = None
    strict_rules: str = ""

    def searchable_text(self) -> str:
        parts: list[str] = [self.category, self.definition, " ".join(self.subcategories)]
        for value in [
            self.positive_keywords_en,
            self.positive_keywords_fr,
            self.typical_actions,
            self.typical_objects,
            self.examples,
        ]:
            parts.extend(value or [])
        return " ".join(parts)


@dataclass(frozen=True)
class CategoryOverride:
    enabled: bool
    priority: int
    pattern: str
    match_mode: str
    applies_to: str
    primary_category: str
    secondary_categories: list[str]
    confidence: float
    reason: str


@dataclass
class CategoryDecision:
    primary_category: str
    secondary_categories: list[str]
    confidence: float
    method: str
    reason: str
    status: str
    scores: dict[str, float]

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


# Conservative built-in rules. They are not a replacement for the taxonomy file;
# they only prevent common high-impact mistakes observed in cybersecurity mappings.
BUILTIN_RULES: list[tuple[str, list[str], list[str], float, str]] = [
    ("11", ["pr.aa", "access right", "access rights", "accès", "droits d'accès", "droit d'accès", "identity", "identité", "authentication", "authentification", "authorization", "autorisation", "account", "compte", "privileg", "privilège", "habilitation", "remote access", "accès distant", "mfa", "multi-factor", "annuaire", "directory service"], ["training", "awareness", "formation", "sensibilisation"], 0.46, "access_control_rule"),
    ("9", ["cryptographic", "cryptographie", "cryptographique", "encryption", "encrypt", "chiffrement", "chiffrer", "key management", "gestion des clés", "clé cryptographique", "certificate", "certificat", "tls", "vpn"], [], 0.44, "cryptography_rule"),
    ("3", ["incident", "security event", "évènement de sécurité", "événement de sécurité", "event reporting", "notification d'incident", "incident response", "réponse à incident", "post-incident", "escalation", "escalade"], ["remote access", "accès distant"], 0.42, "incident_handling_rule"),
    ("4", ["business continuity", "continuité", "crisis", "crise", "backup", "sauvegarde", "restore", "restoration", "recovery", "reprise", "disaster", "rto", "rpo", "denial-of-service", "déni de service"], [], 0.42, "continuity_rule"),
    ("5", ["supplier", "supply chain", "third party", "third-party", "prestataire", "fournisseur", "sous-traitant", "outsourcing", "external provider", "contract", "contrat"], [], 0.40, "supply_chain_rule"),
    ("6", ["patch", "correctif", "vulnerability", "vulnérabilité", "maintenance", "mco", "mcs", "configuration", "hardening", "durcissement", "architecture", "segmentation", "network", "réseau", "development", "développement", "software", "firmware", "change management", "mise en production"], [], 0.39, "system_development_maintenance_rule"),
    ("7", ["effectiveness", "efficacité", "audit", "assessment", "évaluation", "review of measures", "independent review", "test de sécurité", "intrusion test", "control testing", "kpi", "indicator", "indicateur"], ["access review", "revue des droits"], 0.37, "effectiveness_assessment_rule"),
    ("8", ["training", "formation", "awareness", "sensibilisation", "cyber hygiene", "hygiène", "exercise", "exercice", "skills", "compétence"], ["incident response exercise", "business continuity exercise"], 0.40, "training_awareness_rule"),
    ("10", ["human resources", "ressources humaines", "onboarding", "offboarding", "arrivée", "départ", "screening", "background check", "personnel", "employee", "employé"], [], 0.38, "hr_security_rule"),
    ("12", ["asset", "actif", "inventory", "inventaire", "recensement", "cartography", "cartographie", "mapping", "cmdb", "list of systems", "liste des systèmes", "ecosystem mapping", "cartographie de l'écosystème"], ["supplier contract", "contrat fournisseur"], 0.38, "asset_management_rule"),
    ("13", ["physical", "physique", "environmental", "environnemental", "premises", "locaux", "server room", "salle serveur", "datacenter", "data center", "vidéosurveillance", "badge", "fire", "incendie", "climatisation"], [], 0.39, "physical_security_rule"),
    ("1", ["security policy", "politique de sécurité", "pssi", "roles", "rôles", "responsibilities", "responsabilités", "authorities", "gouvernance organisation", "governance organization"], [], 0.34, "security_policy_rule"),
    ("2", ["risk management", "gestion des risques", "risk analysis", "analyse de risque", "legal requirement", "regulatory requirement", "exigence réglementaire", "compliance", "conformité", "action plan", "plan d'action", "risk treatment"], [], 0.36, "risk_management_rule"),
]


def load_enisa_category_cards(app_cfg: AppConfig) -> list[EnisaCategoryCard]:
    path = app_cfg.enisa_category_file
    if not path.exists():
        raise FileNotFoundError(f"ENISA_CATEGORY_FILE not found: {path}")
    df = pd.read_excel(path, sheet_name=app_cfg.enisa_category_sheet or 0, dtype=str).fillna("")
    colmap = {_norm_col(c): c for c in df.columns}
    if "category" not in colmap:
        raise ValueError(f"{path.name} must contain a 'Category' column")

    def cell(row: Any, *names: str) -> str:
        for name in names:
            col = colmap.get(_norm_col(name))
            if col:
                return normalize_text(row.get(col))
        return ""

    cards: list[EnisaCategoryCard] = []
    for _, row in df.iterrows():
        category = cell(row, "Category")
        if not category:
            continue
        subcategories = _split_terms(cell(row, "Sub category", "Subcategory", "Subcategories"))
        number_match = re.match(r"^\s*(\d+)", category)
        number = number_match.group(1) if number_match else ""
        cards.append(
            EnisaCategoryCard(
                category=category,
                subcategories=subcategories,
                key=category_key(category),
                number=number,
                definition=cell(row, "Definition", "Description"),
                positive_keywords_en=_split_terms(cell(row, "Positive keywords EN", "Keywords EN", "Positive keywords")),
                positive_keywords_fr=_split_terms(cell(row, "Positive keywords FR", "Keywords FR")),
                negative_keywords=_split_terms(cell(row, "Negative keywords", "Exclusion keywords")),
                typical_actions=_split_terms(cell(row, "Typical actions", "Actions")),
                typical_objects=_split_terms(cell(row, "Typical objects", "Objects")),
                examples=_split_terms(cell(row, "Examples", "Positive examples")),
                counterexamples=_split_terms(cell(row, "Counterexamples", "Negative examples")),
                strict_rules=cell(row, "Strict rules", "Rules"),
            )
        )
    if not cards:
        raise ValueError(f"No ENISA categories found in {path}")
    return cards


def load_category_overrides(app_cfg: AppConfig) -> list[CategoryOverride]:
    path = getattr(app_cfg, "category_overrides_file", None)
    if not path or not Path(path).exists():
        return []
    df = pd.read_excel(path, sheet_name=0, dtype=str).fillna("")
    colmap = {_norm_col(c): c for c in df.columns}

    def cell(row: Any, *names: str) -> str:
        for name in names:
            col = colmap.get(_norm_col(name))
            if col:
                return normalize_text(row.get(col))
        return ""

    overrides: list[CategoryOverride] = []
    for _, row in df.iterrows():
        pattern = cell(row, "Pattern")
        primary = cell(row, "Primary category", "Force ENISA category")
        if not pattern or not primary:
            continue
        enabled_raw = cell(row, "Enabled") or "true"
        priority_raw = cell(row, "Priority") or "100"
        confidence_raw = cell(row, "Confidence") or "0.98"
        try:
            priority = int(float(priority_raw))
        except Exception:
            priority = 100
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.98
        overrides.append(
            CategoryOverride(
                enabled=enabled_raw.casefold() not in {"false", "0", "no", "non"},
                priority=priority,
                pattern=pattern,
                match_mode=(cell(row, "Match mode") or "contains").casefold(),
                applies_to=(cell(row, "Applies to") or "all").casefold(),
                primary_category=primary,
                secondary_categories=_split_terms(cell(row, "Secondary categories")),
                confidence=max(0.0, min(1.0, confidence)),
                reason=cell(row, "Reason") or f"override: {pattern}",
            )
        )
    return sorted([o for o in overrides if o.enabled], key=lambda o: o.priority, reverse=True)


def classify_requirement_category(
    *,
    framework: str,
    control_id: str,
    title: str,
    original_category: str,
    requirement: str,
    fields: dict[str, Any] | None,
    keywords: list[str] | None,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient | None = None,
    cards: list[EnisaCategoryCard] | None = None,
    overrides: list[CategoryOverride] | None = None,
) -> CategoryDecision:
    cards = cards or load_enisa_category_cards(app_cfg)
    overrides = overrides if overrides is not None else load_category_overrides(app_cfg)
    by_number = {c.number: c for c in cards if c.number}
    by_key = {c.key: c for c in cards}

    fields = fields or {}
    keywords = keywords or []
    text_parts = [framework, control_id, title, original_category, requirement, json.dumps(fields, ensure_ascii=False), " ".join(keywords)]
    full_text = normalize_text(" ".join(text_parts))
    full_lower = full_text.casefold()

    exact = by_key.get(category_key(original_category))
    if exact and not getattr(app_cfg, "category_harmonization_force", False):
        secondary = _secondary_from_scores(_score_categories(full_text, cards), exact.category, cards, app_cfg)
        return CategoryDecision(
            primary_category=exact.category,
            secondary_categories=secondary,
            confidence=1.0,
            method="already_enisa_category",
            reason="Original category already matches the configured ENISA taxonomy.",
            status="validated",
            scores={exact.category: 1.0},
        )

    override = _apply_overrides(full_lower, control_id, title, original_category, requirement, fields, keywords, overrides, cards)
    if override:
        return override

    scores = _score_categories(full_text, cards)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = ranked[0][0]
    top_score = ranked[0][1]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    confidence = _score_to_confidence(top_score, second_score)
    status = _status(confidence, top_score, second_score, app_cfg)
    secondary = _secondary_from_scores(scores, primary, cards, app_cfg)
    method = "deterministic_rules"
    reason = f"deterministic_top_score={top_score:.3f}; margin={top_score-second_score:.3f}"

    should_call_llm = (
        getattr(app_cfg, "category_harmonization_use_llm", True)
        and llm is not None
        and not getattr(app_cfg, "dry_run_without_llm", False)
        and (
            getattr(app_cfg, "category_harmonization_force", False)
            or confidence < getattr(app_cfg, "category_strong_confidence_threshold", 0.85)
            or (top_score - second_score) < getattr(app_cfg, "category_ambiguity_margin", 0.15)
        )
    )
    if should_call_llm:
        try:
            llm_decision = _llm_classify(
                framework=framework,
                control_id=control_id,
                title=title,
                original_category=original_category,
                requirement=requirement,
                fields=fields,
                keywords=keywords,
                ranked=ranked[:5],
                cards=cards,
                app_cfg=app_cfg,
                llm=llm,
            )
            if llm_decision.primary_category in {c.category for c in cards}:
                # Keep deterministic rescue categories as secondary when useful.
                merged_secondary = _merge_secondary(
                    llm_decision.primary_category,
                    llm_decision.secondary_categories + secondary,
                    cards,
                    getattr(app_cfg, "max_secondary_categories", 2),
                )
                llm_decision.secondary_categories = merged_secondary
                return llm_decision
        except Exception:
            # Silent fallback by design: category errors must not break the pipeline.
            reason += "; llm_category_fallback_failed"

    return CategoryDecision(
        primary_category=primary,
        secondary_categories=secondary,
        confidence=confidence,
        method=method,
        reason=reason,
        status=status,
        scores={k: round(v, 4) for k, v in ranked[:5]},
    )


def apply_category_decision_to_row(row: RequirementRow, decision: CategoryDecision, app_cfg: AppConfig) -> None:
    row.original_category = row.original_category or row.category
    row.category = decision.primary_category
    row.category_key = normalize_category(decision.primary_category, case_sensitive=app_cfg.category_case_sensitive, trim_spaces=app_cfg.category_trim_spaces)
    row.subcategory = ""
    row.category_harmonization_reason = f"{decision.method}: {decision.reason}"
    row.category_harmonization_confidence = decision.confidence
    # RequirementRow remains backward-compatible; secondary categories are applied at atomic level.


def apply_category_decision_to_atom(atom: AtomicRequirement, decision: CategoryDecision, app_cfg: AppConfig) -> None:
    atom.original_category = atom.original_category or atom.category
    atom.category = decision.primary_category
    atom.category_key = normalize_category(decision.primary_category, case_sensitive=app_cfg.category_case_sensitive, trim_spaces=app_cfg.category_trim_spaces)
    atom.subcategory = ""
    atom.primary_category = decision.primary_category
    atom.secondary_categories = decision.secondary_categories
    atom.category_confidence = decision.confidence
    atom.category_status = decision.status
    atom.category_reason = decision.reason
    atom.category_method = decision.method
    atom.category_scores = decision.scores
    atom.category_harmonization_reason = f"{decision.method}: {decision.reason}"
    atom.category_harmonization_confidence = decision.confidence


def repair_atoms_categories(
    atoms: list[AtomicRequirement],
    framework_cfg: FrameworkConfig,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient | None,
    logger: JsonlRunLogger | None = None,
    *,
    save_cache: bool = True,
) -> list[AtomicRequirement]:
    """Repair only category metadata in processed atoms.

    It preserves atomization, extracted fields, keyword text and embeddings. This is the
    safe way to fix the taxonomy without paying for a full preprocessing run.
    """
    if not getattr(app_cfg, "enable_category_harmonization", True):
        return atoms

    cards = load_enisa_category_cards(app_cfg)
    overrides = load_category_overrides(app_cfg)
    cdir = cache_dir(framework_cfg, app_cfg)
    cdir.mkdir(parents=True, exist_ok=True)
    decision_cache_path = cdir / "atomic_category_harmonization.json"
    decision_cache = _load_json(decision_cache_path)

    changed = 0
    repaired = 0
    skipped = 0
    low_conf_before = 0
    low_conf_after = 0
    only_low = getattr(app_cfg, "repair_only_low_confidence_categories", False)
    threshold = getattr(app_cfg, "category_strong_confidence_threshold", 0.85)

    for atom in atoms:
        old_category = atom.category
        old_conf = float(getattr(atom, "category_confidence", 0.0) or getattr(atom, "category_harmonization_confidence", 0.0) or 0.0)
        if old_conf < threshold:
            low_conf_before += 1
        if only_low and old_conf >= threshold and getattr(atom, "primary_category", ""):
            skipped += 1
            continue

        key = _atom_decision_cache_key(atom, cards)
        cached = decision_cache.get(key)
        if cached and not getattr(app_cfg, "category_harmonization_force", False):
            decision = _decision_from_cache(cached)
        else:
            decision = classify_requirement_category(
                framework=atom.framework,
                control_id=atom.parent_id or atom.atomic_id,
                title=atom.title,
                original_category=atom.original_category or atom.category,
                requirement=atom.atomic_requirement,
                fields=atom.fields,
                keywords=atom.keywords,
                app_cfg=app_cfg,
                llm=llm,
                cards=cards,
                overrides=overrides,
            )
            decision_cache[key] = decision.as_json()
        apply_category_decision_to_atom(atom, decision, app_cfg)
        repaired += 1
        if atom.category != old_category:
            changed += 1
        if atom.category_confidence < threshold:
            low_conf_after += 1

    _save_json(decision_cache_path, decision_cache)
    report = build_category_quality_report(atoms, framework_cfg.name)
    _save_json(cdir / "category_quality_report.json", report)
    if getattr(app_cfg, "category_report_enabled", True):
        write_category_quality_report_xlsx(report, app_cfg.report_dir / f"category_quality_{framework_cfg.name}.xlsx")

    if save_cache:
        _save_atoms_json(cdir / FULL_CACHE_FILE, atoms)
        # Keep the fields checkpoint consistent so future cache repairs and runs do not reload stale categories.
        if (cdir / FIELDS_CACHE_FILE).exists():
            _save_atoms_json(cdir / FIELDS_CACHE_FILE, atoms)
        if (cdir / ATOMIZED_CACHE_FILE).exists():
            # Atomized cache may not contain fields/embeddings; updating it with full atoms is acceptable and safer
            # than keeping stale categories.
            _save_atoms_json(cdir / ATOMIZED_CACHE_FILE, atoms)

    if logger:
        logger.event(
            "category_repair.done",
            framework=framework_cfg.name,
            atoms=len(atoms),
            repaired=repaired,
            skipped=skipped,
            changed=changed,
            low_confidence_before=low_conf_before,
            low_confidence_after=low_conf_after,
            overrides=len(overrides),
        )
    return atoms


def build_category_quality_report(atoms: list[AtomicRequirement], framework_name: str) -> dict[str, Any]:
    from collections import Counter

    total = len(atoms)
    by_category = Counter(a.category for a in atoms)
    by_status = Counter(getattr(a, "category_status", "") or "unknown" for a in atoms)
    low_conf = [a for a in atoms if float(getattr(a, "category_confidence", 0.0) or 0.0) < 0.60]
    medium_conf = [a for a in atoms if 0.60 <= float(getattr(a, "category_confidence", 0.0) or 0.0) < 0.85]
    changed = [a for a in atoms if (a.original_category or "") and (a.original_category != a.category)]
    multi = [a for a in atoms if getattr(a, "category_status", "") == "multi_domain" or bool(getattr(a, "secondary_categories", []))]
    return {
        "framework": framework_name,
        "total_atoms": total,
        "category_distribution": dict(by_category),
        "status_distribution": dict(by_status),
        "low_confidence_count": len(low_conf),
        "medium_confidence_count": len(medium_conf),
        "changed_count": len(changed),
        "multi_domain_count": len(multi),
        "quality_gate": {
            "low_confidence_rate": round(len(low_conf) / max(total, 1), 4),
            "medium_confidence_rate": round(len(medium_conf) / max(total, 1), 4),
            "changed_rate": round(len(changed) / max(total, 1), 4),
            "recommended_match_scope": "soft_enisa" if len(low_conf) / max(total, 1) > 0.03 else "soft_enisa",
        },
        "low_confidence_examples": [_atom_report_row(a) for a in low_conf[:200]],
        "changed_examples": [_atom_report_row(a) for a in changed[:200]],
        "multi_domain_examples": [_atom_report_row(a) for a in multi[:200]],
    }


def write_category_quality_report_xlsx(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_summary = [
        ["Framework", report.get("framework")],
        ["Total atoms", report.get("total_atoms")],
        ["Low confidence count", report.get("low_confidence_count")],
        ["Medium confidence count", report.get("medium_confidence_count")],
        ["Changed count", report.get("changed_count")],
        ["Multi-domain count", report.get("multi_domain_count")],
        ["Recommended match scope", report.get("quality_gate", {}).get("recommended_match_scope")],
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows_summary, columns=["Metric", "Value"]).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(
            sorted(report.get("category_distribution", {}).items(), key=lambda x: x[0]),
            columns=["Category", "Atoms"],
        ).to_excel(writer, sheet_name="Distribution", index=False)
        for key, sheet in [
            ("low_confidence_examples", "Low confidence"),
            ("changed_examples", "Changed"),
            ("multi_domain_examples", "Multi-domain"),
        ]:
            pd.DataFrame(report.get(key, [])).to_excel(writer, sheet_name=sheet, index=False)


def category_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value).casefold()).strip()


def taxonomy_hash(cards: list[EnisaCategoryCard]) -> str:
    payload = [asdict(c) for c in cards]
    return stable_hash(payload)[:12]


def _norm_col(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _split_terms(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, tuple):
        raw = list(value)
    else:
        raw = re.split(r"[\n;|,]+", str(value))
    out: list[str] = []
    for item in raw:
        text = normalize_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _resolve_category(value: str, cards: list[EnisaCategoryCard]) -> str | None:
    key = category_key(value)
    for card in cards:
        if card.key == key:
            return card.category
    number_match = re.match(r"^\s*(\d+)", value or "")
    if number_match:
        number = number_match.group(1)
        for card in cards:
            if card.number == number:
                return card.category
    return None


def _apply_overrides(
    full_lower: str,
    control_id: str,
    title: str,
    original_category: str,
    requirement: str,
    fields: dict[str, Any],
    keywords: list[str],
    overrides: list[CategoryOverride],
    cards: list[EnisaCategoryCard],
) -> CategoryDecision | None:
    contexts = {
        "all": full_lower,
        "id": control_id.casefold(),
        "control_id": control_id.casefold(),
        "title": title.casefold(),
        "original_category": original_category.casefold(),
        "category": original_category.casefold(),
        "requirement": requirement.casefold(),
        "text": requirement.casefold(),
        "fields": json.dumps(fields, ensure_ascii=False).casefold(),
        "keywords": " ".join(keywords).casefold(),
    }
    for override in overrides:
        context = contexts.get(override.applies_to, full_lower)
        pattern = override.pattern.casefold()
        matched = False
        try:
            if override.match_mode == "regex":
                matched = bool(re.search(override.pattern, context, flags=re.IGNORECASE))
            elif override.match_mode == "exact":
                matched = context.strip() == pattern.strip()
            else:
                matched = pattern in context
        except Exception:
            matched = pattern in context
        if not matched:
            continue
        primary = _resolve_category(override.primary_category, cards)
        if not primary:
            continue
        secondary = _merge_secondary(primary, override.secondary_categories, cards, max_items=2)
        return CategoryDecision(
            primary_category=primary,
            secondary_categories=secondary,
            confidence=override.confidence,
            method="override",
            reason=override.reason,
            status="validated" if override.confidence >= 0.85 else "medium_confidence",
            scores={primary: override.confidence},
        )
    return None


def _score_categories(text: str, cards: list[EnisaCategoryCard]) -> dict[str, float]:
    text_lower = normalize_text(text).casefold()
    source_tokens = set(tokenize(text_lower))
    scores: dict[str, float] = {}
    for card in cards:
        card_text = normalize_text(card.searchable_text()).casefold()
        card_tokens = set(tokenize(card_text))
        inter = len(source_tokens & card_tokens)
        union = len(source_tokens | card_tokens) or 1
        score = 0.18 * (inter / union)

        # Positive keyword / action / object hits.
        for group, weight in [
            ((card.positive_keywords_en or []) + (card.positive_keywords_fr or []), 0.075),
            (card.typical_actions or [], 0.045),
            (card.typical_objects or [], 0.050),
            (card.examples or [], 0.055),
            (card.subcategories or [], 0.030),
        ]:
            for term in group:
                term_norm = normalize_text(term).casefold()
                if term_norm and term_norm in text_lower:
                    score += weight

        for term in card.negative_keywords or []:
            term_norm = normalize_text(term).casefold()
            if term_norm and term_norm in text_lower:
                score -= 0.10
        for term in card.counterexamples or []:
            term_norm = normalize_text(term).casefold()
            if term_norm and term_norm in text_lower:
                score -= 0.08

        # Number/name hints from original category text.
        if card.number and re.search(rf"\b{re.escape(card.number)}\b", text_lower):
            score += 0.16
        if card.category.casefold() in text_lower:
            score += 0.18

        # Built-in strict boosts.
        for number, positives, negatives, boost, _name in BUILTIN_RULES:
            if card.number != number:
                continue
            if any(n.casefold() in text_lower for n in negatives):
                continue
            if any(p.casefold() in text_lower for p in positives):
                score += boost

        scores[card.category] = max(0.0, min(1.25, score))
    return scores


def _score_to_confidence(top_score: float, second_score: float) -> float:
    margin = max(0.0, top_score - second_score)
    confidence = 0.34 + min(0.46, top_score * 0.55) + min(0.20, margin * 0.90)
    return max(0.0, min(0.98, confidence))


def _status(confidence: float, top_score: float, second_score: float, app_cfg: AppConfig) -> str:
    strong = getattr(app_cfg, "category_strong_confidence_threshold", 0.85)
    medium = getattr(app_cfg, "category_medium_confidence_threshold", 0.60)
    margin = getattr(app_cfg, "category_ambiguity_margin", 0.15)
    if (top_score - second_score) < margin and second_score > 0.25:
        return "multi_domain"
    if confidence >= strong:
        return "validated"
    if confidence >= medium:
        return "medium_confidence"
    return "low_confidence"


def _secondary_from_scores(scores: dict[str, float], primary: str, cards: list[EnisaCategoryCard], app_cfg: AppConfig) -> list[str]:
    max_items = getattr(app_cfg, "max_secondary_categories", 2)
    if max_items <= 0:
        return []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary_score = scores.get(primary, 0.0)
    secondary: list[str] = []
    for category, score in ranked:
        if category == primary:
            continue
        if score >= 0.25 and (primary_score - score) <= 0.28:
            secondary.append(category)
        if len(secondary) >= max_items:
            break
    return secondary


def _merge_secondary(primary: str, values: list[str], cards: list[EnisaCategoryCard], max_items: int) -> list[str]:
    merged: list[str] = []
    for value in values:
        resolved = _resolve_category(value, cards)
        if resolved and resolved != primary and resolved not in merged:
            merged.append(resolved)
        if len(merged) >= max_items:
            break
    return merged


def _llm_classify(
    *,
    framework: str,
    control_id: str,
    title: str,
    original_category: str,
    requirement: str,
    fields: dict[str, Any],
    keywords: list[str],
    ranked: list[tuple[str, float]],
    cards: list[EnisaCategoryCard],
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
) -> CategoryDecision:
    card_payload = []
    top_names = {name for name, _ in ranked[:5]}
    # Provide all categories but emphasize top deterministic candidates.
    for card in cards:
        card_payload.append({
            "category": card.category,
            "definition": card.definition,
            "subcategories": card.subcategories,
            "positive_keywords_en": card.positive_keywords_en or [],
            "positive_keywords_fr": card.positive_keywords_fr or [],
            "negative_keywords": card.negative_keywords or [],
            "typical_actions": card.typical_actions or [],
            "typical_objects": card.typical_objects or [],
            "examples": card.examples or [],
            "counterexamples": card.counterexamples or [],
            "deterministic_score": next((round(score, 4) for name, score in ranked if name == card.category), 0.0),
            "is_top_deterministic_candidate": card.category in top_names,
        })
    prompt = render_prompt(
        app_cfg.prompt_category_harmonization,
        framework=framework,
        control_id=control_id,
        title=title,
        original_category=original_category,
        requirement=requirement,
        fields=json.dumps(fields, ensure_ascii=False),
        keywords=json.dumps(keywords, ensure_ascii=False),
        enisa_categories=json.dumps(card_payload, ensure_ascii=False, indent=2),
        deterministic_candidates=json.dumps([{"category": n, "score": round(s, 4)} for n, s in ranked[:5]], ensure_ascii=False),
    )
    result = llm.generate_json(prompt, model=app_cfg.azure_openai_category_deployment)
    if not isinstance(result, dict):
        raise ValueError("Invalid LLM category response")
    primary = _resolve_category(str(result.get("primary_category") or result.get("category") or ""), cards)
    if not primary:
        raise ValueError("LLM returned an invalid category")
    raw_secondary = result.get("secondary_categories") or result.get("secondary_category") or []
    if isinstance(raw_secondary, str):
        raw_secondary = _split_terms(raw_secondary)
    secondary = _merge_secondary(primary, [str(x) for x in raw_secondary if str(x).strip()], cards, getattr(app_cfg, "max_secondary_categories", 2))
    try:
        confidence = float(result.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    status = str(result.get("status") or "").strip() or ("validated" if confidence >= 0.85 else "medium_confidence" if confidence >= 0.60 else "low_confidence")
    reason = normalize_text(result.get("reason") or "llm_category_harmonization")
    return CategoryDecision(
        primary_category=primary,
        secondary_categories=secondary,
        confidence=confidence,
        method="llm_constrained",
        reason=reason,
        status=status,
        scores={k: round(v, 4) for k, v in ranked[:5]},
    )


def _atom_decision_cache_key(atom: AtomicRequirement, cards: list[EnisaCategoryCard]) -> str:
    payload = {
        "taxonomy": taxonomy_hash(cards),
        "id": atom.atomic_id,
        "parent_id": atom.parent_id,
        "original_category": atom.original_category or atom.category,
        "requirement": atom.atomic_requirement,
        "fields": atom.fields,
        "keywords": atom.keywords,
    }
    return stable_hash(payload)


def _decision_from_cache(data: dict[str, Any]) -> CategoryDecision:
    return CategoryDecision(
        primary_category=str(data.get("primary_category") or data.get("category") or ""),
        secondary_categories=[str(x) for x in data.get("secondary_categories", []) if str(x).strip()] if isinstance(data.get("secondary_categories"), list) else _split_terms(str(data.get("secondary_categories") or "")),
        confidence=float(data.get("confidence") or 0.0),
        method=str(data.get("method") or "cache"),
        reason=str(data.get("reason") or "cache"),
        status=str(data.get("status") or ""),
        scores=data.get("scores") if isinstance(data.get("scores"), dict) else {},
    )


def _atom_report_row(atom: AtomicRequirement) -> dict[str, Any]:
    return {
        "atomic_id": atom.atomic_id,
        "parent_id": atom.parent_id,
        "original_category": atom.original_category,
        "primary_category": atom.category,
        "secondary_categories": "; ".join(getattr(atom, "secondary_categories", []) or []),
        "confidence": getattr(atom, "category_confidence", 0.0),
        "status": getattr(atom, "category_status", ""),
        "method": getattr(atom, "category_method", ""),
        "reason": getattr(atom, "category_reason", ""),
        "text": atom.atomic_requirement[:500],
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _save_atoms_json(path: Path, atoms: list[AtomicRequirement]) -> None:
    from dataclasses import asdict

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump([asdict(a) for a in atoms], fh, ensure_ascii=False, indent=2)
