# IperPaper agent instructions

These instructions apply to the whole repository.

## Main Instructions

1. For Python, use the `.venv` virtual environment unless otherwise specified.
2. Give every new or modified Python function and method a concise Google-style
   docstring. Start with a one-line summary, then document parameters under
   `Args:` and the return value under `Returns:` (omit a section only when it is
   not applicable). For a multi-line docstring, put the opening `"""` on its own
   line and start the summary on the following line. Keep the summary beside the
   opening `"""` only when the entire docstring fits on one line. Use this format:

   ```yaml
   """
   Describe what the function does.

   Args:
       arg1: Description of the first argument.
       arg2: Description of the second argument.

   Returns:
       ReturnType: Description of the returned value.
   """
   ```

## Instruction ownership

This file defines repository conventions, source acquisition, and validation/build
workflows. Before any build, including an annotation-free build, read
[prompts/enhance.md](prompts/enhance.md) and follow its native-reference
requirements for equation, figure, table, and bibliography links. For authored
annotations, read `enhance.md` completely before creating or changing annotations.
Annotation-free builds skip only the authored-annotation requirements, not the
source, reference-compatibility, or build-validation requirements.

## Source acquisition and project layout

When enhancing a paper, produce its annotated TeX project and annotation metadata,
and preserve distinct original material. Before reconstructing a PDF, identify the
paper and exact revision when possible and check for publicly recoverable source. Prefer the
matching arXiv revision, then a clearly matching author/project repository, then
official publisher/conference source material. Verify title, authors, version/date when available,
section structure, equations, figures, and appendices. Do not silently substitute
another version; reconstruct only when usable matching source is unavailable.

Keep each paper under `papers/<paper-stem>/`:

- `original/`: unmodified supplied or recovered source material.
- `annotated/`: the working TeX file or complete project, preserving relative paths,
  figures, bibliography, styles/classes, and other compilation assets.
- `annotated/<paper-stem>.annotations.json`: authored annotation metadata.
- `annotated/<paper-stem>.citations.json`: build-maintained citation metadata.
- `<paper-stem>.html` and, when requested, `<paper-stem>.native.html`: readers.
- `<paper-stem>.pdf`: only when explicitly requested with `--pdf-output`.

If a paper is authored directly as annotated source with no distinct original,
keep only the canonical source in `annotated/`; no duplicate or empty `original/`
is needed. Keep a self-contained single-file paper as one TeX file and a source
archive/project as a project. Preserve `\input` / `\include` organization when practical.

Before generating or regenerating source or readers, inspect existing annotation
and citation metadata. Reuse annotations when valid and their IDs match the TeX;
regenerate only when missing, invalid, or the user requests updated annotations.

When rebuilding an existing paper whose TeX contains `\iperpaper` wrappers or
whose project contains an `*.annotations.json` file, always pass that matching
annotations JSON as the build command's second positional argument. The
`annotations` argument is optional in the CLI only for explicitly requested
annotation-free builds; omitting it for an authored-annotation project makes
the compiled targets fail validation or drops the authored annotation content.

## Annotation-free builds

When explicitly requested, preserve the supplied or recovered TeX without adding
`\iperpaper` wrappers or creating annotations JSON. Omit the annotations positional
argument and use `--mode pdf_html` unless the user requests another mode:

```bash
python -m iperpaper build papers/<paper-stem>/annotated/ \
  --main main.tex --mode pdf_html \
  -o papers/<paper-stem>/<paper-stem>.html
```

Deterministically generated native equation, figure, table, and citation tooltips
are still allowed. Source acquisition, preservation, reference compatibility,
verification, and reporting rules still apply.

## Validation and build workflow

1. Locate/acquire the paper, inspect the whole project to understand its notation,
   and prepare its workspace using the rules above.
2. For authored annotations, follow `prompts/enhance.md`, reuse valid metadata,
   and audit targets, semantic-ID reuse, and native-reference compatibility.
3. Use standalone validation as an optional early checkpoint:

   ```bash
   python -m iperpaper validate \
     papers/<paper-stem>/annotated/ \
     papers/<paper-stem>/annotated/<paper-stem>.annotations.json \
     --main main.tex
   ```

4. Build the requested readers; this performs the same compiled-PDF target
   validation and automatic-reference extraction internally:

   ```bash
   python -m iperpaper build \
     papers/<paper-stem>/annotated/ \
     papers/<paper-stem>/annotated/<paper-stem>.annotations.json \
     --main main.tex --mode all \
     -o papers/<paper-stem>/<paper-stem>.html
   ```

    For an existing annotated project, do not omit the annotations JSON from
    this command, even though the CLI marks the argument as optional. Use the
    annotation-free command above only when that mode was explicitly requested.

   Use `--mode all` when both readers are requested; the default is `pdf_html`.
   In `all` mode, `-o <stem>.html` also produces `<stem>.native.html`. In
   `native_html` mode, the native reader is written directly to `-o`; choose
   `<paper-stem>.native.html` to follow the repository naming convention.
   For a single TeX file, pass that file and omit `--main`. The PDF stays temporary
   unless `--pdf-output papers/<paper-stem>/<paper-stem>.pdf` is requested.
   Citation metadata retains stable TeX/BibTeX keys and rendered indices; preserve
   the cache and use `--regenerate-links` when a fresh external lookup is required.
   Tooltip math is compiled with the main paper's preamble and embedded as SVG.
5. Fix validation and extraction errors rather than weakening checks. If a native
   reference is unsupported and cannot be fixed while preserving scientific
   content, report the limitation; do not invent authored reference metadata.
6. When project code changes, run:

   ```bash
   python -m unittest discover -s tests -v
   ```

7. Report source provenance, annotated source and metadata, citation metadata,
   generated readers, any requested standalone PDF, and fidelity/verification
   limitations.

## Dependencies and maintenance

- Use `latexmk` for compilation; tooltip math also requires `pdfcrop` and
  `pdftocairo`. PDF-backed readers use pinned PDF.js assets. Native HTML additionally
  requires Pandoc and uses MathJax 4 assets.
- Do not add model-specific API calls or API-key handling to `iperpaper.py` unless
  explicitly requested.
