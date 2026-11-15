#!/usr/bin/env python3
"""Build Nesto's diagrams with one restrained brand system and a shared grid."""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/assets"
WIDTH, HEIGHT = 1160, 480
BG, PANEL, LINE = "#0b1b2b", "#11263a", "#2a3e52"
INK, MUTED, GOLD = "#f4f1ea", "#abb9c6", "#d2af70"


def text(x, y, value, size=18, color=MUTED, *, anchor="start", weight=400):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(value)}</text>')


def line(x1, y1, x2, y2, color=LINE, *, arrow=False):
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return (f'<path d="M{x1} {y1}H{x2}" fill="none" stroke="{color}" '
            f'stroke-width="1.5"{marker}/>') if y1 == y2 else (
            f'<path d="M{x1} {y1}L{x2} {y2}" fill="none" stroke="{color}" '
            f'stroke-width="1.5"{marker}/>')


def canvas(title, subtitle, number, description):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>',
        '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" '
        f'orient="auto"><path d="M0 0L7 3.5L0 7" fill="{GOLD}"/></marker></defs>',
        '<style>text{font-family:Arial,Helvetica,sans-serif}</style>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="{BG}"/>',
        line(56, 32, 88, 32, GOLD),
        text(1104, 38, f"NESTO / {number}", 13, GOLD, anchor="end"),
        text(56, 78, title, 32, INK, weight=500),
        text(56, 111, subtitle, 17),
        line(56, 140, 1104, 140),
    ]


def panel(x, width, eyebrow, title, first, second, *, y=180, height=188):
    return [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" '
        f'fill="{PANEL}" stroke="{LINE}"/>',
        text(x + 24, y + 32, eyebrow, 13, GOLD),
        text(x + 24, y + 78, title, 25, INK, weight=500),
        text(x + 24, y + 119, first, 18),
        text(x + 24, y + 149, second, 18),
    ]


def finish(name, content, note):
    content += [line(56, 416, 1104, 416), text(56, 449, note, 16), "</svg>"]
    OUT.joinpath(name).write_text("\n".join(content) + "\n")


def architecture():
    s = canvas(
        "System architecture", "From a property brief to a narrated video.", "01",
        "The private Next.js Studio supplies footage and a brief to the FastAPI and worker-based "
        "eight-agent director. MoviePy and FFmpeg produce the video and subtitles. "
        "Structured project state connects the stages.",
    )
    s += panel(56, 296, "INPUT", "Private Studio", "Footage + director brief", "Next.js interface")
    s += panel(432, 296, "ORCHESTRATION", "Eight-agent director", "FastAPI + worker", "Shared Project State")
    s += panel(808, 296, "OUTPUT", "Narrated video", "MP4 + subtitles", "MoviePy / FFmpeg")
    s += [line(368, 274, 416, 274, GOLD, arrow=True),
          line(744, 274, 792, 274, GOLD, arrow=True)]
    finish("system-overview.svg", s, "Structured artifacts connect scene evidence, narration, timing and review.")


def workflow():
    s = canvas(
        "Agent workflow", "Eight responsibilities, grouped into three clear stages.", "02",
        "Understand groups Vision, Planner and Script. Align groups Voice and Timeline. "
        "Produce groups Editing, Rendering and Evaluation. Timeline validates narration "
        "budgets before TTS and reconciles measured speech afterward.",
    )
    # One line of progression; no serpentine routing or repeated Timeline node.
    centers = [204, 580, 956]
    for left, right in zip(centers, centers[1:]):
        s.append(line(left + 28, 190, right - 28, 190, GOLD, arrow=True))
    for x, index, title, first, second, summary in [
        (204, "01", "Understand", "Vision · Planner", "Script", "Visual facts + story"),
        (580, "02", "Align", "Voice", "Timeline", "Speech + scene timing"),
        (956, "03", "Produce", "Editing · Rendering", "Evaluation", "Execution + review"),
    ]:
        s += [f'<circle cx="{x}" cy="190" r="20" fill="{PANEL}" stroke="{GOLD}"/>',
              text(x, 195, index, 13, GOLD, anchor="middle"),
              text(x, 246, title, 26, INK, anchor="middle", weight=500),
              text(x, 288, first, 21, INK, anchor="middle"),
              text(x, 320, second, 21, INK, anchor="middle"),
              text(x, 365, summary, 17, anchor="middle")]
    finish("agent-workflow.svg", s, "Timeline checks budgets before TTS, then aligns scenes with measured speech.")


def boundaries():
    s = canvas(
        "Data boundaries", "A clear separation between publication and private processing.", "03",
        "The public repository contains source code, diagrams and the recorded walkthrough. "
        "API credentials and private footage, logs and runtime workspaces stay in the "
        "private environment. Only the selected recording is published.",
    )
    s += panel(56, 480, "PUBLIC REPOSITORY", "Published", "Source code + diagrams", "Recorded walkthrough")
    s += panel(624, 480, "PRIVATE ENVIRONMENT", "Server only", "API keys + credentials", "Footage, logs + runtime files")
    s.append(line(580, 196, 580, 352))
    finish("data-boundaries.svg", s, "Only the selected recording is shared; provider credentials remain on the server.")


if __name__ == "__main__":
    architecture()
    workflow()
    boundaries()
    print("Built 3 diagrams with one Nesto palette, typography system and alignment grid.")
