#!/usr/bin/env python3
"""Detect and fix PDFs whose embedded text is missing or garbage.

Requires pdftotext (poppler-utils); ocrmypdf additionally for fixing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# Pages with fewer non-whitespace chars than this don't count as text pages
MIN_PAGE_CHARS = 30

# A text page is garbage if its alphanumeric share is above these thresholds.
BAD_ALNUM_RATIO = 0.30
BAD_FFFD_RATIO = 0.30

# A document is flagged if this share of its text pages is garbage.
FRACTION_BAD_PAGES = 0.25

BACKUP_DIR_NAME = "ocr_backups"

# How to fix each fixable classification.
FIX_FLAGS = {"NO_TEXT": "--redo-ocr", "BAD_TEXT": "--force-ocr"}


@dataclass
class DocReport:
    path: Path
    text_pages: int = 0
    bad_pages: int = 0
    corrupt: bool = False

    @property
    def classification(self) -> str:
        if self.corrupt:
            return "CORRUPT"
        if self.text_pages == 0:
            return "NO_TEXT"
        if self.bad_pages / self.text_pages >= FRACTION_BAD_PAGES:
            return "BAD_TEXT"
        return "OK"


def analyse_pdf(path: Path) -> DocReport:
    """Classify one PDF by inspecting the text of every page."""
    report = DocReport(path=path)
    out = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0 and not out.stdout.strip():
        report.corrupt = True  # poppler can't read the file at all
        return report
    # don't trust the exit code: broken PDFs often still emit text
    for page_text in out.stdout.split("\f"):
        chars = [c for c in page_text if not c.isspace()]
        if len(chars) < MIN_PAGE_CHARS:
            continue
        report.text_pages += 1
        alnum = sum(1 for c in chars if c.isalnum())
        fffd = sum(1 for c in chars if c == "\ufffd")
        if alnum / len(chars) <= BAD_ALNUM_RATIO or fffd / len(chars) >= BAD_FFFD_RATIO:
            report.bad_pages += 1
    return report


def fix_pdf(report: DocReport, root: Path) -> bool:
    """Backup and OCR the PDF in place. Returns True on success."""
    backup_path = root / BACKUP_DIR_NAME / report.path.relative_to(root)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report.path, backup_path)

    tmp = report.path.with_name(report.path.stem + ".ocr.pdf")
    cmd = [
        "ocrmypdf",
        FIX_FLAGS[report.classification],
        "--output-type",
        "pdf",
        str(report.path),
        str(tmp),
    ]
    if subprocess.run(cmd).returncode != 0:
        print(f"    ERROR: ocrmypdf failed for {report.path}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(report.path)
    print(f"    OK (backup: {backup_path})")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", type=Path, help="library directory to scan")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only report findings, don't run ocrmypdf",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="parallel workers for text extraction (default: 8)",
    )
    args = parser.parse_args()

    for cmd in ["pdftotext"] + ([] if args.dry_run else ["ocrmypdf"]):
        if not shutil.which(cmd):
            sys.exit(f"Error: required command '{cmd}' not found in PATH.")

    root = args.directory.resolve()
    pdfs = sorted(
        p
        for p in root.rglob("*.pdf")
        if BACKUP_DIR_NAME not in p.relative_to(root).parts
    )
    print(f"Scanning {len(pdfs)} PDFs under {root} ...", file=sys.stderr)

    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        reports = list(ex.map(analyse_pdf, pdfs))

    to_fix: list[DocReport] = []
    for report in reports:
        classification = report.classification
        if classification == "OK":
            continue
        detail = (
            f"{report.bad_pages}/{report.text_pages} bad pages  "
            if classification == "BAD_TEXT"
            else ""
        )
        print(f"  {classification:<8} {detail}{report.path}")
        if classification in FIX_FLAGS:
            to_fix.append(report)

    def count(cls: str) -> int:
        return sum(r.classification == cls for r in reports)

    print(
        f"\nSummary: BAD_TEXT: {count('BAD_TEXT')}, NO_TEXT: {count('NO_TEXT')}, "
        f"CORRUPT: {count('CORRUPT')}, OK: {count('OK')}  (of {len(reports)} PDFs)"
    )

    if not to_fix:
        print("Nothing to fix.")
        return
    if args.dry_run:
        print(
            f"\n{len(to_fix)} PDF(s) need fixing (dry run, no changes made). "
            "Re-run without --dry-run to fix them."
        )
        return

    print(f"\nFixing {len(to_fix)} PDF(s) (backups under {root / BACKUP_DIR_NAME}) ...")
    failed = 0
    for report in to_fix:
        print(f"  {report.path.name} ({FIX_FLAGS[report.classification]})")
        if not fix_pdf(report, root):
            failed += 1
    print(f"\nDone. {len(to_fix) - failed} fixed, {failed} failed. ")


if __name__ == "__main__":
    main()
