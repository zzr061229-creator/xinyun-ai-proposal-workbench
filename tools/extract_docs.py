#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extract text/tables from the downloaded competition materials (docx/xlsx/pptx/pdf)."""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(r"C:\Users\zzr\Desktop\新云AI提案工作台\materials")
OUT = Path(r"C:\Users\zzr\Desktop\新云AI提案工作台\extracted")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    lines = []
    if body is None:
        return ""
    for child in body:
        if child.tag == f"{W}p":
            text = "".join(t.text or "" for t in child.iter(f"{W}t")).strip()
            if text:
                lines.append(text)
        elif child.tag == f"{W}tbl":
            for tr in child.findall(f"{W}tr"):
                cells = []
                for tc in tr.findall(f"{W}tc"):
                    cells.append(" ".join("".join(t.text or "" for t in p.iter(f"{W}t")).strip()
                                          for p in tc.findall(f"{W}p")).strip())
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def xlsx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.findall(f"{S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rroot:
                rels[rel.get("Id")] = rel.get("Target")
        out = []
        for idx, sheet in enumerate(wb.iter(f"{S}sheet"), 1):
            name = sheet.get("name") or f"Sheet{idx}"
            rid = sheet.get(f"{R}id")
            target = rels.get(rid, f"worksheets/sheet{idx}.xml")
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                continue
            sroot = ET.fromstring(z.read(target))
            out.append(f"\n===== SHEET: {name} =====")
            for row in sroot.iter(f"{S}row"):
                vals = []
                for c in row.findall(f"{S}c"):
                    ref = c.get("r") or ""
                    t = c.get("t")
                    v = c.find(f"{S}v")
                    is_ = c.find(f"{S}is")
                    if t == "s" and v is not None:
                        try:
                            val = shared[int(v.text)]
                        except Exception:
                            val = v.text or ""
                    elif t == "inlineStr" and is_ is not None:
                        val = "".join(x.text or "" for x in is_.iter(f"{S}t"))
                    elif v is not None:
                        val = v.text or ""
                    else:
                        val = ""
                    vals.append(f"{ref}={val}" if val != "" else "")
                if any(vals):
                    out.append("\t".join(vals))
        return "\n".join(out)


def pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        slides = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        slides.sort(key=lambda n: int(re.search(r"slide(\d+)\.xml", n).group(1)))
        out = []
        for n in slides:
            root = ET.fromstring(z.read(n))
            texts = [t.text or "" for t in root.iter(f"{A}t")]
            out.append(f"\n===== {n} =====")
            out.append("\n".join(x for x in texts if x.strip()))
        return "\n".join(out)


def pdf_text(path: Path) -> str:
    import fitz
    doc = fitz.open(path)
    out = []
    for i, page in enumerate(doc, 1):
        out.append(f"\n===== PAGE {i} =====")
        out.append(page.get_text())
    return "\n".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted(SRC.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        try:
            if suffix == ".docx":
                text = docx_text(path)
            elif suffix == ".xlsx":
                text = xlsx_text(path)
            elif suffix == ".pptx":
                text = pptx_text(path)
            elif suffix == ".pdf":
                text = pdf_text(path)
            else:
                continue
            rel = path.relative_to(SRC)
            target = OUT / (str(rel) + ".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{len(text):>8} chars -> {target}")
        except Exception as e:
            print(f"ERROR {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
