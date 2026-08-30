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

## Goal

When a user asks you to enhance a scientific paper with IperPaper, produce:

1. the recoverable **original paper/source** when it is distinct from the annotated source;
2. an **annotated TeX source**: one `.tex` file or a complete TeX project directory with its supporting assets;
3. a `*.annotations.json` file containing annotation metadata and explanations.

IperPaper compiles the annotated TeX, extracts annotation rectangles from the PDF, pre-renders TeX math used in explanations, and builds an interactive PDF-backed reader, a native HTML reader, or both.

A typical request can be as short as:

> Follow AGENTS.md for `/path/to/paper.tex`.

> Follow AGENTS.md for `/path/to/tex-project/`.

> Follow AGENTS.md for `https://arxiv.org/pdf/...`.

## Source acquisition

Before reconstructing a paper from PDF, check whether the original source package is publicly recoverable.

1. Identify the paper and exact version/revision when possible.
2. Prefer the matching arXiv source revision when applicable, then a clearly matching author/project repository, then official publisher/conference source material.
3. Verify title, authors, version/date when available, section structure, equations, figures, and appendices.
4. Do not silently substitute another version.
5. Reconstruct TeX from the PDF only when usable matching source is unavailable.

## Preserve the TeX project

- Keep every paper in `papers/<paper-stem>/`.
- Put the unmodified supplied or recovered source material in `papers/<paper-stem>/original/`.
- Put the annotated TeX file or complete annotated TeX project in `papers/<paper-stem>/annotated/`, preserving its internal relative paths.
- Put `<paper-stem>.annotations.json` and `<paper-stem>.citations.json` in `papers/<paper-stem>/annotated/` beside the annotated source. Put `<paper-stem>.html` and `<paper-stem>.native.html` directly in `papers/<paper-stem>/`; persist `<paper-stem>.pdf` there only when requested with `--pdf-output`.
- If a paper is authored directly as an annotated source and there is no distinct original, do not duplicate it: keep the single canonical TeX source in `annotated/`. An empty `original/` directory is not required.
- Before generating or regenerating annotated TeX or reader artifacts, inspect `papers/<paper-stem>/annotated/` for existing annotation and citation metadata. Reuse annotation metadata when its IDs match the annotated TeX; regenerate it only when it is missing, invalid, or the user requests updated annotations.
- Keep `\input` / `\include` organization when practical.
- Preserve figures, bibliography files, styles/classes, and other files needed to compile the paper.
- Add annotation wrappers only where needed in TeX source.
- Make sure `xcolor` and `hyperref` are available without changing original link styling globally.
- Follow `prompts/enhance.md` for the `\iperpaper{ID}{...}` wrapper, metadata contract, semantic-ID rules, TeX math syntax inside explanations, and the distinction between authored annotations and automatically generated reference tooltips.
- Give every relevant probability distribution, acronym, named operator, or recurring concept a shared `background` entry in the annotations JSON, and list that key in the `background` field of every annotation that uses it. The same background key may be reused by many annotations. Add an optional human-readable `label` when the stable key is not suitable as a heading, and add a `link` field with a Wikipedia or other authoritative URL; the reader renders the label as a blue clickable link to it.
- For probability distributions, the background explanation must state whether the distribution is discrete or continuous, its support, and its density or probability mass function in TeX math.
- Every symbol introduced inside an explanation must itself be explained: give it its own background entry and list it in the introducing entry's optional `background` field (for example, the Gamma function in a Gamma density).
- Every occurrence of a background concept in the paper's notation should be covered by an annotation that references that background key. If no existing paper-specific annotation covers an occurrence, add one targeting it in the TeX (for example, wrapping the distribution operator itself). Such background-only annotations may leave `short` and `details` empty; the reader then uses the annotation's actual formula/symbol/text `label` as the panel heading (linked when the first background entry has a `link`) and shows the background explanation once. Validation fails if an annotation has empty `short`, `details`, and `background`.

## Workflow

1. Locate the supplied paper.
2. Read `prompts/enhance.md` completely.
3. Acquire the best matching source.
4. Inspect the whole paper/project so notation is understood in context.
5. Create or inspect `papers/<paper-stem>/`, preserving distinct original material under `original/` and checking `annotated/` for reusable annotation and citation metadata.
6. Copy/create the annotated TeX under `papers/<paper-stem>/annotated/`, preserving structure and assets, and write annotation metadata in that same directory only when no valid matching metadata exists or annotations need updating. If the original and annotated source are intentionally identical, keep only the canonical TeX in `annotated/`.
7. Audit annotation-ID reuse. Do not reuse an ID just because notation looks the same; distributions, time-indexed variables, or overloaded symbols with different semantic roles need distinct tooltips/IDs.
8. Leave equation references, figure references, table references, and bibliography citations native. Do not wrap `\eqref`, equation-, figure-, or table-targeting `\ref` / `\autoref` / `\cref`, `\cite`, or citation variants in `\iperpaper`. IperPaper uses their ordinary compiled PDF links, LaTeX `.aux` data, equation/figure/table source, rendered figure/table artwork, and bibliography entries to generate these tooltips deterministically during validation/build.
9. Audit reference compatibility instead of writing reference metadata. Referenced equations must have reachable `\label` commands inside standard numbered equation environments, referenced figures and tables must keep their labels and captions, and cited entries must remain available through `thebibliography` or a classic BibTeX-generated `.bbl`. Preserve referenced `.bib` databases and stable citation keys: IperPaper uses their explicit title, author, and DOI fields for citation lookup and keys its citation cache by the TeX/BibTeX key. Fix automatic-reference extraction errors; do not replace them with AI-written `eqref_`, `figref_`, `tabref_`, or `bibref_` annotations.
10. Use the standalone validator as an early target check:

   ```bash
   python -m iperpaper validate \
     papers/<paper-stem>/annotated/ \
     papers/<paper-stem>/annotated/<paper-stem>.annotations.json \
     --main main.tex
   ```

   For a single TeX file, pass the file and omit `--main`.
11. Fix validation failures rather than weakening validation.
12. Build the PDF and reader:

   ```bash
   python -m iperpaper build \
     papers/<paper-stem>/annotated/ \
     papers/<paper-stem>/annotated/<paper-stem>.annotations.json \
     --main main.tex \
     --mode all \
     -o papers/<paper-stem>/<paper-stem>.html
   ```

   `build` performs the same compiled-PDF target validation and automatic-reference extraction internally, so the standalone `validate` command above is an early checkpoint rather than a prerequisite. It keeps the compiled PDF in its temporary build workspace and in memory for the requested readers; pass `--pdf-output papers/<paper-stem>/<paper-stem>.pdf` to persist a standalone copy. The build maintains `papers/<paper-stem>/annotated/<paper-stem>.citations.json` and writes both HTML readers at the paper root. Citation records retain both the stable citation key and rendered index; use `--regenerate-links` when a fresh external lookup is required. When authored or generated annotation explanations contain `$...$`, `$$...$$`, `\(...\)`, or `\[...\]`, the build compiles those fragments with the paper's main LaTeX preamble and embeds SVG renderings in the reader.

   Use `--mode all` when both the exact PDF-backed reader and the reflowable native HTML reader are requested. With `-o papers/<paper-stem>/<paper-stem>.html`, this also writes `papers/<paper-stem>/<paper-stem>.native.html`. The default remains `pdf_html`.

13. Run tests when project code changed:

   ```bash
   python -m unittest discover -s tests -v
   ```
14. Report the annotated source, annotation and citation metadata, any requested standalone PDF, generated HTML reader(s), source provenance, and any fidelity/verification limitations.

## Important constraints

- Do not add model-specific API calls or API-key handling to `iperpaper.py`, unless explicitly requested.
- Do not store the complete TeX document inside annotation JSON.
- Do not silently rewrite scientific content to make annotation easier.
- Prefer exact matching source TeX over PDF reconstruction.
- Preserve assets needed to compile the paper.
- Every authored metadata annotation must create at least one real `iperpaper:` PDF link after LaTeX compilation. Automatically generated equation/figure/table/citation annotations instead reuse native internal PDF-link rectangles.
- Every compiled `iperpaper:` link must have matching metadata.
- Do not add authored `eqref_`, `figref_`, `tabref_`, or `bibref_` annotations; keep the native reference command unchanged and let the build generate its tooltip.
- Reuse an annotation ID only when the same explanation is semantically correct at every occurrence.
- Original paper links must remain visually and functionally unchanged by IperPaper styling.
- `latexmk` is required for compilation. Tooltip-math rendering also uses `pdfcrop` and `pdftocairo`. The PDF-backed reader uses pinned PDF.js assets; native HTML builds additionally require Pandoc and use pinned MathJax assets.

For architecture history, review notes, known tradeoffs, and future ideas, see `INFO.md`. Do not let historical alternatives in `INFO.md` override the current workflow in this file, `README.md`, or `prompts/enhance.md`.
