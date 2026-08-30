from __future__ import annotations

import argparse
import base64
import difflib
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pybtex.database import Person, parse_file
from pybtex.exceptions import PybtexError
from pybtex.richtext import Text
from pypdf import PdfReader
from pypdf.generic import ContentStream

from bib_utils import enrich_bibliography_entry
from iperpaper_native_html import (
    automatic_reference_id as _automatic_reference_id,
    build_native_html,
)
from iperpaper_templates import read_template, resource_path

ANNOTATION_ID = r"[A-Za-z0-9_.-]+"
LEVEL_DESTINATION = re.compile(rf"^iperpaper-level-(start|content|end):2:({ANNOTATION_ID})$")
ANNOTATION_KINDS = {"symbol", "operator", "concept", "notation", "equation", "reference"}
ANNOTATION_FIELDS = {"id", "kind", "label", "short", "details", "background"}
ANNOTATION_OPTIONAL_FIELDS = {
    "external_url",
    "figure_preview",
    "paper_title",
    "paper_title_source",
    "paper_title_verified",
}
RICH_TEXT_FIELDS = ("label", "short", "details")
BACKGROUND_FIELDS = ("short", "details")
TEX_SUFFIXES = {".tex", ".latex"}
EQUATION_ENVIRONMENTS = {
    "equation",
    "align",
    "alignat",
    "flalign",
    "gather",
    "multline",
}
PDFJS_VERSION = "6.2.108"
PDFJS_MODULE_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/build/pdf.min.mjs"
PDFJS_WORKER_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/build/pdf.worker.min.mjs"
PDFJS_WASM_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/wasm/"
PDFJS_CMAP_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/cmaps/"
PDFJS_STANDARD_FONT_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/standard_fonts/"
PDFJS_VIEWER_CSS_URL = f"https://cdn.jsdelivr.net/npm/pdfjs-dist@{PDFJS_VERSION}/web/pdf_viewer.css"
BUILD_MODES = ("pdf_html", "native_html", "all")
CITATION_CACHE_VERSION = 4

# Figure- and table-reference previews are displayed at this fraction of the
# printed artwork's size. Keep this as a single top-level setting so it is easy
# to tune consistently for both kinds of float.
FIGURE_TOOLTIP_SCALE = 0.8
FIGURE_PREVIEW_DPI = 144


def _require_command(name: str, message: str) -> str:
    """
    Locate a required executable or raise an actionable error.

    Args:
        name: Executable name to locate on ``PATH``.
        message: Error message to raise when the executable is unavailable.

    Returns:
        str: Path to the executable.
    """
    command = shutil.which(name)
    if command is None:
        raise RuntimeError(message)
    return command


def require_latexmk() -> str:
    """
    Locate the latexmk executable required for TeX compilation.

    Returns:
        str: Path to ``latexmk``.
    """
    return _require_command(
        "latexmk",
        "IperPaper compiles annotated TeX with latexmk. Install a TeX distribution "
        "that provides latexmk and make sure it is on PATH.",
    )


def require_pdfcrop() -> str:
    """
    Locate the pdfcrop executable required for math rendering.

    Returns:
        str: Path to ``pdfcrop``.
    """
    return _require_command(
        "pdfcrop",
        "IperPaper pre-renders annotation math with LaTeX and pdfcrop. Install the "
        "TeX utility that provides pdfcrop (on Ubuntu/Debian: texlive-extra-utils).",
    )


def require_pdftocairo() -> str:
    """
    Locate the pdftocairo executable required for PDF conversion.

    Returns:
        str: Path to ``pdftocairo``.
    """
    return _require_command(
        "pdftocairo",
        "IperPaper converts pre-rendered annotation math from PDF to SVG with "
        "pdftocairo. Install Poppler (on Ubuntu/Debian: poppler-utils).",
    )


def load_annotations(path: Path) -> dict[str, Any]:
    """
    Load and validate annotation metadata from JSON.

    Args:
        path: Annotation JSON file to read.

    Returns:
        dict[str, Any]: Validated annotation metadata.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    validate_annotation_metadata(data)
    return data


def validate_annotation_metadata(data: dict[str, Any]) -> None:
    """
    Validate the structure and values of annotation metadata.

    Args:
        data: Annotation metadata to validate.
    """
    if not isinstance(data, dict):
        raise ValueError("Annotation metadata must be a JSON object")

    required_top = {"title", "annotations", "background"}
    missing = required_top - data.keys()
    if missing:
        raise ValueError(f"Annotation JSON missing keys: {sorted(missing)}")
    extra_top = data.keys() - required_top
    if extra_top:
        raise ValueError(f"Annotation JSON has unexpected keys: {sorted(extra_top)}")

    if not isinstance(data["title"], str) or not data["title"].strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(data["annotations"], list):
        raise ValueError("annotations must be a list")

    background = data["background"]
    if not isinstance(background, dict):
        raise ValueError("background must be an object mapping keys to explanations")
    for key, entry in background.items():
        if not isinstance(key, str) or not re.fullmatch(ANNOTATION_ID, key):
            raise ValueError(f"background key {key!r} must contain only letters, digits, ., _, or -")
        if not isinstance(entry, dict):
            raise ValueError(f"background {key!r} must be an object")
        missing_fields = {"short", "details"} - entry.keys()
        if missing_fields:
            raise ValueError(f"background {key!r} missing keys: {sorted(missing_fields)}")
        extra_fields = entry.keys() - {"short", "details", "label", "link", "background"}
        if extra_fields:
            raise ValueError(f"background {key!r} has unexpected keys: {sorted(extra_fields)}")
        for field in ("short", "details"):
            if not isinstance(entry[field], str):
                raise ValueError(f"background {key!r} field {field} must be a string")
        if "label" in entry and (not isinstance(entry["label"], str) or not entry["label"]):
            raise ValueError(f"background {key!r} field label must be a non-empty string")
        if "link" in entry and (not isinstance(entry["link"], str) or not entry["link"]):
            raise ValueError(f"background {key!r} field link must be a non-empty string")
        nested_refs = entry.get("background", [])
        if not isinstance(nested_refs, list) or any(not isinstance(ref, str) for ref in nested_refs):
            raise ValueError(f"background {key!r} field background must be a list of strings")

    ids: set[str] = set()
    for i, ann in enumerate(data["annotations"]):
        if not isinstance(ann, dict):
            raise ValueError(f"annotation {i} must be an object")

        missing_fields = ANNOTATION_FIELDS - ann.keys()
        if missing_fields:
            raise ValueError(f"annotation {i} missing keys: {sorted(missing_fields)}")
        extra_fields = ann.keys() - ANNOTATION_FIELDS - ANNOTATION_OPTIONAL_FIELDS
        if extra_fields:
            raise ValueError(f"annotation {i} has unexpected keys: {sorted(extra_fields)}")

        ann_id = ann["id"]
        if not isinstance(ann_id, str) or not ann_id:
            raise ValueError(f"annotation {i} has invalid id")
        if not re.fullmatch(ANNOTATION_ID, ann_id):
            raise ValueError(f"annotation {i} id must contain only letters, digits, ., _, or -")
        if ann_id in ids:
            raise ValueError(f"duplicate annotation id: {ann_id}")
        ids.add(ann_id)

        if not isinstance(ann["kind"], str) or ann["kind"] not in ANNOTATION_KINDS:
            raise ValueError(
                f"annotation {ann_id} has invalid kind {ann['kind']!r}; "
                f"expected one of {sorted(ANNOTATION_KINDS)}"
            )
        for field in ANNOTATION_FIELDS - {"id", "kind", "background"}:
            if not isinstance(ann[field], str):
                raise ValueError(f"annotation {ann_id} field {field} must be a string")

        background_refs = ann["background"]
        if not isinstance(background_refs, list) or any(not isinstance(ref, str) for ref in background_refs):
            raise ValueError(f"annotation {ann_id} field background must be a list of strings")
        unknown_refs = [ref for ref in background_refs if ref not in background]
        if unknown_refs:
            raise ValueError(
                f"annotation {ann_id} references unknown background keys: {sorted(set(unknown_refs))}"
            )
        if len(set(background_refs)) != len(background_refs):
            raise ValueError(f"annotation {ann_id} has duplicate background keys")

        preview = ann.get("figure_preview")
        if preview is not None:
            if not isinstance(preview, dict):
                raise ValueError(f"annotation {ann_id} field figure_preview must be an object")
            expected_preview_fields = {"src", "width_pt", "height_pt", "scale"}
            if set(preview) != expected_preview_fields:
                raise ValueError(
                    f"annotation {ann_id} field figure_preview must contain exactly "
                    f"{sorted(expected_preview_fields)}"
                )
            if not isinstance(preview["src"], str) or not preview["src"].startswith("data:image/"):
                raise ValueError(f"annotation {ann_id} figure_preview src must be an image data URL")
            for field in ("width_pt", "height_pt", "scale"):
                value = preview[field]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    raise ValueError(f"annotation {ann_id} figure_preview {field} must be a positive number")

        external_url = ann.get("external_url")
        if external_url is not None and (
            not isinstance(external_url, str) or not re.fullmatch(r"https?://[^\s]+", external_url)
        ):
            raise ValueError(f"annotation {ann_id} field external_url must be an HTTP(S) URL")

        paper_title_verified = ann.get("paper_title_verified")
        if "paper_title_verified" in ann and not isinstance(paper_title_verified, bool):
            raise ValueError(f"annotation {ann_id} field paper_title_verified must be a boolean")

        paper_title_source = ann.get("paper_title_source")
        if "paper_title_source" in ann and not isinstance(paper_title_source, str):
            raise ValueError(f"annotation {ann_id} field paper_title_source must be a string")

        if not ann["short"] and not ann["details"] and not background_refs:
            raise ValueError(
                f"annotation {ann_id} has empty short, details, and background; "
                "it would show no explanation"
            )

    for key, entry in background.items():
        unknown_refs = [ref for ref in entry.get("background", []) if ref not in background]
        if unknown_refs:
            raise ValueError(
                f"background {key!r} references unknown background keys: {sorted(set(unknown_refs))}"
            )
        if key in entry.get("background", []):
            raise ValueError(f"background {key!r} references itself")


def _read_text(path: Path) -> str:
    """
    Read a UTF-8 text file while replacing invalid bytes.

    Args:
        path: Text file to read.

    Returns:
        str: Decoded file content.
    """
    return path.read_text(encoding="utf-8", errors="replace")


def tex_files(source: Path) -> list[Path]:
    """
    Find TeX source files for a paper source path.

    Args:
        source: TeX source file or project directory.

    Returns:
        list[Path]: Resolved TeX source paths.
    """
    if source.is_file():
        if source.suffix.lower() not in TEX_SUFFIXES:
            raise ValueError("Paper source must be a .tex/.latex file or a directory containing TeX")
        return [source.resolve()]
    if not source.is_dir():
        raise ValueError(f"Paper source does not exist: {source}")
    files = sorted(p.resolve() for p in source.rglob("*") if p.is_file() and p.suffix.lower() in TEX_SUFFIXES)
    if not files:
        raise ValueError(f"No .tex/.latex files found under {source}")
    return files


def resolve_project(source: Path, main: str | None = None) -> tuple[Path, Path]:
    """
    Resolve a paper source to its project root and main TeX file.

    Args:
        source: TeX source file or project directory.
        main: Optional main TeX path relative to a project directory.

    Returns:
        tuple[Path, Path]: The resolved project root and main TeX file.
    """
    source = source.resolve()
    if source.is_file():
        if main:
            raise ValueError("--main is only valid when the paper source is a directory")
        if source.suffix.lower() not in TEX_SUFFIXES:
            raise ValueError("Paper source must be a .tex/.latex file or a directory containing TeX")
        return source.parent, source

    if not source.is_dir():
        raise ValueError(f"Paper source does not exist: {source}")

    if main:
        candidate = (source / main).resolve()
        try:
            candidate.relative_to(source)
        except ValueError as exc:
            raise ValueError("--main must point to a file inside the TeX project directory") from exc
        if not candidate.is_file() or candidate.suffix.lower() not in TEX_SUFFIXES:
            raise ValueError(f"Main TeX file not found: {candidate}")
        return source, candidate

    conventional = source / "main.tex"
    if conventional.is_file():
        return source, conventional.resolve()

    all_tex = tex_files(source)
    document_roots = [p for p in all_tex if re.search(r"\\documentclass(?:\[[^]]*\])?\s*\{", _read_text(p))]
    if len(document_roots) == 1:
        return source, document_roots[0]
    if len(document_roots) > 1:
        choices = ", ".join(str(p.relative_to(source)) for p in document_roots[:8])
        raise ValueError(f"Multiple possible main TeX files found ({choices}); pass --main RELATIVE_PATH")
    if len(all_tex) == 1:
        return source, all_tex[0]
    raise ValueError("Could not identify the main TeX file; pass --main RELATIVE_PATH")


def _run_latexmk(tex_path: Path, project_root: Path, outdir: Path) -> Path:
    """
    Compile a TeX file with latexmk into a designated directory.

    Args:
        tex_path: TeX file to compile, relative to the project root when applicable.
        project_root: Root directory of the TeX project.
        outdir: Directory in which compilation artifacts are written.

    Returns:
        Path: Path to the compiled PDF.
    """
    latexmk = require_latexmk()
    command = [
        latexmk,
        "-pdf",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-outdir={outdir}",
        str(tex_path),
    ]
    environment = os.environ.copy()
    levels_style = resource_path("iperpaper-levels.sty")
    texinputs = environment.get("TEXINPUTS", "")
    environment["TEXINPUTS"] = f"{levels_style.parent}{os.pathsep}{texinputs}"
    proc = subprocess.run(
        command,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if proc.returncode != 0:
        details = (proc.stdout + "\n" + proc.stderr).strip()
        tail = "\n".join(details.splitlines()[-40:])
        raise RuntimeError(f"latexmk failed while compiling {tex_path}:\n{tail}")
    pdf_path = outdir / f"{tex_path.stem}.pdf"
    if not pdf_path.is_file():
        candidates = sorted(outdir.glob("*.pdf"))
        if len(candidates) == 1:
            pdf_path = candidates[0]
        else:
            raise RuntimeError(
                f"latexmk succeeded but IperPaper could not identify the compiled PDF in {outdir}"
            )
    return pdf_path


def compile_pdf(source: Path, main: str | None = None) -> bytes:
    """
    Compile a TeX paper and return the resulting PDF bytes.

    Args:
        source: TeX source file or project directory.
        main: Optional main TeX path relative to a project directory.

    Returns:
        bytes: Compiled PDF content.
    """
    project_root, main_file = resolve_project(source, main)
    relative_main = main_file.relative_to(project_root)
    with tempfile.TemporaryDirectory(prefix="iperpaper-latex-") as tmp:
        outdir = Path(tmp).resolve()
        return _run_latexmk(relative_main, project_root, outdir).read_bytes()


def extract_pdf_targets(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], list[dict[str, float]]]:
    """
    Return IperPaper link rectangles and page sizes from a compiled PDF.

    Args:
        pdf_bytes: Compiled PDF content.

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, float]]]: Annotation targets and page dimensions.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    targets: list[dict[str, Any]] = []
    pages: list[dict[str, float]] = []
    for page_index, page in enumerate(reader.pages):
        if int(page.rotation or 0) % 360 != 0:
            raise ValueError(
                "Rotated PDF pages are not supported by the overlay mapper yet; "
                f"page {page_index + 1} has rotation {page.rotation}."
            )
        crop = page.cropbox
        left, bottom, right, top = map(float, (crop.left, crop.bottom, crop.right, crop.top))
        width, height = right - left, top - bottom
        if width <= 0 or height <= 0:
            raise ValueError(f"Compiled PDF page {page_index + 1} has invalid dimensions")
        pages.append({"width": width, "height": height})
        for ref in page.get("/Annots", []):
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Link":
                continue
            action = annot.get("/A")
            uri = action.get("/URI") if action else None
            if not isinstance(uri, str) or not uri.startswith("iperpaper:"):
                continue
            ann_id = uri[len("iperpaper:") :]
            if not re.fullmatch(ANNOTATION_ID, ann_id):
                raise ValueError(f"Compiled PDF contains invalid IperPaper URI: {uri!r}")
            rect = annot.get("/Rect")
            if not rect or len(rect) != 4:
                continue
            x0, y0, x1, y1 = map(float, rect)
            x_lo, x_hi = sorted((x0, x1))
            y_lo, y_hi = sorted((y0, y1))
            targets.append(
                {
                    "id": ann_id,
                    "page": page_index + 1,
                    "x": max(0.0, min(1.0, (x_lo - left) / width)),
                    "y": max(0.0, min(1.0, (top - y_hi) / height)),
                    "width": max(0.0, min(1.0, (x_hi - x_lo) / width)),
                    "height": max(0.0, min(1.0, (y_hi - y_lo) / height)),
                }
            )
    return targets, pages


def extract_pdf_level_sections(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """
    Return collapsible level-2 ranges recorded as PDF named destinations.

    Args:
        pdf_bytes: Compiled PDF content.

    Returns:
        list[dict[str, Any]]: Ordered collapsible section ranges.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_metrics: list[tuple[float, float]] = []
    grouped: dict[str, dict[str, Any]] = {}
    for page_index, page in enumerate(reader.pages):
        crop = page.cropbox
        bottom, top = float(crop.bottom), float(crop.top)
        page_metrics.append((bottom, top))
        height = top - bottom
        for ref in page.get("/Annots", []):
            annotation = ref.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            action = annotation.get("/A")
            destination_name = annotation.get("/Dest")
            if not isinstance(destination_name, str) and action and action.get("/S") == "/GoTo":
                destination_name = action.get("/D")
            if not isinstance(destination_name, str):
                continue
            match = LEVEL_DESTINATION.fullmatch(destination_name)
            if not match or match.group(1) != "start":
                continue
            _, section_id = match.groups()
            rect = annotation.get("/Rect")
            if not rect or len(rect) != 4:
                continue
            _, y0, _, y1 = map(float, rect)
            y_lo, y_hi = sorted((y0, y1))
            title_start = max(0.0, min(1.0, (top - y_hi) / height))
            title_end = max(0.0, min(1.0, (top - y_lo) / height))
            section = grouped.setdefault(section_id, {"id": section_id, "level": 2})
            title = section.get("title")
            if title and title["page"] != page_index + 1:
                raise ValueError(f"Level section {section_id!r} title crosses PDF pages")
            start = min(title["y"], title_start) if title else title_start
            end = max(title["y"] + title["height"], title_end) if title else title_end
            section["title"] = {
                "page": page_index + 1,
                "y": start,
                "height": end - start,
            }

    for name, destination in reader.named_destinations.items():
        match = LEVEL_DESTINATION.fullmatch(name)
        if not match:
            continue
        marker, section_id = match.groups()
        page_index = reader.get_destination_page_number(destination)
        if page_index < 0 or page_index >= len(reader.pages):
            raise ValueError(f"Level marker {name!r} points outside the compiled PDF")
        bottom, top = page_metrics[page_index]
        height = top - bottom
        destination_top = destination.top
        if destination_top is None:
            destination_top = top
        y = max(0.0, min(1.0, (top - float(destination_top)) / height))
        section = grouped.setdefault(section_id, {"id": section_id, "level": 2})
        if marker in section:
            raise ValueError(f"Duplicate {marker} marker for level section {section_id!r}")
        section[marker] = {"page": page_index + 1, "y": y}

    sections: list[dict[str, Any]] = []
    for section_id, section in grouped.items():
        missing = {"start", "content", "end"} - section.keys()
        if missing:
            raise ValueError(
                f"Level section {section_id!r} is missing compiled PDF markers: {sorted(missing)}"
            )
        positions = [(section[name]["page"] - 1) + section[name]["y"] for name in ("start", "content", "end")]
        if positions != sorted(positions):
            raise ValueError(f"Level section {section_id!r} has out-of-order start/content/end markers")
        sections.append(section)

    sections.sort(key=lambda item: (item["start"]["page"] - 1) + item["start"]["y"])
    for previous, current in zip(sections, sections[1:]):
        previous_end = (previous["end"]["page"] - 1) + previous["end"]["y"]
        current_start = (current["start"]["page"] - 1) + current["start"]["y"]
        if current_start < previous_end:
            raise ValueError(
                f"Level section {current['id']!r} overlaps or is nested inside "
                f"level section {previous['id']!r}"
            )
    return sections


def validate_compiled_targets(annotations: dict[str, Any], targets: list[dict[str, Any]]) -> None:
    """
    Check that compiled annotation targets match the metadata.

    Args:
        annotations: Annotation metadata.
        targets: Compiled annotation target rectangles.
    """
    validate_annotation_metadata(annotations)
    annotation_ids = {ann["id"] for ann in annotations["annotations"]}
    target_ids = {target["id"] for target in targets}
    unknown = target_ids - annotation_ids
    if unknown:
        raise ValueError(f"Compiled PDF references unknown annotation ids: {sorted(unknown)}")
    unused = annotation_ids - target_ids
    if unused:
        raise ValueError(
            "annotations have no compiled PDF target; check that their TeX marker is reachable "
            f"and uses \\iperpaper{{ID}}{{...}}: {sorted(unused)}"
        )


def _merge_automatic_annotations(
    annotations: dict[str, Any], automatic: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Merge generated reference annotations into authored metadata.

    Args:
        annotations: Annotation metadata.
        automatic: Automatically generated reference annotations.

    Returns:
        dict[str, Any]: Combined and validated annotation metadata.
    """
    merged = {
        "title": annotations["title"],
        "annotations": list(annotations["annotations"]),
        "background": annotations["background"],
    }
    existing = {annotation["id"] for annotation in merged["annotations"]}
    duplicate = existing & {annotation["id"] for annotation in automatic}
    if duplicate:
        raise ValueError(f"Automatic reference annotation ids collide with metadata: {sorted(duplicate)}")
    merged["annotations"].extend(automatic)
    validate_annotation_metadata(merged)
    return merged


def compile_and_collect_annotations(
    source: Path,
    annotations: dict[str, Any],
    main: str | None = None,
    lookup_citation_urls: bool = False,
    citation_cache_path: Path | None = None,
    regenerate_links: bool = False,
) -> tuple[bytes, list[dict[str, Any]], list[dict[str, float]], dict[str, Any]]:
    """
    Compile a paper and collect authored and generated annotations.

    Args:
        source: TeX source file or project directory.
        annotations: Annotation metadata.
        main: Optional main TeX path relative to a project directory.
        lookup_citation_urls: Whether to enrich citations with reliable external links.
        citation_cache_path: Optional persistent citation metadata cache path.
        regenerate_links: Whether to refresh links while retaining cached metadata as fallback.

    Returns:
        tuple[bytes, list[dict[str, Any]], list[dict[str, float]], dict[str, Any]]: PDF bytes, targets, pages, and merged annotations.
    """
    validate_annotation_metadata(annotations)
    project_root, main_file = resolve_project(source, main)
    relative_main = main_file.relative_to(project_root)
    with tempfile.TemporaryDirectory(prefix="iperpaper-latex-") as tmp:
        outdir = Path(tmp).resolve()
        pdf_bytes = _run_latexmk(relative_main, project_root, outdir).read_bytes()
        explicit_targets, pages = extract_pdf_targets(pdf_bytes)
        validate_compiled_targets(annotations, explicit_targets)
        bibliography_paths = sorted(outdir.rglob("*.bbl"))
        source_bbl = main_file.with_suffix(".bbl")
        if source_bbl.is_file():
            bibliography_paths.append(source_bbl)
        automatic, automatic_targets = extract_automatic_reference_annotations(
            pdf_bytes,
            project_root,
            sorted(outdir.rglob("*.aux")),
            bibliography_paths,
            explicit_targets,
            lookup_citation_urls,
            citation_cache_path,
            regenerate_links,
        )
    merged = _merge_automatic_annotations(annotations, automatic)
    return pdf_bytes, explicit_targets + automatic_targets, pages, merged


def compile_and_validate(
    source: Path, annotations: dict[str, Any], main: str | None = None
) -> tuple[bytes, list[dict[str, Any]], list[dict[str, float]]]:
    """
    Compile a paper and validate all annotation targets.

    Args:
        source: TeX source file or project directory.
        annotations: Annotation metadata.
        main: Optional main TeX path relative to a project directory.

    Returns:
        tuple[bytes, list[dict[str, Any]], list[dict[str, float]]]: PDF bytes, targets, and page dimensions.
    """
    pdf_bytes, targets, pages, _ = compile_and_collect_annotations(source, annotations, main)
    return pdf_bytes, targets, pages


def _is_escaped(text: str, index: int) -> bool:
    """
    Check whether a character is escaped by an odd number of backslashes.

    Args:
        text: Text to parse or transform.
        index: Current character offset in the text.

    Returns:
        bool: ``True`` when the indexed character is escaped.
    """
    slash_count = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slash_count += 1
        index -= 1
    return slash_count % 2 == 1


def _skip_tex_space(text: str, index: int) -> int:
    """
    Advance past whitespace in TeX text.

    Args:
        text: Text to parse or transform.
        index: Current character offset in the text.

    Returns:
        int: Offset of the next non-whitespace character.
    """
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _read_tex_delimited(text: str, index: int, opener: str = "{", closer: str = "}") -> tuple[str, int]:
    """
    Read a balanced delimited group from TeX text.

    Args:
        text: Text to parse or transform.
        index: Current character offset in the text.
        opener: Opening delimiter.
        closer: Closing delimiter.

    Returns:
        tuple[str, int]: Delimited content and the offset after its closer.
    """
    index = _skip_tex_space(text, index)
    if index >= len(text) or text[index] != opener:
        raise ValueError(f"Expected {opener!r} in TeX data")
    depth = 1
    start = index + 1
    index += 1
    while index < len(text):
        if text[index] == opener and not _is_escaped(text, index):
            depth += 1
        elif text[index] == closer and not _is_escaped(text, index):
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    raise ValueError(f"Unclosed {opener!r} group in TeX data")


def _top_level_tex_groups(text: str) -> list[str]:
    """
    Parse consecutive top-level brace groups from TeX text.

    Args:
        text: Text to parse or transform.

    Returns:
        list[str]: Contents of the parsed top-level groups.
    """
    groups: list[str] = []
    index = 0
    while True:
        index = _skip_tex_space(text, index)
        if index >= len(text):
            return groups
        group, index = _read_tex_delimited(text, index)
        groups.append(group)


def _strip_tex_comments(text: str) -> str:
    """
    Remove unescaped TeX comments while retaining line breaks.

    Args:
        text: Text to parse or transform.

    Returns:
        str: TeX text without comments.
    """
    output: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "%" and not _is_escaped(text, index):
            newline = text.find("\n", index)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        output.append(text[index])
        index += 1
    return "".join(output)


def _replace_tex_command_with_argument(text: str, command: str, argument: int) -> str:
    """
    Replace each TeX command with one of its arguments.

    Args:
        text: Text to parse or transform.
        command: TeX command name without the leading backslash.
        argument: Argument position, either 1 or 2, whose content should be retained.

    Returns:
        str: Rewritten TeX text.
    """
    pattern = re.compile(rf"\\{re.escape(command)}\b")
    while True:
        match = pattern.search(text)
        if not match:
            return text
        index = match.end()
        try:
            first, index = _read_tex_delimited(text, index)
            if argument == 1:
                replacement = first
            else:
                second, index = _read_tex_delimited(text, index)
                replacement = second
        except ValueError:
            return text
        text = text[: match.start()] + replacement + text[index:]


def _unwrap_iperpaper(text: str) -> str:
    """
    Replace IperPaper wrappers with their visible TeX content.

    Args:
        text: TeX text containing IperPaper wrappers.

    Returns:
        str: TeX with wrapper macros removed.
    """
    return _replace_tex_command_with_argument(text, "iperpaper", 2)


def _plain_bibliography_text(text: str) -> str:
    """
    Convert a TeX bibliography entry into readable tooltip text.

    Args:
        text: TeX bibliography entry to simplify.

    Returns:
        str: Readable bibliography text.
    """
    text = _strip_tex_comments(text)
    text = text.replace(r"\newblock", " ")
    text = _replace_tex_command_with_argument(text, "href", 2)
    for command in ("url", "doi", "emph", "textit", "textbf", "texttt", "textrm"):
        text = _replace_tex_command_with_argument(text, command, 1)
    replacements = {
        r"\&": "&",
        r"\%": "%",
        r"\_": "_",
        r"\#": "#",
        "~": " ",
        "---": "—",
        "--": "–",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _plain_bibtex_text(text: str) -> str:
    """
    Render a BibTeX field containing LaTeX markup as plain Unicode text.

    Args:
        text: Raw BibTeX field value.

    Returns:
        str: Plain Unicode field text.
    """
    try:
        return re.sub(r"\s+", " ", Text.from_latex(text).render_as("text")).strip()
    except PybtexError:
        return _plain_bibliography_text(text).replace("{", "").replace("}", "")


def _plain_bibtex_person(person: Person) -> str:
    """
    Render a parsed BibTeX person in natural given-to-family order.

    Args:
        person: Parsed Pybtex person.

    Returns:
        str: Plain Unicode author name.
    """
    parts = [
        *person.first_names,
        *person.middle_names,
        *person.prelast_names,
        *person.last_names,
        *person.lineage_names,
    ]
    return _plain_bibtex_text(" ".join(parts))


def _bibliography_source_paths(project_root: Path) -> list[Path]:
    """
    Find BibTeX databases explicitly referenced by the TeX project.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        list[Path]: Existing referenced BibTeX files without duplicates.
    """
    paths: list[Path] = []
    for tex_path in tex_files(project_root):
        text = _strip_tex_comments(_read_text(tex_path))
        references: list[str] = []
        for match in re.finditer(r"\\bibliography\s*\{([^{}]+)\}", text):
            references.extend(match.group(1).split(","))
        references.extend(
            match.group(1)
            for match in re.finditer(
                r"\\addbibresource(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}",
                text,
            )
        )
        for reference in references:
            relative = Path(reference.strip())
            if not relative.name:
                continue
            if relative.suffix.lower() != ".bib":
                relative = relative.with_suffix(".bib")
            candidates = (project_root / relative, tex_path.parent / relative)
            path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
            if path is not None and path not in paths:
                paths.append(path)
    return paths


def _extract_bibtex_metadata(project_root: Path) -> dict[str, dict[str, Any]]:
    """
    Extract trusted title and author metadata from referenced BibTeX databases.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        dict[str, dict[str, Any]]: BibTeX metadata keyed by citation key.
    """
    metadata: dict[str, dict[str, Any]] = {}
    for path in _bibliography_source_paths(project_root):
        try:
            database = parse_file(str(path), bib_format="bibtex")
        except (OSError, UnicodeError, PybtexError):
            continue
        for key, bib_entry in database.entries.items():
            title = _plain_bibtex_text(bib_entry.fields.get("title", ""))
            authors = [
                name
                for person in bib_entry.persons.get("author", [])
                if (name := _plain_bibtex_person(person))
            ]
            record: dict[str, Any] = {
                "authors": authors,
                "lookup_source": " ".join(bib_entry.fields.values()),
            }
            if title:
                record["paper_title"] = title
            doi = bib_entry.fields.get("doi")
            if isinstance(doi, str) and doi.strip():
                record["doi"] = doi.strip()
            metadata.setdefault(key, record)
    return metadata


def _extract_equations(project_root: Path) -> dict[str, dict[str, str]]:
    """
    Extract labeled equation bodies from a TeX project.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        dict[str, dict[str, str]]: Equation metadata keyed by TeX label.
    """
    equations: dict[str, dict[str, str]] = {}
    begin_pattern = re.compile(r"\\begin\s*\{\s*(" + "|".join(sorted(EQUATION_ENVIRONMENTS)) + r")(\*)?\s*\}")
    for path in tex_files(project_root):
        raw = _read_text(path)
        text = _strip_tex_comments(raw)
        for begin in begin_pattern.finditer(text):
            environment = begin.group(1)
            star = begin.group(2) or ""
            end_pattern = re.compile(rf"\\end\s*\{{\s*{re.escape(environment + star)}\s*\}}")
            end = end_pattern.search(text, begin.end())
            if not end:
                continue
            body = text[begin.end() : end.start()]
            labels = list(re.finditer(r"\\label\s*\{([^{}]+)\}", body))
            if not labels:
                continue
            cleaned = re.sub(r"\\label\s*\{[^{}]+\}", "", body)
            cleaned = re.sub(r"\\(?:notag|nonumber)\b", "", cleaned)
            cleaned = _unwrap_iperpaper(cleaned).strip()
            if environment != "equation" and not re.search(
                r"\\begin\s*\{(?:aligned|gathered|multlined)\}", cleaned
            ):
                cleaned = rf"\begin{{aligned}}{cleaned}\end{{aligned}}"
            for label_match in labels:
                label = label_match.group(1).strip()
                equations.setdefault(
                    label,
                    {
                        "tex": cleaned,
                    },
                )
    return equations


def _extract_bibliography_entries(
    project_root: Path, artifact_paths: list[Path]
) -> dict[str, dict[str, Any]]:
    """
    Extract bibliography entries from build artifacts and TeX sources.

    Args:
        project_root: Root directory of the TeX project.
        artifact_paths: Compiled artifact paths that may contain bibliography entries.

    Returns:
        dict[str, dict[str, Any]]: Bibliography metadata keyed by citation key.
    """
    entries: dict[str, dict[str, Any]] = {}
    bibtex_metadata = _extract_bibtex_metadata(project_root)
    candidates = artifact_paths + tex_files(project_root)
    for path in candidates:
        raw = _read_text(path)
        text = _strip_tex_comments(raw)
        matches = list(re.finditer(r"\\bibitem\b", text))
        for offset, match in enumerate(matches):
            index = _skip_tex_space(text, match.end())
            if index < len(text) and text[index] == "[":
                try:
                    _, index = _read_tex_delimited(text, index, "[", "]")
                except ValueError:
                    continue
            try:
                key, body_start = _read_tex_delimited(text, index)
            except ValueError:
                continue
            body_end = matches[offset + 1].start() if offset + 1 < len(matches) else len(text)
            bibliography_end = text.find(r"\end{thebibliography}", body_start, body_end)
            if bibliography_end >= 0:
                body_end = bibliography_end
            key = key.strip()
            source = text[body_start:body_end]
            entry = {
                "text": _plain_bibliography_text(source),
                "source": source,
                "_paper_title_verified": False,
            }
            source_metadata = bibtex_metadata.get(key)
            if source_metadata:
                paper_title = source_metadata.get("paper_title")
                if isinstance(paper_title, str) and paper_title:
                    entry["paper_title"] = paper_title
                    entry["_paper_title_verified"] = True
                    entry["_paper_title_source"] = "bibtex"
                authors = source_metadata.get("authors")
                if isinstance(authors, list) and authors:
                    entry["authors"] = authors
                lookup_source = source_metadata.get("lookup_source")
                if isinstance(lookup_source, str) and lookup_source:
                    entry["_lookup_source"] = source + " " + lookup_source
                doi = source_metadata.get("doi")
                if isinstance(doi, str) and doi:
                    entry["_doi"] = doi
            entries.setdefault(key, entry)
    return entries


def default_citation_cache_path(annotations_path: Path) -> Path:
    """
    Derive the default citation metadata cache path.

    Args:
        annotations_path: Path to the paper's annotation metadata.

    Returns:
        Path: Citation cache path beside the annotation metadata.
    """
    suffix = ".annotations.json"
    if annotations_path.name.endswith(suffix):
        stem = annotations_path.name[: -len(suffix)]
        return annotations_path.with_name(stem + ".citations.json")
    return annotations_path.with_suffix(".citations.json")


def _load_citation_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    """
    Load citation metadata keyed by the TeX bibliography citation key.

    Args:
        path: Optional JSON cache path.

    Returns:
        dict[str, dict[str, Any]]: Cache records keyed by TeX citation key.

    Raises:
        ValueError: If the cache exists but is not valid JSON metadata.
    """
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid citation cache JSON in {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("citations", []), list):
        raise ValueError(f"Invalid citation cache format in {path}: expected a citations list")

    cache: dict[str, dict[str, Any]] = {}
    for item in value["citations"]:
        if not isinstance(item, dict):
            continue
        citation_key = item.get("citation_key")
        if not isinstance(citation_key, str) or not citation_key.strip():
            continue
        citation_key = citation_key.strip()
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, (int, str)):
            continue
        index_key = str(index).strip()
        if not index_key:
            continue
        paper_title_verified = item.get("paper_title_verified") is True
        paper_title = item.get("paper_title", "") if paper_title_verified else ""
        authors = item.get("authors", [])
        links = item.get("links", [])
        record: dict[str, Any] = {
            "citation_key": citation_key,
            "index": int(index_key) if index_key.isdigit() else index_key,
            "paper_title": paper_title if isinstance(paper_title, str) else "",
            "paper_title_source": (
                item.get("paper_title_source", "")
                if isinstance(item.get("paper_title_source", ""), str)
                else ""
            ),
            "paper_title_verified": paper_title_verified,
            "lookup_complete": item.get("lookup_complete") is True,
            "authors": (
                [author for author in authors if isinstance(author, str)] if isinstance(authors, list) else []
            ),
            "links": [link for link in links if isinstance(link, str)] if isinstance(links, list) else [],
        }
        manual_url = item.get("external_url")
        if isinstance(manual_url, str) and manual_url:
            record["links"].insert(0, manual_url)
        record["links"] = list(dict.fromkeys(record["links"]))
        cache[citation_key] = record
    return cache


def _apply_citation_cache(entry: dict[str, Any], cached: dict[str, Any]) -> None:
    """
    Apply one cached citation record to a bibliography entry.

    Args:
        entry: Parsed bibliography entry to update in place.
        cached: Cached citation metadata.
    """
    paper_title = cached.get("paper_title")
    if cached.get("paper_title_verified") is True and isinstance(paper_title, str) and paper_title:
        entry["paper_title"] = paper_title
        entry["_paper_title_verified"] = True
        paper_title_source = cached.get("paper_title_source")
        entry["_paper_title_source"] = (
            paper_title_source if isinstance(paper_title_source, str) and paper_title_source else "cache"
        )
    authors = cached.get("authors")
    if isinstance(authors, list) and authors:
        entry["authors"] = [author for author in authors if isinstance(author, str)]
    links = cached.get("links")
    if isinstance(links, list):
        valid_links = [
            link for link in links if isinstance(link, str) and re.fullmatch(r"https?://[^\s]+", link)
        ]
        if valid_links:
            entry["links"] = list(dict.fromkeys(valid_links))
            entry["external_url"] = entry["links"][0]


def _citation_cache_record(
    citation_key: str,
    index: str,
    entry: dict[str, Any],
    lookup_complete: bool,
) -> dict[str, Any]:
    """
    Convert an enriched bibliography entry to a cache record.

    Args:
        citation_key: Stable key used by ``\\cite`` and ``\\bibitem``.
        index: Rendered citation index.
        entry: Parsed and optionally enriched bibliography entry.
        lookup_complete: Whether citation lookup was enabled for this record.

    Returns:
        dict[str, Any]: JSON-serializable citation metadata.
    """
    raw_links = entry.get("links", [])
    links = [link for link in raw_links if isinstance(link, str)] if isinstance(raw_links, list) else []
    external_url = entry.get("external_url")
    if isinstance(external_url, str) and external_url:
        links.insert(0, external_url)
    links = list(dict.fromkeys(links))
    raw_authors = entry.get("authors", [])
    authors = (
        [author for author in raw_authors if isinstance(author, str)] if isinstance(raw_authors, list) else []
    )
    paper_title = entry.get("paper_title")
    return {
        "citation_key": citation_key,
        "index": int(index) if index.isdigit() else index,
        "paper_title": paper_title if isinstance(paper_title, str) else "",
        "paper_title_source": entry.get("_paper_title_source", ""),
        "paper_title_verified": entry.get("_paper_title_verified") is True,
        "authors": authors,
        "links": links,
        "lookup_complete": lookup_complete,
    }


def _save_citation_cache(path: Path | None, cache: dict[str, dict[str, Any]]) -> None:
    """
    Save citation metadata in a stable, human-editable JSON format.

    Args:
        path: Optional JSON cache path.
        cache: Citation records keyed by TeX citation key.
    """
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)

    def sort_key(record: dict[str, Any]) -> tuple[int, int | str]:
        index = record.get("index")
        if isinstance(index, int) and not isinstance(index, bool):
            return 0, index
        if isinstance(index, str) and index.strip().isdigit():
            return 0, int(index.strip())
        return 1, str(index)

    citations = sorted(cache.values(), key=sort_key)
    payload = {"version": CITATION_CACHE_VERSION, "citations": citations}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plain_figure_caption(text: str) -> str:
    """
    Turn a source caption into readable tooltip text while preserving TeX math.

    Args:
        text: TeX caption source to simplify.

    Returns:
        str: Readable caption text.
    """
    text = _strip_tex_comments(text)
    text = _unwrap_iperpaper(text)
    text = _replace_tex_command_with_argument(text, "href", 2)
    for command in (
        "emph",
        "textit",
        "textbf",
        "texttt",
        "textrm",
        "textsf",
        "mbox",
    ):
        text = _replace_tex_command_with_argument(text, command, 1)
    text = re.sub(r"\\(?:cite|citep|citet|citealp|citealt)\s*\{[^{}]*\}", "", text)
    text = re.sub(
        r"\\(?:Cref|cref|autoref|ref)\s*\{[^{}]*\}",
        "the referenced figure",
        text,
    )
    replacements = {
        r"\&": "&",
        r"\%": "%",
        r"\_": "_",
        r"\#": "#",
        r"\,": " ",
        "~": " ",
        "---": "—",
        "--": "–",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _extract_figures(project_root: Path) -> dict[str, dict[str, str]]:
    """
    Extract the main caption associated with each figure label.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        dict[str, dict[str, str]]: Figure metadata keyed by TeX label.
    """
    figures: dict[str, dict[str, str]] = {}
    begin_pattern = re.compile(r"\\begin\s*\{\s*figure\*?\s*\}")
    end_pattern = re.compile(r"\\end\s*\{\s*figure\*?\s*\}")
    command_pattern = re.compile(r"\\(caption|label)\b")
    for path in tex_files(project_root):
        text = _strip_tex_comments(_read_text(path))
        for begin in begin_pattern.finditer(text):
            end = end_pattern.search(text, begin.end())
            if not end:
                continue
            body = text[begin.end() : end.start()]
            last_caption = ""
            for command in command_pattern.finditer(body):
                index = command.end()
                if command.group(1) == "caption":
                    index = _skip_tex_space(body, index)
                    if index < len(body) and body[index] == "[":
                        try:
                            _, index = _read_tex_delimited(body, index, "[", "]")
                        except ValueError:
                            continue
                    try:
                        caption, _ = _read_tex_delimited(body, index)
                    except ValueError:
                        continue
                    last_caption = _plain_figure_caption(caption)
                    continue
                try:
                    label, _ = _read_tex_delimited(body, index)
                except ValueError:
                    continue
                label = label.strip()
                if label and last_caption:
                    figures.setdefault(label, {"caption": last_caption})
    return figures


def _extract_tables(project_root: Path) -> dict[str, dict[str, str]]:
    """
    Extract the caption and tabular source associated with each table label.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        dict[str, dict[str, str]]: Table metadata keyed by TeX label.
    """
    tables: dict[str, dict[str, str]] = {}
    begin_pattern = re.compile(r"\\begin\s*\{\s*table\*?\s*\}")
    end_pattern = re.compile(r"\\end\s*\{\s*table\*?\s*\}")
    command_pattern = re.compile(r"\\(caption|label)\b")
    # Match standard and custom environments whose names identify them as a
    # tabular construct (for example tabularx, tblr, longtblr, or mytabular).
    # Captions often sit below these environments, so isolating the inner body
    # prevents the live caption from also being rasterized into the preview.
    tabular_pattern = re.compile(
        r"\\begin\s*\{\s*(?P<env>[A-Za-z@]*(?:tabular|tblr|longtable)[A-Za-z@*]*)\s*\}"
        r"([\s\S]*?)"
        r"\\end\s*\{\s*(?P=env)\s*\}"
    )
    for path in tex_files(project_root):
        text = _strip_tex_comments(_read_text(path))
        for begin in begin_pattern.finditer(text):
            end = end_pattern.search(text, begin.end())
            if not end:
                continue
            body = text[begin.end() : end.start()]
            tabular_match = tabular_pattern.search(body)
            tabular = tabular_match.group(2) if tabular_match else body
            last_caption = ""
            last_caption_offset = -1
            for command in command_pattern.finditer(body):
                index = command.end()
                if command.group(1) == "caption":
                    index = _skip_tex_space(body, index)
                    if index < len(body) and body[index] == "[":
                        try:
                            _, index = _read_tex_delimited(body, index, "[", "]")
                        except ValueError:
                            continue
                    try:
                        caption, _ = _read_tex_delimited(body, index)
                    except ValueError:
                        continue
                    last_caption = _plain_figure_caption(caption)
                    last_caption_offset = command.start()
                    continue
                try:
                    label, _ = _read_tex_delimited(body, index)
                except ValueError:
                    continue
                label = label.strip()
                if label and last_caption:
                    caption_position = "unknown"
                    if tabular_match:
                        caption_position = (
                            "before" if last_caption_offset < tabular_match.start() else "after"
                        )
                    tables.setdefault(
                        label,
                        {
                            "caption": last_caption,
                            "caption_position": caption_position,
                            "tabular": tabular,
                        },
                    )
    return tables


def _parse_aux_reference_data(aux_paths: list[Path]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """
    Parse equation and bibliography labels from LaTeX auxiliary files.

    Args:
        aux_paths: LaTeX auxiliary files to parse.

    Returns:
        tuple[dict[str, dict[str, str]], dict[str, str]]: Equation metadata and rendered bibliography labels.
    """
    equation_labels: dict[str, dict[str, str]] = {}
    bibliography_labels: dict[str, str] = {}
    for path in aux_paths:
        text = _read_text(path)
        for match in re.finditer(r"\\newlabel\b", text):
            try:
                label, index = _read_tex_delimited(text, match.end())
                payload, _ = _read_tex_delimited(text, index)
                fields = _top_level_tex_groups(payload)
            except ValueError:
                continue
            if len(fields) >= 4 and fields[3].startswith("equation."):
                equation_labels[label] = {
                    "number": fields[0],
                    "page": fields[1],
                    "destination": fields[3],
                }
        for match in re.finditer(r"\\bibcite\b", text):
            try:
                key, index = _read_tex_delimited(text, match.end())
                label, _ = _read_tex_delimited(text, index)
            except ValueError:
                continue
            try:
                label_fields = _top_level_tex_groups(label) if label.lstrip().startswith("{") else []
            except ValueError:
                label_fields = []
            bibliography_labels[key] = label_fields[0] if label_fields else label
    return equation_labels, bibliography_labels


def _parse_aux_figure_reference_data(aux_paths: list[Path]) -> dict[str, dict[str, str]]:
    """
    Parse figure reference data from LaTeX auxiliary files.

    Args:
        aux_paths: LaTeX auxiliary files to parse.

    Returns:
        dict[str, dict[str, str]]: Figure reference metadata keyed by label.
    """
    figure_labels: dict[str, dict[str, str]] = {}
    for path in aux_paths:
        text = _read_text(path)
        for match in re.finditer(r"\\newlabel\b", text):
            try:
                label, index = _read_tex_delimited(text, match.end())
                payload, _ = _read_tex_delimited(text, index)
                fields = _top_level_tex_groups(payload)
            except ValueError:
                continue
            if len(fields) >= 4 and fields[3].startswith("figure"):
                figure_labels[label] = {
                    "number": fields[0],
                    "page": fields[1],
                    "destination": fields[3],
                }
    return figure_labels


def _parse_aux_table_reference_data(aux_paths: list[Path]) -> dict[str, dict[str, str]]:
    """
    Parse table reference data from LaTeX auxiliary files.

    Args:
        aux_paths: LaTeX auxiliary files to parse.

    Returns:
        dict[str, dict[str, str]]: Table reference metadata keyed by label.
    """
    table_labels: dict[str, dict[str, str]] = {}
    for path in aux_paths:
        text = _read_text(path)
        for match in re.finditer(r"\\newlabel\b", text):
            try:
                label, index = _read_tex_delimited(text, match.end())
                payload, _ = _read_tex_delimited(text, index)
                fields = _top_level_tex_groups(payload)
            except ValueError:
                continue
            if len(fields) >= 4 and fields[3].startswith("table"):
                table_labels[label] = {
                    "number": fields[0],
                    "page": fields[1],
                    "destination": fields[3],
                }
    return table_labels


def _normalized_pdf_rect(page: Any, rect: Any, page_number: int) -> dict[str, float | int]:
    """
    Normalize a PDF rectangle to page-relative coordinates.

    Args:
        page: PDF page object containing the rectangle.
        rect: Rectangle in PDF user coordinates.
        page_number: One-based PDF page number.

    Returns:
        dict[str, float | int]: Page-relative rectangle data.
    """
    crop = page.cropbox
    left, bottom, right, top = map(float, (crop.left, crop.bottom, crop.right, crop.top))
    width, height = right - left, top - bottom
    x0, y0, x1, y1 = map(float, rect)
    x_lo, x_hi = sorted((x0, x1))
    y_lo, y_hi = sorted((y0, y1))
    return {
        "page": page_number,
        "x": max(0.0, min(1.0, (x_lo - left) / width)),
        "y": max(0.0, min(1.0, (top - y_hi) / height)),
        "width": max(0.0, min(1.0, (x_hi - x_lo) / width)),
        "height": max(0.0, min(1.0, (y_hi - y_lo) / height)),
    }


def _targets_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """
    Check whether two annotation targets overlap substantially.

    Args:
        first: First page-relative target rectangle.
        second: Second page-relative target rectangle.

    Returns:
        bool: ``True`` when the targets overlap substantially.
    """
    if first["page"] != second["page"]:
        return False
    left = max(first["x"], second["x"])
    right = min(first["x"] + first["width"], second["x"] + second["width"])
    top = max(first["y"], second["y"])
    bottom = min(first["y"] + first["height"], second["y"] + second["height"])
    if right <= left or bottom <= top:
        return False
    intersection = (right - left) * (bottom - top)
    smaller = min(first["width"] * first["height"], second["width"] * second["height"])
    return smaller > 0 and intersection / smaller >= 0.5


def _pdf_matrix_multiply(first: list[float], second: list[float]) -> list[float]:
    """
    Multiply two PDF affine transformation matrices.

    Args:
        first: Left PDF affine transformation matrix.
        second: Right PDF affine transformation matrix.

    Returns:
        list[float]: Combined affine transformation matrix.
    """
    return [
        first[0] * second[0] + first[1] * second[2],
        first[0] * second[1] + first[1] * second[3],
        first[2] * second[0] + first[3] * second[2],
        first[2] * second[1] + first[3] * second[3],
        first[4] * second[0] + first[5] * second[2] + second[4],
        first[4] * second[1] + first[5] * second[3] + second[5],
    ]


def _transform_pdf_point(matrix: list[float], x: float, y: float) -> tuple[float, float]:
    """
    Transform a point with a PDF affine matrix.

    Args:
        matrix: Six-value PDF affine transformation matrix.
        x: Horizontal point coordinate.
        y: Vertical point coordinate.

    Returns:
        tuple[float, float]: Transformed point coordinates.
    """
    return (
        x * matrix[0] + y * matrix[2] + matrix[4],
        x * matrix[1] + y * matrix[3] + matrix[5],
    )


def _page_xobject_boxes(page: Any) -> list[tuple[float, float, float, float]]:
    """
    Return direct image/Form boxes in PDF user coordinates.

    Args:
        page: PDF page whose image and form objects should be inspected.

    Returns:
        list[tuple[float, float, float, float]]: Detected image and form boxes.
    """
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") or {}
    contents = page.get_contents()
    if contents is None or not xobjects:
        return []
    stream = ContentStream(contents, page.pdf)
    matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    stack: list[list[float]] = []
    boxes: list[tuple[float, float, float, float]] = []
    for operands, operator in stream.operations:
        if operator == b"q":
            stack.append(list(matrix))
        elif operator == b"Q":
            matrix = stack.pop() if stack else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        elif operator == b"cm" and len(operands) >= 6:
            matrix = _pdf_matrix_multiply([float(value) for value in operands[:6]], matrix)
        elif operator == b"Do" and operands:
            ref = xobjects.get(operands[0])
            if ref is None:
                continue
            obj = ref.get_object()
            subtype = obj.get("/Subtype")
            if subtype == "/Image":
                raw_box = (0.0, 0.0, 1.0, 1.0)
                object_matrix = matrix
            elif subtype == "/Form" and obj.get("/BBox"):
                raw_box = tuple(float(value) for value in obj["/BBox"])
                form_matrix = [float(value) for value in obj.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                object_matrix = _pdf_matrix_multiply(form_matrix, matrix)
            else:
                continue
            x0, y0, x1, y1 = raw_box
            corners = [
                _transform_pdf_point(object_matrix, x0, y0),
                _transform_pdf_point(object_matrix, x0, y1),
                _transform_pdf_point(object_matrix, x1, y0),
                _transform_pdf_point(object_matrix, x1, y1),
            ]
            xs = [point[0] for point in corners]
            ys = [point[1] for point in corners]
            box = (min(xs), min(ys), max(xs), max(ys))
            if box[2] - box[0] >= 20 and box[3] - box[1] >= 20:
                boxes.append(box)
    return boxes


def _page_rule_boxes(page: Any) -> list[tuple[float, float, float, float]]:
    """
    Return table-like painted path boxes in PDF user coordinates.

    Args:
        page: PDF page whose painted paths should be inspected.

    Returns:
        list[tuple[float, float, float, float]]: Detected painted path boxes.
    """
    contents = page.get_contents()
    if contents is None:
        return []
    stream = ContentStream(contents, page.pdf)
    matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    stack: list[list[float]] = []
    path: list[tuple[float, float]] = []
    boxes: list[tuple[float, float, float, float]] = []
    paint_operators = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
    for operands, operator in stream.operations:
        if operator == b"q":
            stack.append(list(matrix))
        elif operator == b"Q":
            matrix = stack.pop() if stack else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        elif operator == b"cm" and len(operands) >= 6:
            matrix = _pdf_matrix_multiply([float(value) for value in operands[:6]], matrix)
        elif operator in {b"m", b"l"} and len(operands) >= 2:
            path.append(_transform_pdf_point(matrix, float(operands[0]), float(operands[1])))
        elif operator == b"re" and len(operands) >= 4:
            x, y, width, height = (float(value) for value in operands[:4])
            path.extend(
                _transform_pdf_point(matrix, px, py)
                for px, py in ((x, y), (x + width, y), (x, y + height), (x + width, y + height))
            )
        elif operator in paint_operators:
            if len(path) >= 2:
                xs = [point[0] for point in path]
                ys = [point[1] for point in path]
                box = (min(xs), min(ys), max(xs), max(ys))
                if box[2] - box[0] >= 20 or box[3] - box[1] >= 20:
                    boxes.append(box)
            path = []
        elif operator == b"n":
            path = []
    return boxes


def _boxes_touch(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    gap: float = 42.0,
) -> bool:
    """
    Check whether two artwork boxes overlap or lie within a gap.

    Args:
        first: First artwork box in PDF user coordinates.
        second: Second artwork box in PDF user coordinates.
        gap: Maximum separation at which boxes are considered touching.

    Returns:
        bool: ``True`` when the boxes touch within the allowed gap.
    """
    horizontal_overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    vertical_overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    horizontal_gap = max(0.0, max(first[0], second[0]) - min(first[2], second[2]))
    vertical_gap = max(0.0, max(first[1], second[1]) - min(first[3], second[3]))
    min_width = min(first[2] - first[0], second[2] - second[0])
    min_height = min(first[3] - first[1], second[3] - second[1])
    return (vertical_overlap >= 0.15 * min_height and horizontal_gap <= gap) or (
        horizontal_overlap >= 0.15 * min_width and vertical_gap <= gap
    )


def _figure_artwork_box(
    reader: PdfReader, destination: str
) -> tuple[int, tuple[float, float, float, float]] | None:
    """
    Locate the rendered artwork associated with a figure destination.

    Args:
        reader: PDF reader containing named destinations and pages.
        destination: Named PDF destination associated with the content.

    Returns:
        tuple[int, tuple[float, float, float, float]] | None: Page number and artwork bounds, or ``None`` if not found.
    """
    named = reader.named_destinations.get(destination)
    if named is None:
        return None
    page_index = reader.get_destination_page_number(named)
    if page_index < 0:
        return None
    page = reader.pages[page_index]
    crop = page.cropbox
    page_top = float(crop.top)
    anchor_top = page_top - float(named.top if named.top is not None else page_top)
    boxes = _page_xobject_boxes(page)
    if not boxes:
        return None

    def top_distance(box: tuple[float, float, float, float]) -> float:
        """
        Measure a box's vertical distance from the figure anchor.

        Args:
            box: Artwork box in PDF user coordinates.

        Returns:
            float: Absolute vertical distance from the anchor.
        """
        return abs((page_top - box[3]) - anchor_top)

    seed = min(boxes, key=lambda box: (top_distance(box), -(box[2] - box[0]) * (box[3] - box[1])))
    if top_distance(seed) > 120:
        return None
    selected = [seed]
    remaining = [box for box in boxes if box is not seed]
    changed = True
    while changed:
        changed = False
        for box in list(remaining):
            if any(_boxes_touch(box, chosen) for chosen in selected):
                selected.append(box)
                remaining.remove(box)
                changed = True
    padding = 1.5
    x0 = max(float(crop.left), min(box[0] for box in selected) - padding)
    y0 = max(float(crop.bottom), min(box[1] for box in selected) - padding)
    x1 = min(float(crop.right), max(box[2] for box in selected) + padding)
    y1 = min(float(crop.top), max(box[3] for box in selected) + padding)
    return page_index + 1, (x0, y0, x1, y1)


def _plain_table_tokens(source: str) -> list[str]:
    """
    Return stable prose-like tokens from tabular TeX for PDF text matching.

    Args:
        source: Tabular TeX source to tokenize.

    Returns:
        list[str]: Normalized table tokens.
    """
    source = _unwrap_iperpaper(_strip_tex_comments(source))
    source = re.sub(r"\\(?:begin|end)\s*\{[^{}]+\}", " ", source)
    source = re.sub(r"\\(?:hline|toprule|midrule|bottomrule|cline|cmidrule)\b(?:\s*\{[^{}]*\})?", " ", source)
    source = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", " ", source)
    source = re.sub(r"[{}$&_^~|]+|\\\\", " ", source)
    return re.findall(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", source.lower())


def _pdf_word_boxes(pdf_path: Path) -> dict[int, list[tuple[str, float, float, float, float]]]:
    """
    Extract Poppler word boxes, keyed by one-based page number.

    Args:
        pdf_path: Path to the compiled PDF.

    Returns:
        dict[int, list[tuple[str, float, float, float, float]]]: Word boxes grouped by one-based page number.
    """
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        return {}
    proc = subprocess.run(
        [pdftotext, "-bbox", str(pdf_path), "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {}
    pages: dict[int, list[tuple[str, float, float, float, float]]] = {}
    page_number = 0
    page_pattern = re.compile(r"<page\s+width=\"[0-9.]+\"\s+height=\"[0-9.]+\">")
    word_pattern = re.compile(
        r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" xMax="([0-9.]+)" ' r'yMax="([0-9.]+)">([^<]*)</word>'
    )
    for line in proc.stdout.splitlines():
        if page_pattern.search(line):
            page_number += 1
            pages[page_number] = []
            continue
        match = word_pattern.search(line)
        if not match or page_number == 0:
            continue
        token = re.sub(r"[^a-z0-9.-]+", "", html.unescape(match.group(5)).lower())
        if token:
            pages[page_number].append((token, *(float(match.group(index)) for index in range(1, 5))))
    return pages


def _table_artwork_box(
    reader: PdfReader,
    destination: str,
    table_source: dict[str, str],
    words_by_page: dict[int, list[tuple[str, float, float, float, float]]],
) -> tuple[int, tuple[float, float, float, float]] | None:
    """
    Locate rendered table text near its PDF destination.

    Args:
        reader: PDF reader containing named destinations and pages.
        destination: Named PDF destination associated with the content.
        table_source: Extracted table source and caption metadata.
        words_by_page: Extracted PDF word boxes grouped by page.

    Returns:
        tuple[int, tuple[float, float, float, float]] | None: Page number and table bounds, or ``None`` if not found.
    """
    named = reader.named_destinations.get(destination)
    if named is None:
        return None
    page_index = reader.get_destination_page_number(named)
    if page_index < 0:
        return None
    page_number = page_index + 1
    page = reader.pages[page_index]
    crop = page.cropbox
    page_top = float(crop.top)
    anchor_top = page_top - float(named.top if named.top is not None else page_top)
    words = words_by_page.get(page_number, [])
    source_tokens = _plain_table_tokens(table_source["tabular"])
    caption_position = table_source.get("caption_position", "unknown")
    # Hyperref destinations are not consistent about whether a caption-below
    # table is anchored at the caption or at the float's top. Search in both
    # directions, then use the located caption as the hard before/after bound.
    candidates = [word for word in words if anchor_top - 460 <= word[2] <= anchor_top + 460]

    # Locate the separately rendered caption and use it as a hard boundary.
    # This prevents shared words (for example "model size") from pulling the
    # live caption back into the raster table crop.
    caption_tokens = _plain_table_tokens(table_source.get("caption", ""))
    if len(caption_tokens) >= 2:
        caption_matcher = difflib.SequenceMatcher(
            None, [word[0] for word in candidates], caption_tokens, autojunk=False
        )
        caption_words: list[tuple[str, float, float, float, float]] = []
        for block in caption_matcher.get_matching_blocks():
            if block.size >= 2:
                caption_words.extend(candidates[block.a : block.a + block.size])
        if caption_words:
            caption_top = min(word[2] for word in caption_words)
            caption_bottom = max(word[4] for word in caption_words)
            if caption_position == "after":
                candidates = [word for word in candidates if word[4] < caption_top - 1]
            elif caption_position == "before":
                candidates = [word for word in candidates if word[2] > caption_bottom + 1]
    if len(source_tokens) < 2 or len(candidates) < 2:
        return None
    # Poppler may emit table text column-by-column even though TeX source is
    # row-by-row, so sequence matching is not reliable here. Match the token
    # vocabulary, then keep the contiguous row cluster nearest the caption.
    source_vocabulary = set(source_tokens)
    token_matches = [word for word in candidates if word[0] in source_vocabulary]
    token_matches.sort(key=lambda word: (word[2] + word[4]) / 2)
    clusters: list[list[tuple[str, float, float, float, float]]] = []
    for word in token_matches:
        center = (word[2] + word[4]) / 2
        if not clusters:
            clusters.append([word])
            continue
        previous_center = max((item[2] + item[4]) / 2 for item in clusters[-1])
        if center - previous_center <= 28:
            clusters[-1].append(word)
        else:
            clusters.append([word])
    viable_clusters = [cluster for cluster in clusters if len(cluster) >= 2]
    if caption_position == "after":
        matched = viable_clusters[-1] if viable_clusters else []
    elif caption_position == "before":
        matched = viable_clusters[0] if viable_clusters else []
    else:
        matched = max(viable_clusters, key=len, default=[])
    if len(matched) < 2:
        return None

    top = min(word[2] for word in matched)
    bottom = max(word[4] for word in matched)
    left = min(word[1] for word in matched)
    right = max(word[3] for word in matched)
    # Include unmatched math/symbol cells that lie inside the detected rows.
    row_words = [
        word
        for word in candidates
        if top - 4 <= (word[2] + word[4]) / 2 <= bottom + 4
        and left - 24 <= (word[1] + word[3]) / 2 <= right + 24
    ]
    if row_words:
        left = min(word[1] for word in row_words)
        right = max(word[3] for word in row_words)
        top = min(word[2] for word in row_words)
        bottom = max(word[4] for word in row_words)
    # Booktabs and ruled tables can extend beyond their text. Fold in nearby
    # painted rules so the preview represents the actual printed table width.
    for rule_x0, rule_y0, rule_x1, rule_y1 in _page_rule_boxes(page):
        rule_top = page_top - rule_y1
        rule_bottom = page_top - rule_y0
        overlaps_rows = rule_bottom >= top - 8 and rule_top <= bottom + 8
        overlaps_columns = rule_x1 >= left - 12 and rule_x0 <= right + 12
        if overlaps_rows and overlaps_columns:
            left = min(left, rule_x0)
            right = max(right, rule_x1)
            top = min(top, rule_top)
            bottom = max(bottom, rule_bottom)
    padding_x, padding_y = 10.0, 5.0
    x0 = max(float(crop.left), left - padding_x)
    x1 = min(float(crop.right), right + padding_x)
    # Poppler boxes use a top-origin coordinate system; PDF boxes use bottom-origin.
    y0 = max(float(crop.bottom), page_top - bottom - padding_y)
    y1 = min(float(crop.top), page_top - top + padding_y)
    if x1 - x0 < 20 or y1 - y0 < 10:
        return None
    return page_number, (x0, y0, x1, y1)


def _render_figure_previews(
    pdf_bytes: bytes,
    reader: PdfReader,
    destinations: set[str],
    table_sources: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Render cropped previews for referenced figures and tables.

    Args:
        pdf_bytes: Compiled PDF content.
        reader: PDF reader containing named destinations and pages.
        destinations: Named PDF destinations to preview.
        table_sources: Optional table source metadata keyed by destination.

    Returns:
        dict[str, dict[str, Any]]: Preview metadata keyed by PDF destination.
    """
    table_sources = table_sources or {}
    all_destinations = destinations | set(table_sources)
    if not all_destinations:
        return {}
    pdftocairo = require_pdftocairo()
    rendered: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="iperpaper-figure-previews-") as tmp:
        work = Path(tmp)
        pdf_path = work / "paper.pdf"
        pdf_path.write_bytes(pdf_bytes)
        words_by_page = _pdf_word_boxes(pdf_path) if table_sources else {}
        pixels_per_point = FIGURE_PREVIEW_DPI / 72.0
        for index, destination in enumerate(sorted(all_destinations), start=1):
            if destination in table_sources:
                located = _table_artwork_box(reader, destination, table_sources[destination], words_by_page)
            else:
                located = _figure_artwork_box(reader, destination)
            if located is None:
                continue
            page_number, (x0, y0, x1, y1) = located
            page = reader.pages[page_number - 1]
            crop = page.cropbox
            width_pt, height_pt = x1 - x0, y1 - y0
            output_prefix = work / f"figure-{index}"
            command = [
                pdftocairo,
                "-png",
                "-singlefile",
                "-r",
                str(FIGURE_PREVIEW_DPI),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-x",
                str(round((x0 - float(crop.left)) * pixels_per_point)),
                "-y",
                str(round((float(crop.top) - y1) * pixels_per_point)),
                "-W",
                str(max(1, round(width_pt * pixels_per_point))),
                "-H",
                str(max(1, round(height_pt * pixels_per_point))),
                str(pdf_path),
                str(output_prefix),
            ]
            proc = subprocess.run(command, check=False, capture_output=True, text=True)
            png_path = output_prefix.with_suffix(".png")
            if proc.returncode != 0 or not png_path.is_file():
                continue
            payload = base64.b64encode(png_path.read_bytes()).decode("ascii")
            rendered[destination] = {
                "src": f"data:image/png;base64,{payload}",
                "width_pt": round(width_pt, 3),
                "height_pt": round(height_pt, 3),
                "scale": FIGURE_TOOLTIP_SCALE,
            }
    return rendered


def extract_automatic_reference_annotations(
    pdf_bytes: bytes,
    project_root: Path,
    aux_paths: list[Path],
    bibliography_paths: list[Path],
    explicit_targets: list[dict[str, Any]],
    lookup_citation_urls: bool = False,
    citation_cache_path: Path | None = None,
    regenerate_links: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Generate tooltips and rectangles from native equation, float, and citation links.

    Args:
        pdf_bytes: Compiled PDF content.
        project_root: Root directory of the TeX project.
        aux_paths: LaTeX auxiliary files to parse.
        bibliography_paths: Bibliography artifact files to parse.
        explicit_targets: Authored annotation targets extracted from the PDF.
        lookup_citation_urls: Whether to enrich citations with reliable external links.
        citation_cache_path: Optional persistent citation metadata cache path.
        regenerate_links: Whether to refresh links while retaining cached metadata as fallback.

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, Any]]]: Generated annotations and target rectangles.
    """
    equation_labels, bibliography_labels = _parse_aux_reference_data(aux_paths)
    equations = _extract_equations(project_root)
    figures = _extract_figures(project_root)
    tables = _extract_tables(project_root)
    figure_labels = {
        label: item for label, item in _parse_aux_figure_reference_data(aux_paths).items() if label in figures
    }
    table_labels = {
        label: item for label, item in _parse_aux_table_reference_data(aux_paths).items() if label in tables
    }
    bibliography = _extract_bibliography_entries(project_root, bibliography_paths)
    citation_cache = _load_citation_cache(citation_cache_path)
    updated_citation_cache: dict[str, dict[str, Any]] = {}
    if lookup_citation_urls or citation_cache_path is not None:
        for key, entry in bibliography.items():
            citation_index = bibliography_labels.get(key)
            rendered_index = str(citation_index) if citation_index is not None else None
            cached = citation_cache.get(key)
            use_cached = cached is not None and not (lookup_citation_urls and regenerate_links)
            if use_cached:
                _apply_citation_cache(entry, cached)
            elif lookup_citation_urls:
                if cached is not None:
                    _apply_citation_cache(entry, cached)
                enrich_bibliography_entry(entry)
            if rendered_index and (lookup_citation_urls or cached is not None):
                lookup_complete = (
                    cached.get("lookup_complete") is True
                    if use_cached and cached is not None
                    else lookup_citation_urls
                )
                updated_citation_cache[key] = _citation_cache_record(
                    key,
                    rendered_index,
                    entry,
                    lookup_complete,
                )
        _save_citation_cache(citation_cache_path, updated_citation_cache)
    equations_by_destination = {item["destination"]: (label, item) for label, item in equation_labels.items()}
    figures_by_destination = {item["destination"]: (label, item) for label, item in figure_labels.items()}
    tables_by_destination = {item["destination"]: (label, item) for label, item in table_labels.items()}
    legacy_targets = [
        target
        for target in explicit_targets
        if target["id"].startswith(("eqref_", "figref_", "tabref_", "bibref_"))
    ]
    reader = PdfReader(io.BytesIO(pdf_bytes))
    targets: list[dict[str, Any]] = []
    annotations: dict[str, dict[str, Any]] = {}
    figure_destinations: dict[str, str] = {}
    table_destinations: dict[str, str] = {}

    for page_number, page in enumerate(reader.pages, start=1):
        for ref in page.get("/Annots", []):
            annotation = ref.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            action = annotation.get("/A") or {}
            destination = annotation.get("/Dest")
            if not isinstance(destination, str) and action.get("/S") == "/GoTo":
                destination = action.get("/D")
            rect = annotation.get("/Rect")
            if not isinstance(destination, str) or not rect or len(rect) != 4:
                continue

            generated: dict[str, Any] | None = None
            if destination.startswith("equation.") and destination not in equations_by_destination:
                raise ValueError(
                    f"Could not resolve native equation destination {destination!r} from LaTeX aux data"
                )
            if destination in equations_by_destination:
                label, resolved = equations_by_destination[destination]
                source_equation = equations.get(label)
                if not source_equation:
                    raise ValueError(
                        f"Could not extract the TeX body for referenced equation label {label!r}"
                    )
                ann_id = _automatic_reference_id("equation", label)
                number = resolved["number"]
                generated = {
                    "id": ann_id,
                    "kind": "equation",
                    "label": f"$$ {source_equation['tex']} $$",
                    "short": f"Equation ({number}): $$ {source_equation['tex']} $$",
                    "details": (
                        f"Native reference to Equation ({number}), generated automatically "
                        f"from TeX label {label}."
                    ),
                    "background": [],
                }
            elif destination.startswith("figure") and destination not in figures_by_destination:
                raise ValueError(
                    f"Could not resolve native figure destination {destination!r} from LaTeX aux data"
                )
            elif destination in figures_by_destination:
                label, resolved = figures_by_destination[destination]
                source_figure = figures.get(label)
                if not source_figure:
                    raise ValueError(f"Could not extract the caption for referenced figure label {label!r}")
                ann_id = _automatic_reference_id("figure", label)
                number = resolved["number"]
                generated = {
                    "id": ann_id,
                    "kind": "reference",
                    "label": f"Figure {number}",
                    "short": f"Figure {number}: {source_figure['caption']}",
                    "details": (
                        f"Native reference to Figure {number}, generated automatically "
                        f"from TeX label {label}."
                    ),
                    "background": [],
                }
                figure_destinations[ann_id] = destination
            elif destination.startswith("table") and destination not in tables_by_destination:
                raise ValueError(
                    f"Could not resolve native table destination {destination!r} from LaTeX aux data"
                )
            elif destination in tables_by_destination:
                label, resolved = tables_by_destination[destination]
                source_table = tables.get(label)
                if not source_table:
                    raise ValueError(f"Could not extract the caption for referenced table label {label!r}")
                ann_id = _automatic_reference_id("table", label)
                number = resolved["number"]
                generated = {
                    "id": ann_id,
                    "kind": "reference",
                    "label": f"Table {number}",
                    "short": f"Table {number}: {source_table['caption']}",
                    "details": (
                        f"Native reference to Table {number}, generated automatically "
                        f"from TeX label {label}."
                    ),
                    "background": [],
                }
                table_destinations[ann_id] = destination
            elif destination.startswith("cite."):
                key = destination[len("cite.") :]
                if key not in bibliography_labels:
                    raise ValueError(f"Could not resolve cited key {key!r} from LaTeX aux data")
                entry = bibliography.get(key)
                if not entry or not entry["text"]:
                    raise ValueError(f"Could not extract the bibliography entry for cited key {key!r}")
                number = bibliography_labels[key]
                ann_id = _automatic_reference_id("bibliography", key)
                rendered_label = f"[{number}]"
                generated = {
                    "id": ann_id,
                    "kind": "reference",
                    "label": rendered_label,
                    "short": f"{rendered_label} {entry['text']}",
                    "details": (
                        f"Native bibliography reference {rendered_label}, generated "
                        f"automatically from citation key {key}."
                    ),
                    "background": [],
                    "paper_title_source": entry.get("_paper_title_source", ""),
                    "paper_title_verified": entry.get("_paper_title_verified") is True,
                }
                if entry.get("paper_title"):
                    generated["paper_title"] = entry["paper_title"]
                if entry.get("external_url"):
                    generated["external_url"] = entry["external_url"]
            if generated is None:
                continue

            target = {"id": generated["id"], **_normalized_pdf_rect(page, rect, page_number)}
            if any(_targets_overlap(target, legacy) for legacy in legacy_targets):
                continue
            annotations[generated["id"]] = generated
            targets.append(target)

    table_sources = {
        destination: tables[label]
        for label, resolved in table_labels.items()
        if (destination := resolved["destination"]) in set(table_destinations.values())
    }
    previews = _render_figure_previews(
        pdf_bytes,
        reader,
        set(figure_destinations.values()),
        table_sources,
    )
    for ann_id, destination in {**figure_destinations, **table_destinations}.items():
        preview = previews.get(destination)
        if preview and ann_id in annotations:
            annotations[ann_id]["figure_preview"] = preview

    return list(annotations.values()), targets


def split_math_segments(text: str) -> list[tuple[str, str, bool]]:
    """
    Split annotation text into ('text'|'math', content, display) segments.

    Args:
        text: Annotation text containing prose and TeX math.

    Returns:
        list[tuple[str, str, bool]]: Tuples of segment kind, content, and display mode.
    """
    segments: list[tuple[str, str, bool]] = []
    text_start = 0
    i = 0
    while i < len(text):
        opener = closer = None
        display = False
        if text.startswith(r"\(", i):
            opener, closer = r"\(", r"\)"
        elif text.startswith(r"\[", i):
            opener, closer, display = r"\[", r"\]", True
        elif text.startswith("$$", i) and not _is_escaped(text, i):
            opener, closer, display = "$$", "$$", True
        elif text[i] == "$" and not _is_escaped(text, i):
            opener, closer = "$", "$"

        if opener is None:
            i += 1
            continue

        search_from = i + len(opener)
        end = search_from
        while True:
            end = text.find(closer, end)
            if end < 0:
                i += len(opener)
                break
            if closer.startswith("$") and _is_escaped(text, end):
                end += len(closer)
                continue
            if closer.startswith("\\") and _is_escaped(text, end):
                end += len(closer)
                continue
            if text_start < i:
                segments.append(("text", text[text_start:i], False))
            math = text[search_from:end].strip()
            if math:
                segments.append(("math", math, display))
            else:
                segments.append(("text", text[i : end + len(closer)], False))
            i = end + len(closer)
            text_start = i
            break

    if text_start < len(text):
        segments.append(("text", text[text_start:], False))
    if not segments:
        segments.append(("text", text, False))
    return segments


def _find_document_begin(source: str) -> int:
    """
    Find the start of the TeX document outside comments.

    Args:
        source: Complete main-file TeX source.

    Returns:
        int: Offset of the document environment.
    """
    pattern = re.compile(r"\\begin\s*\{\s*document\s*\}")
    i = 0
    in_comment = False
    while i < len(source):
        ch = source[i]
        if in_comment:
            if ch == "\n":
                in_comment = False
            i += 1
            continue
        if ch == "%" and not _is_escaped(source, i):
            in_comment = True
            i += 1
            continue
        if ch == "\\":
            match = pattern.match(source, i)
            if match:
                return i
        i += 1
    raise ValueError("Could not find \\begin{document} in the main TeX file")


def _paper_preamble(source: Path, main: str | None = None) -> tuple[Path, str]:
    """
    Read the main TeX preamble and project root.

    Args:
        source: TeX source file or project directory.
        main: Optional main TeX path relative to a project directory.

    Returns:
        tuple[Path, str]: Project root and TeX preamble.
    """
    project_root, main_file = resolve_project(source, main)
    source_text = _read_text(main_file)
    return project_root, source_text[: _find_document_begin(source_text)]


def _collect_math_fragments(annotations: dict[str, Any]) -> list[tuple[str, bool, bool]]:
    """
    Collect unique math fragments used by annotation text.

    Args:
        annotations: Annotation metadata.

    Returns:
        list[tuple[str, bool, bool]]: Unique math fragments and rendering attributes.
    """
    fragments: list[tuple[str, bool, bool]] = []
    seen: set[tuple[str, bool, bool]] = set()
    rich_texts: list[str] = []
    for ann in annotations["annotations"]:
        rich_texts.extend(ann[field] for field in RICH_TEXT_FIELDS)
    for entry in annotations.get("background", {}).values():
        rich_texts.extend(entry[field] for field in BACKGROUND_FIELDS)
    for text in rich_texts:
        for kind, content, display in split_math_segments(text):
            if kind != "math":
                continue
            key = (content, display, False)
            if key not in seen:
                seen.add(key)
                fragments.append(key)
    # Labels become detail-panel titles, so compile a separate bold math
    # variant without changing matching formulas in tooltip prose or details.
    for ann in annotations["annotations"]:
        for kind, content, display in split_math_segments(ann["label"]):
            if kind != "math":
                continue
            key = (content, display, True)
            if key not in seen:
                seen.add(key)
                fragments.append(key)
    return fragments


def _svg_dimensions_as_points(svg: str) -> str:
    """
    Preserve pdftocairo's PDF-point dimensions when SVG is embedded in HTML.

    Args:
        svg: SVG markup to update.

    Returns:
        str: Updated SVG markup.
    """
    root = re.search(r"<svg\b[^>]*>", svg)
    if not root:
        return svg
    updated = re.sub(
        r'\b(width|height)="([0-9]+(?:\.[0-9]+)?)"',
        r'\1="\2pt"',
        root.group(0),
    )
    return svg[: root.start()] + updated + svg[root.end() :]


def _render_math_svgs(
    source: Path,
    annotations: dict[str, Any],
    main: str | None = None,
) -> dict[tuple[str, bool, bool], str]:
    """
    Render annotation math fragments as embedded SVG data URLs.

    Args:
        source: TeX source file or project directory.
        annotations: Annotation metadata.
        main: Optional main TeX path relative to a project directory.

    Returns:
        dict[tuple[str, bool, bool], str]: SVG data URLs keyed by math fragment attributes.
    """
    fragments = _collect_math_fragments(annotations)
    if not fragments:
        return {}

    pdfcrop = require_pdfcrop()
    pdftocairo = require_pdftocairo()
    project_root, preamble = _paper_preamble(source, main)

    with tempfile.TemporaryDirectory(prefix="iperpaper-tooltip-math-") as tmp:
        work = Path(tmp).resolve()
        tex_path = work / "iperpaper-tooltip-math.tex"
        body: list[str] = [
            preamble,
            "\n\\pagestyle{empty}\n\\begin{document}\n",
        ]
        for index, (fragment, display, bold) in enumerate(fragments, start=1):
            style = r"\displaystyle " if display else ""
            body.append(f"% IperPaper tooltip math fragment {index}\n")
            math = f"\\({style}{fragment}\\)"
            if bold:
                math = "{\\boldmath" + math + "}"
            body.append(f"\\thispagestyle{{empty}}\\noindent\\mbox{{{math}}}\n")
            if index != len(fragments):
                body.append("\\newpage\n")
        body.append("\\end{document}\n")
        tex_path.write_text("".join(body), encoding="utf-8")

        pdf_path = _run_latexmk(tex_path, project_root, work)
        cropped_pdf = work / "iperpaper-tooltip-math-cropped.pdf"
        crop_proc = subprocess.run(
            [pdfcrop, "--margins", "1", str(pdf_path), str(cropped_pdf)],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if crop_proc.returncode != 0 or not cropped_pdf.is_file():
            details = (crop_proc.stdout + "\n" + crop_proc.stderr).strip()
            raise RuntimeError(f"pdfcrop failed while preparing annotation math:\n{details[-4000:]}")

        page_count = len(PdfReader(str(cropped_pdf)).pages)
        if page_count != len(fragments):
            raise RuntimeError(
                "Annotation math rendering produced an unexpected number of pages: "
                f"expected {len(fragments)}, got {page_count}"
            )

        rendered: dict[tuple[str, bool, bool], str] = {}
        for index, key in enumerate(fragments, start=1):
            svg_path = work / f"math-{index}.svg"
            svg_proc = subprocess.run(
                [
                    pdftocairo,
                    "-svg",
                    "-f",
                    str(index),
                    "-l",
                    str(index),
                    str(cropped_pdf),
                    str(svg_path),
                ],
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if svg_proc.returncode != 0 or not svg_path.is_file():
                details = (svg_proc.stdout + "\n" + svg_proc.stderr).strip()
                raise RuntimeError(
                    f"pdftocairo failed while converting annotation math fragment {index}:\n"
                    f"{details[-4000:]}"
                )
            svg = _svg_dimensions_as_points(svg_path.read_text(encoding="utf-8"))
            payload = base64.b64encode(svg.encode("utf-8")).decode("ascii")
            rendered[key] = f"data:image/svg+xml;base64,{payload}"
        return rendered


def _rich_text_html(
    text: str,
    math_svgs: dict[tuple[str, bool, bool], str],
    *,
    bold_math: bool = False,
) -> str:
    """
    Render annotation prose and pre-rendered math as HTML.

    Args:
        text: Annotation text containing prose and TeX math.
        math_svgs: Pre-rendered math SVG data URLs keyed by fragment attributes.
        bold_math: Whether to select bold renderings for math fragments.

    Returns:
        str: Escaped HTML containing embedded math images.
    """
    output: list[str] = []
    for kind, content, display in split_math_segments(text):
        if kind == "text":
            output.append(html.escape(content).replace("\n", "<br>"))
            continue
        src = math_svgs.get((content, display, bold_math))
        if not src:
            output.append(html.escape(content))
            continue
        class_name = "ip-math ip-math-display" if display else "ip-math"
        alt = html.escape(content, quote=True)
        output.append(f'<img class="{class_name}" src="{src}" alt="{alt}">')
    return "".join(output)


def _rich_text_html_with_bold_substring(
    text: str,
    bold_text: str,
    math_svgs: dict[tuple[str, bool, bool], str],
) -> str:
    """
    Render rich text while bolding one plain-text substring.

    Args:
        text: Annotation text containing prose and TeX math.
        bold_text: Exact plain-text substring to emphasize.
        math_svgs: Pre-rendered math SVG data URLs.

    Returns:
        str: Escaped HTML with the requested substring wrapped in ``strong``.
    """
    match = re.search(re.escape(bold_text), text, re.IGNORECASE)
    if not match:
        return _rich_text_html(text, math_svgs)
    start, end = match.span()
    return (
        _rich_text_html(text[:start], math_svgs)
        + "<strong>"
        + _rich_text_html(text[start:end], math_svgs)
        + "</strong>"
        + _rich_text_html(text[end:], math_svgs)
    )


def _resolve_annotation_fallbacks(ann: dict[str, Any], background: dict[str, Any]) -> None:
    """
    Fill empty short/details from the first referenced background entry.

    Args:
        ann: Annotation object to update.
        background: Background explanations keyed by stable identifier.
    """
    ann["_background_used"] = []
    for field in ("short", "details"):
        if not ann[field] and ann["background"]:
            key = ann["background"][0]
            ann[field] = background[key][field]
            if key not in ann["_background_used"]:
                ann["_background_used"].append(key)


def render_annotations_for_html(
    source: Path,
    annotations: dict[str, Any],
    main: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return runtime annotation objects with LaTeX-rendered rich-text fields.

    Args:
        source: TeX source file or project directory.
        annotations: Annotation metadata.
        main: Optional main TeX path relative to a project directory.

    Returns:
        list[dict[str, Any]]: HTML-ready annotation objects.
    """
    validate_annotation_metadata(annotations)
    math_svgs = _render_math_svgs(source, annotations, main)
    rendered_background: dict[str, dict[str, Any]] = {}
    for key, entry in annotations.get("background", {}).items():
        rendered_background[key] = {
            "label": entry.get("label", key),
            **{f"{field}_html": _rich_text_html(entry[field], math_svgs) for field in BACKGROUND_FIELDS},
        }
        link = entry.get("link")
        if link:
            rendered_background[key]["link"] = str(link)
    rendered: list[dict[str, Any]] = []
    for ann in annotations["annotations"]:
        item = dict(ann)
        _resolve_annotation_fallbacks(item, annotations["background"])
        for field in RICH_TEXT_FIELDS:
            item[f"{field}_html"] = _rich_text_html(item[field], math_svgs, bold_math=field == "label")
        item["tooltip_html"] = _rich_text_html(item["short"], math_svgs)
        paper_title = item.get("paper_title")
        if isinstance(paper_title, str) and paper_title and item.get("paper_title_verified") is True:
            item["tooltip_html"] = _rich_text_html_with_bold_substring(item["short"], paper_title, math_svgs)
        block_keys = list(item["background"])
        for key in item["background"]:
            for nested in annotations["background"][key].get("background", []):
                if nested not in block_keys:
                    block_keys.append(nested)
        is_background_only = not ann["short"] and not ann["details"]
        item["background_html"] = [
            {"key": key, **rendered_background[key]}
            for key in block_keys
            if key not in item["_background_used"]
            or (is_background_only and item["_background_used"] == [key])
        ]
        item["background_only"] = is_background_only and bool(block_keys)
        del item["_background_used"]
        rendered.append(item)
    return rendered


def extract_pdf_text_margins(pdf_bytes: bytes) -> dict[str, float]:
    """
    Estimate the dominant left margin and furthest right text edge in the PDF.

    Args:
        pdf_bytes: Compiled PDF content.

    Returns:
        dict[str, float]: Left and right text bounds as page-width fractions.
    """
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        return {"left": 0.0, "right": 1.0}
    with tempfile.TemporaryDirectory(prefix="iperpaper-margins-") as tmp:
        pdf_path = Path(tmp) / "margins.pdf"
        pdf_path.write_bytes(pdf_bytes)
        proc = subprocess.run(
            [pdftotext, "-bbox", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {"left": 0.0, "right": 1.0}
        word_pattern = re.compile(
            r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" xMax="([0-9.]+)" yMax="([0-9.]+)">([^<]*)</word>'
        )
        page_pattern = re.compile(r'<page width="([0-9.]+)" height="([0-9.]+)">')
        lefts: list[float] = []
        rights: list[float] = []
        width = 0.0
        for line in proc.stdout.splitlines():
            page_match = page_pattern.search(line)
            if page_match:
                width = float(page_match.group(1))
                continue
            word_match = word_pattern.search(line)
            if word_match and width > 0:
                lefts.append(float(word_match.group(1)))
                rights.append(float(word_match.group(3)))
        if not lefts or width <= 0:
            return {"left": 0.0, "right": 1.0}
        lefts.sort()
        rights.sort()
        # Dominant left margin: the most common value rounded to 2pt, robust to
        # headings or floats that stick out of the text column.
        rounded = [round(value / 2) * 2 for value in lefts]
        counts: dict[float, int] = {}
        for value in rounded:
            counts[value] = counts.get(value, 0) + 1
        dominant_left = max(counts, key=lambda value: counts[value])
        # Right edge: the maximum word extent so no text line can ever fall
        # under the split-view panel.
        right_edge = max(rights)
        return {
            "left": max(0.0, min(1.0, dominant_left / width)),
            "right": max(0.0, min(1.0, right_edge / width)),
        }


def build_html(
    pdf_bytes: bytes,
    annotations: dict[str, Any],
    targets: list[dict[str, Any]],
    pages: list[dict[str, float]],
    rendered_annotations: list[dict[str, Any]] | None = None,
    level_sections: list[dict[str, Any]] | None = None,
    text_margins: dict[str, float] | None = None,
) -> str:
    """
    Build the interactive PDF-backed HTML reader.

    Args:
        pdf_bytes: Compiled PDF content.
        annotations: Annotation metadata.
        targets: Compiled annotation target rectangles.
        pages: Compiled PDF page dimensions.
        rendered_annotations: HTML-ready annotation objects.
        level_sections: Optional collapsible section ranges extracted from the PDF.
        text_margins: Optional page-relative text margin measurements.

    Returns:
        str: Complete PDF-backed reader HTML.
    """
    title = html.escape(str(annotations["title"]))
    pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii")
    runtime_annotations = rendered_annotations
    if runtime_annotations is None:
        runtime_annotations = []
        for ann in annotations["annotations"]:
            block_keys = list(ann["background"])
            for key in ann["background"]:
                for nested in annotations["background"][key].get("background", []):
                    if nested not in block_keys:
                        block_keys.append(nested)
            is_background_only = not ann["short"] and not ann["details"]
            item = {
                **ann,
                **{f"{field}_html": html.escape(ann[field]) for field in RICH_TEXT_FIELDS},
                "background_html": [
                    {
                        "key": key,
                        "label": annotations["background"][key].get("label", key),
                        **{
                            f"{field}_html": html.escape(annotations["background"][key][field])
                            for field in BACKGROUND_FIELDS
                        },
                        **(
                            {"link": annotations["background"][key]["link"]}
                            if "link" in annotations["background"][key]
                            else {}
                        ),
                    }
                    for key in block_keys
                    if key not in (ann.get("_background_used") or [])
                    or (is_background_only and (ann.get("_background_used") or []) == [key])
                ],
            }
            _resolve_annotation_fallbacks(item, annotations["background"])
            item["short_html"] = html.escape(item["short"])
            item["details_html"] = html.escape(item["details"])
            item["background_only"] = is_background_only and bool(block_keys)
            del item["_background_used"]
            runtime_annotations.append(item)
    annotations_json = json.dumps(runtime_annotations, ensure_ascii=False).replace("</", "<\\/")
    targets_json = json.dumps(targets, separators=(",", ":"))
    pages_json = json.dumps(pages, separators=(",", ":"))
    level_sections_json = json.dumps(level_sections or [], separators=(",", ":"))
    margins = text_margins or {"left": 0.0, "right": 1.0}
    margins_json = json.dumps(margins, separators=(",", ":"))

    template = read_template("pdf_reader.html")

    replacements = {
        "__IP_TITLE__": title,
        "__IP_PDFJS_MODULE_URL__": PDFJS_MODULE_URL,
        "__IP_PDFJS_WORKER_URL__": PDFJS_WORKER_URL,
        "__IP_PDFJS_WASM_URL__": PDFJS_WASM_URL,
        "__IP_PDFJS_CMAP_URL__": PDFJS_CMAP_URL,
        "__IP_PDFJS_STANDARD_FONT_URL__": PDFJS_STANDARD_FONT_URL,
        "__IP_PDFJS_VIEWER_CSS_URL__": PDFJS_VIEWER_CSS_URL,
        "__IP_PDF_BASE64__": pdf_base64,
        "__IP_ANNOTATIONS__": annotations_json,
        "__IP_TARGETS__": targets_json,
        "__IP_PAGE_SIZES__": pages_json,
        "__IP_LEVEL_SECTIONS__": level_sections_json,
        "__IP_TEXT_MARGINS__": margins_json,
        "__IP_PAPER_TITLE_JSON__": json.dumps(str(annotations["title"]), ensure_ascii=False).replace(
            "</", "<\\/"
        ),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def default_output_path(annotations_path: Path) -> Path:
    """
    Derive the default reader HTML path from annotation metadata.

    Metadata inside a canonical ``annotated/`` directory writes its reader to
    the parent paper directory. Other metadata keeps the historical sibling
    output behavior.

    Args:
        annotations_path: Path to the annotation metadata file.

    Returns:
        Path: Default PDF-backed reader path.
    """
    name = annotations_path.name
    suffix = ".annotations.json"
    output_name = (
        name[: -len(suffix)] + ".html"
        if name.endswith(suffix)
        else annotations_path.with_suffix(".html").name
    )
    if annotations_path.parent.name == "annotated":
        return annotations_path.parent.parent / output_name
    return annotations_path.with_name(output_name)


def default_pdf_path(html_path: Path) -> Path:
    """
    Derive the default PDF path from the reader HTML path.

    Args:
        html_path: Path of the PDF-backed HTML reader.

    Returns:
        Path: Default compiled PDF path.
    """
    return html_path.with_suffix(".pdf")


def default_native_html_path(html_path: Path) -> Path:
    """
    Derive the native HTML path from the reader HTML path.

    Args:
        html_path: Path of the PDF-backed HTML reader.

    Returns:
        Path: Default native reader path.
    """
    return html_path.with_name(html_path.stem + ".native.html")


def write_outputs(
    source: Path,
    annotations: dict[str, Any],
    html_output: Path,
    pdf_output: Path | None = None,
    main: str | None = None,
    mode: str = "pdf_html",
    native_html_output: Path | None = None,
    lookup_citation_urls: bool = True,
    citation_cache_path: Path | None = None,
    regenerate_links: bool = False,
) -> tuple[int, int]:
    """
    Compile a paper and write the requested reader artifacts.

    Args:
        source: TeX source file or project directory.
        annotations: Annotation metadata.
        html_output: Primary HTML output path for the selected build mode.
        pdf_output: Optional output path for the compiled PDF. When omitted, the
            compiled PDF is kept in memory for the requested readers.
        main: Optional main TeX path relative to a project directory.
        mode: Reader build mode.
        native_html_output: Optional native reader path when building both modes.
        lookup_citation_urls: Whether to look up reliable external citation links.
        citation_cache_path: Optional persistent citation metadata cache path.
        regenerate_links: Whether to refresh links while retaining cached metadata as fallback.

    Returns:
        tuple[int, int]: Number of PDF pages and annotation targets written.
    """
    if mode not in BUILD_MODES:
        raise ValueError(f"mode must be one of {BUILD_MODES}, got {mode!r}")
    pdf_bytes, targets, pages, merged_annotations = compile_and_collect_annotations(
        source,
        annotations,
        main,
        lookup_citation_urls,
        citation_cache_path,
        regenerate_links,
    )
    level_sections = extract_pdf_level_sections(pdf_bytes)
    text_margins = extract_pdf_text_margins(pdf_bytes)
    rendered_annotations = render_annotations_for_html(source, merged_annotations, main)
    html_output.parent.mkdir(parents=True, exist_ok=True)
    if pdf_output is not None:
        pdf_output.parent.mkdir(parents=True, exist_ok=True)
        pdf_output.write_bytes(pdf_bytes)
    if mode in {"pdf_html", "all"}:
        html_output.write_text(
            build_html(
                pdf_bytes,
                merged_annotations,
                targets,
                pages,
                rendered_annotations,
                level_sections,
                text_margins,
            ),
            encoding="utf-8",
        )
    if mode in {"native_html", "all"}:
        project_root, main_file = resolve_project(source, main)
        native_output = (
            html_output
            if mode == "native_html"
            else native_html_output or default_native_html_path(html_output)
        )
        native_output.parent.mkdir(parents=True, exist_ok=True)
        native_output.write_text(
            build_native_html(
                project_root, main_file, merged_annotations, rendered_annotations, text_margins
            ),
            encoding="utf-8",
        )
    return len(pages), len(targets)


def main() -> None:
    """Run the IperPaper command-line interface."""
    parser = argparse.ArgumentParser(
        prog="iperpaper",
        description="Compile annotated TeX and build interactive PDF-backed or native HTML.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate_cmd = sub.add_parser(
        "validate", help="Compile TeX and validate PDF annotation targets against metadata"
    )
    validate_cmd.add_argument("source", help="Annotated .tex file or annotated TeX project directory")
    validate_cmd.add_argument("annotations", help="Path to *.annotations.json")
    validate_cmd.add_argument("--main", help="Main TeX file relative to SOURCE when SOURCE is a directory")

    build_cmd = sub.add_parser("build", help="Compile annotated TeX and build interactive HTML")
    build_cmd.add_argument("source", help="Annotated .tex file or annotated TeX project directory")
    build_cmd.add_argument("annotations", help="Path to *.annotations.json")
    build_cmd.add_argument("--main", help="Main TeX file relative to SOURCE when SOURCE is a directory")
    build_cmd.add_argument(
        "-o",
        "--output",
        help=(
            "Output HTML path (defaults to the paper root for metadata in "
            "annotated/, otherwise beside the annotation JSON)"
        ),
    )
    build_cmd.add_argument("--pdf-output", help="Also write the compiled PDF to this path")
    build_cmd.add_argument(
        "--no-citation-link-lookup",
        action="store_true",
        help="Do not query external services for citation links",
    )
    build_cmd.add_argument(
        "--citation-cache",
        help="Citation metadata JSON path (defaults beside the annotation JSON)",
    )
    build_cmd.add_argument(
        "--regenerate-links",
        "--regenerate_links",
        dest="regenerate_links",
        action="store_true",
        help="Query citation services again while retaining cached metadata as fallback",
    )
    build_cmd.add_argument(
        "--mode",
        choices=BUILD_MODES,
        default="pdf_html",
        help=(
            "HTML renderer: pdf_html (current PDF.js reader), native_html "
            "(reflowable TeX conversion), or all (default: pdf_html)"
        ),
    )

    args = parser.parse_args()
    source = Path(args.source)
    annotations_path = Path(args.annotations)
    annotations = load_annotations(annotations_path)

    if args.command == "validate":
        pdf_bytes, targets, pages = compile_and_validate(source, annotations, args.main)
        del pdf_bytes
        _, main_file = resolve_project(source, args.main)
        print(
            f"Valid IperPaper project: {main_file} "
            f"({len(pages)} pages, {len(targets)} annotation targets)"
        )
    elif args.command == "build":
        base_output = Path(args.output) if args.output else default_output_path(annotations_path)
        output = base_output
        if args.mode == "native_html" and args.output is None:
            output = default_native_html_path(output)
        pdf_output = Path(args.pdf_output) if args.pdf_output else None
        native_output = default_native_html_path(output) if args.mode == "all" else None
        citation_cache_path = (
            Path(args.citation_cache)
            if args.citation_cache
            else default_citation_cache_path(annotations_path)
        )
        page_count, target_count = write_outputs(
            source,
            annotations,
            output,
            pdf_output,
            args.main,
            args.mode,
            native_output,
            not args.no_citation_link_lookup,
            citation_cache_path,
            args.regenerate_links,
        )
        if pdf_output is not None:
            print(f"Wrote compiled PDF to {pdf_output}")
        print(f"Wrote citation metadata to {citation_cache_path}")
        if args.mode in {"pdf_html", "all"}:
            print(
                f"Wrote PDF-backed interactive paper to {output} "
                f"({page_count} pages, {target_count} annotation targets)"
            )
        if args.mode in {"native_html", "all"}:
            native_output = output if args.mode == "native_html" else native_output
            print(f"Wrote native interactive paper to {native_output}")


if __name__ == "__main__":
    main()
