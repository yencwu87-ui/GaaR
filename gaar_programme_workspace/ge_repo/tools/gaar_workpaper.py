#!/usr/bin/env python3
"""Render the governing policy as a regulatory-grade workpaper (navy and ice-blue house style).

    python tools/gaar_workpaper.py --report reports/gate_status-<time>.json --out ~/Desktop/GaaR_Quality_Policy_Workpaper.docx

The workpaper is a presentation of two records: the policy text, identified by its hash in the banner, and a
gate-status report, which must verify and must be about that exact policy text. It refuses otherwise, so the
document can never pair a policy with status about a different version. Regenerate it; never edit it.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_BREAK  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt, RGBColor, Cm  # noqa: E402

from governance.production import gate_status, policy_approval as pa  # noqa: E402

NAVY = RGBColor(0x1F, 0x38, 0x64)
ICE = "DCE6F2"
NAVY_HEX = "1F3864"


def _shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc.append(shd)


def _runs(paragraph, text, size=None, bold=False, colour=None):
    """Inline **bold** and `code`, nothing else."""
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt((size or 10.5) - 1)          # code sized to its context, a touch smaller
        else:
            run = paragraph.add_run(part)
        if bold:
            run.bold = True
        if size:
            run.font.size = Pt(size)
        if colour:
            run.font.color.rgb = colour


def _table(document, header, rows, widths=None):
    table = document.add_table(rows=1 + len(rows), cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for i, text in enumerate(header):
        cell = table.rows[0].cells[i]
        _shade(cell, NAVY_HEX)
        cell.paragraphs[0].text = ""
        _runs(cell.paragraphs[0], text, size=9, bold=True, colour=RGBColor(0xFF, 0xFF, 0xFF))
    for r, row in enumerate(rows, start=1):
        for i, text in enumerate(row):
            cell = table.rows[r].cells[i]
            if r % 2 == 0:
                _shade(cell, ICE)
            cell.paragraphs[0].text = ""
            _runs(cell.paragraphs[0], text, size=9)
    widths = widths or ([16.6 / len(header)] * len(header) if len(header) != 2 else [5.2, 11.4])
    table.autofit = False
    for i, width in enumerate(widths):                     # grid widths, which Word and LibreOffice both read
        table.columns[i].width = Cm(width)
        for row in table.rows:
            row.cells[i].width = Cm(width)
    document.add_paragraph()
    return table


def _styles(document):
    body = document.styles["Normal"]
    body.font.name = "Calibri"
    body.font.size = Pt(10.5)
    body.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    for level, size in ((1, 16), (2, 13), (3, 11.5)):
        style = document.styles[f"Heading {level}"]
        style.font.name = "Cambria"
        style.font.size = Pt(size)
        style.font.color.rgb = NAVY
        style.font.bold = True
        rpr = style.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:                        # an element can be falsy while present: test for None
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            fonts.set(qn(attr), "Cambria")


def _render_markdown(document, text):
    lines = text.splitlines()
    i, paragraph = 0, []

    def flush():
        if paragraph:
            _runs(document.add_paragraph(), " ".join(paragraph))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            p = document.add_paragraph()
            run = p.add_run("\n".join(block))
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
            p.paragraph_format.left_indent = Cm(0.5)
        elif line.startswith("#"):
            flush()
            level = len(line) - len(line.lstrip("#"))
            if level > 1:                                   # the document title is the workpaper's own
                document.add_heading(line.lstrip("#").strip(), level=min(level - 1, 3))
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            _table(document, rows[0], rows[1:])
            continue
        elif re.match(r"^\s*(- |\d+\. )", line):
            flush()
            number = re.match(r"^\s*(\d+)\. ", line)
            item = [re.sub(r"^\s*(- |\d+\. )", "", line)]
            # A continuation is any indented, non-blank line that does not start a new item. Bullets indent
            # continuations by two spaces, numbered items by three; requiring three split every wrapped bullet.
            while (i + 1 < len(lines) and lines[i + 1].startswith("  ") and lines[i + 1].strip()
                   and not re.match(r"^\s*(- |\d+\. )", lines[i + 1])):
                i += 1
                item.append(lines[i].strip())
            if number:
                # The policy's own numbering, not Word's running count: "§9, item 2" must mean what the text says.
                p = document.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.9)
                p.paragraph_format.first_line_indent = Cm(-0.6)
                _runs(p, f"{number.group(1)}.\u2002" + " ".join(item))
            else:
                _runs(document.add_paragraph(style="List Bullet"), " ".join(item))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
        i += 1
    flush()


def build(report_path: Path, out: Path) -> dict:
    report = json.loads(report_path.read_text())
    check = gate_status.verify(report)
    if not check["valid"]:
        raise ValueError(f"the gate-status report does not verify ({check['reason']}); regenerate it")
    identity = pa.policy_identity(pa.POLICY)
    if report["policy"]["policy_sha256"] != identity["policy_sha256"]:
        raise ValueError("the gate-status report is about a different policy text; regenerate it for this one")

    document = Document()
    for section in document.sections:
        section.left_margin = section.right_margin = Cm(2.2)
        section.top_margin = section.bottom_margin = Cm(2.0)
    _styles(document)
    title = document.add_paragraph()
    _runs(title, "GaaR Pilot Quality Policy", size=22, bold=True, colour=NAVY)
    title.runs[0].font.name = "Cambria"
    subtitle = document.add_paragraph()
    _runs(subtitle, "Workpaper — generated from the governing text; do not edit, regenerate", size=11,
          colour=RGBColor(0x40, 0x55, 0x75))
    approval = next(g for g in report["gates"] if g["gate"] == "Policy approval")
    _table(document, ["Item", "Value"], [
        ["Policy version", identity["policy_version"]],
        ["Policy SHA-256", identity["policy_sha256"]],
        ["Approval state", f"{approval['state']}: {approval['evidence']}"],
        ["Gate-status report", f"as of {report['as_of']}; content hash {report['body_sha256'][:16]}; verified"],
        ["Source", f"`{identity['policy_path']}`"],
    ], widths=[3.6, 13.0])

    _render_markdown(document, pa.POLICY.read_text())

    appendix = document.add_heading("Appendix A — Gate status", level=1)
    appendix.paragraph_format.page_break_before = True       # no stray blank page
    _runs(document.add_paragraph(), f"How each gate was held as of **{report['as_of']}**"
          + (f" for series **{report['series']}**" if report["series"] else "")
          + ". Derived from the inputs in the receipt below; verified before rendering.")
    _table(document, ["Gate", "State", "Evidence"],
           [[g["gate"], g["state"], g["evidence"]] for g in report["gates"]], widths=[4.2, 2.6, 9.8])
    _runs(document.add_paragraph(), f"**Guard register:** {report['guard_register']['summary']}")
    document.add_heading("Derivation receipt", level=2)
    receipt = report["derivation_receipt"]
    _runs(document.add_paragraph(), f"Generated {receipt['generated_at']} by `{receipt['generator']}` "
          f"({receipt['generator_sha256'][:16]}).")
    _table(document, ["Input", "Path", "Hash or head"],
           [[i["kind"], f"`{i['path']}`", (i.get("sha256") or i.get("head") or "—")[:24]] for i in receipt["inputs"]],
           widths=[3.6, 8.4, 4.6])

    # Word requires a paragraph after a final table. At normal size it spills onto a blank last page whenever the
    # table ends at the foot of a page (seen on the Mac rendering of v18), so it is made 1 pt with no spacing.
    closing = document.add_paragraph()
    closing.paragraph_format.space_before = closing.paragraph_format.space_after = Pt(0)
    closing.paragraph_format.line_spacing = Pt(1)
    mark = OxmlElement("w:rPr")                               # the paragraph mark's own size sets the line
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "2")
    mark.append(size)
    closing._p.get_or_add_pPr().append(mark)

    footer = document.sections[0].footer.paragraphs[0]
    _runs(footer, f"GaaR quality policy {identity['policy_version']} · {identity['policy_sha256'][:12]} · "
                  "generated workpaper, do not edit", size=8, colour=RGBColor(0x40, 0x55, 0x75))
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(out)
    return {"status": "WORKPAPER_WRITTEN", "workpaper": str(out), "policy_version": identity["policy_version"],
            "policy_sha256": identity["policy_sha256"], "gate_status_as_of": report["as_of"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, help="a gate-status report JSON from tools/gaar_gate_status.py")
    parser.add_argument("--out", required=True, help="where to write the .docx")
    args = parser.parse_args()
    print(json.dumps(build(Path(args.report).expanduser(), Path(args.out).expanduser()), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
