import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import iperpaper
import iperpaper_native_html
from iperpaper_templates import read_template

HAS_LATEX = shutil.which("latexmk") is not None
HAS_PANDOC = shutil.which("pandoc") is not None
HAS_MATH_RENDER = HAS_LATEX and shutil.which("pdfcrop") is not None and shutil.which("pdftocairo") is not None


class IperPaperNativeHtmlTests(unittest.TestCase):
    def fixture_annotations(self):
        """
        Create minimal valid annotation metadata for tests.

        Returns:
            Any: Minimal annotation metadata.
        """
        return json.loads(Path("tests/fixtures/annotations.json").read_text(encoding="utf-8"))

    def test_tex_rewrite_preserves_nested_annotation_content(self):
        """Verify that tex rewrite preserves nested annotation content."""
        source = r"Text \iperpaper{term_one}{a \textbf{nested} term} and $x$."
        rewritten = iperpaper_native_html._replace_iperpaper_with_hrefs(source)
        self.assertEqual(
            rewritten,
            r"Text \href{iperpaper:term_one}{a \textbf{nested} term} and $x$.",
        )

    def test_native_reader_template_is_an_external_resource(self):
        """Verify that the native reader template is external to the Python module."""
        template = (
            Path(iperpaper_native_html.__file__).with_name("iperpaper_templates") / "native_reader.html"
        )
        self.assertTrue(template.read_text(encoding="utf-8").startswith("<!doctype html>"))
        self.assertTrue(read_template("native_reader.html").startswith("<!doctype html>"))
        self.assertNotIn(
            "<!doctype html>",
            Path(iperpaper_native_html.__file__).read_text(encoding="utf-8"),
        )

    def test_reader_templates_open_enriched_citations_in_new_tabs(self):
        """Verify that both readers route enriched citations to external URLs."""
        pdf_template = read_template("pdf_reader.html")
        native_template = read_template("native_reader.html")

        self.assertIn("window.open(a.external_url,'_blank','noopener,noreferrer')", pdf_template)
        self.assertIn("window.open(a.external_url,'_blank','noopener,noreferrer')", native_template)
        self.assertIn("t.innerHTML=a.tooltip_html||a.short_html", pdf_template)
        self.assertIn("t.innerHTML=a.tooltip_html||a.short_html", native_template)

    def test_reader_templates_persist_right_click_highlights(self):
        """Verify that both readers toggle persistent right-click highlights."""
        pdf_template = read_template("pdf_reader.html")
        native_template = read_template("native_reader.html")

        for template, mode, version in ((pdf_template, "pdf", 7), (native_template, "native", 5)):
            self.assertIn(f"iperpaper:highlights:v{version}:{mode}:", template)
            self.assertIn("localStorage.setItem(HIGHLIGHT_STORAGE_KEY", template)
            self.assertIn("new Intl.Segmenter", template)
            self.assertIn("addEventListener('contextmenu'", template)
            self.assertIn("event.preventDefault()", template)
            self.assertIn("user-highlight-layer", template)
            self.assertIn('id="ask-ai"', template)
            self.assertIn("selectionchange", template)
        self.assertIn("function addPdfHighlightRect", pdf_template)
        self.assertIn("function pdfBlockFormulaRect", pdf_template)
        self.assertIn("if(item.kind==='equation')", pdf_template)
        self.assertIn("const blockRect=pdfBlockFormulaRect(rects)", pdf_template)
        self.assertIn("for(const rect of rects)addPdfHighlightRect", pdf_template)
        self.assertIn(
            ".user-highlight-layer { position:absolute; inset:0; z-index:1; pointer-events:none; "
            "mix-blend-mode:multiply; }",
            pdf_template,
        )
        self.assertIn(
            ".user-highlight { position:absolute; background:rgb(255 250 207); border-radius:2px; }",
            pdf_template,
        )
        self.assertIn("el.style.width=rect.width+2+'px'", pdf_template)
        self.assertNotIn("::highlight(iperpaper-user-highlight)", pdf_template)
        self.assertNotIn("className='highlight appended'", pdf_template)
        self.assertIn("function pdfHighlightAt", pdf_template)
        self.assertIn("function normalizePdfHighlightText", pdf_template)
        self.assertIn("function storedHighlightRange", pdf_template)
        self.assertIn(
            "const boundaryText=text.replace(/([^.!?])\\n\\n(?=[ \\t]*[a-z])/g,'$1  ')", pdf_template
        )
        self.assertIn("previousBreak=boundaryText.lastIndexOf('\\n\\n'", pdf_template)
        self.assertIn("nextBreak=boundaryText.indexOf('\\n\\n',offset)", pdf_template)
        self.assertIn("sentenceBounds(boundaryText.slice(start,end),offset-start)", pdf_template)
        self.assertIn("function equivalentPdfHighlight", pdf_template)
        self.assertIn("userHighlights.filter(saved=>equivalentPdfHighlight(saved,item))", pdf_template)
        self.assertIn("node?.nodeType!==Node.ELEMENT_NODE", pdf_template)
        self.assertIn("CSS.highlights.set(USER_HIGHLIGHT_NAME,new Highlight(...ranges))", native_template)
        self.assertIn("nativeHighlightRanges(resolved.model,resolved.start,resolved.end)", native_template)
        self.assertIn("CSS?.highlights?.delete(USER_HIGHLIGHT_NAME)", native_template)
        self.assertIn(".user-highlight { position:absolute; background:rgb(255 250 207);", native_template)
        self.assertIn(
            "::highlight(iperpaper-user-highlight) { background:rgb(255 250 207); }", native_template
        )
        self.assertIn(
            "for(const range of ranges)for(const rect of mergedNativeRects(range.getClientRects()))",
            native_template,
        )
        self.assertIn("pdfEquationBounds", pdf_template)
        self.assertIn("function pdfRectsShareLine", pdf_template)
        self.assertIn("const sameLine=pdfRectsShareLine(previous.rect,rect)", pdf_template)
        self.assertIn("lines.find(item=>pdfRectsShareLine(item,rect))", pdf_template)
        self.assertIn("function isPdfEquationComponent", pdf_template)
        self.assertIn("block.some(line=>isPdfEquationLine(line,shell))", pdf_template)
        self.assertIn("function repairPdfHighlight", pdf_template)
        self.assertIn("repaired=repairPdfHighlight(item,model,shell)||repaired", pdf_template)
        self.assertIn("isPdfVisualBlockBreak", pdf_template)
        self.assertIn("baselineGap>maxHeight*1.8||fontRatio>1.28", pdf_template)
        self.assertIn("pdfProseBounds", pdf_template)
        self.assertIn(
            "pdfProseBounds(model,pdfSentenceBounds(model.text,offset),caret.node,shell)", pdf_template
        )
        self.assertIn("pdfSentenceBounds", pdf_template)
        self.assertIn("capHighlightRect", pdf_template)
        self.assertIn("mergedNativeRects", native_template)
        self.assertIn("capNativeHighlightRect", native_template)
        self.assertIn("event.target.closest('.math.display')", native_template)
        self.assertIn("function nativeHighlightAt", native_template)
        self.assertIn("function nativeMathSentenceText", native_template)
        self.assertIn("sentenceText+=nativeMathSentenceText(value)", native_template)
        self.assertIn("function sentenceBounds(text,offset,boundaryText=text)", native_template)
        self.assertIn("sentenceText+=value.replace(/[\\r\\n]/g,' ');", native_template)
        self.assertIn(".map(repairNativeHighlight)", native_template)
        self.assertIn("function repairNativeHighlight", native_template)
        self.assertIn("bounds.end===oldEnd", native_template)
        self.assertIn("sentenceBounds(model.text,offset,model.sentenceText)", native_template)

    def test_figure_cref_rewrite_preserves_single_and_multiple_links(self):
        """Verify that figure cref rewrite preserves single and multiple links."""
        annotations = {
            "annotations": [
                {
                    "id": iperpaper_native_html.automatic_reference_id("figure", "fig:one"),
                    "label": "Figure 1",
                },
                {
                    "id": iperpaper_native_html.automatic_reference_id("figure", "fig:two"),
                    "label": "Figure 2",
                },
            ]
        }
        rewritten = iperpaper_native_html._replace_figure_crefs_with_hrefs(
            r"See \cref{fig:one} and \Cref{fig:one,fig:two}.", annotations
        )

        self.assertEqual(
            rewritten,
            r"See Figure~\href{#fig:one}{1} and Figures~\href{#fig:one}{1} and \href{#fig:two}{2}.",
        )

    def test_table_cref_rewrite_preserves_single_and_multiple_links(self):
        """Verify that table cref rewrite preserves single and multiple links."""
        annotations = {
            "annotations": [
                {
                    "id": iperpaper_native_html.automatic_reference_id("table", "tab:one"),
                    "label": "Table 1",
                },
                {
                    "id": iperpaper_native_html.automatic_reference_id("table", "tab:two"),
                    "label": "Table 2",
                },
            ]
        }
        rewritten = iperpaper_native_html._replace_figure_crefs_with_hrefs(
            r"See \cref{tab:one} and \Cref{tab:one,tab:two}.", annotations
        )

        self.assertEqual(
            rewritten,
            r"See Table~\href{#tab:one}{1} and Tables~\href{#tab:one}{1} and \href{#tab:two}{2}.",
        )

    def test_custom_tabular_is_rewritten_for_pandoc(self):
        """Verify that custom tables are rewritten for Pandoc."""
        source = r"""\begin{mytabular}{
  colspec = {| L{7em} | C{3em} |},
  row{1} = {font=\bfseries},
}
A & B \\
\o1 & \textbf{2} \\
\end{mytabular}"""

        rewritten = iperpaper_native_html._replace_my_tabular(source)

        self.assertIn(r"\begin{tabular}{ll}", rewritten)
        self.assertIn(r"A & B", rewritten)
        self.assertNotIn(r"mytabular", rewritten)
        self.assertNotIn(r"\o", rewritten)

    def test_native_tex_rewrite_expands_paper_macros_and_layout(self):
        """Verify that native TeX removes layout leaks and expands paper macros."""
        source = r"""\begin{adjustwidth}{0.95cm}{0.95cm}
\begin{hyphenrules}{nohyphenation}
\[
    \lnpp(x_t|z_t,h_t) + \ensuremath{\sg(\qp(z_t|h_t,x_t))} + \H[\p<\pi_\theta>(a_t|s_t)] + \hspace*{-2.4ex}
\]
\end{hyphenrules}
\end{adjustwidth}"""

        rewritten = iperpaper_native_html._replace_native_tex_commands(source)

        self.assertNotIn("0.95cm", rewritten)
        self.assertNotIn("nohyphenation", rewritten)
        self.assertIn(r"\ln p_\phi(x_t|z_t,h_t)", rewritten)
        self.assertIn(r"\operatorname{sg}(q_\phi(z_t|h_t,x_t))", rewritten)
        self.assertIn(r"\operatorname{H}[\pi_\theta(a_t|s_t)]", rewritten)
        self.assertIn(r"\hspace{-2.4ex}", rewritten)
        self.assertNotIn(r"\hspace*", rewritten)
        self.assertNotIn(r"\ensuremath", rewritten)

    def test_native_title_metadata_replaces_orphan_maketitle_marker(self):
        """Verify that native output starts with title metadata, not a footnote marker."""
        document = {
            "meta": {
                "title": {"t": "MetaInlines", "c": [{"t": "Str", "c": "Paper"}]},
                "author": {
                    "t": "MetaList",
                    "c": [{"t": "MetaInlines", "c": [{"t": "Str", "c": "Author"}]}],
                },
            },
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Span",
                            "c": [["", [], []], [{"t": "Note", "c": []}]],
                        }
                    ],
                },
                {"t": "Div", "c": [["", ["center"], []], []]},
            ],
        }

        transformed, _ = iperpaper_native_html._transform_pandoc_ast(
            document, {"title": "Paper", "annotations": []}
        )

        title_block = transformed["blocks"][0]
        self.assertTrue(iperpaper_native_html._is_center_div(title_block))
        self.assertEqual(title_block["c"][1][0]["c"][0]["c"], "Paper")
        self.assertEqual(title_block["c"][1][1]["c"][0]["c"], "Author")
        self.assertNotEqual(title_block["t"], "Para")

    def test_graphic_reference_resolves_declared_graphic_path(self):
        """Verify that extensionless graphics resolve through graphicspath."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "figures" / "tasks" / "dmc.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            tex_path = root / "figures" / "tasks" / "figure.tex"
            rewritten = iperpaper_native_html._replace_graphic_references(
                r"\includegraphics{tasks/dmc}",
                root,
                tex_path,
                [root / "figures"],
                {},
            )

        self.assertIn(r"{figures/tasks/dmc.jpg}", rewritten)

    def test_level_two_becomes_collapsed_details(self):
        """Verify that level two becomes collapsed details."""
        document = {
            "meta": {},
            "blocks": [
                {
                    "t": "Div",
                    "c": [
                        ["", ["leveltwo"], []],
                        [
                            {
                                "t": "Para",
                                "c": [
                                    {
                                        "t": "Span",
                                        "c": [
                                            ["", [], []],
                                            [{"t": "Str", "c": "Optional detail"}],
                                        ],
                                    },
                                    {"t": "SoftBreak"},
                                    {"t": "Str", "c": "Hidden body"},
                                ],
                            }
                        ],
                    ],
                }
            ],
        }
        transformed, _ = iperpaper_native_html._transform_pandoc_ast(
            document, {"title": "x", "annotations": []}
        )

        blocks = transformed["blocks"]
        self.assertEqual(
            blocks[0]["c"][1],
            '<details class="level-accordion level-2"><summary>',
        )
        self.assertEqual(
            blocks[1],
            {"t": "Plain", "c": [{"t": "Str", "c": "Optional detail"}]},
        )
        self.assertEqual(
            blocks[3],
            {"t": "Para", "c": [{"t": "Str", "c": "Hidden body"}]},
        )
        self.assertEqual(blocks[-1]["c"][1], "</div></details>")

    def test_generated_references_replace_pandoc_bibliography(self):
        """Verify that generated references replace pandoc bibliography."""
        ann_id = iperpaper_native_html.automatic_reference_id("bibliography", "paper")
        document = {
            "meta": {},
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Cite",
                            "c": [[{"citationId": "paper"}], []],
                        }
                    ],
                },
                {
                    "t": "Div",
                    "c": [
                        ["", ["thebibliography"], []],
                        [
                            {
                                "t": "Para",
                                "c": [
                                    {
                                        "t": "Span",
                                        "c": [
                                            ["", [], []],
                                            [{"t": "Str", "c": "99"}],
                                        ],
                                    }
                                ],
                            },
                            {
                                "t": "Para",
                                "c": [{"t": "Str", "c": "Duplicate entry"}],
                            },
                        ],
                    ],
                },
            ],
        }
        annotations = {
            "title": "x",
            "annotations": [
                {
                    "id": ann_id,
                    "kind": "reference",
                    "label": "Reference [1]",
                }
            ],
        }

        transformed, cited_keys = iperpaper_native_html._transform_pandoc_ast(document, annotations)

        self.assertEqual(cited_keys, ["paper"])
        self.assertEqual(len(transformed["blocks"]), 1)
        self.assertNotIn("thebibliography", json.dumps(transformed))
        self.assertNotIn("Duplicate entry", json.dumps(transformed))

    def test_generated_figure_reference_is_activated(self):
        """Verify that generated figure reference is activated."""
        ann_id = iperpaper_native_html.automatic_reference_id("figure", "fig:plot")
        document = {
            "meta": {},
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Link",
                            "c": [
                                [
                                    "",
                                    [],
                                    [["reference-type", "ref"], ["reference", "fig:plot"]],
                                ],
                                [{"t": "Str", "c": "Figure 1"}],
                                ["#fig:plot", ""],
                            ],
                        }
                    ],
                }
            ],
        }
        annotations = {
            "title": "x",
            "annotations": [{"id": ann_id, "kind": "reference", "label": "Figure 1"}],
        }

        transformed, _ = iperpaper_native_html._transform_pandoc_ast(document, annotations)
        attrs = transformed["blocks"][0]["c"][0]["c"][0]

        self.assertIn("ip-target", attrs[1])
        self.assertIn(["data-annotation-id", ann_id], attrs[2])

    def test_generated_equation_reference_uses_resolved_number(self):
        """Verify that generated equation reference uses resolved number."""
        ann_id = iperpaper_native_html.automatic_reference_id("equation", "eq:sum")
        document = {
            "meta": {},
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Link",
                            "c": [
                                [
                                    "",
                                    [],
                                    [["reference-type", "eqref"], ["reference", "eq:sum"]],
                                ],
                                [{"t": "Str", "c": "[eq:sum]"}],
                                ["#eq:sum", ""],
                            ],
                        }
                    ],
                }
            ],
        }
        annotations = {
            "title": "x",
            "annotations": [
                {
                    "id": ann_id,
                    "kind": "equation",
                    "label": "$$a=b$$",
                    "short": "Equation (7): $$a=b$$",
                }
            ],
        }

        transformed, _ = iperpaper_native_html._transform_pandoc_ast(document, annotations)
        link = transformed["blocks"][0]["c"][0]

        self.assertEqual(link["c"][1], [{"t": "Str", "c": "(7)"}])
        self.assertIn(["data-annotation-id", ann_id], link["c"][0][2])

    def test_references_use_top_level_heading(self):
        """Verify that references use top level heading."""
        ann_id = iperpaper_native_html.automatic_reference_id("bibliography", "paper")
        annotation = {
            "id": ann_id,
            "kind": "reference",
            "label": "Reference [1]",
            "short": "[1] Reference",
            "details": "Reference details",
            "short_html": "[1] Reference",
            "details_html": "Reference details",
        }
        annotations = {"title": "x", "annotations": [annotation]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(
                iperpaper_native_html,
                "_pandoc_native_fragment",
                return_value=("<p>Body</p>", ["paper"]),
            ):
                output = iperpaper_native_html.build_native_html(
                    root, root / "main.tex", annotations, [annotation]
                )

        self.assertIn(
            '<section class="references"><h1 id="references">References</h1>',
            output,
        )
        self.assertNotIn('<section class="references"><h2>', output)
        self.assertNotIn("Introduced:", output)

    def test_background_display_label_is_supported(self):
        """Verify that background display label is supported."""
        annotation = {
            "id": "gamma",
            "kind": "concept",
            "label": "Gamma",
            "short": "short",
            "details": "details",
            "background_html": [
                {
                    "key": "GammaFunction",
                    "label": "Gamma function",
                    "short_html": "background short",
                    "details_html": "background details",
                }
            ],
            "background_only": False,
        }
        annotations = {"title": "x", "annotations": [annotation]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(
                iperpaper_native_html,
                "_pandoc_native_fragment",
                return_value=("<p>Body</p>", []),
            ):
                output = iperpaper_native_html.build_native_html(
                    root, root / "main.tex", annotations, [annotation]
                )

        self.assertIn('"label": "Gamma function"', output)
        self.assertIn("const label=bg.label||bg.key", output)
        self.assertIn(".annotation-title { color:var(--ink); font-size:15px; font-weight:700", output)
        self.assertIn("title.innerHTML=a.label_html", output)
        self.assertNotIn("k.textContent=a.kind", output)
        self.assertNotIn("Generally:", output)

    @unittest.skipUnless(HAS_PANDOC, "pandoc is required")
    def test_html_is_reflowable_and_keeps_prose_and_math_targets(self):
        """Verify that html is reflowable and keeps prose and math targets."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.tex"
            source.write_text(
                r"""\documentclass{article}
\usepackage{hyperref}
\newcommand{\iperpaper}[2]{\href{iperpaper:#1}{#2}}
\begin{document}
Native \iperpaper{term}{annotated text} and $\iperpaper{symbol}{x_i}$.
\end{document}
""",
                encoding="utf-8",
            )
            annotations = {
                "title": "Native test",
                "annotations": [
                    {
                        "id": "term",
                        "kind": "concept",
                        "label": "term",
                        "short": "short",
                        "details": "details",
                    },
                    {
                        "id": "symbol",
                        "kind": "symbol",
                        "label": "symbol",
                        "short": "short",
                        "details": "details",
                    },
                ],
            }
            rendered = [
                {
                    **annotation,
                    **{f"{field}_html": annotation[field] for field in iperpaper.RICH_TEXT_FIELDS},
                }
                for annotation in annotations["annotations"]
            ]
            output = iperpaper_native_html.build_native_html(root, source, annotations, rendered)

        self.assertIn(
            '<header class="ip-header"><a class="brand" href="https://github.com/davidenitti/IperPaper/" target="_blank" rel="noopener noreferrer">IperPaper</a><button id="layout-toggle" class="layout-toggle" type="button" aria-pressed="false" title="Toggle split reading view">Split</button></header>',
            output,
        )
        self.assertIn('href="iperpaper:term"', output)
        self.assertIn(iperpaper_native_html._native_math_class("symbol"), output)
        self.assertIn("annotated text", output)
        self.assertIn(".ip-paper > .center:first-child", output)
        self.assertIn("font-size:clamp(2rem,4.3vw,2.55rem)", output)
        self.assertIn("font-family:var(--paper-font)", output)
        self.assertNotIn(".ip-target,.ip-target *", output)
        self.assertIn(".ip-target:hover { background:rgba(0,0,170,.06); outline:none; }", output)
        self.assertIn(
            ".ip-target:focus-visible { background:rgba(0,0,170,.06); outline:1px solid rgba(0,0,170,.20)",
            output,
        )
        self.assertIn("width:min(1050px,calc(100vw - 32px))", output)
        self.assertIn("font-size:21px", output)
        self.assertIn("line-height:1.35", output)
        self.assertIn("mathjax@4/tex-chtml-nofont.js", output)
        self.assertIn("font:'mathjax-newcm'", output)
        self.assertIn("%%FONT%%-font@4", output)
        self.assertIn("mtextInheritFont:true", output)
        self.assertIn("matchFontHeight:false", output)
        self.assertIn("enableExplorer:false", output)
        self.assertIn("speech:false,braille:false,assistiveMml:true", output)
        self.assertIn("'[tex]/ams'", output)
        self.assertIn("white-space:pre-line", output)
        self.assertIn(
            "position:sticky; top:0; z-index:30; width:100%; height:var(--ip-header-height)", output
        )
        self.assertIn(
            "display:flex; align-items:center; justify-content:flex-start; gap:10px; padding:0 11px; background:var(--bg); border:0; border-radius:0",
            output,
        )
        self.assertIn(
            ".brand { color:#3266C7; font-weight:750; letter-spacing:-.02em; text-decoration:none; }",
            output,
        )
        self.assertIn(
            '<header class="ip-header"><a class="brand" href="https://github.com/davidenitti/IperPaper/" target="_blank" rel="noopener noreferrer">IperPaper</a><button id="layout-toggle" class="layout-toggle" type="button" aria-pressed="false" title="Toggle split reading view">Split</button></header>',
            output,
        )
        self.assertIn("position:sticky; top:0", output)
        self.assertIn("top:var(--ip-header-height); bottom:0", output)
        self.assertIn("const minTop=(header?.getBoundingClientRect().bottom||0)+pad", output)
        self.assertNotIn("hover to peek", output)
        self.assertIn(r'content:"\25b6"', output)
        self.assertIn(r'content:"\25bc"', output)
        self.assertIn(".level-accordion[open] > summary::before", output)
        self.assertIn("initializeLevelSections()", output)
        self.assertNotIn("PDF_BASE64", output)
        self.assertNotIn("pdfjs", output.lower())

    def test_embeds_latin_modern_when_tex_requests_lmodern(self):
        """Verify that embeds latin modern when tex requests lmodern."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\usepackage{lmodern}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            font = root / "font.otf"
            font.write_bytes(b"fake-font")
            with mock.patch.object(iperpaper_native_html, "_find_tex_font", return_value=font):
                faces, family = iperpaper_native_html._paper_font_css(root)
            mathjax_font = iperpaper_native_html._mathjax_font(root)

        self.assertIn("data:font/otf;base64,", faces)
        self.assertIn("font-weight:700", faces)
        self.assertIn("IperPaper Latin Modern", family)
        self.assertEqual(mathjax_font, "mathjax-modern")

    def test_does_not_force_latin_modern_for_other_tex_fonts(self):
        """Verify that other TeX fonts do not force Latin Modern."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            faces, family = iperpaper_native_html._paper_font_css(root)
            mathjax_font = iperpaper_native_html._mathjax_font(root)

        self.assertEqual(faces, "")
        self.assertEqual(family, "Georgia,'Times New Roman',serif")
        self.assertEqual(mathjax_font, "mathjax-newcm")

    @unittest.skipUnless(HAS_MATH_RENDER, "latexmk, pdfcrop and pdftocairo are required")
    @unittest.skipUnless(HAS_PANDOC, "pandoc is required")
    def test_mode_all_writes_pdf_and_native_html_with_rendered_math(self):
        """Verify that mode all writes pdf and native html with rendered math."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "fixture.html"
            native_html_path = root / "fixture.native.html"
            pdf_path = root / "fixture.pdf"
            pages, targets = iperpaper.write_outputs(
                Path("tests/fixtures/annotated_project"),
                self.fixture_annotations(),
                html_path,
                pdf_path,
                mode="all",
                native_html_output=native_html_path,
            )
            self.assertTrue(html_path.is_file())
            self.assertTrue(native_html_path.is_file())
            self.assertTrue(pdf_path.is_file())
            self.assertGreater(pages, 0)
            self.assertGreater(targets, 0)
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("pdfjs-dist@", html_text)
            self.assertIn("data:image/svg+xml;base64,", html_text)
            self.assertNotIn("mathjax", html_text.lower())
            native_html_text = native_html_path.read_text(encoding="utf-8")
            self.assertIn(
                '<header class="ip-header"><a class="brand" href="https://github.com/davidenitti/IperPaper/" target="_blank" rel="noopener noreferrer">IperPaper</a><button id="layout-toggle" class="layout-toggle" type="button" aria-pressed="false" title="Toggle split reading view">Split</button></header>',
                native_html_text,
            )
            self.assertIn("MathJax", native_html_text)
            self.assertNotIn("PDF_BASE64", native_html_text)

    def test_default_native_html_path(self):
        """Verify the default native HTML path."""
        self.assertEqual(
            iperpaper.default_native_html_path(Path("papers/paper/paper.html")),
            Path("papers/paper/paper.native.html"),
        )

    def test_require_pandoc_error_is_actionable(self):
        """Verify that require pandoc error is actionable."""
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Pandoc"):
                iperpaper_native_html.require_pandoc()


if __name__ == "__main__":
    unittest.main()
