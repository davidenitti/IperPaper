from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from iperpaper_templates import read_template

ANNOTATION_ID = r"[A-Za-z0-9_.-]+"
TEX_SUFFIXES = {".tex", ".latex"}
GRAPHIC_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".svg", ".eps")
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@4/tex-chtml-nofont.js"
MATHJAX_FONT_PATH = "https://cdn.jsdelivr.net/npm/@mathjax/%%FONT%%-font@4"
LATIN_MODERN_FONTS = (
    ("lmroman10-regular.otf", "400", "normal"),
    ("lmroman10-italic.otf", "400", "italic"),
    ("lmroman10-bold.otf", "700", "normal"),
    ("lmroman10-bolditalic.otf", "700", "italic"),
)


def require_pandoc() -> str:
    """
    Locate the Pandoc executable required for native HTML builds.

    Returns:
        str: Path to ``pandoc``.
    """
    command = shutil.which("pandoc")
    if command is None:
        raise RuntimeError(
            "IperPaper native_html builds convert TeX with Pandoc. Install pandoc and "
            "make sure it is on PATH, or build with --mode pdf_html."
        )
    return command


def _require_pdftocairo() -> str:
    """
    Locate the PDF-to-image converter used for native figure embedding.

    Returns:
        str: Path to ``pdftocairo``.

    Raises:
        RuntimeError: If ``pdftocairo`` is unavailable.
    """
    command = shutil.which("pdftocairo")
    if command is None:
        raise RuntimeError(
            "Native HTML builds need pdftocairo to embed PDF figures. "
            "Install poppler-utils and make sure it is on PATH."
        )
    return command


def automatic_reference_id(kind: str, key: str) -> str:
    """
    Create a stable annotation ID for an automatic reference.

    Args:
        kind: Reference kind, such as equation, figure, table, or bibliography.
        key: Source TeX label or bibliography citation key.

    Returns:
        str: Stable, sanitized annotation identifier.
    """
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_.-") or kind
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    prefixes = {
        "equation": "eqref_auto",
        "figure": "figref_auto",
        "table": "tabref_auto",
        "bibliography": "bibref_auto",
    }
    prefix = prefixes.get(kind, f"{kind}ref_auto")
    return f"{prefix}_{slug}_{digest}"


def _read_text(path: Path) -> str:
    """
    Read a UTF-8 text file while replacing invalid bytes.

    Args:
        path: Text file to read.

    Returns:
        str: Decoded file content.
    """
    return path.read_text(encoding="utf-8", errors="replace")


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


def _is_escaped(text: str, index: int) -> bool:
    """
    Check whether a character is escaped by an odd number of backslashes.

    Args:
        text: Text to parse or transform.
        index: Current character offset in the text.

    Returns:
        bool: ``True`` when the indexed character is escaped.
    """
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


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


def _replace_iperpaper_with_hrefs(text: str) -> str:
    """
    Expose authored IperPaper targets to Pandoc without expanding their TeX macro.

    Args:
        text: Text to parse or transform.

    Returns:
        str: Rewritten TeX source.
    """
    pattern = re.compile(r"\\iperpaper\b")
    output: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            return "".join(output)
        output.append(text[cursor : match.start()])
        try:
            ann_id, index = _read_tex_delimited(text, match.end())
            visible, end = _read_tex_delimited(text, index)
        except ValueError:
            output.append(text[match.start() : match.end()])
            cursor = match.end()
            continue
        if not re.fullmatch(ANNOTATION_ID, ann_id):
            output.append(text[match.start() : end])
        else:
            output.append(rf"\href{{iperpaper:{ann_id}}}{{{visible}}}")
        cursor = end


def _replace_figure_crefs_with_hrefs(text: str, annotations: dict[str, Any]) -> str:
    """
    Preserve cleveref figure and table links that Pandoc otherwise drops.

    Args:
        text: Text to parse or transform.
        annotations: Annotation metadata.

    Returns:
        str: Rewritten TeX source.
    """
    by_id = {annotation["id"]: annotation for annotation in annotations["annotations"]}
    pattern = re.compile(r"\\(?:Cref|cref)\b")
    output: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            return "".join(output)
        output.append(text[cursor : match.start()])
        try:
            labels_text, end = _read_tex_delimited(text, match.end())
        except ValueError:
            output.append(text[match.start() : match.end()])
            cursor = match.end()
            continue
        labels = [label.strip() for label in labels_text.split(",") if label.strip()]
        links: list[str] = []
        reference_kind = ""
        for label in labels:
            figure_annotation = by_id.get(automatic_reference_id("figure", label))
            table_annotation = by_id.get(automatic_reference_id("table", label))
            kind = "figure" if figure_annotation else "table"
            annotation = figure_annotation or table_annotation
            if not annotation:
                links = []
                break
            if reference_kind and reference_kind != kind:
                links = []
                break
            reference_kind = kind
            heading = "Figure" if kind == "figure" else "Table"
            number = annotation.get("label", label).removeprefix(heading + " ")
            links.append(rf"\href{{#{label}}}{{{number}}}")
        if not links:
            output.append(text[match.start() : end])
        else:
            singular = "Figure" if reference_kind == "figure" else "Table"
            plural = singular + "s"
            if len(links) == 1:
                output.append(singular + "~" + links[0])
            elif len(links) == 2:
                output.append(plural + "~" + links[0] + " and " + links[1])
            else:
                output.append(plural + "~" + ", ".join(links[:-1]) + ", and " + links[-1])
        cursor = end


def _native_math_class(ann_id: str) -> str:
    """
    Encode an annotation ID as a MathJax-safe CSS class.

    Args:
        ann_id: Stable annotation identifier.

    Returns:
        str: MathJax-safe CSS class name.
    """
    return "ipann-" + ann_id.encode("ascii").hex()


def _replace_math_annotation_hrefs(text: str) -> str:
    """
    Rewrite annotation links inside math as MathJax classes.

    Args:
        text: Text to parse or transform.

    Returns:
        str: Math source with annotation classes.
    """
    pattern = re.compile(r"\\href\s*\{")
    output: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            return "".join(output)
        output.append(text[cursor : match.start()])
        try:
            destination, index = _read_tex_delimited(text, match.end() - 1)
            visible, end = _read_tex_delimited(text, index)
        except ValueError:
            output.append(text[match.start() : match.end()])
            cursor = match.end()
            continue
        if destination.startswith("iperpaper:") and re.fullmatch(
            ANNOTATION_ID, destination[len("iperpaper:") :]
        ):
            ann_id = destination[len("iperpaper:") :]
            output.append(rf"\class{{{_native_math_class(ann_id)}}}{{{visible}}}")
        else:
            output.append(text[match.start() : end])
        cursor = end


def _pandoc_attrs_with_annotation(attrs: list[Any], ann_id: str) -> list[Any]:
    """
    Attach annotation metadata to Pandoc element attributes.

    Args:
        attrs: Pandoc identifier, classes, and key-value attributes.
        ann_id: Stable annotation identifier.

    Returns:
        list[Any]: Updated Pandoc attributes.
    """
    identifier, classes, key_values = attrs
    classes = list(classes)
    if "ip-target" not in classes:
        classes.append("ip-target")
    key_values = [pair for pair in key_values if pair[0] != "data-annotation-id"]
    key_values.append(["data-annotation-id", ann_id])
    return [identifier, classes, key_values]


def _reference_number(annotation: dict[str, Any], fallback: str) -> str:
    """
    Extract the displayed number from a generated reference annotation.

    Args:
        annotation: Generated annotation metadata.
        fallback: Text to use when no reference number can be extracted.

    Returns:
        str: Rendered reference number or the fallback.
    """
    equation = re.match(r"Equation\s+(\([^)]*\))\s*:", annotation.get("short", ""))
    if equation:
        return equation.group(1)
    match = re.search(r"(\([^)]*\)|\[[^]]*\])$", annotation.get("label", ""))
    return match.group(1) if match else fallback


def _transform_pandoc_ast(
    document: dict[str, Any], annotations: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """
    Transform a Pandoc document AST for native IperPaper behavior.

    Args:
        document: Pandoc JSON document to transform.
        annotations: Annotation metadata.

    Returns:
        tuple[dict[str, Any], list[str]]: Transformed document and citation keys in encounter order.
    """
    by_id = {ann["id"]: ann for ann in annotations["annotations"]}
    has_generated_bibliography = any(ann_id.startswith("bibref_auto_") for ann_id in by_id)
    cited_keys: list[str] = []

    def citation_inlines(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert Pandoc citations into annotated reference links.

        Args:
            citations: Pandoc citation objects to convert.

        Returns:
            list[dict[str, Any]]: Pandoc inline nodes for the citations.
        """
        result: list[dict[str, Any]] = []
        for index, citation in enumerate(citations):
            key = citation["citationId"]
            if key not in cited_keys:
                cited_keys.append(key)
            ann_id = automatic_reference_id("bibliography", key)
            annotation = by_id.get(ann_id)
            label = _reference_number(annotation, f"[{key}]") if annotation else f"[{key}]"
            if index:
                result.extend([{"t": "Str", "c": ","}, {"t": "Space"}])
            attrs = _pandoc_attrs_with_annotation(["", [], []], ann_id)
            result.append(
                {
                    "t": "Link",
                    "c": [attrs, [{"t": "Str", "c": label}], [f"#ref-{key}", ""]],
                }
            )
        return result

    def walk(value: Any) -> Any:
        """
        Recursively transform nodes in the Pandoc document tree.

        Args:
            value: Pandoc AST value to transform recursively.

        Returns:
            Any: Transformed AST value.
        """
        if isinstance(value, list):
            transformed: list[Any] = []
            for item in value:
                updated = walk(item)
                if isinstance(item, dict) and isinstance(updated, list):
                    transformed.extend(updated)
                else:
                    transformed.append(updated)
            return transformed
        if not isinstance(value, dict):
            return value

        node_type = value.get("t")
        if node_type == "Cite":
            return citation_inlines(value["c"][0])
        if node_type == "Math":
            value["c"][1] = _replace_math_annotation_hrefs(value["c"][1])
            return value
        if node_type == "Div":
            attrs, blocks = value["c"]
            if "thebibliography" in attrs[1] and has_generated_bibliography:
                return []
            if "leveltwo" in attrs[1] and blocks:
                first = blocks[0]
                if first.get("t") in {"Para", "Plain"} and first.get("c"):
                    title = first["c"][0]
                    if title.get("t") == "Span":
                        title_inlines = walk(title["c"][1])
                        body_inlines = first["c"][1:]
                        while body_inlines and body_inlines[0].get("t") in {
                            "SoftBreak",
                            "Space",
                        }:
                            body_inlines.pop(0)
                        body_blocks = []
                        if body_inlines:
                            body_blocks.append({"t": first["t"], "c": body_inlines})
                        body_blocks.extend(blocks[1:])
                        return [
                            {
                                "t": "RawBlock",
                                "c": [
                                    "html",
                                    '<details class="level-accordion level-2"><summary>',
                                ],
                            },
                            {"t": "Plain", "c": title_inlines},
                            {
                                "t": "RawBlock",
                                "c": ["html", '</summary><div class="level-body">'],
                            },
                            *walk(body_blocks),
                            {"t": "RawBlock", "c": ["html", "</div></details>"]},
                        ]
        if node_type == "Link":
            attrs, inlines, target = value["c"]
            destination = target[0]
            if destination.startswith("iperpaper:"):
                ann_id = destination[len("iperpaper:") :]
                value["c"][0] = _pandoc_attrs_with_annotation(attrs, ann_id)
            else:
                attr_map = dict(attrs[2])
                reference_type = attr_map.get("reference-type")
                label = attr_map.get("reference", destination.removeprefix("#"))
                reference_kind = None
                if reference_type == "eqref" or label.startswith("eq:"):
                    reference_kind = "equation"
                elif label.startswith("fig:") or automatic_reference_id("figure", label) in by_id:
                    reference_kind = "figure"
                elif label.startswith(("tab:", "table:")) or automatic_reference_id("table", label) in by_id:
                    reference_kind = "table"
                if reference_kind:
                    ann_id = automatic_reference_id(reference_kind, label)
                    annotation = by_id.get(ann_id)
                    if annotation:
                        value["c"][0] = _pandoc_attrs_with_annotation(attrs, ann_id)
                    if annotation and reference_kind == "equation":
                        value["c"][1] = [
                            {
                                "t": "Str",
                                "c": _reference_number(annotation, f"[{label}]"),
                            }
                        ]
            value["c"][1] = walk(value["c"][1])
            return value
        return {key: walk(child) for key, child in value.items()}

    transformed = walk(document)
    blocks = transformed.get("blocks")
    if isinstance(blocks, list):
        removed_orphan_note = False
        if len(blocks) > 1 and _is_orphan_note_paragraph(blocks[0]) and _is_center_div(blocks[1]):
            blocks = blocks[1:]
            removed_orphan_note = True
        if removed_orphan_note or not blocks or not _is_center_div(blocks[0]):
            title_block = _native_title_block(transformed)
            if title_block is not None:
                blocks.insert(0, title_block)
        transformed["blocks"] = blocks
    transformed.setdefault("meta", {})["title"] = {
        "t": "MetaInlines",
        "c": [{"t": "Str", "c": annotations["title"]}],
    }
    return transformed, cited_keys


def _tex_files(project_root: Path) -> list[Path]:
    """
    Find every TeX source file beneath a project root.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        list[Path]: TeX source paths beneath the project root.
    """
    return sorted(
        path for path in project_root.rglob("*") if path.is_file() and path.suffix.lower() in TEX_SUFFIXES
    )


def _graphic_search_paths(project_root: Path) -> list[Path]:
    """
    Collect graphic directories declared by a TeX project.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        list[Path]: Ordered graphic search directories.
    """
    project_root = project_root.resolve()
    paths = [project_root]
    graphicspath_pattern = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\})+)\}")
    for tex_path in _tex_files(project_root):
        for match in graphicspath_pattern.finditer(_read_text(tex_path)):
            for entry in re.findall(r"\{([^{}]*)\}", match.group(1)):
                candidate = Path(entry.strip())
                if not candidate.is_absolute():
                    candidate = project_root / candidate
                candidate = candidate.resolve()
                if candidate not in paths:
                    paths.append(candidate)
    return paths


def _resolve_graphic_path(
    project_root: Path,
    tex_path: Path,
    reference: str,
    search_paths: list[Path],
) -> Path | None:
    """
    Resolve an includegraphics reference to an existing project asset.

    Args:
        project_root: Root directory of the TeX project.
        tex_path: TeX file containing the image reference.
        reference: Includegraphics path without braces.
        search_paths: Graphic directories declared by the project.

    Returns:
        Path | None: Resolved asset path, or ``None`` when it is unavailable.
    """
    reference_path = Path(reference.strip())
    if not reference_path.name:
        return None
    project_root = project_root.resolve()
    tex_path = tex_path.resolve()
    if reference_path.is_absolute():
        candidates = [reference_path]
    else:
        bases = [tex_path.parent, project_root, *search_paths]
        candidates = [base / reference_path for base in bases]
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        variants = [candidate]
        if not candidate.suffix:
            variants.extend(candidate.with_suffix(suffix) for suffix in GRAPHIC_SUFFIXES)
        for variant in variants:
            if variant.is_file():
                return variant
    return None


def _convert_pdf_graphic(pdf_path: Path, pdftocairo: str, converted_graphics: dict[Path, Path]) -> Path:
    """
    Convert a PDF figure to a single-page PNG for native HTML.

    Args:
        pdf_path: PDF figure inside the temporary project copy.
        pdftocairo: Path to the ``pdftocairo`` executable.
        converted_graphics: Cache of already converted figure paths.

    Returns:
        Path: PNG path written beside the source figure.

    Raises:
        RuntimeError: If conversion fails or produces no PNG.
    """
    pdf_path = pdf_path.resolve()
    cached = converted_graphics.get(pdf_path)
    if cached is not None:
        return cached
    png_path = pdf_path.with_name(f"{pdf_path.stem}.iperpaper-native.png")
    if not png_path.is_file():
        proc = subprocess.run(
            [
                pdftocairo,
                "-png",
                "-singlefile",
                "-r",
                "144",
                "-f",
                "1",
                "-l",
                "1",
                str(pdf_path),
                str(png_path.with_suffix("")),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not png_path.is_file():
            details = (proc.stdout + "\n" + proc.stderr).strip()
            raise RuntimeError(f"Could not convert native HTML figure {pdf_path}:\n{details}")
    converted_graphics[pdf_path] = png_path
    return png_path


def _replace_graphic_references(
    text: str,
    project_root: Path,
    tex_path: Path,
    search_paths: list[Path],
    converted_graphics: dict[Path, Path],
) -> str:
    """
    Rewrite image references to project-relative, embeddable asset paths.

    Args:
        text: TeX text to transform.
        project_root: Root directory of the temporary TeX project.
        tex_path: TeX file containing the image references.
        search_paths: Graphic directories declared by the project.
        converted_graphics: Cache of converted PDF figures.

    Returns:
        str: TeX text with resolvable image paths.
    """
    pattern = re.compile(r"(\\includegraphics\*?(?:\s*\[[^\]]*\])?\s*\{)([^{}]+)(\})")

    def replace(match: re.Match[str]) -> str:
        resolved = _resolve_graphic_path(project_root, tex_path, match.group(2), search_paths)
        if resolved is None:
            return match.group(0)
        if resolved.suffix.lower() == ".pdf":
            resolved = _convert_pdf_graphic(resolved, _require_pdftocairo(), converted_graphics)
        try:
            relative = resolved.relative_to(project_root.resolve()).as_posix()
        except ValueError:
            return match.group(0)
        return f"{match.group(1)}{relative}{match.group(3)}"

    return pattern.sub(replace, text)


def _replace_my_tabular(text: str) -> str:
    """
    Convert the project's custom table environment to standard tabular TeX.

    Args:
        text: TeX text to transform.

    Returns:
        str: TeX text with custom table wrappers normalized for Pandoc.
    """
    begin_pattern = re.compile(r"\\begin\s*\{\s*mytabular\s*\}")
    end_pattern = re.compile(r"\\end\s*\{\s*mytabular\s*\}")
    output: list[str] = []
    cursor = 0
    match = begin_pattern.search(text)
    while match:
        try:
            _, body_start = _read_tex_delimited(text, match.end())
        except ValueError:
            output.append(text[cursor:])
            return "".join(output)
        end_match = end_pattern.search(text, body_start)
        if end_match is None:
            output.append(text[cursor:])
            return "".join(output)
        body = text[body_start : end_match.start()]
        column_count = (
            max(
                (len(re.findall(r"(?<!\\)&", line)) for line in body.splitlines()),
                default=0,
            )
            + 1
        )
        body = re.sub(r"(?<!\\)\\o(?![A-Za-z])", "", body)
        output.append(text[cursor : match.start()])
        output.append(f"\\begin{{tabular}}{{{'l' * column_count}}}")
        output.append(body)
        output.append(r"\end{tabular}")
        cursor = end_match.end()
        match = begin_pattern.search(text, cursor)
    output.append(text[cursor:])
    return "".join(output)


def _replace_tex_command_arguments(
    text: str,
    command: str,
    argument_count: int,
    replacement: Callable[[list[str]], str],
) -> str:
    """
    Replace a TeX command with a fixed number of braced arguments.

    Args:
        text: TeX text to transform.
        command: Command name without its leading backslash.
        argument_count: Number of braced arguments to consume.
        replacement: Function that returns replacement text for the arguments.

    Returns:
        str: TeX text with matching command invocations replaced.
    """
    pattern = re.compile(rf"\\{re.escape(command)}\b")
    output: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            return "".join(output)
        index = match.end()
        arguments: list[str] = []
        try:
            for _ in range(argument_count):
                argument, index = _read_tex_delimited(text, index)
                arguments.append(argument)
        except ValueError:
            output.append(text[cursor : match.end()])
            cursor = match.end()
            continue
        output.append(text[cursor : match.start()])
        output.append(replacement(arguments))
        cursor = index


def _strip_tex_environment(text: str, environment: str, argument_count: int) -> str:
    """
    Remove a TeX environment wrapper and its braced arguments.

    Args:
        text: TeX text to transform.
        environment: Environment name without its surrounding braces.
        argument_count: Number of braced arguments on the begin command.

    Returns:
        str: TeX text without the matching environment wrappers.
    """
    begin_pattern = re.compile(rf"\\begin\s*\{{\s*{re.escape(environment)}\s*\}}")
    output: list[str] = []
    cursor = 0
    while True:
        match = begin_pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            break
        index = match.end()
        try:
            for _ in range(argument_count):
                _, index = _read_tex_delimited(text, index)
        except ValueError:
            output.append(text[cursor:])
            break
        output.append(text[cursor : match.start()])
        cursor = index
    end_pattern = re.compile(rf"\\end\s*\{{\s*{re.escape(environment)}\s*\}}")
    return end_pattern.sub("", "".join(output))


def _replace_probability_macros(text: str) -> str:
    """
    Expand the paper's custom probability and information macros.

    Args:
        text: TeX text to transform.

    Returns:
        str: TeX text using MathJax-compatible probability notation.
    """
    pattern = re.compile(r"\\(lnpp|pp|qp|p|P|H|E|D|KL)\b")
    defaults = {
        "lnpp": r"\ln p_\phi",
        "pp": r"p_\phi",
        "qp": r"q_\phi",
        "p": "p",
        "P": "P",
        "H": "H",
        "E": "E",
        "D": "D",
        "KL": "KL",
    }
    output: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            output.append(text[cursor:])
            return "".join(output)
        command = match.group(1)
        index = _skip_tex_space(text, match.end())
        base = defaults[command]
        if index < len(text) and text[index] == "<":
            try:
                base, index = _read_tex_delimited(text, index, "<", ">")
            except ValueError:
                output.append(text[cursor : match.end()])
                cursor = match.end()
                continue
        opener = "(" if command in {"lnpp", "pp", "qp", "p", "P"} else "["
        closer = ")" if opener == "(" else "]"
        if index >= len(text) or text[index] != opener:
            output.append(text[cursor : match.end()])
            cursor = match.end()
            continue
        try:
            content, end = _read_tex_delimited(text, index, opener, closer)
        except ValueError:
            output.append(text[cursor : match.end()])
            cursor = match.end()
            continue
        content = _replace_probability_macros(content)
        if command in {"P", "H", "E", "D", "KL"}:
            base = rf"\operatorname{{{base}}}"
        output.append(text[cursor : match.start()])
        output.append(f"{base}{opener}{content}{closer}")
        cursor = end


def _replace_native_tex_commands(text: str) -> str:
    """
    Normalize paper-specific TeX commands for native HTML conversion.

    Args:
        text: TeX text to transform.

    Returns:
        str: TeX text that Pandoc and MathJax can render natively.
    """
    text = re.sub(r"\\hspace\s*\*", lambda _match: r"\hspace", text)
    text = _strip_tex_environment(text, "adjustwidth", 2)
    text = _strip_tex_environment(text, "hyphenrules", 1)
    text = _replace_tex_command_arguments(text, "raisebox", 2, lambda args: args[1])
    for command in ("llap", "blap", "tlap", "hbox"):
        text = _replace_tex_command_arguments(text, command, 1, lambda args: args[0])
    text = re.sub(r"\\vbox\s+to\s+[^\s{]+\s*", "", text)
    text = re.sub(r"\\vss\b", "", text)
    text = _replace_probability_macros(text)
    text = _replace_tex_command_arguments(text, "ensuremath", 1, lambda args: args[0])
    operator_macros = {
        "softmax": r"\operatorname{softmax}",
        "logsoftmax": r"\operatorname{log\,softmax}",
        "symlog": r"\operatorname{symlog}",
        "symexp": r"\operatorname{symexp}",
        "twohot": r"\operatorname{twohot}",
        "sg": r"\operatorname{sg}",
        "sign": r"\operatorname{sign}",
        "abs": r"\operatorname{abs}",
        "erf": r"\operatorname{erf}",
        "EMA": r"\operatorname{EMA}",
        "Per": r"\operatorname{Per}",
        "ema": r"\operatorname{ema}",
        "per": r"\operatorname{per}",
        "fot": r"\frac{1}{2}",
        "defined": r"\doteq",
        "without": r"\setminus",
        "eye": r"\mathbb{I}",
    }
    for command, replacement in operator_macros.items():
        text = re.sub(
            rf"\\{re.escape(command)}\b",
            lambda _match, value=replacement: value,
            text,
        )
    return text


def _is_center_div(block: Any) -> bool:
    """
    Check whether a Pandoc block is a centered div.

    Args:
        block: Pandoc AST block to inspect.

    Returns:
        bool: ``True`` when the block has the ``center`` class.
    """
    if not isinstance(block, dict) or block.get("t") != "Div":
        return False
    content = block.get("c")
    return isinstance(content, list) and len(content) == 2 and "center" in content[0][1]


def _is_orphan_note_paragraph(block: Any) -> bool:
    """
    Check whether a block is only the title affiliation footnote marker.

    Args:
        block: Pandoc AST block to inspect.

    Returns:
        bool: ``True`` when the block contains only one footnote marker.
    """
    if not isinstance(block, dict) or block.get("t") != "Para":
        return False
    inlines = block.get("c")
    if not isinstance(inlines, list) or len(inlines) != 1:
        return False
    span = inlines[0]
    if not isinstance(span, dict) or span.get("t") != "Span":
        return False
    span_content = span.get("c")
    return (
        isinstance(span_content, list)
        and len(span_content) == 2
        and isinstance(span_content[1], list)
        and len(span_content[1]) == 1
        and isinstance(span_content[1][0], dict)
        and span_content[1][0].get("t") == "Note"
    )


def _native_title_block(document: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build a centered title block from Pandoc document metadata.

    Args:
        document: Pandoc document AST containing title and author metadata.

    Returns:
        dict[str, Any] | None: Centered title block, or ``None`` without a title.
    """
    meta = document.get("meta", {})
    title = meta.get("title")
    if not isinstance(title, dict) or title.get("t") != "MetaInlines":
        return None
    title_inlines = title.get("c")
    if not isinstance(title_inlines, list) or not title_inlines:
        return None
    blocks: list[dict[str, Any]] = [{"t": "Para", "c": title_inlines}]
    authors = meta.get("author")
    if isinstance(authors, dict) and authors.get("t") == "MetaList":
        for author in authors.get("c", []):
            if not isinstance(author, dict) or author.get("t") != "MetaInlines":
                continue
            author_inlines = author.get("c")
            if isinstance(author_inlines, list) and author_inlines:
                blocks.append({"t": "Para", "c": author_inlines})
    return {"t": "Div", "c": [["", ["center"], []], blocks]}


def _uses_latin_modern(project_root: Path) -> bool:
    """
    Check whether a TeX project loads the Latin Modern package.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        bool: ``True`` when Latin Modern is explicitly requested.
    """
    package = re.compile(r"\\usepackage(?:\[[^]]*\])?\{([^}]*)\}")
    for path in _tex_files(project_root):
        for match in package.finditer(_read_text(path)):
            if "lmodern" in {name.strip() for name in match.group(1).split(",")}:
                return True
    return False


def _find_tex_font(filename: str) -> Path | None:
    """
    Locate a TeX font file with kpsewhich.

    Args:
        filename: TeX font filename to locate.

    Returns:
        Path | None: Font path, or ``None`` when unavailable.
    """
    kpsewhich = shutil.which("kpsewhich")
    if kpsewhich:
        proc = subprocess.run(
            [kpsewhich, filename],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            candidate = Path(proc.stdout.strip())
            if candidate.is_file():
                return candidate
    return None


def _paper_font_css(project_root: Path) -> tuple[str, str]:
    """
    Build embedded font CSS and a fallback family for the paper.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        tuple[str, str]: Embedded font-face CSS and the selected font family.
    """
    generic_fallback = "Georgia,'Times New Roman',serif"
    if not _uses_latin_modern(project_root):
        return "", generic_fallback

    faces: list[str] = []
    for filename, weight, style in LATIN_MODERN_FONTS:
        path = _find_tex_font(filename)
        if path is None:
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        faces.append(
            "@font-face{font-family:'IperPaper Latin Modern';"
            f"src:url(data:font/otf;base64,{encoded}) format('opentype');"
            f"font-weight:{weight};font-style:{style};font-display:swap;}}"
        )
    latin_fallback = "'Latin Modern Roman','LM Roman 10','Computer Modern Serif'," + generic_fallback
    family = "'IperPaper Latin Modern'," + latin_fallback if faces else latin_fallback
    return "".join(faces), family


def _mathjax_font(project_root: Path) -> str:
    """
    Select the MathJax font that best matches the paper.

    Args:
        project_root: Root directory of the TeX project.

    Returns:
        str: MathJax font package name.
    """
    return "mathjax-modern" if _uses_latin_modern(project_root) else "mathjax-newcm"


def _pandoc_native_fragment(
    project_root: Path, main_file: Path, annotations: dict[str, Any]
) -> tuple[str, list[str]]:
    """
    Convert an annotated TeX project into a native HTML fragment.

    Args:
        project_root: Root directory of the TeX project.
        main_file: Main TeX file for the project.
        annotations: Annotation metadata.

    Returns:
        tuple[str, list[str]]: Native HTML fragment and cited keys.
    """
    pandoc = require_pandoc()
    project_root = project_root.resolve()
    main_file = main_file.resolve()
    relative_main = main_file.relative_to(project_root)
    with tempfile.TemporaryDirectory(prefix="iperpaper-native-") as tmp:
        work = Path(tmp) / "project"
        shutil.copytree(project_root, work)
        search_paths = _graphic_search_paths(work)
        converted_graphics: dict[Path, Path] = {}
        for path in _tex_files(work):
            rewritten = _replace_iperpaper_with_hrefs(_read_text(path))
            rewritten = _replace_figure_crefs_with_hrefs(rewritten, annotations)
            rewritten = _replace_my_tabular(rewritten)
            if path.name != "commands.tex":
                rewritten = _replace_native_tex_commands(rewritten)
            rewritten = _replace_graphic_references(rewritten, work, path, search_paths, converted_graphics)
            path.write_text(rewritten, encoding="utf-8")

        read_proc = subprocess.run(
            [pandoc, str(relative_main), "--from=latex", "--to=json", "--resource-path=."],
            cwd=work,
            check=False,
            capture_output=True,
            text=True,
        )
        if read_proc.returncode != 0:
            details = (read_proc.stdout + "\n" + read_proc.stderr).strip()
            raise RuntimeError(f"Pandoc failed while reading {main_file}:\n{details}")
        document = json.loads(read_proc.stdout)
        document, cited_keys = _transform_pandoc_ast(document, annotations)

        template_path = work / ".iperpaper-native-template.html"
        template_path.write_text("$body$", encoding="utf-8")
        write_proc = subprocess.run(
            [
                pandoc,
                "--from=json",
                "--to=html5",
                "--standalone",
                f"--template={template_path.name}",
                "--embed-resources",
                "--mathjax=" + MATHJAX_URL,
                "--resource-path=.",
            ],
            cwd=work,
            input=json.dumps(document, ensure_ascii=False),
            check=False,
            capture_output=True,
            text=True,
        )
        if write_proc.returncode != 0:
            details = (write_proc.stdout + "\n" + write_proc.stderr).strip()
            raise RuntimeError(f"Pandoc failed while writing native HTML:\n{details}")
    return write_proc.stdout, cited_keys


def build_native_html(
    project_root: Path,
    main_file: Path,
    annotations: dict[str, Any],
    rendered_annotations: list[dict[str, Any]],
    text_margins: dict[str, float] | None = None,
) -> str:
    """
    Build a reflowable native HTML reader.

    Args:
        project_root: Root directory of the TeX project.
        main_file: Main TeX file for the project.
        annotations: Annotation metadata.
        rendered_annotations: HTML-ready annotation objects.
        text_margins: Optional page-relative text margin measurements.

    Returns:
        str: Complete native reader HTML.
    """
    fragment, cited_keys = _pandoc_native_fragment(project_root, main_file, annotations)
    title = html.escape(str(annotations["title"]))
    title_json = json.dumps(str(annotations["title"]), ensure_ascii=False).replace("</", "<\\/")
    font_faces, paper_font = _paper_font_css(project_root)
    mathjax_font = _mathjax_font(project_root)
    annotations_json = json.dumps(rendered_annotations, ensure_ascii=False).replace("</", "<\\/")
    math_classes_json = json.dumps(
        {_native_math_class(ann["id"]): ann["id"] for ann in annotations["annotations"]},
        separators=(",", ":"),
    )
    by_id = {ann["id"]: ann for ann in rendered_annotations}
    reference_items: list[tuple[int, str]] = []
    for order, key in enumerate(cited_keys):
        ann_id = automatic_reference_id("bibliography", key)
        annotation = by_id.get(ann_id)
        if annotation:
            label = _reference_number(annotation, "")
            match = re.fullmatch(r"\[(\d+)\]", label)
            sort_key = int(match.group(1)) if match else 1_000_000 + order
            reference_items.append(
                (
                    sort_key,
                    f'<li id="ref-{html.escape(key, quote=True)}">{annotation["short_html"]}</li>',
                )
            )
    references_html = ""
    if reference_items:
        references = [item for _, item in sorted(reference_items)]
        references_html = (
            '<section class="references"><h1 id="references">References</h1><ol>'
            + "".join(references)
            + "</ol></section>"
        )

    template = read_template("native_reader.html")
    replacements = {
        "__IP_TITLE__": title,
        "__IP_MATHJAX_FONT__": mathjax_font,
        "__IP_MATHJAX_FONT_PATH__": MATHJAX_FONT_PATH,
        "__IP_MATHJAX_URL__": MATHJAX_URL,
        "__IP_FONT_FACES__": font_faces,
        "__IP_PAPER_FONT__": paper_font,
        "__IP_DOCUMENT_FRAGMENT__": fragment,
        "__IP_REFERENCES__": references_html,
        "__IP_ANNOTATIONS__": annotations_json,
        "__IP_MATH_TARGET_CLASSES__": math_classes_json,
        "__IP_PAPER_TITLE_JSON__": title_json,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
