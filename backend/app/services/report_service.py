from io import BytesIO
from fpdf import FPDF
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tempfile
import os
import re


def _sanitize_text(text: str) -> str:
    """Replace Unicode characters unsupported by standard PDF fonts with ASCII equivalents."""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    replacements = {
        "\u2018": "'", "\u2019": "'",   # smart single quotes
        "\u201c": '"', "\u201d": '"',   # smart double quotes
        "\u2013": "-", "\u2014": "--",  # en-dash, em-dash
        "\u2010": "-", "\u2011": "-",   # hyphens
        "\u2012": "-", "\u2015": "--",  # figure dash, horizontal bar
        "\u2022": "*",                  # bullet
        "\u2026": "...",                # ellipsis
        "\u00a0": " ",                  # non-breaking space
        "\u2032": "'", "\u2033": '"',   # prime, double prime
        "\u2190": "<-", "\u2192": "->", # arrows
        "\u2264": "<=", "\u2265": ">=", # comparison
        "\u2260": "!=",                 # not equal
        "\u00b7": "*",                  # middle dot
        "\u200b": "",                   # zero-width space
        "\u200e": "", "\u200f": "",     # directional marks
        "\ufeff": "",                   # BOM
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Remove any remaining non-latin-1 characters
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


# ── Chart Generators ──────────────────────────────────

def _create_radar_chart(scores: dict) -> str:
    """Create a radar/spider chart of the 5 score components. Returns temp file path."""
    categories = ["Content", "Keyword", "Depth", "Communication", "Confidence"]
    values = [
        scores.get("content_score", 0),
        scores.get("keyword_score", 0),
        scores.get("depth_score", 0),
        scores.get("communication_score", 0),
        scores.get("confidence_score", 0),
    ]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    values_plot = values + [values[0]]
    angles += [angles[0]]

    fig, ax = plt.subplots(figsize=(4.5, 4.5), subplot_kw=dict(polar=True))
    ax.fill(angles, values_plot, color="#667eea", alpha=0.25)
    ax.plot(angles, values_plot, color="#667eea", linewidth=2, marker="o", markersize=6)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=9, fontweight="bold")
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=7, color="grey")
    ax.set_title("Skills Radar", fontsize=13, fontweight="bold", pad=20, color="#333")

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight", transparent=False)
    plt.close(fig)
    return tmp.name


def _create_question_bar_chart(evaluations: list) -> str:
    """Bar chart of per-question overall scores. Returns temp file path."""
    labels = [f"Q{i+1}" for i in range(len(evaluations))]
    overall = [e.get("scores", {}).get("overall_score", 0) for e in evaluations]
    colors = ["#22c55e" if s >= 70 else "#f59e0b" if s >= 40 else "#ef4444" for s in overall]

    fig, ax = plt.subplots(figsize=(max(5, len(labels) * 0.8), 3.5))
    bars = ax.bar(labels, overall, color=colors, edgecolor="white", linewidth=0.5, width=0.6)

    for bar, score in zip(bars, overall):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{score:.0f}", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax.set_ylim(0, 110)
    ax.set_ylabel("Score", fontsize=10)
    ax.set_title("Question-wise Scores", fontsize=12, fontweight="bold", color="#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.axhline(y=70, color="#22c55e", linestyle="--", linewidth=0.8, alpha=0.5)
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


def _create_round_comparison_chart(round_summary: dict) -> str:
    """Side-by-side bar chart comparing Technical vs HR round scores."""
    tech = round_summary.get("technical", {})
    hr = round_summary.get("hr", {})

    categories = ["Score", "Questions Asked"]
    tech_vals = [tech.get("score", 0), tech.get("questions_asked", 0)]
    hr_vals = [hr.get("score", 0), hr.get("questions_asked", 0)]

    fig, axes = plt.subplots(1, 2, figsize=(6, 3))

    # Score comparison
    ax1 = axes[0]
    bars1 = ax1.bar(["Technical", "HR"], [tech.get("score", 0), hr.get("score", 0)],
                    color=["#667eea", "#f093fb"], edgecolor="white", width=0.5)
    for bar in bars1:
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{bar.get_height():.1f}", ha="center", fontsize=9, fontweight="bold")
    ax1.set_ylim(0, 110)
    ax1.set_title("Round Scores", fontsize=11, fontweight="bold")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.axhline(y=70, color="green", linestyle="--", linewidth=0.7, alpha=0.4)

    # Questions count
    ax2 = axes[1]
    bars2 = ax2.bar(["Technical", "HR"],
                    [tech.get("questions_asked", 0), hr.get("questions_asked", 0)],
                    color=["#667eea", "#f093fb"], edgecolor="white", width=0.5)
    for bar in bars2:
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                 f"{int(bar.get_height())}", ha="center", fontsize=9, fontweight="bold")
    ax2.set_title("Questions Asked", fontsize=11, fontweight="bold")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    # Status labels
    tech_label = "PASS" if tech.get("passed") else "FAIL"
    hr_label = "PASS" if hr.get("passed") else "FAIL"
    fig.suptitle(f"Technical: {tech_label}  |  HR: {hr_label}", fontsize=10,
                 color="#555", y=0.02)
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


def _create_score_components_chart(scores: dict) -> str:
    """Horizontal bar chart showing all score components."""
    labels = ["Content", "Keyword", "Depth", "Communication", "Confidence", "Overall"]
    values = [
        scores.get("content_score", 0),
        scores.get("keyword_score", 0),
        scores.get("depth_score", 0),
        scores.get("communication_score", 0),
        scores.get("confidence_score", 0),
        scores.get("overall_score", 0),
    ]
    colors = ["#667eea", "#764ba2", "#f093fb", "#5ee7df", "#b8cbb8", "#0acffe"]

    fig, ax = plt.subplots(figsize=(6, 3))
    bars = ax.barh(labels, values, color=colors, edgecolor="white", height=0.55)

    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1.5, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", fontsize=9, fontweight="bold")

    ax.set_xlim(0, 110)
    ax.set_title("Score Components Breakdown", fontsize=12, fontweight="bold", color="#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.axvline(x=70, color="green", linestyle="--", linewidth=0.7, alpha=0.5)
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


# ── Progress bar helper ───────────────────────────────

def _draw_progress_bar(pdf, x, y, width, height, pct, color_rgb):
    """Draw a filled progress bar on the PDF."""
    pdf.set_draw_color(200, 200, 200)
    pdf.set_fill_color(230, 230, 230)
    pdf.rect(x, y, width, height, "DF")
    fill_w = width * min(pct / 100, 1.0)
    if fill_w > 0:
        pdf.set_fill_color(*color_rgb)
        pdf.rect(x, y, fill_w, height, "F")


# ── Main PDF Generator ───────────────────────────────

def _sanitize_report(obj):
    """Recursively sanitize all strings in the report data structure."""
    if isinstance(obj, str):
        return _sanitize_text(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_report(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_report(v) for v in obj]
    return obj


def generate_pdf_report(report: dict) -> bytes:
    """Generate a professional PDF performance report with matplotlib charts."""
    report = _sanitize_report(report)
    chart_files = []

    try:
        # Generate all charts first
        scores = report.get("overall_scores", {})
        evaluations = report.get("question_evaluations", [])
        round_summary = report.get("round_summary", {})

        chart_files.append(_create_radar_chart(scores))
        if evaluations:
            chart_files.append(_create_question_bar_chart(evaluations))
        chart_files.append(_create_round_comparison_chart(round_summary))
        chart_files.append(_create_score_components_chart(scores))

        # ── Build PDF ─────────────────────────────────
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        # ══════════════════════════════════════════════
        # PAGE 1: Title, Info, Scores, Radar Chart
        # ══════════════════════════════════════════════
        pdf.add_page()

        # Header bar
        pdf.set_fill_color(102, 126, 234)
        pdf.rect(0, 0, 210, 35, "F")
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_text_color(255, 255, 255)
        pdf.set_y(8)
        pdf.cell(0, 12, "Interview Performance Report", ln=True, align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, datetime.now().strftime("%B %d, %Y"), ln=True, align="C")
        pdf.ln(10)

        # Candidate info box
        pdf.set_draw_color(102, 126, 234)
        pdf.set_fill_color(245, 247, 255)
        pdf.rect(10, pdf.get_y(), 190, 28, "DF")
        info_y = pdf.get_y() + 3
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(51, 51, 51)
        pdf.set_xy(15, info_y)
        pdf.cell(90, 7, f"Candidate: {report.get('candidate_name', 'N/A')}")
        pdf.cell(0, 7, f"Role: {report.get('job_role', 'N/A')}", ln=True)
        pdf.set_x(15)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(90, 7, f"Total Questions: {report.get('total_questions', 0)}")
        overall = report.get('overall_score', scores.get('overall_score', 0))
        rec = report.get("recommendation", "N/A")
        pdf.cell(0, 7, f"Recommendation: {rec}", ln=True)
        pdf.ln(8)

        # Overall score with progress bars
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(102, 126, 234)
        pdf.cell(0, 10, "Overall Scores", ln=True)
        pdf.set_draw_color(102, 126, 234)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        score_items = [
            ("Content", scores.get("content_score", 0)),
            ("Keyword Coverage", scores.get("keyword_score", 0)),
            ("Depth", scores.get("depth_score", 0)),
            ("Communication", scores.get("communication_score", 0)),
            ("Confidence", scores.get("confidence_score", 0)),
            ("OVERALL", scores.get("overall_score", 0)),
        ]

        for label, val in score_items:
            is_overall = label == "OVERALL"
            pdf.set_font("Helvetica", "B" if is_overall else "", 11 if is_overall else 10)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(55, 7, label)

            bar_y = pdf.get_y() + 1.5
            color = (34, 139, 34) if val >= 70 else (255, 165, 0) if val >= 40 else (220, 20, 60)
            _draw_progress_bar(pdf, 65, bar_y, 100, 4, val, color)

            pdf.set_x(170)
            pdf.set_text_color(*color)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, f"{val:.1f}%", ln=True)
        pdf.ln(3)

        # Radar chart
        if chart_files[0] and os.path.exists(chart_files[0]):
            remaining = 297 - pdf.get_y() - 15
            img_h = min(remaining, 75)
            if img_h > 30:
                pdf.image(chart_files[0], x=55, w=100, h=img_h)

        # ══════════════════════════════════════════════
        # PAGE 2: Round Comparison + Score Components + Strengths/Weaknesses
        # ══════════════════════════════════════════════
        pdf.add_page()

        # Round comparison chart
        round_chart_idx = 2  # index of round comparison chart
        if len(chart_files) > round_chart_idx and os.path.exists(chart_files[round_chart_idx]):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 10, "Round Comparison", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)
            pdf.image(chart_files[round_chart_idx], x=15, w=180, h=55)
            pdf.ln(5)

        # Score components chart
        score_chart_idx = 3  # index of score components chart
        if len(chart_files) > score_chart_idx and os.path.exists(chart_files[score_chart_idx]):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 10, "Score Breakdown", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)
            pdf.image(chart_files[score_chart_idx], x=15, w=180, h=55)
            pdf.ln(5)

        # Strengths
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(34, 139, 34)
        pdf.cell(0, 9, ">> Strengths", ln=True)
        pdf.set_draw_color(34, 139, 34)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 51, 51)
        for s in report.get("strengths", []):
            pdf.cell(0, 6, f"  [+] {s}", ln=True)
        pdf.ln(3)

        # Weaknesses
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(220, 20, 60)
        pdf.cell(0, 9, ">> Areas for Improvement", ln=True)
        pdf.set_draw_color(220, 20, 60)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 51, 51)
        for w in report.get("weaknesses", []):
            pdf.cell(0, 6, f"  [-] {w}", ln=True)
        pdf.ln(3)

        # Suggestions
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(255, 140, 0)
        pdf.cell(0, 9, ">> Improvement Suggestions", ln=True)
        pdf.set_draw_color(255, 140, 0)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 51, 51)
        for idx, s in enumerate(report.get("improvement_suggestions", []), 1):
            pdf.cell(0, 6, f"  {idx}. {s}", ln=True)
        pdf.ln(3)

        # Communication & Confidence feedback
        comm = report.get("communication_feedback", "")
        conf = report.get("confidence_analysis", "")
        if comm or conf:
            if pdf.get_y() > 240:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 9, ">> Communication & Confidence", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(51, 51, 51)
            if comm:
                pdf.set_x(10)
                pdf.multi_cell(190, 6, f"Communication: {comm}")
            if conf:
                pdf.set_x(10)
                pdf.multi_cell(190, 6, f"Confidence: {conf}")

        # ══════════════════════════════════════════════
        # EXPLAINABILITY: Dimension Analysis (SHAP-based)
        # ══════════════════════════════════════════════
        explainability = report.get("explainability")
        if explainability:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 10, "AI-Powered Performance Analysis", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)

            # Explanation text
            explanation = explainability.get("explanation", "")
            if explanation:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(51, 51, 51)
                pdf.set_x(10)
                pdf.multi_cell(190, 6, explanation)
                pdf.ln(3)

            # Dimension scores table
            dim_scores = explainability.get("dimension_scores", {})
            if dim_scores:
                pdf.set_font("Helvetica", "B", 12)
                pdf.set_text_color(102, 126, 234)
                pdf.cell(0, 8, "Dimension Breakdown", ln=True)
                pdf.ln(2)

                for dim_name, dim_data in dim_scores.items():
                    dim_score = dim_data.get("score", 0)
                    dim_grade = dim_data.get("grade", "N/A")
                    grade_color = (34, 139, 34) if dim_score >= 70 else (255, 165, 0) if dim_score >= 50 else (220, 20, 60)

                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(51, 51, 51)
                    pdf.cell(55, 7, dim_name)

                    bar_y = pdf.get_y() + 1.5
                    _draw_progress_bar(pdf, 65, bar_y, 80, 4, dim_score, grade_color)

                    pdf.set_x(150)
                    pdf.set_text_color(*grade_color)
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.cell(25, 7, f"{dim_score:.0f}%")
                    pdf.set_font("Helvetica", "", 9)
                    pdf.cell(0, 7, dim_grade, ln=True)
                pdf.ln(3)

            # Top positive factors
            top_pos = explainability.get("top_positive_factors", [])
            if top_pos:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(34, 139, 34)
                pdf.cell(0, 7, "Key Strengths (AI-detected)", ln=True)
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(51, 51, 51)
                for factor in top_pos[:4]:
                    fname = factor.get("feature", "").replace("_", " ").title()
                    pdf.cell(0, 6, f"  [+] {fname} (impact: +{factor.get('impact', 0):.2f})", ln=True)
                pdf.ln(2)

            # Top negative factors
            top_neg = explainability.get("top_negative_factors", [])
            if top_neg:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(220, 20, 60)
                pdf.cell(0, 7, "Key Weaknesses (AI-detected)", ln=True)
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(51, 51, 51)
                for factor in top_neg[:4]:
                    fname = factor.get("feature", "").replace("_", " ").title()
                    pdf.cell(0, 6, f"  [-] {fname} (impact: {factor.get('impact', 0):.2f})", ln=True)
                pdf.ln(2)

            # Targeted improvement suggestions from explainability
            expl_suggestions = explainability.get("improvement_suggestions", [])
            if expl_suggestions:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(255, 140, 0)
                pdf.cell(0, 7, "Targeted Improvement Actions", ln=True)
                pdf.ln(1)
                for sug in expl_suggestions[:6]:
                    if pdf.get_y() > 260:
                        pdf.add_page()
                    category = sug.get("category", "General")
                    priority = sug.get("priority", "medium").upper()
                    cur_score = sug.get("current_score", 0)
                    suggestion_text = sug.get("suggestion", "")
                    p_color = (220, 20, 60) if priority == "HIGH" else (255, 140, 0) if priority == "MEDIUM" else (100, 100, 100)

                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_text_color(*p_color)
                    pdf.cell(0, 6, f"  [{priority}] {category} (current: {cur_score:.0f}%)", ln=True)
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(51, 51, 51)
                    pdf.set_x(14)
                    pdf.multi_cell(186, 5, suggestion_text)
                    pdf.ln(1)

        # ══════════════════════════════════════════════
        # DEVELOPMENT ROADMAP: 4-Phase Improvement Plan
        # ══════════════════════════════════════════════
        roadmap = report.get("development_roadmap")
        if roadmap:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 10, "Personalized Development Roadmap", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)

            # Candidate profile summary
            profile = roadmap.get("candidate_profile", {})
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(0, 6, f"Target Role: {profile.get('target_role', 'General')}  |  "
                           f"Duration: {profile.get('total_weeks', 8)} weeks  |  "
                           f"Current Score: {profile.get('overall_score', 0):.0f}%", ln=True)
            pdf.ln(3)

            # Dimension analysis summary
            dim_analysis = roadmap.get("dimension_analysis", {})
            weak_areas = dim_analysis.get("weak_areas", [])
            moderate_areas = dim_analysis.get("moderate_areas", [])
            strong_areas = dim_analysis.get("strong_areas", [])

            if weak_areas:
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(220, 20, 60)
                weak_names = ", ".join(f"{a['name']} ({a['score']:.0f}%)" for a in weak_areas)
                pdf.cell(0, 6, f"Weak areas: {weak_names}", ln=True)
            if moderate_areas:
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(255, 165, 0)
                mod_names = ", ".join(f"{a['name']} ({a['score']:.0f}%)" for a in moderate_areas)
                pdf.cell(0, 6, f"Moderate areas: {mod_names}", ln=True)
            if strong_areas:
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(34, 139, 34)
                strong_names = ", ".join(f"{a['name']} ({a['score']:.0f}%)" for a in strong_areas)
                pdf.cell(0, 6, f"Strong areas: {strong_names}", ln=True)
            pdf.ln(4)

            # 4 Phases
            phase_colors = [
                (220, 20, 60),    # Phase 1: Red (Foundation Fix)
                (255, 140, 0),    # Phase 2: Orange (Enhancement)
                (102, 126, 234),  # Phase 3: Blue (Simulation)
                (34, 139, 34),    # Phase 4: Green (Mastery)
            ]
            for i, phase in enumerate(roadmap.get("phases", [])):
                if pdf.get_y() > 220:
                    pdf.add_page()
                color = phase_colors[i] if i < len(phase_colors) else (51, 51, 51)

                # Phase header
                pdf.set_fill_color(*color)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Helvetica", "B", 11)
                phase_name = phase.get("name", f"Phase {i+1}")
                duration = phase.get("duration_weeks", 2)
                pdf.cell(190, 8, f"  Phase {i+1}: {phase_name} ({duration} weeks)", ln=True, fill=True)

                # Objective
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 6, f"  Objective: {phase.get('objective', '')}", ln=True)

                # Focus areas
                focus = ", ".join(phase.get("focus_areas", []))
                if focus:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(51, 51, 51)
                    pdf.cell(0, 5, f"  Focus: {focus}", ln=True)

                # Tasks (show up to 4)
                tasks = phase.get("tasks", [])
                for task in tasks[:4]:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(51, 51, 51)
                    t_priority = task.get("priority", "medium")
                    t_icon = "*" if t_priority == "high" else "-"
                    pdf.cell(0, 5, f"    {t_icon} {task.get('title', '')}", ln=True)

                # Daily commitment & success criteria
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(0, 5, f"  Commitment: {phase.get('daily_commitment', '')}  |  "
                               f"Success: {phase.get('success_criteria', '')}", ln=True)
                pdf.ln(3)

            # Progress metrics
            metrics = roadmap.get("progress_metrics", [])
            if metrics:
                if pdf.get_y() > 230:
                    pdf.add_page()
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(102, 126, 234)
                pdf.cell(0, 8, "Progress Targets", ln=True)
                pdf.ln(1)
                for m in metrics:
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(51, 51, 51)
                    pdf.cell(0, 5, f"  {m['dimension']}: {m['baseline']:.0f}% -> {m['target']:.0f}% "
                                   f"(+{m['improvement_needed']:.0f}% needed)", ln=True)
                pdf.ln(3)

        # ══════════════════════════════════════════════
        # PAGE 3+: Question-wise Breakdown with bar chart
        # ══════════════════════════════════════════════
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(102, 126, 234)
        pdf.cell(0, 10, "Question-wise Breakdown", ln=True)
        pdf.set_draw_color(102, 126, 234)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

        # Question bar chart
        q_chart_idx = 1  # index of question bar chart
        if len(chart_files) > q_chart_idx and os.path.exists(chart_files[q_chart_idx]):
            pdf.image(chart_files[q_chart_idx], x=15, w=180, h=55)
            pdf.ln(5)

        # Individual question details
        for idx, qe in enumerate(evaluations, 1):
            if pdf.get_y() > 225:
                pdf.add_page()

            q_scores = qe.get("scores", {})
            q_overall = q_scores.get("overall_score", 0)
            badge_color = (34, 139, 34) if q_overall >= 70 else (255, 165, 0) if q_overall >= 40 else (220, 20, 60)

            # Question header with score badge
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(102, 126, 234)
            q_text = qe.get("question", "")
            if len(q_text) > 75:
                q_text = q_text[:75] + "..."
            pdf.cell(155, 8, f"Q{idx} [{qe.get('round', '')}]: {q_text}")
            pdf.set_fill_color(*badge_color)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(25, 8, f"{q_overall:.0f}/100", ln=True, align="C", fill=True)

            # Candidate's Answer
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(0, 5, "Your Answer:", ln=True)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            answer_text = qe.get("answer", "N/A")
            if len(answer_text) > 300:
                answer_text = answer_text[:300] + "..."
            pdf.set_x(10)
            pdf.multi_cell(190, 5, answer_text)
            pdf.ln(1)

            # Ideal Answer
            ideal = qe.get("ideal_answer", "")
            if ideal:
                if pdf.get_y() > 240:
                    pdf.add_page()
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(34, 139, 34)
                pdf.cell(0, 5, "Ideal Answer:", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(60, 100, 60)
                if len(ideal) > 300:
                    ideal = ideal[:300] + "..."
                pdf.set_x(10)
                pdf.multi_cell(190, 5, ideal)
                pdf.ln(1)

            # Score breakdown inline
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(0, 5,
                     f"Content: {q_scores.get('content_score', 0):.0f}  |  "
                     f"Keyword: {q_scores.get('keyword_score', 0):.0f}  |  "
                     f"Depth: {q_scores.get('depth_score', 0):.0f}  |  "
                     f"Comm: {q_scores.get('communication_score', 0):.0f}  |  "
                     f"Conf: {q_scores.get('confidence_score', 0):.0f}",
                     ln=True)

            # Keywords
            matched = ", ".join(qe.get("keywords_matched", [])) or "None"
            missed = ", ".join(qe.get("keywords_missed", [])) or "None"
            pdf.set_text_color(34, 139, 34)
            pdf.cell(0, 5, f"Keywords Hit: {matched}", ln=True)
            pdf.set_text_color(220, 20, 60)
            pdf.cell(0, 5, f"Keywords Missed: {missed}", ln=True)

            # Feedback
            feedback = qe.get("feedback", "")
            if feedback:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(100, 100, 100)
                if len(feedback) > 200:
                    feedback = feedback[:200] + "..."
                pdf.set_x(10)
                pdf.multi_cell(190, 5, f"Feedback: {feedback}")
            pdf.ln(4)

        # ══════════════════════════════════════════════
        # PROCTORING & INTEGRITY REPORT
        # ══════════════════════════════════════════════
        proctoring = report.get("proctoring", {})
        integrity_report = proctoring.get("integrity_report", {})
        has_proctoring = bool(proctoring.get("violation_log") or integrity_report)

        if has_proctoring:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(102, 126, 234)
            pdf.cell(0, 10, "Proctoring & Integrity Report", ln=True)
            pdf.set_draw_color(102, 126, 234)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)

            # Overall integrity score and verdict
            integrity_score = proctoring.get("integrity_score",
                integrity_report.get("integrity_score", 100))
            risk_verdict = proctoring.get("risk_verdict",
                integrity_report.get("final_verdict", "SAFE"))
            verdict_color = (34, 139, 34) if risk_verdict == "SAFE" else \
                (255, 165, 0) if risk_verdict == "SUSPICIOUS" else (220, 20, 60)

            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(*verdict_color)
            pdf.cell(90, 8, f"Integrity Score: {integrity_score:.0f}/100")
            pdf.cell(0, 8, f"Verdict: {risk_verdict}", ln=True)
            pdf.ln(3)

            # Identity verification
            identity_data = integrity_report.get("identity", {})
            identity_mismatches = proctoring.get("identity_mismatches",
                identity_data.get("mismatches", 0))
            identity_checks = identity_data.get("total_verifications", 0)

            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(0, 7, "Identity Verification", ln=True)
            pdf.set_font("Helvetica", "", 10)
            if identity_mismatches > 0:
                pdf.set_text_color(220, 20, 60)
                pdf.cell(0, 6, f"  Person changes detected: {identity_mismatches} "
                    f"(out of {identity_checks} checks)", ln=True)
            elif identity_checks > 0:
                pdf.set_text_color(34, 139, 34)
                pdf.cell(0, 6, f"  Identity verified consistently across {identity_checks} checks", ln=True)
            else:
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 6, "  No identity verification data available", ln=True)
            pdf.ln(2)

            # Proctoring statistics
            proc_stats = integrity_report.get("proctoring_stats", {})
            gaze_violations = proctoring.get("gaze_violations", 0)
            multi_person = proctoring.get("multi_person_alerts",
                proc_stats.get("person_alerts", 0))
            tab_switches = proctoring.get("tab_switches",
                proc_stats.get("tab_switches", 0))
            suspicious_objs = proctoring.get("suspicious_objects_detected",
                proc_stats.get("suspicious_objects_detected", 0))
            face_absence = proc_stats.get("face_absence_total_sec",
                proctoring.get("total_away_time_sec", 0))

            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(51, 51, 51)
            pdf.cell(0, 7, "Monitoring Summary", ln=True)
            pdf.set_font("Helvetica", "", 10)

            stats_items = [
                ("Gaze violations (looking away)", gaze_violations,
                    (220, 20, 60) if gaze_violations > 5 else (255, 165, 0) if gaze_violations > 0 else (34, 139, 34)),
                ("Multiple person alerts", multi_person,
                    (220, 20, 60) if multi_person > 0 else (34, 139, 34)),
                ("Tab switches", tab_switches,
                    (220, 20, 60) if tab_switches > 3 else (255, 165, 0) if tab_switches > 0 else (34, 139, 34)),
                ("Suspicious objects detected", suspicious_objs,
                    (220, 20, 60) if suspicious_objs > 0 else (34, 139, 34)),
                ("Person changes (identity mismatch)", identity_mismatches,
                    (220, 20, 60) if identity_mismatches > 0 else (34, 139, 34)),
                ("Face absence (seconds)", round(face_absence, 1),
                    (220, 20, 60) if face_absence > 30 else (255, 165, 0) if face_absence > 10 else (34, 139, 34)),
            ]

            for label, value, color in stats_items:
                pdf.set_text_color(*color)
                pdf.cell(120, 6, f"  {label}:")
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, str(value), ln=True)
                pdf.set_font("Helvetica", "", 10)
            pdf.ln(3)

            # Violation details (from integrity report timeline)
            violations = integrity_report.get("violations", {})
            violation_breakdown = violations.get("breakdown", {})
            if violation_breakdown:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(51, 51, 51)
                pdf.cell(0, 7, "Violation Breakdown", ln=True)
                pdf.set_font("Helvetica", "", 10)
                for vtype, vcount in violation_breakdown.items():
                    label = vtype.replace("_", " ").title()
                    v_color = (220, 20, 60) if vcount > 3 else (255, 165, 0) if vcount > 0 else (34, 139, 34)
                    pdf.set_text_color(*v_color)
                    pdf.cell(0, 6, f"  {label}: {vcount}", ln=True)
                pdf.ln(2)

            # Detected objects list (from violation log)
            violation_log = proctoring.get("violation_log", [])
            object_violations = [v for v in violation_log
                if v.get("type") in ("phone_detected", "suspicious_object")]
            if not object_violations:
                timeline = violations.get("timeline", [])
                object_violations = [v for v in timeline
                    if v.get("violation_type") in ("phone_detected", "suspicious_object")]

            if object_violations:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(220, 20, 60)
                pdf.cell(0, 7, "Suspicious Objects Detected", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(51, 51, 51)
                for v in object_violations[:10]:
                    ts = v.get("timestamp", v.get("time", ""))
                    details = v.get("details", v.get("type", ""))
                    pdf.cell(0, 5, f"  [{ts}] {details}", ln=True)
                pdf.ln(2)

        # ── Footer on last page ───────────────────────
        pdf.set_y(-25)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, "Generated by AI Interview Platform", align="C", ln=True)
        pdf.cell(0, 5, f"Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", align="C")

        return bytes(pdf.output())

    finally:
        # Clean up temp chart files
        for f in chart_files:
            try:
                if f and os.path.exists(f):
                    os.unlink(f)
            except OSError:
                pass
