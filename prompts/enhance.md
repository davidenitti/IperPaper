You are preparing an IperPaper-enhanced scientific paper.

Produce TWO artifacts:

1. annotated LaTeX source, either a single `.tex` file or a complete multi-file TeX project;
2. an annotation metadata JSON file.

Do not embed the TeX source inside JSON.

Within this repository, use one workspace per paper:

- preserve distinct unmodified source material in `papers/<paper-stem>/original/`;
- place the annotated TeX file or project in `papers/<paper-stem>/annotated/`;
- place annotation/citation JSON beside the annotated source in `papers/<paper-stem>/annotated/`, and place the compiled PDF and both HTML readers directly in `papers/<paper-stem>/`;
- when there is no distinct original because the paper is authored directly as annotated TeX, keep only the canonical TeX in `annotated/` rather than duplicating it.

## Prefer recoverable original source

If the user supplied a PDF or paper URL, do not immediately reconstruct LaTeX from the PDF.

- Inspect the paper for an identifier/version, especially an arXiv identifier such as `arXiv:YYMM.NNNNNv2`.
- Search for publicly available original TeX/source matching the exact paper and revision when source access is available.
- Prefer the exact matching arXiv source archive when available; otherwise use a clearly matching author/project repository or official source package.
- Verify title, authors, version/date when available, section structure, equations, figures, and appendices before using recovered source.
- Do not silently substitute another version.

## Annotated TeX artifact

Preserve a self-contained paper as one annotated `.tex` file. Preserve a source archive/project as a project:

- keep relative paths and `\input` / `\include` structure when practical;
- keep source files, figures/images, bibliography files, styles/classes, and other resources needed to compile the paper;
- preserve scientific content, order, labels, references, citations, macros, environments, figures, captions, tables, and appendices;
- do not rewrite, summarize, translate, normalize, or reformat the paper except where an IperPaper wrapper or required package/setup is inserted.

Make sure `xcolor` and `hyperref` are available. Reuse the paper's existing package setup when possible; do not duplicate package loads with conflicting options.

After those packages are available, define the IperPaper link style once in the document preamble:

```tex
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

This wrapper is local to authored IperPaper targets. Original citations, URLs, cross-references, and other paper links keep their existing appearance and behavior.

## Annotation metadata JSON

The JSON file has exactly these top-level fields:

- `title`: paper title as a non-empty string;
- `annotations`: an array of annotation objects;
- `background`: an object mapping background keys to shared explanations (see below).

Each annotation object contains these string fields:

- `id`: unique stable ASCII identifier using only letters, digits, `.`, `_`, or `-`;
- `kind`: exactly one of `symbol`, `operator`, `concept`, `notation`, `equation`, or `reference`; `reference` is normally reserved for build-generated figure, table, and bibliography tooltips rather than authored JSON;
- `label`: the actual formula, symbol, or text explained by the annotation; use TeX math delimiters for mathematical labels so the reader renders them as formulas;
- `short`: one or two context-specific tooltip sentences, or an empty string to reuse the first background entry's `short` (see below);
- `details`: concise deeper explanation including role, intuition, domain/units when relevant, and nearby equation/prose connections, or an empty string to reuse the first background entry's `details`.

Each annotation object also contains a `background` field: a list of background keys
relevant to that annotation. It may be empty when no shared background is useful.

When an annotation's `short` and/or `details` is an empty string, the reader
substitutes the corresponding text from the **first** key in its `background`
list, and does not repeat that entry as a separate block below. This lets a
pure-background annotation (for example, one whose only job is to explain
"$\Exp$" itself) contain no text of its own. Validation fails if `short`,
`details`, and `background` are all empty, because such an annotation would show
no explanation at all.

When an annotation has **no text of its own** (both `short` and `details` empty),
the detail panel uses the annotation's `label` — the actual formula, symbol, or
text being explained — as its normal-weight heading, followed directly by the
background explanation without a duplicate background heading. If the first
background entry has a `link`, the annotation label is rendered as that blue
clickable link. Annotation `kind` values are not used as visible panel titles.

## Background section

The `background` object holds reusable explanations for notation and concepts that
appear in multiple annotations. Each key maps to an object with these fields:

- `short`: one or two sentences defining the distribution, acronym, operator, or concept;
- `details`: a deeper explanation of what it is, its standard properties, and how it is used;
- `label` (optional): the human-readable heading shown for this background block. The key remains the stable identifier, and the key is used as the heading when `label` is omitted;
- `link` (optional): a URL to a reference page — Wikipedia or another authoritative
  source — explaining the distribution or concept. When present, the reader renders
  the background label as a blue clickable link to that page.
- `background` (optional): a list of background keys for symbols or concepts that
  the entry's own explanation introduces. The reader shows those entries as
  additional labeled blocks below this one, so every symbol used in an explanation
  is itself explained.

For probability distributions, the explanation must state:

- whether the distribution is discrete or continuous;
- its support;
- its density (continuous) or probability mass function (discrete), in TeX math.

```json
{
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
      "id": "race_time",
      "kind": "symbol",
      "label": "auxiliary exponential variable",
      "short": "$X_i$ is an auxiliary exponential variable with rate $\\lambda_i$.",
      "details": "It is used to express selection as a minimum over waiting times.",
      "background": ["Exp"]
    }
  ]
}
```

Rules:

- Every relevant probability distribution, acronym, named operator, or recurring
  concept used by an annotation must have a background entry, and the annotation
  must list its key in its `background` field.
- Every occurrence of a background concept in the paper's notation should be
  covered by an annotation that references that background key. If no existing
  paper-specific annotation covers an occurrence, add one targeting it in the TeX
  (for example, wrapping the symbol `\Exp` itself). Such background-only
  annotations may leave `short` and `details` empty so the reader reuses the
  background text directly instead of showing it twice.
- The same background key is reused by every annotation that needs it; do not
  duplicate the explanation inside each annotation.
- Background keys use only letters, digits, `.`, `_`, or `-`, and should be short,
  stable identifiers such as `Exp`, `KL`, or `PCG64`.
- Use `label` for a readable background heading when the stable key is a compound
  identifier such as `GammaFunction`; do not put spaces in the key.
- Every referenced key must exist in the `background` object; validation fails otherwise.
- Keep each entry self-contained: when the annotation has its own text, the entry
  is shown below it in the detail panel, labeled with its key (linked when a
  `link` URL is given).
- Do not create background entries for paper-specific symbols that already have
  their own annotations; background is for shared general knowledge, not local roles.
- Every symbol introduced inside an explanation — for example the Gamma function
  $\\Gamma(k)$ appearing in a Gamma density — must itself be explained: give it its
  own background entry and list it in the introducing entry's `background` field.

### Math inside explanations

Use TeX math delimiters inside annotation and background `short` or `details`
whenever mathematical notation is clearer than plain text.

Prefer inline math with `$...$`:

```json
{
  "short": "The previous action $a_{t-1}$ is fed into the sequence model.",
  "details": "The transition distribution $p_\\phi(z_t \\mid h_t, x_t)$ predicts the latent state at time $t$."
}
```

`$$...$$`, `\(...\)`, and `\[...\]` are also supported. Remember that JSON requires TeX backslashes to be escaped as `\\`.

Do not put HTML or Markdown formatting in annotation strings. IperPaper compiles the math fragments with LaTeX during the build, using the main paper's preamble/macros, and embeds the resulting SVGs in the tooltip/detail reader.

When a paper-specific macro is defined only later inside the document body or only in a local group, prefer equivalent TeX that is valid from the main document preamble rather than relying on that local definition.

## Annotation markers

Use the SAME marker form in prose and math:

`\iperpaper{ANNOTATION_ID}{ORIGINAL_LATEX}`

Examples:

```tex
We minimize the \iperpaper{ann_cross_entropy}{cross-entropy loss}.
```

```tex
$p_{\iperpaper{theta}{\theta}}(x)$
```

```tex
\[
\iperpaper{expectation}{\mathbb{E}_{x \sim p(x)}}[f(x)]
\]
```

The visible second argument must preserve the original TeX expression. `\iperpaper` emits an ordinary `\href{iperpaper:ID}{...}` PDF link internally, so the LaTeX compiler creates the PDF rectangle used as the hover/click target.

Rules:

- Do not use MathJax-only markers.
- Do not use raw `\href{iperpaper:...}{...}` for new annotations; use `\iperpaper{ID}{...}`.
- Avoid nested IperPaper annotations. Prefer non-overlapping atomic targets.
- Do not annotate punctuation or obvious arithmetic symbols unless their role is unusual.

## Automatic equation, figure, table, and bibliography reference tooltips

Do not author IperPaper wrappers or JSON entries for equation references, figure references, table references, or bibliography citations. Leave their native TeX unchanged, for example:

```tex
Eq.~\eqref{eq:training-objective}
Figure~\ref{fig:overview}
Table~\ref{tab:results}
\cite{smith2024}
```

During validation/build, IperPaper inspects the ordinary internal PDF links and generates reference overlays deterministically:

- `\eqref{...}` and equation-targeting `\ref{...}` / `\autoref{...}` reuse the native link rectangle and show the resolved equation number plus the exact labeled equation body extracted from the TeX source;
- figure-targeting `\ref{...}`, `\cref{...}`, and related native links show the compiled figure artwork together with its source caption; the preview defaults to 80% of the figure's printed width via `FIGURE_TOOLTIP_SCALE`;
- table-targeting `\ref{...}`, `\cref{...}`, and related native links show the rendered table together with its source caption; they reuse `FIGURE_TOOLTIP_SCALE`, so their preview also defaults to 80% of the printed table width;
- each native bibliography link created by `\cite{...}` or a citation variant reuses its own rectangle and shows the matching rendered bibliography label and entry;
- repeated links to the same equation, figure, table, or citation key reuse generated metadata but keep every native rectangle;
- clicks continue through the original PDF link, so its appearance and navigation behavior remain unchanged.

Keep equation labels inside standard numbered equation environments, keep figure and table labels associated with their captions, and preserve the paper's bibliography source or generated `.bbl`. In particular, retain referenced `.bib` databases and stable citation keys: their explicit title, author, and DOI fields support citation lookup, and the citation cache is keyed by the TeX/BibTeX key. If automatic extraction reports an unsupported reference, preserve the scientific source and report the limitation rather than inventing explicit reference metadata.

## Semantic identity and annotation-ID reuse

Reuse an annotation ID only when **the explanation should genuinely be the same at every occurrence**. Matching glyphs or matching base notation are not enough.

Use different IDs when any of these changes the local meaning:

- temporal role, such as `$a_t$` versus `$a_{t-1}$`;
- predicted variable/output;
- conditioning variables;
- distribution/head/function role;
- domain, units, or interpretation;
- a symbol that is deliberately overloaded in different sections.

For example, a model may use the same base notation `p_\phi` for several predictive distributions. Do not give all of these the same tooltip merely because they share `p_\phi`:

```tex
\iperpaper{dynamics_distribution}{p_\phi(\hat z_t \mid h_t)}
\iperpaper{reward_distribution}{p_\phi(\hat r_t \mid h_t,z_t)}
\iperpaper{continue_distribution}{p_\phi(\hat c_t \mid h_t,z_t)}
\iperpaper{decoder_distribution}{p_\phi(\hat x_t \mid h_t,z_t)}
```

Their metadata should explain the dynamics predictor, reward predictor, continuation predictor, and decoder separately.

By contrast, the parameter symbol `\phi` itself may reuse one annotation ID across those equations if it truly refers to the same model parameter set and the same explanation is correct everywhere.

Before finalizing, audit every reused ID and ask: **Would showing exactly the same tooltip at all of these targets be correct and useful?** If not, split the ID.

## Math coverage

For important displayed equations, prefer dense semantic coverage rather than annotating only the whole equation. Inventory meaningful atomic symbols/functions/operators that a reader may need to understand, for example:

- objective/loss functions;
- parameters and state variables;
- probability distributions and predictive heads;
- expectations, sums, gradients, norms, KL divergence and other nontrivial operators;
- learned coefficients/weights;
- time/horizon indices when paper-specific;
- named sub-losses or functions.

Prefer annotating `\mathcal L` and `\phi` separately over wrapping `\mathcal L(\phi)` as one target when both have useful independent meanings. For a probability distribution whose arguments define its role, prefer annotating the complete local distribution expression rather than only the repeated base token.

## What to annotate

Prioritize paper-specific notation and concepts that may block understanding. Use context from the whole paper/project to disambiguate symbols. Do not invent definitions; state ambiguity when the paper itself is ambiguous.

## Final self-check

- TeX remains normal compilable LaTeX with `xcolor` and `hyperref` available.
- The robust `\iperpaper` wrapper is defined once after those packages are available, with the PDF-string fallback shown above.
- Every IperPaper target uses `\iperpaper{ID}{...}` in prose or math.
- Original paper links remain unmodified.
- Metadata contains only `title`, `annotations`, and `background` at top level.
- Every relevant distribution, acronym, or recurring concept used by an annotation has a background entry, and the annotation lists that key in its `background` field.
- Every background key referenced by an annotation exists in the `background` object.
- TeX notation inside explanation strings is wrapped in supported math delimiters and JSON backslashes are escaped.
- Every annotation ID appears in at least one reachable TeX marker.
- Every marker has matching metadata.
- No annotation wrappers are nested.
- Every reused annotation ID has the same semantic meaning at every target; same-looking notation with different roles uses different IDs.
- Equation references, figure references, table references, and citations remain native TeX commands without `\iperpaper` wrappers or authored metadata.
- Validation/build successfully generates their tooltips from native PDF links, labeled equation/figure/table source, figure/table artwork, and bibliography data.
- Automatic equation, figure, table, and bibliography targets retain their original visible style and click destination.
- Referenced `.bib` databases and citation keys are preserved so citation metadata and cached links remain associated with the correct entries.
- Multi-file structure and visible assets are preserved when available.
