# Annotation quality and format

Use this specification when creating or editing authored annotations. Produce an
annotated TeX file or project and a separate annotations JSON file; never embed
the complete TeX document in JSON. Repository layout, source acquisition, metadata
reuse, build commands, dependencies, and reporting are defined in
[AGENTS.md](../AGENTS.md).

## Annotated TeX artifact

Preserve scientific content, order, labels, references, citations, macros,
environments, figures, captions, tables, and appendices. Do not rewrite, summarize,
translate, normalize, or reformat the paper except to insert annotation wrappers
or required package/setup code. Follow the project-preservation rules in AGENTS.md.

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
relevant to that annotation, without duplicate keys. It may be empty when no shared
background is useful.

When an annotation's `short` and/or `details` is an empty string, the reader
substitutes the corresponding text from the **first** key in its `background`
list when that list is nonempty, and does not repeat that entry as a separate block below. This lets a
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

Background expansion is one level deep: dependencies of the annotation's directly
listed entries are shown, but their dependencies are not recursively expanded.
List any deeper prerequisites directly on the annotation when needed. Background
entries cannot reference themselves; keep dependencies free of cycles.

For probability distributions, the explanation must state:

- whether the distribution is discrete or continuous;
- its support;
- its density (continuous) or probability mass function (discrete), in TeX math.

```json
{
  "title": "Exponential race example",
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

- Include background that helps explain the current target, equation, or
  explanation, including its mathematical role even when the tooltip does not
  name the concept. Keep REINFORCE for an advantage weighting its policy-gradient
  update; omit categorical/NLL background from a critic overview that does not
  use those details. Broader topical association alone is insufficient. Do not
  expand an explanation merely to justify an unnecessary background entry.
- Every relevant probability distribution, acronym, named operator, or recurring
  concept used by an annotation must have a background entry, and the annotation
  must list its key in its `background` field.
- Every occurrence of a background concept in the paper's notation should be
  covered by an annotation that references that background key. If no existing
  paper-specific annotation covers an occurrence, add one targeting it in the TeX
  (for example, wrapping the symbol `\Exp` itself). Such background-only
  annotations may leave `short` and `details` empty so the reader reuses the
  background text directly instead of showing it twice. This coverage requirement
  does not mean attaching that background to every nearby annotation.
- The same background key is reused by every annotation that needs it; do not
  duplicate the explanation inside each annotation.
- Background keys use only letters, digits, `.`, `_`, or `-`, and should be short,
  stable identifiers such as `Exp`, `KL`, or `PCG64`.
- Use `label` for a readable background heading when the stable key is a compound
  identifier such as `GammaFunction`; do not put spaces in the key.
- Supply a Wikipedia or other authoritative `link` for authored background entries,
  even though the metadata format permits omitting it.
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

In both short tooltips and detailed explanations, refer to the paper's actual
symbols whenever needed to make inputs, outputs, dependencies, or nearby
relationships explicit. Pair words with notation (for example, "latent code
$\mathbf{z}$" and "generated image $f_\theta(\mathbf{z})$") rather than leaving
the reader to guess which quantity is meant. Preserve the paper's terminology
and mathematical typography, including bold vectors, hats, subscripts, and
superscripts. Explain any additional symbols you introduce. Use a compact formula
when it clarifies the relationship; do not repeat a whole equation unnecessarily.
Keep these relationships local: a general function in a background section must
not inherit an architectural decomposition introduced only for a later method.

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

The build generates tooltips from native PDF links: labeled equation source,
rendered figures/tables with captions, and bibliography entries. Keep reachable
labels inside standard numbered equation environments, figure/table labels and
captions, and citations available through `thebibliography` or a classic
BibTeX-generated `.bbl`. Preserve `.bib` databases and stable citation keys,
including explicit title, author, and DOI fields used for citation lookup.

Do not create authored `eqref_`, `figref_`, `tabref_`, or `bibref_` annotations.
Original links retain their appearance. Equation, figure, and table links retain
their native destinations; generated citations may open a resolved external
resource, otherwise retaining their native bibliography destination. See AGENTS.md
for handling extraction failures.

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

## Final authoring checks

- Audit compiled targets: every authored metadata ID must create at least one real
  `iperpaper:` PDF link, and every such link must have matching metadata.
- Check wrappers are not nested, and audit reused IDs using the semantic-identity
  rule above.
- Check metadata against the schema above, including existing background keys,
  nonempty effective explanations, and correctly delimited/escaped TeX math.
- Verify scientific content and original link styling/destinations are preserved,
  and native references meet the compatibility requirements above.
- Complete validation/build and reporting using the workflow in AGENTS.md.
