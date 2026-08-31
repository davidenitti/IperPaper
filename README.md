# IperPaper 0.2

IperPaper turns a scientific paper into an interactive PDF-backed or native HTML reader where mathematical symbols and technical concepts explain themselves on hover and click. The PDF-backed reader preserves the compiled layout; native HTML is an experimental alternative that might not work correctly with highly customized LaTeX.

An AI agent prepares semantic LaTeX annotations plus explanation metadata. IperPaper deterministically adds tooltips for native equation, figure, table, and citation references, compiles the paper, validates the targets, pre-renders tooltip math, and builds the browser reader.

For each paper, IperPaper can add:

- equation-reference previews on hover, with clicks that jump to the referenced equation;
- citation previews on hover, with clicks that open a verified paper PDF or linked resource when available, or jump to the bibliography entry otherwise;
- figure and table previews when their references are hovered;
- blue semantic annotations on equations, derivation steps, and technical terms, with short hover explanations and full explanations in a side panel;
- clickable links from background explanations to corresponding Wikipedia pages;
- a text-selection menu for asking ChatGPT or Perplexity to explain the selected passage;
- a split layout that keeps the paper and explanation panel side by side;
- two reading levels, with a self-contained Level 1 main text and collapsible Level 2 explanations and derivations.

## Examples

### Tutorial: Gumbel-Max Watermarking

This tutorial was written specifically with IperPaper in mind. It provides a compact example of semantic annotations, explanatory tooltips, and mathematical notation designed for interactive reading. Read it as [PDF-backed HTML](https://davidenitti.github.io/IperPaper/papers/tutorial_gumbel_max_watermarking/tutorial_gumbel_max_watermarking.html) or [native HTML](https://davidenitti.github.io/IperPaper/papers/tutorial_gumbel_max_watermarking/tutorial_gumbel_max_watermarking.native.html).

The tutorial's [annotations JSON](papers/tutorial_gumbel_max_watermarking/annotated/tutorial_gumbel_max_watermarking.annotations.json) contains the authored explanations and reusable background entries associated with `\iperpaper` targets in the TeX source. Its [citations JSON](papers/tutorial_gumbel_max_watermarking/annotated/tutorial_gumbel_max_watermarking.citations.json) is the build-maintained cache of bibliography keys, rendered citation numbers, verified metadata, and resolved external links.

### Mastering Diverse Domains through World Models

This is an existing research paper annotated using IperPaper. It demonstrates how the annotation workflow can be applied to a complete paper while preserving its original structure and content. Read it as [PDF-backed HTML](https://davidenitti.github.io/IperPaper/papers/Mastering%20Diverse%20Domains%20through%20World%20Models/Mastering%20Diverse%20Domains%20through%20World%20Models.html) or [native HTML](https://davidenitti.github.io/IperPaper/papers/Mastering%20Diverse%20Domains%20through%20World%20Models/Mastering%20Diverse%20Domains%20through%20World%20Models.native.html).

See the paper's [annotations JSON](papers/Mastering%20Diverse%20Domains%20through%20World%20Models/annotated/Mastering%20Diverse%20Domains%20through%20World%20Models.annotations.json) and its build-maintained [citations JSON](papers/Mastering%20Diverse%20Domains%20through%20World%20Models/annotated/Mastering%20Diverse%20Domains%20through%20World%20Models.citations.json).

Note: Native HTML is not perfect for this paper.

### AI-authored and programmatically generated content

For both examples, the AI agent chooses the semantic targets, inserts the `\iperpaper{ID}{...}` wrappers into a preserved copy of the TeX source, and writes the annotations JSON with contextual explanations and reusable background entries. `iperpaper build` then works programmatically: it compiles and validates the TeX, discovers native equation/figure/table/citation references, generates their tooltip metadata, maintains the citations JSON, renders explanation math and previews, and produces the HTML readers. The build does not use an LLM.

## Setup

### 1. Install IperPaper

From the repository:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For a non-editable local installation:

```bash
python -m pip install .
```

The Python package depends on `pypdf` and `Pybtex`; the installation commands
above install both automatically.

### 2. Install the system dependencies

On Ubuntu/Debian, install the standard build dependencies in one go:

```bash
sudo apt update
sudo apt install \
  latexmk \
  texlive-latex-extra \
  texlive-fonts-recommended \
  texlive-science \
  texlive-extra-utils \
  poppler-utils \
  pandoc
```

These provide the main tools IperPaper uses:

- `latexmk` / `pdflatex`: compile the annotated paper and tooltip math;
- `pdfcrop`: crop each pre-rendered tooltip formula to its content;
- `pdftocairo`: convert cropped formulas to SVG and referenced figure/table artwork to PNG;
- `pdftotext`: optionally estimate the paper's text margins for split view placement;
- `pandoc`: convert TeX to responsive HTML for `native_html` and `all` builds.

Individual papers can require additional TeX packages, fonts, bibliography tools, or custom classes.

## Recommended: use an AI coding agent

Give the agent the IperPaper repository and the paper, then ask it to follow `AGENTS.md`.

Examples:

```text
Follow AGENTS.md for /path/to/paper.tex
```

```text
Follow AGENTS.md for /path/to/paper-source/
```

```text
Follow AGENTS.md for /path/to/paper.pdf
```

```text
Follow AGENTS.md for https://arxiv.org/pdf/2401.01234v2
```

The agent should recover matching original TeX when possible, read `prompts/enhance.md`, preserve the project and assets, add annotation targets, write metadata, validate its work, build the html, and inspect the output.

`AGENTS.md` is the operational workflow for coding agents. `prompts/enhance.md` is the detailed annotation contract.

## Output artifacts

A project typically produces:

```text
papers/paper/
├── original/                 # unmodified supplied/recovered material
│   └── ...
├── annotated/                # annotated TeX project
│   ├── main.tex
│   ├── sections/
│   ├── figures/
│   ├── references.bib
│   ├── paper.annotations.json
│   ├── paper.citations.json
│   └── ...
├── paper.pdf                  # optional; written with --pdf-output
├── paper.html                # PDF-backed reader
└── paper.native.html         # responsive reader
```

A self-contained paper uses one `.tex` file inside `papers/paper/annotated/`.
When the original and annotated source are intentionally identical, keep only
that canonical TeX file in `annotated/` instead of duplicating it under
`original/`.

- **annotated TeX**: paper source containing IperPaper PDF-link targets;
- **annotations JSON**: authored semantic explanations, shared background explanations for distributions/acronyms/concepts, and metadata; equation/figure/table/citation entries are generated in memory during the build and embedded in the readers rather than written back to this file;
- **citations JSON**: reusable citation titles, authors, rendered indexes, stable citation keys, and resolved links; this cache is generated by `build` and can be manually corrected;
- **PDF**: paper compiled by LaTeX for validation and PDF-backed HTML; persisted
  only when `--pdf-output` is supplied;
- **PDF HTML**: PDF.js reader containing the compiled PDF data, annotation geometry, explanation metadata, pre-rendered tooltip-math SVGs, and generated figure-preview PNGs;
- **native HTML**: responsive text converted from TeX, with DOM annotation targets, MathJax paper math, and the same pre-rendered tooltip explanations.

All files associated with a paper therefore stay together under its paper
workspace.


## Pipeline

- **Input:** a TeX file, TeX project, PDF, or paper URL.
- **AI agent:**
  - recovers the exact TeX source when possible;
  - understands notation in the paper's context;
  - inserts `\iperpaper{ID}{...}` semantic targets;
  - writes semantic annotation metadata;
  - leaves equation, figure, table, and citation references native.
- **Annotated source:** TeX plus `annotations.json`.
- **`iperpaper build`:**
  - compiles the paper with LaTeX;
  - validates annotation metadata against real PDF link rectangles;
  - discovers native equation, figure, table, and citation links;
  - generates reference tooltips from TeX, `.aux`, and bibliography data;
  - reuses or refreshes citation metadata by stable citation key;
  - extracts annotation rectangles;
  - renders explanation math as SVG and figure previews as PNG;
  - keeps the compiled PDF in memory or writes it with `--pdf-output`;
  - builds the PDF-backed reader, native HTML reader, or both.
- **Output:**
  - `paper.html`: exact-layout PDF.js reader;
  - `paper.native.html`: responsive Pandoc and MathJax reader;
  - hover and click explanations in either reader.

`iperpaper build` performs target validation and automatic-reference extraction before it creates the reader. The separate `iperpaper validate` command is an optional early check: it compiles the paper, verifies authored metadata against actual `iperpaper:` PDF rectangles, and verifies that native reference tooltips can be generated, but it does not render tooltip math or create the HTML reader.

The default `pdf_html` reader displays the PDF compiled from the annotated LaTeX source. The optional `native_html` renderer converts the TeX structure to responsive HTML. Annotation explanations remain in JSON, and mathematical fragments in those explanations are typeset by LaTeX during `iperpaper build` in either mode.


## Annotation targets in TeX

The TeX project needs `xcolor` and `hyperref`. Reuse the paper's package setup when possible, then define the IperPaper wrapper once in the preamble:

```tex
\usepackage{xcolor}
\usepackage{hyperref}

\definecolor{iperpaperlink}{HTML}{0000AA}
\DeclareRobustCommand{\iperpaper}[2]{%
  \begingroup
  \hypersetup{pdfborder=0 0 0}%
  \href{iperpaper:#1}{{\color{iperpaperlink}#2}}%
  \endgroup
}
\pdfstringdefDisableCommands{%
  \def\iperpaper#1#2{#2}%
}
```

The wrapper applies only to authored semantic targets. Existing citations, URLs, cross-references, and other links retain the paper's normal appearance and behavior.

Prose target:

```tex
We minimize the \iperpaper{cross_entropy}{cross-entropy loss}.
```

Math target:

```tex
$p_{\iperpaper{theta}{\theta}}(x)$
```

A complete local distribution can be targeted when its arguments define a specific semantic role:

```tex
\iperpaper{reward_distribution}{p_\phi(\hat r_t \mid h_t,z_t)}
```

The same annotation ID can be reused across multiple PDF rectangles only when the same explanation is correct at each occurrence.

## Automatic reference tooltips

Keep equation references, figure references, table references, and citations as ordinary TeX:

```tex
See Eq.~\eqref{eq:objective}, Figure~\ref{fig:overview}, Table~\ref{tab:results}, and \cite{smith2024}.
```

Do not wrap these commands in `\iperpaper` and do not add `eqref_`, `figref_`, `tabref_`, or `bibref_` objects to the authored annotation JSON. During compilation, IperPaper:

1. reads resolved equation, figure, and table destinations/numbers and bibliography labels from LaTeX `.aux` files;
2. extracts labeled equation bodies from standard `equation`, `align`, `alignat`, `flalign`, `gather`, and `multline` environments;
3. extracts referenced figure captions from TeX and crops the rendered figure artwork from the compiled PDF;
4. extracts referenced table captions and tabular source from TeX and crops the rendered table artwork from the compiled PDF;
5. extracts `\bibitem` entries from `thebibliography` source or classic BibTeX `.bbl` output and uses explicit `title`, `author`, and `doi` fields from referenced `.bib` databases as trusted metadata; `.bbl` formatting is never used to infer a paper title;
6. finds the matching native internal-link rectangles in the compiled PDF;
7. generates tooltip metadata and overlays those native rectangles without changing their color; equation, figure, and table references keep their native destinations, while citations with a resolved external target open that resource.

Generated equation-reference metadata uses the extracted formula as its label, figure references use `Figure N`, table references use `Table N`, and bibliography references use their rendered `[N]` label. Figure- and table-reference hover cards show the rendered artwork together with the source caption, with the reference label in bold. Their display width defaults to 80% of the printed artwork width and is controlled by the shared `FIGURE_TOOLTIP_SCALE` setting in `iperpaper.py`; `FIGURE_PREVIEW_DPI` controls the embedded PNG resolution. Each number in a multi-citation keeps its own native PDF link and receives the tooltip for that bibliography entry. Repeated links to the same label or citation key share generated metadata. Clicking an equation, figure, or table target follows the underlying native PDF link. A citation opens its resolved external target when one is available and otherwise follows its native bibliography link.

When bibliography lookup is enabled, explicit direct PDF URLs and arXiv PDFs
take priority, followed by PDFs verified from explicit landing pages, Crossref
full-text links that return actual PDF bytes, OpenAlex locations explicitly
marked open access, and recognized open-access PDFs reported by Semantic
Scholar. A trusted DOI selects a service's DOI lookup when available; otherwise
Crossref is queried with separate title and author parameters, and OpenAlex and
Semantic Scholar are searched by title and authors. Remote results must also
match the available trusted title and authors, including results retrieved by
DOI. If one matching OpenAlex or Semantic Scholar record has no usable PDF,
IperPaper continues through the other matching candidates. OpenAlex records
marked `closed` or `BRONZE` are left unlinked because their PDF may still
require a subscription. Repository copies that are not exposed by these
services must be supplied as an explicit bibliography URL.

## Annotation metadata and TeX in tooltips

Metadata is stored separately:

```json
{
  "title": "Paper title",
  "background": {
    "Exp": {
      "short": "An exponential distribution is a continuous probability distribution on the nonnegative real numbers, controlled by a positive rate parameter $\\lambda$.",
      "details": "With rate $\\lambda>0$, its density is $f_Y(x)=\\lambda e^{-\\lambda x}$ and its survival function is $\\Pr(Y>x)=e^{-\\lambda x}$ for $x\\ge0$. Its mean is $1/\\lambda$, and it is memoryless: $\\Pr(Y>s+t\\mid Y>s)=\\Pr(Y>t)$. The inverse-transform identity $-\\log U\\sim\\Exp(1)$ holds for $U\\sim\\U(0,1)$, and if $E\\sim\\Exp(1)$ with $c>0$, then $E/c\\sim\\Exp(c)$.",
      "link": "https://en.wikipedia.org/wiki/Exponential_distribution"
    },
    "CDF": {
      "short": "The cumulative distribution function (CDF) $F_X(x)=\\Pr(X\\le x)$ gives the probability that a random variable takes a value at most $x$.",
      "details": "For continuous variables the CDF is nondecreasing with limits $0$ and $1$; a smaller CDF at every threshold means a stochastically larger distribution. The survival function is $\\Pr(X>x)=1-F_X(x)$.",
      "link": "https://en.wikipedia.org/wiki/Cumulative_distribution_function"
    }
  },
  "annotations": [
    {
      "id": "previous_action",
      "kind": "symbol",
      "label": "$a_{t-1}$",
      "short": "The previous action $a_{t-1}$ is an input to the sequence model.",
      "details": "It is the action from timestep $t-1$, before the model computes the next hidden state $h_t$.",
      "background": []
    },
    {
      "id": "waiting_time",
      "kind": "symbol",
      "label": "$\\tau_i$",
      "short": "$\\tau_i$ is the exponential waiting time for event $i$.",
      "details": "Each candidate receives one independent waiting time; the smallest wins.",
      "background": ["Exp"]
    },
    {
      "id": "exp_distribution",
      "kind": "concept",
      "label": "exponential distribution",
      "short": "",
      "details": "",
      "background": ["Exp"]
    }
  ]
}
```

The top-level `background` object holds reusable explanations for probability
distributions, acronyms, named operators, and recurring concepts. Each entry has
`short` and `details` strings, may contain TeX math, and is shown below the
annotation's own text in the detail panel whenever an annotation lists its key in
the annotation's `background` field. The same background key can be reused by any
number of annotations; validation fails if an annotation references a key that
does not exist.

An optional `label` field supplies the human-readable heading shown for the
background block. The key remains the stable identifier used by annotations, and
the key is used as the heading when `label` is omitted.

An optional `link` field holds a Wikipedia or other authoritative URL explaining
the concept. When present, the reader renders the background title (for example,
the background label) as a blue clickable link to that page.

For probability distributions, the background explanation must state whether the
distribution is discrete or continuous, its support, and its density (continuous)
or probability mass function (discrete) in TeX math.

Every symbol introduced inside an explanation must itself be explained: give it
its own background entry and list it in the introducing entry's optional
`background` field. The reader shows those nested entries as additional labeled
blocks below the introducing one — for example, the Gamma function $\Gamma(k)$
used in a Gamma density gets its own `GammaFunction` entry referenced from the
`Gamma` entry and can use `"label": "Gamma function"` for its visible heading.

Every occurrence of a background concept in the paper's notation should be
covered by an annotation that references that background key — for example, an
annotation wrapping the symbol `\Exp` itself. Such background-only annotations
may leave `short` and `details` empty.

When an annotation's `short` or `details` is empty, the reader substitutes the
corresponding text from the first key in its `background` list and skips that
entry's separate block, so nothing appears twice. When an annotation has no text
of its own (both fields empty), the detail panel uses the annotation's `label`—the
actual formula, symbol, or text being explained—as its normal-weight heading and
shows the first background explanation directly below it without a duplicate
background heading. When that background entry has a `link`, the annotation label
is the blue clickable link. Annotation `kind` values are metadata and are not used
as visible panel titles. Validation fails if `short`, `details`, and `background`
are all empty, because such an annotation would show no explanation at all.

Use `$...$` for inline TeX inside explanation strings — including background
entries. `$$...$$`, `\(...\)`, and `\[...\]` are also supported. JSON backslashes
must be escaped, for example:

```json
{
  "short": "The transition distribution $p_\\phi(z_t \\mid h_t,x_t)$ predicts the next latent state."
}
```

During `iperpaper build`, IperPaper:

1. collects the unique math fragments from `label`, `short`, and `details` of every annotation, plus `short` and `details` of every background entry;
2. extracts the main paper's LaTeX preamble;
3. compiles the fragments in one temporary LaTeX document, so paper packages and preamble macros are available;
4. crops each formula tightly;
5. converts each cropped formula to SVG;
6. embeds those SVGs in the generated HTML.

If a notation macro exists only inside the document body or a local TeX group, write the equivalent TeX in the metadata using commands that are available from the main preamble.

## Distinguishing similar notation

Annotation IDs represent semantic explanations, not just glyph strings.

For example, the same base notation `p_\phi` may appear in several different predictive heads:

```tex
\iperpaper{dynamics_distribution}{p_\phi(\hat z_t \mid h_t)}
\iperpaper{reward_distribution}{p_\phi(\hat r_t \mid h_t,z_t)}
\iperpaper{continue_distribution}{p_\phi(\hat c_t \mid h_t,z_t)}
\iperpaper{decoder_distribution}{p_\phi(\hat x_t \mid h_t,z_t)}
```

These should have different metadata when they represent different distributions or model roles. Likewise, `$a_t$` and `$a_{t-1}$` should not share a tooltip when one means the current action and the other the previous action.

A parameter such as `\phi` itself may still reuse one annotation when its meaning is genuinely unchanged across occurrences.

`prompts/enhance.md` contains the detailed semantic-ID and math-coverage rules for agents.

## Source acquisition

For PDF or URL inputs, the agent should first look for matching original source.

For arXiv papers, the exact revision matters. `v2`, for example, means revision 2 of that arXiv submission; the agent should try to recover the source for the same revision rather than silently substituting another one.

Preferred source order:

1. exact matching arXiv source/revision;
2. clearly matching author/project repository;
3. official publisher or conference source package;
4. PDF-to-TeX reconstruction when matching source is unavailable.

Keep the TeX files and supporting assets required for compilation. The PDF-backed reader preserves every visible asset from the compiled paper. Native HTML converts those assets through Pandoc and may require converter-specific support for unusual figures or environments.

## Build manually

### Single TeX file

```bash
iperpaper build \
  papers/paper/annotated/paper.tex \
  papers/paper/annotated/paper.annotations.json \
  --mode all \
  -o papers/paper/paper.html
```

### TeX project directory

```bash
iperpaper build \
  papers/paper/annotated/ \
  papers/paper/annotated/paper.annotations.json \
  --main main.tex \
  --mode all \
  -o papers/paper/paper.html
```

`--main` is optional when `main.tex` exists or IperPaper can identify a single document root.

When annotation metadata is inside `annotated/`, omitting `-o` places the HTML
reader at the parent paper root; the citation JSON remains beside the annotation
JSON. The PDF is compiled internally for validation and for the PDF-backed
reader, but is not persisted unless `--pdf-output` is supplied.

With citation-link lookup enabled, which is the default for `build`, IperPaper
chooses citation targets in this order: an explicit direct PDF URL, an arXiv
identifier, a PDF verified from an explicit landing-page URL, a Crossref
full-text URL verified by its PDF bytes, a direct open PDF found through a
high-confidence OpenAlex match, a recognized open-access PDF reported by
Semantic Scholar, and finally the first explicit HTTP(S) URL as a fallback. An
explicit landing-page URL can therefore be replaced by a verified open PDF.
Crossref uses a DOI when supplied; otherwise it queries the title and authors
separately. OpenAlex and Semantic Scholar likewise use the DOI when available
and also search by title and authors. Every remote candidate must match the
available trusted title and authors. IperPaper keeps scanning matching OpenAlex
and Semantic Scholar candidates when an earlier result has no usable PDF.
Citations without a usable URL retain their normal reference behavior. The
`--no-citation-link-lookup` option disables external citation service queries;
existing cached metadata is still reused.

Builds also write citation metadata to `<paper>.citations.json` beside the
annotation JSON. The file contains one record per bibliography entry with its
stable TeX/BibTeX `citation_key`, rendered `index`, `paper_title`,
`paper_title_source`, `paper_title_verified`, `authors`, and `links`; it can be
edited to add or replace links. Existing records are matched by `citation_key`
and reused without querying the external services, so citation renumbering does
not misapply cached metadata. Pass `--regenerate-links` to query the services
again; existing cached or manually edited metadata remains available as a
fallback and is replaced when fresh metadata is found. The informational
`lookup_complete` field records whether lookup was enabled when that record was
last refreshed; it does not promise that a link was found or that every service
responded.

Automatic citation titles are bolded when they come from an explicit BibTeX
`title` field, a metadata service, or a cache record marked
`paper_title_verified`. Unresolved or fallback titles remain unbolded and are
not stored as `paper_title`; the original bibliography text remains the display
fallback.

Choose the renderer with `--mode`:

```bash
# Existing PDF.js reader (the default)
iperpaper build papers/paper/annotated/paper.tex \
  papers/paper/annotated/paper.annotations.json \
  --mode pdf_html -o papers/paper/paper.html

# Responsive, PDF-free HTML document
iperpaper build papers/paper/annotated/paper.tex \
  papers/paper/annotated/paper.annotations.json \
  --mode native_html -o papers/paper/paper.native.html

# Build both; this writes paper.html and paper.native.html
iperpaper build papers/paper/annotated/paper.tex \
  papers/paper/annotated/paper.annotations.json \
  --mode all -o papers/paper/paper.html
```

An `all` build treats `-o` as the PDF-backed path and inserts `.native` before the native output's `.html` suffix. Both modes share one LaTeX compilation and tooltip-math rendering pass. The native HTML does not embed or load the PDF. The compiled PDF is kept in memory unless `--pdf-output` is supplied.

### Optional early validation

If you want to check the paper/metadata targets before rendering tooltip math and creating the reader:

```bash
iperpaper validate \
  papers/paper/annotated/ \
  papers/paper/annotated/paper.annotations.json \
  --main main.tex
```

`build` repeats this validation internally, so a successful standalone `validate` is a checkpoint rather than a prerequisite.

## Validation performed by build

Before the reader is generated, IperPaper compiles the TeX and inspects the resulting PDF.

The target validation succeeds when:

- every compiled `iperpaper:ID` link has matching metadata;
- every metadata annotation has at least one real link rectangle in the compiled PDF;
- every discovered native equation/figure/table/citation link can be matched to its resolved source or bibliography entry.

Markers in comments or unreachable TeX files therefore do not count as targets.

Tooltip-math compilation happens later in `iperpaper build`; malformed TeX in explanation strings is reported as a build error.

## Reader behavior

### PDF-backed HTML

The generated HTML embeds the compiled PDF. A pinned PDF.js runtime renders each page at the browser's device pixel ratio.

Each page contains:

- a PDF canvas for the visible page;
- a PDF.js text layer for selection and copy;
- a PDF.js annotation layer for ordinary PDF links and internal references;
- an IperPaper overlay for explanation targets.

Authored IperPaper target text is styled in the compiled PDF by the `\iperpaper` wrapper. Automatic reference targets preserve the paper's native link styling. The overlay adds no permanent underline. Hovering an authored, equation, figure, table, or citation target shows its short explanation; hovering a generated figure or table target shows the preview and caption. Clicking an authored target opens the detailed explanation panel. Equation, figure, and table targets follow their original PDF destinations; citations open a resolved external resource when available and otherwise jump to the bibliography entry.

Math inside the explanation appears as SVG produced by the paper's LaTeX environment during the build.

### Native HTML

The native renderer converts TeX to a responsive HTML document with Pandoc and renders paper equations with MathJax. Authored `\iperpaper` wrappers become DOM targets, while native equation, figure, table, and citation references are connected to the same generated tooltip metadata as the PDF-backed reader. It has no embedded PDF and does not load PDF.js.

When generated citation metadata is available, native HTML emits one numbered `References` section with the same top-level heading hierarchy as the paper and suppresses Pandoc's duplicate raw `thebibliography` rendering.

This mode prioritizes reflow, mobile reading, search, and accessibility over exact publication layout. Arbitrary document classes, custom environments, TikZ, and highly customized TeX macros may require converter-specific support; use `pdf_html` when exact fidelity is required.

When a project loads `lmodern`, native HTML embeds the matching Latin Modern Roman faces for portable typography and selects MathJax 4's `mathjax-modern` font for equations. MathJax inherits the paper font for textual content inside formulas and does not automatically enlarge math to match the surrounding font's x-height. Other TeX font packages currently use a browser-safe serif prose fallback and MathJax's lighter New Computer Modern math font; matching arbitrary TeX fonts requires additional package-specific mappings.

### Collapsible reading levels

The reader can also collapse opt-in level-2 TeX regions while keeping each section heading visible. The source places named PDF destinations immediately before the heading, immediately after the heading, and at the end of the region:

```tex
\hypertarget{iperpaper-level-start:2:two-1}{}
\subsection{\texorpdfstring{\protect\hyperlink{iperpaper-level-start:2:two-1}{Extra detail}}{Extra detail}}
\hypertarget{iperpaper-level-content:2:two-1}{}
The expandable body goes here.
\par
\hypertarget{iperpaper-level-end:2:two-1}{}
```

Use a unique ASCII ID for each level-2 region. The self-link around the title gives the reader its exact PDF rectangle without changing the visible heading. During `build`, IperPaper creates a compact closed disclosure row with a colored guide and chevron; opening it reveals the level-2 body.

Projects normally wrap those markers in a `leveltwo` environment, as the tutorial's `iperpaper-levels.sty` does:

```tex
\begin{leveltwo}{Extra detail}
The expandable body goes here.
\end{leveltwo}
```

In `native_html` mode, the same `leveltwo` regions become semantic HTML
`<details>` disclosures. They are collapsed by default, keep the Level 2 title
visible, and use the same guide-and-chevron interaction without PDF geometry.

## Current limitations

- The PDF-backed reader uses the PDF compiled locally from the annotated source. Mapping annotations onto a separately supplied publisher/original PDF would require a PDF-registration step that is not currently implemented.
- Tooltip math is compiled from the main document preamble. Macros defined only later in the document body or inside local groups are not automatically in scope for tooltip rendering.
- The PDF-backed HTML embeds the PDF itself, so it includes the PDF's base64-size overhead plus reader code, metadata, and formula SVGs.
- The PDF-backed reader loads pinned PDF.js assets from jsDelivr; native HTML loads MathJax 4 assets from jsDelivr. Either therefore needs network access for its renderer unless those assets are hosted locally.
- The paper must compile in the local TeX environment with its required packages and fonts.
- IperPaper invokes `latexmk -pdf`, so compilation follows the pdfLaTeX path. The CLI does not currently provide XeLaTeX or LuaLaTeX engine selection.
- Automatic reference extraction currently expects hyperref-style native PDF links, equation labels inside the supported standard numbered environments, figure and table labels paired with source captions, and bibliography entries represented by `\bibitem` in source or a classic BibTeX `.bbl`. Figure previews currently crop direct PDF image/Form XObjects; a figure drawn entirely with page operators (for example, TikZ) can still receive its caption tooltip but may not receive an artwork preview. Table previews also depend on matching rendered table text through `pdftotext`. Highly customized reference macros or biblatex data-only `.bbl` files may require additional support.
- Rotated PDF pages are not supported by the overlay mapper yet.
- Annotation geometry uses each PDF link's axis-aligned `/Rect`. Optional `/QuadPoints` geometry is not interpreted, so unusually shaped or transformed links may produce imprecise overlays.

## Tests

Install the test dependency in the project environment with:

```bash
python -m pip install -e '.[test]'
```

```bash
python -m pytest
```

Core and PDF-backed tests live in `tests/test_iperpaper.py`; native HTML tests live in `tests/test_iperpaper_native_html.py`.
