"""Executive-summary PDF for a mapping run.

Excel remains the full-detail deliverable; the PDF is a concise management summary
(KPIs + the most material gaps). Built with reportlab (pure Python, no system deps).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from src.models import MappingDecision

_NAVY = colors.HexColor("#17365D")
_BLUE = colors.HexColor("#1F4E78")
_LIGHT = colors.HexColor("#D9EAF7")
_GREY = colors.HexColor("#F2F2F2")


def _parent_rows(decisions: list[MappingDecision]) -> list[tuple[str, str, float]]:
    """Aggregate atomic decisions to (parent_id, category, avg_coverage)."""
    groups: dict[str, list[MappingDecision]] = defaultdict(list)
    for d in decisions:
        pid = d.source_parent_id or d.source_id.rsplit("#", 1)[0]
        groups[pid].append(d)
    rows = []
    for pid, items in groups.items():
        avg = sum(i.coverage_level for i in items) / max(len(items), 1)
        category = next((i.source_category for i in items if i.source_category), "")
        rows.append((pid, category, round(avg, 1)))
    return rows


def generate_mapping_pdf(
    *,
    source_name: str,
    target_name: str,
    run_id: str,
    summary: dict,
    a_to_b: list[MappingDecision],
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"summary_{run_id}.pdf"

    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], textColor=_NAVY, fontSize=20)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=_BLUE, fontSize=13, spaceBefore=10)
    normal = styles["BodyText"]

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"Synthèse mapping {source_name} → {target_name}")
    flow = []

    flow.append(Paragraph("Synthèse de conformité NIS2", title))
    flow.append(Paragraph(f"<b>{source_name}</b> &rarr; <b>{target_name}</b>", normal))
    flow.append(Paragraph(f"Généré le {datetime.now():%Y-%m-%d %H:%M} · Run {run_id}", normal))
    flow.append(Spacer(1, 8 * mm))

    # --- KPIs ---
    flow.append(Paragraph("Indicateurs clés", h2))
    kpi_data = [
        ["Couverture moyenne", f"{summary.get('average_coverage', 0)}%"],
        ["Décisions analysées", str(summary.get("atomic_decisions", 0))],
        ["Écarts (couverture 0)", str(summary.get("gaps", 0))],
    ]
    kpi = Table(kpi_data, colWidths=[80 * mm, 80 * mm])
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), _LIGHT),
        ("TEXTCOLOR", (0, 0), (0, -1), _NAVY),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [_GREY, _GREY]),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(kpi)
    flow.append(Spacer(1, 6 * mm))

    # --- Most material gaps (lowest-covered parent requirements) ---
    flow.append(Paragraph(f"Écarts prioritaires — {source_name} couvert par {target_name}", h2))
    rows = sorted(_parent_rows(a_to_b), key=lambda r: r[2])[:20]
    table_data = [["Exigence source", "Catégorie ENISA", "Couverture"]]
    for pid, category, cov in rows:
        table_data.append([Paragraph(pid, normal), Paragraph(category or "—", normal), f"{cov:.0f}%"])
    gaps_table = Table(table_data, colWidths=[45 * mm, 90 * mm, 25 * mm], repeatRows=1)
    gaps_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E2F3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY]),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(gaps_table)

    doc.build(flow)
    return path
