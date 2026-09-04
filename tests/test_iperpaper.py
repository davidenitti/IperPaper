import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader
from pypdf.generic import ContentStream

import bib_utils
import iperpaper
from iperpaper_templates import read_template

HAS_LATEX = shutil.which("latexmk") is not None
HAS_MATH_RENDER = HAS_LATEX and shutil.which("pdfcrop") is not None and shutil.which("pdftocairo") is not None


class IperPaperTests(unittest.TestCase):
    def fixture_annotations(self):
        """
        Create minimal valid annotation metadata for tests.

        Returns:
            Any: Minimal annotation metadata.
        """
        return json.loads(Path("tests/fixtures/annotations.json").read_text(encoding="utf-8"))

    def test_metadata_validates(self):
        """Verify that metadata validates."""
        iperpaper.validate_annotation_metadata(self.fixture_annotations())

    def test_empty_title_is_rejected(self):
        """Verify that empty or whitespace-only titles are rejected."""
        for title in ("", "   "):
            data = self.fixture_annotations()
            data["title"] = title
            with self.assertRaisesRegex(ValueError, "title must be a non-empty string"):
                iperpaper.validate_annotation_metadata(data)

    def test_pdf_reader_template_is_an_external_resource(self):
        """Verify that the PDF reader template is external to the Python module."""
        template = Path(iperpaper.__file__).with_name("iperpaper_templates") / "pdf_reader.html"
        self.assertTrue(template.read_text(encoding="utf-8").startswith("<!doctype html>"))
        self.assertTrue(read_template("pdf_reader.html").startswith("<!doctype html>"))
        self.assertNotIn("<!doctype html>", Path(iperpaper.__file__).read_text(encoding="utf-8"))

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_packaged_levels_style_compiles_for_external_project(self):
        """Verify that a paper can load the packaged reading-level style."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{iperpaper-levels}
\begin{document}
\begin{leveltwo}{Further detail}
Content.
\end{leveltwo}
\end{document}
""",
                encoding="utf-8",
            )
            pdf = iperpaper.compile_pdf(root)

        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_removed_generic_field_is_rejected(self):
        """Verify that removed generic field is rejected."""
        data = self.fixture_annotations()
        data["annotations"][0]["generic"] = "obsolete field"
        with self.assertRaisesRegex(ValueError, "unexpected keys.*generic"):
            iperpaper.validate_annotation_metadata(data)

    def test_figure_preview_metadata_drives_scaled_tooltip(self):
        """Verify that figure preview metadata drives scaled tooltip."""
        data = {
            "title": "x",
            "background": {},
            "annotations": [
                {
                    "id": "figref_auto_plot",
                    "kind": "reference",
                    "label": "Figure 1",
                    "short": "Figure 1: A useful plot.",
                    "details": "Generated figure reference.",
                    "background": [],
                    "figure_preview": {
                        "src": "data:image/png;base64,AA==",
                        "width_pt": 200,
                        "height_pt": 100,
                        "scale": 0.8,
                    },
                }
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        output = iperpaper.build_html(b"%PDF", data, [], [], data["annotations"])
        self.assertIn("a.figure_preview.width_pt*a.figure_preview.scale", output)
        self.assertIn("figure-tooltip-image", output)
        self.assertIn("label.textContent=a.label", output)
        self.assertIn("id.startsWith('figref_')", output)
        self.assertIn("id.startsWith('tabref_')", output)

    def test_extract_figures_uses_main_caption_before_label(self):
        """Verify that extract figures uses main caption before label."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\begin{figure}
\caption{Panel caption}
\caption{Main caption with \textbf{emphasis} and $x_t$.}
\label{fig:plot}
\end{figure}
""",
                encoding="utf-8",
            )
            figures = iperpaper._extract_figures(root)

        self.assertEqual(figures["fig:plot"]["caption"], "Main caption with emphasis and $x_t$.")

    def test_extract_tables_keeps_caption_and_tabular_source(self):
        """Verify that extract tables keeps caption and tabular source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\begin{table}
\caption{Results with \textbf{strong} performance.}
\label{tab:results}
\begin{tabular}{lr}
Method & Score \\
Alpha & 91 \\
\end{tabular}
\end{table}
""",
                encoding="utf-8",
            )
            tables = iperpaper._extract_tables(root)

        self.assertEqual(tables["tab:results"]["caption"], "Results with strong performance.")
        self.assertIn("Method & Score", tables["tab:results"]["tabular"])

    def test_extract_tables_excludes_caption_below_custom_tabular(self):
        """Verify that extract tables excludes caption below custom tabular."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\begin{table}
\centering
\begin{mytabular}{colspec={lr}}
Method & Score \\
Alpha & 91 \\
\end{mytabular}
\caption{Scores for the compared methods.}
\label{tab:results}
\end{table}
""",
                encoding="utf-8",
            )
            tables = iperpaper._extract_tables(root)

        self.assertIn("Method & Score", tables["tab:results"]["tabular"])
        self.assertNotIn("Scores for the compared methods", tables["tab:results"]["tabular"])

    def test_background_only_annotation_falls_back_to_background_text(self):
        """Verify that background only annotation falls back to background text."""
        data = {
            "title": "x",
            "background": {
                "Exp": {
                    "short": "Exponential short.",
                    "details": "Exponential details.",
                }
            },
            "annotations": [
                {
                    "id": "exp",
                    "kind": "concept",
                    "label": "Exp",
                    "short": "",
                    "details": "",
                    "background": ["Exp"],
                }
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)
        self.assertEqual(rendered[0]["short_html"], "Exponential short.")
        self.assertEqual(rendered[0]["details_html"], "Exponential details.")
        self.assertTrue(rendered[0]["background_only"])
        self.assertEqual([block["key"] for block in rendered[0]["background_html"]], ["Exp"])

    def test_all_empty_short_details_background_is_rejected(self):
        """Verify that metadata with empty short, details, and background is rejected."""
        data = {
            "title": "x",
            "background": {},
            "annotations": [
                {
                    "id": "empty",
                    "kind": "concept",
                    "label": "empty",
                    "short": "",
                    "details": "",
                    "background": [],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "empty short, details, and background"):
            iperpaper.validate_annotation_metadata(data)

    def test_own_text_keeps_background_block(self):
        """Verify that own text keeps background block."""
        data = {
            "title": "x",
            "background": {
                "Exp": {
                    "short": "Exponential short.",
                    "details": "Exponential details.",
                }
            },
            "annotations": [
                {
                    "id": "race",
                    "kind": "symbol",
                    "label": "X_i",
                    "short": "$X_i$ is a waiting time.",
                    "details": "It is exponential.",
                    "background": ["Exp"],
                }
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)
        self.assertIn("waiting time", rendered[0]["short_html"])
        self.assertNotIn("Exponential short.", rendered[0]["short_html"])
        self.assertEqual(len(rendered[0]["background_html"]), 1)
        self.assertEqual(rendered[0]["background_html"][0]["key"], "Exp")
        self.assertIn("Exponential short.", rendered[0]["background_html"][0]["short_html"])

    def test_background_link_is_rendered_in_background_block(self):
        """Verify that background link is rendered in background block."""
        data = {
            "title": "x",
            "background": {
                "Exp": {
                    "short": "Exponential short.",
                    "details": "Exponential details.",
                    "link": "https://en.wikipedia.org/wiki/Exponential_distribution",
                }
            },
            "annotations": [
                {
                    "id": "race",
                    "kind": "symbol",
                    "label": "X_i",
                    "short": "$X_i$ is a waiting time.",
                    "details": "It is exponential.",
                    "background": ["Exp"],
                }
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)
        self.assertEqual(
            rendered[0]["background_html"][0]["link"],
            "https://en.wikipedia.org/wiki/Exponential_distribution",
        )
        out = iperpaper.build_html(b"%PDF", data, [], [], rendered)
        self.assertIn("bg.link", out)
        self.assertNotIn("Generally:", out)

    def test_invalid_background_link_is_rejected(self):
        """Verify that invalid background link is rejected."""
        data = {
            "title": "x",
            "background": {"Exp": {"short": "s", "details": "d", "link": ""}},
            "annotations": [],
        }
        with self.assertRaisesRegex(ValueError, "link"):
            iperpaper.validate_annotation_metadata(data)

    def test_invalid_background_label_is_rejected(self):
        """Verify that invalid background label is rejected."""
        data = {
            "title": "x",
            "background": {"Exp": {"short": "s", "details": "d", "label": ""}},
            "annotations": [],
        }
        with self.assertRaisesRegex(ValueError, "label"):
            iperpaper.validate_annotation_metadata(data)

    def test_background_only_annotation_is_flagged(self):
        """Verify that background only annotation is flagged."""
        data = {
            "title": "x",
            "background": {
                "Gamma": {
                    "short": "Gamma distribution.",
                    "details": "Continuous, on $x\\ge0$.",
                    "link": "https://en.wikipedia.org/wiki/Gamma_distribution",
                }
            },
            "annotations": [
                {
                    "id": "gamma_example",
                    "kind": "notation",
                    "label": "Gam(100,1)",
                    "short": "",
                    "details": "",
                    "background": ["Gamma"],
                },
                {
                    "id": "own_text",
                    "kind": "symbol",
                    "label": "X",
                    "short": "$X$ is Gamma.",
                    "details": "With shape 100.",
                    "background": ["Gamma"],
                },
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)
        self.assertTrue(rendered[0]["background_only"])
        self.assertFalse(rendered[1]["background_only"])
        out = iperpaper.build_html(b"%PDF", data, [], [], rendered)
        self.assertIn("a.background_only", out)

    def test_nested_background_entries_are_shown(self):
        """Verify that nested background entries are shown."""
        data = {
            "title": "x",
            "background": {
                "Gamma": {
                    "short": "Gamma distribution.",
                    "details": "Its density uses $\\Gamma(k)$, the Gamma function.",
                    "background": ["GammaFunction"],
                },
                "GammaFunction": {
                    "label": "Gamma function",
                    "short": "The Gamma function generalizes the factorial.",
                    "details": "$\\Gamma(k)=(k-1)!$ for positive integers $k$.",
                },
            },
            "annotations": [
                {
                    "id": "gamma_null",
                    "kind": "equation",
                    "label": "S_T",
                    "short": "$S_T$ is Gamma distributed.",
                    "details": "Sum of exponentials.",
                    "background": ["Gamma"],
                }
            ],
        }
        iperpaper.validate_annotation_metadata(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)
        keys = [block["key"] for block in rendered[0]["background_html"]]
        self.assertEqual(keys, ["Gamma", "GammaFunction"])
        labels = [block["label"] for block in rendered[0]["background_html"]]
        self.assertEqual(labels, ["Gamma", "Gamma function"])
        out = iperpaper.build_html(b"%PDF", data, [], [], rendered)
        self.assertIn('"label": "Gamma function"', out)

    def test_self_referencing_background_is_rejected(self):
        """Verify that self referencing background is rejected."""
        data = {
            "title": "x",
            "background": {"A": {"short": "s", "details": "d", "background": ["A"]}},
            "annotations": [],
        }
        with self.assertRaisesRegex(ValueError, "references itself"):
            iperpaper.validate_annotation_metadata(data)

    def test_bibliography_entries_include_explicit_source_bbl(self):
        """Verify that bibliography entries include explicit source bbl."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            (root / "main.bbl").write_text(
                r"""\begin{thebibliography}{9}
\bibitem[Silver et~al.(2016)Silver]{silver2016alphago}
David Silver. Mastering the game of go.
\end{thebibliography}
""",
                encoding="utf-8",
            )

            entries = iperpaper._extract_bibliography_entries(root, [root / "main.bbl"])

        self.assertIn("silver2016alphago", entries)
        self.assertIn("David Silver", entries["silver2016alphago"]["text"])

    def test_bibliography_entries_do_not_infer_title_from_emphasis(self):
        """Verify that venue emphasis is not stored as a paper title."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                "\\documentclass{article}\\begin{document}x\\end{document}",
                encoding="utf-8",
            )
            (root / "main.bbl").write_text(
                r"""\begin{thebibliography}{9}
\bibitem{bellemare2017c51} Marc G. Bellemare et al.
\newblock A distributional perspective on reinforcement learning.
\newblock In \emph{International Conference on Machine Learning}, pages 449--458.
\end{thebibliography}
""",
                encoding="utf-8",
            )

            entries = iperpaper._extract_bibliography_entries(root, [root / "main.bbl"])

        self.assertNotIn("paper_title", entries["bellemare2017c51"])
        self.assertIn("International Conference on Machine Learning", entries["bellemare2017c51"]["text"])

    def test_bibliography_entries_use_referenced_bibtex_metadata(self):
        """Verify that explicit BibTeX fields provide trusted citation metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}\bibliography{references}\end{document}",
                encoding="utf-8",
            )
            (root / "main.bbl").write_text(
                r"""\begin{thebibliography}{9}
\bibitem{paper} R{\'e}mi Munos. A useful result. 2026.
\end{thebibliography}
""",
                encoding="utf-8",
            )
            (root / "references.bib").write_text(
                r"""@article{paper,
  title = {{A Useful {Result}}},
  author = {Munos, R{\'e}mi and {OpenAI}},
  journal = {arXiv preprint arXiv:2601.01234},
  doi = {10.1000/example},
  year = {2026}
}
""",
                encoding="utf-8",
            )
            (root / "unrelated.bib").write_text(
                "@article{paper, title={Wrong Unrelated Title}, author={Wrong, Author}}",
                encoding="utf-8",
            )

            entries = iperpaper._extract_bibliography_entries(root, [root / "main.bbl"])

        entry = entries["paper"]
        self.assertEqual(entry["paper_title"], "A Useful Result")
        self.assertEqual(entry["authors"], ["Rémi Munos", "OpenAI"])
        self.assertTrue(entry["_paper_title_verified"])
        self.assertEqual(entry["_paper_title_source"], "bibtex")
        self.assertIn("arXiv:2601.01234", entry["_lookup_source"])
        self.assertEqual(entry["_doi"], "10.1000/example")

    def test_unverified_citation_cache_title_is_discarded(self):
        """Verify that an unverified cached title cannot become paper metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "paper.citations.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 4,
                        "citations": [
                            {
                                "citation_key": "bellemare2017c51",
                                "index": 28,
                                "paper_title": "International Conference on Machine Learning",
                                "paper_title_verified": False,
                                "authors": [],
                                "links": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            cache = iperpaper._load_citation_cache(cache_path)

        self.assertEqual(cache["bellemare2017c51"]["paper_title"], "")

    def test_unverified_cache_does_not_erase_bibtex_metadata(self):
        """Verify that unverified cache data cannot erase trusted BibTeX fields."""
        entry = {
            "paper_title": "Trusted BibTeX Title",
            "authors": ["Ada Author"],
            "_paper_title_verified": True,
            "_paper_title_source": "bibtex",
        }

        iperpaper._apply_citation_cache(
            entry,
            {
                "paper_title": "",
                "paper_title_verified": False,
                "authors": [],
                "links": [],
            },
        )

        self.assertEqual(entry["paper_title"], "Trusted BibTeX Title")
        self.assertEqual(entry["authors"], ["Ada Author"])
        self.assertTrue(entry["_paper_title_verified"])
        self.assertEqual(entry["_paper_title_source"], "bibtex")

    def test_legacy_citation_cache_without_citation_key_is_not_reused(self):
        """Verify that index-only cache records cannot be applied to another paper."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "paper.citations.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "citations": [
                            {
                                "index": 1,
                                "paper_title": "Potentially Stale Title",
                                "paper_title_verified": True,
                                "authors": [],
                                "links": ["https://example.org/stale.pdf"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            cache = iperpaper._load_citation_cache(cache_path)

        self.assertEqual(cache, {})

    def test_bibliography_enrichment_uses_explicit_url_without_lookup(self):
        """Verify that an explicit bibliography URL is used without a remote lookup."""
        entry = {
            "text": "A presentation.",
            "source": r"A presentation. \url{https://example.org/slides.pdf}",
        }
        with mock.patch("bib_utils.crossref_pdf_url") as lookup:
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://example.org/slides.pdf")
        lookup.assert_not_called()

    def test_bibliography_refresh_preserves_cached_pdf_over_explicit_landing_page(self):
        """Verify that refresh fallback keeps a cached PDF ahead of a landing page."""
        entry = {
            "text": "Ada Lovelace. A Reliable Paper Title for Testing.",
            "source": r"\url{https://repository.example.org/paper/}",
            "links": [
                "https://repository.example.org/paper.pdf",
                "https://repository.example.org/paper/",
            ],
            "external_url": "https://repository.example.org/paper.pdf",
        }
        with (
            mock.patch("bib_utils._crossref_work", return_value=None),
            mock.patch("bib_utils._openalex_works", return_value=iter(())),
            mock.patch("bib_utils._semantic_scholar_works", return_value=iter(())),
        ):
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://repository.example.org/paper.pdf")
        self.assertEqual(
            entry["links"],
            [
                "https://repository.example.org/paper.pdf",
                "https://repository.example.org/paper/",
            ],
        )

    def test_bibliography_enrichment_discovers_verified_pdf_from_landing_page(self):
        """Verify that an empty cache can discover a direct PDF beside a landing page."""
        entry = {
            "text": "Jiayi Fu et al. GumbelSoft.",
            "source": r"\url{https://aclanthology.org/2024.acl-long.315/}",
        }
        with mock.patch("bib_utils.remote_url_is_pdf", return_value=True) as verify_pdf:
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(
            entry["external_url"],
            "https://aclanthology.org/2024.acl-long.315.pdf",
        )
        self.assertEqual(
            entry["links"],
            [
                "https://aclanthology.org/2024.acl-long.315.pdf",
                "https://aclanthology.org/2024.acl-long.315/",
            ],
        )
        verify_pdf.assert_called_once_with("https://aclanthology.org/2024.acl-long.315.pdf")

    def test_bibliography_enrichment_uses_reliably_matched_open_pdf(self):
        """Verify that a high-confidence Crossref result uses OpenAlex's PDF URL."""
        entry = {
            "text": "Ada Lovelace. A Reliable Paper Title for Testing.",
            "source": r"Ada Lovelace. \emph{A Reliable Paper Title for Testing}.",
        }
        crossref = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1000/example",
                        "title": ["A Reliable Paper Title for Testing"],
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "link": [],
                    }
                ]
            }
        }
        openalex = {
            "title": "A Reliable Paper Title for Testing",
            "authorships": [
                {"author": {"display_name": "Ada Lovelace"}},
            ],
            "open_access": {"oa_status": "green"},
            "best_oa_location": {
                "is_oa": True,
                "pdf_url": "https://example.org/paper.pdf",
            },
        }
        with mock.patch("bib_utils.load_remote_json", side_effect=[crossref, openalex]):
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://example.org/paper.pdf")
        self.assertEqual(entry["authors"], ["Ada Lovelace"])

    def test_openalex_bronze_pdf_is_not_used(self):
        """Verify that an OpenAlex bronze PDF is not used as a citation target."""
        openalex = {
            "open_access": {"oa_status": "bronze"},
            "best_oa_location": {
                "is_oa": True,
                "pdf_url": "https://publisher.example/paper.pdf",
            },
        }
        with mock.patch("bib_utils.load_remote_json", return_value=openalex):
            pdf_url = bib_utils._openalex_pdf_url("10.1000/example")

        self.assertIsNone(pdf_url)

    def test_openalex_title_search_uses_title_and_author_match(self):
        """Verify that OpenAlex can resolve a paper without a Crossref DOI."""
        entry = {
            "text": "Marc Bellemare et al. A distributional perspective on reinforcement learning.",
            "source": "A distributional perspective on reinforcement learning.",
            "paper_title": "A distributional perspective on reinforcement learning",
            "authors": ["Marc G Bellemare", "Will Dabney", "Rémi Munos"],
            "_paper_title_verified": True,
            "_paper_title_source": "bibtex",
        }
        crossref = {"message": {"items": []}}
        openalex = {
            "results": [
                {
                    "doi": "https://doi.org/10.48550/arxiv.1707.06887",
                    "title": "A Distributional Perspective on Reinforcement Learning",
                    "authorships": [
                        {"author": {"display_name": "Marc G. Bellemare"}},
                        {"author": {"display_name": "Will Dabney"}},
                        {"author": {"display_name": "Rémi Munos"}},
                    ],
                    "open_access": {"oa_status": "green"},
                    "best_oa_location": {
                        "is_oa": True,
                        "pdf_url": "https://arxiv.org/pdf/1707.06887",
                    },
                }
            ]
        }
        with mock.patch("bib_utils.load_remote_json", side_effect=[crossref, openalex]) as load_json:
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://arxiv.org/pdf/1707.06887")
        self.assertEqual(entry["_paper_title_source"], "openalex")
        self.assertIn("query.author=", load_json.call_args_list[0].args[0])

    def test_openalex_title_search_rejects_wrong_authors(self):
        """Verify that an exact title alone cannot override conflicting authors."""
        work = {
            "results": [
                {
                    "title": "A Reliable Paper Title for Testing",
                    "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                    "open_access": {"oa_status": "green"},
                    "best_oa_location": {
                        "is_oa": True,
                        "pdf_url": "https://example.org/wrong.pdf",
                    },
                }
            ]
        }
        with mock.patch("bib_utils.load_remote_json", return_value=work):
            result = bib_utils._openalex_work(
                "A Reliable Paper Title for Testing",
                ["Ada Lovelace"],
            )

        self.assertIsNone(result)

    def test_openalex_title_search_continues_after_closed_match(self):
        """Verify that a later open duplicate is used after a closed match."""
        entry = {
            "text": "Chelsea Finn and Sergey Levine. Deep visual foresight for planning robot motion.",
            "source": "Deep visual foresight for planning robot motion.",
            "paper_title": "Deep visual foresight for planning robot motion",
            "authors": ["Chelsea Finn", "Sergey Levine"],
            "_paper_title_verified": True,
            "_paper_title_source": "bibtex",
        }
        crossref = {"message": {"items": []}}
        openalex = {
            "results": [
                {
                    "id": "https://openalex.org/W2528489519",
                    "doi": "https://doi.org/10.1109/icra.2017.7989324",
                    "title": "Deep visual foresight for planning robot motion",
                    "authorships": [
                        {"author": {"display_name": "Chelsea Finn"}},
                        {"author": {"display_name": "Sergey Levine"}},
                    ],
                    "open_access": {"oa_status": "closed"},
                    "best_oa_location": None,
                    "locations": [],
                },
                {
                    "id": "https://openalex.org/W2953317238",
                    "doi": "https://doi.org/10.48550/arxiv.1610.00696",
                    "title": "Deep Visual Foresight for Planning Robot Motion",
                    "authorships": [
                        {"author": {"display_name": "Chelsea Finn"}},
                        {"author": {"display_name": "Sergey Levine"}},
                    ],
                    "open_access": {"oa_status": "green"},
                    "best_oa_location": {
                        "is_oa": True,
                        "pdf_url": "https://arxiv.org/pdf/1610.00696",
                    },
                },
            ]
        }
        with mock.patch("bib_utils.load_remote_json", side_effect=[crossref, openalex]):
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://arxiv.org/pdf/1610.00696")
        self.assertEqual(entry["_paper_title_source"], "openalex")

    def test_crossref_pdf_link_requires_pdf_bytes(self):
        """Verify that Crossref HTML landing pages cannot become PDF targets."""
        work = {
            "links": [
                {
                    "URL": "https://publisher.example/download",
                    "content-type": "application/pdf",
                }
            ]
        }
        with mock.patch("bib_utils.remote_url_is_pdf", return_value=False):
            rejected = bib_utils._crossref_pdf_url(work)
        with mock.patch("bib_utils.remote_url_is_pdf", return_value=True):
            accepted = bib_utils._crossref_pdf_url(work)

        self.assertIsNone(rejected)
        self.assertEqual(accepted, "https://publisher.example/download")

    def test_bibliography_enrichment_uses_semantic_scholar_repository_pdf(self):
        """Verify that a repository PDF from Semantic Scholar is used after OpenAlex."""
        entry = {
            "text": "Ada Lovelace. A Reliable Paper Title for Testing.",
            "source": r"Ada Lovelace. \emph{A Reliable Paper Title for Testing}.",
        }
        crossref = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1000/example",
                        "title": ["A Reliable Paper Title for Testing"],
                        "link": [],
                    }
                ]
            }
        }
        openalex = {"best_oa_location": None, "locations": []}
        semantic_scholar = {
            "title": "A Reliable Paper Title for Testing",
            "openAccessPdf": {
                "url": "https://repository.example.org/paper.pdf",
                "status": "GREEN",
            },
        }
        with mock.patch(
            "bib_utils.load_remote_json",
            side_effect=[crossref, openalex, {"results": []}, semantic_scholar],
        ):
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://repository.example.org/paper.pdf")

    def test_bibliography_enrichment_rejects_unreliable_match(self):
        """Verify that a weak bibliographic match does not receive an external URL."""
        entry = {
            "text": "Ada Lovelace. A Reliable Paper Title for Testing.",
            "source": r"Ada Lovelace. \emph{A Reliable Paper Title for Testing}.",
        }
        crossref = {
            "message": {
                "items": [{"DOI": "10.1000/example", "title": ["An Unrelated Publication"], "link": []}]
            }
        }
        with mock.patch("bib_utils.load_remote_json", return_value=crossref) as load_json:
            bib_utils.enrich_bibliography_entry(entry)

        self.assertNotIn("external_url", entry)
        self.assertEqual(load_json.call_count, 1)

    def test_bibliography_enrichment_converts_bare_arxiv_id_to_pdf(self):
        """Verify that arXiv metadata enriches the entry without changing PDF priority."""
        entry = {"text": "An arXiv preprint.", "source": "An arXiv preprint, arXiv:2504.12229."}
        response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A Canonical arXiv Paper Title</title>
    <author><name>Ada Lovelace</name></author>
  </entry>
</feed>
"""
        with mock.patch("bib_utils.load_remote_text", return_value=response) as load_text:
            bib_utils.enrich_bibliography_entry(entry)

        self.assertEqual(entry["external_url"], "https://arxiv.org/pdf/2504.12229")
        self.assertEqual(entry["paper_title"], "A Canonical arXiv Paper Title")
        self.assertEqual(entry["authors"], ["Ada Lovelace"])
        self.assertTrue(entry["_paper_title_verified"])
        load_text.assert_called_once()

    def test_bibliography_entries_ignore_unrelated_project_bbl(self):
        """Verify that bibliography entries ignore unrelated project bbl."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\begin{thebibliography}{9}
\bibitem{shared}Current entry from the paper.
\end{thebibliography}
""",
                encoding="utf-8",
            )
            (root / "old.bbl").write_text(
                r"""\begin{thebibliography}{9}
\bibitem{shared}Stale entry from another build.
\end{thebibliography}
""",
                encoding="utf-8",
            )

            entries = iperpaper._extract_bibliography_entries(root, [])

        self.assertIn("Current entry", entries["shared"]["text"])
        self.assertNotIn("Stale entry", entries["shared"]["text"])

    def test_citation_cache_saves_numeric_index_order(self):
        """Verify that citation cache indexes are saved in numeric order."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "paper.citations.json"
            cache = {
                "ten": {"citation_key": "ten", "index": "10"},
                "two": {"citation_key": "two", "index": "2"},
                "one": {"citation_key": "one", "index": "1"},
                "three": {"citation_key": "three", "index": "3"},
            }
            iperpaper._save_citation_cache(cache_path, cache)
            saved = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual([item["index"] for item in saved["citations"]], ["1", "2", "3", "10"])

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_citation_cache_reuses_metadata_and_regenerates_on_request(self):
        """Verify that cached citation metadata avoids lookup and supports refresh."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage[colorlinks=true]{hyperref}
\begin{document}
See \cite{smith}.
\begin{thebibliography}{9}
\bibitem{smith} Ada Smith. \emph{A Useful Result}. 2026.
\end{thebibliography}
\end{document}
""",
                encoding="utf-8",
            )
            cache_path = root / "paper.citations.json"
            empty = {"title": "Citation cache", "background": {}, "annotations": []}
            first_enrichment = mock.Mock(
                side_effect=lambda entry: entry.update(
                    {
                        "paper_title": "A Useful Result",
                        "_paper_title_verified": True,
                        "authors": ["Ada Smith"],
                        "links": ["https://api.example.org/paper.pdf"],
                        "external_url": "https://api.example.org/paper.pdf",
                    }
                )
            )
            with mock.patch("iperpaper.enrich_bibliography_entry", first_enrichment):
                _, _, _, _ = iperpaper.compile_and_collect_annotations(
                    root,
                    empty,
                    lookup_citation_urls=True,
                    citation_cache_path=cache_path,
                )

            cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache_data["version"], 4)
            self.assertEqual(cache_data["citations"][0]["citation_key"], "smith")
            self.assertEqual(cache_data["citations"][0]["index"], 1)
            self.assertEqual(cache_data["citations"][0]["authors"], ["Ada Smith"])
            cache_data["citations"][0]["index"] = 99
            cache_data["citations"][0]["links"] = ["https://manual.example.org/paper.pdf"]
            cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

            cached_enrichment = mock.Mock()
            with mock.patch("iperpaper.enrich_bibliography_entry", cached_enrichment):
                _, _, _, cached = iperpaper.compile_and_collect_annotations(
                    root,
                    empty,
                    lookup_citation_urls=True,
                    citation_cache_path=cache_path,
                )

            cached_enrichment.assert_not_called()
            reloaded_cache = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded_cache["citations"][0]["index"], 1)
            cached_citation = next(
                annotation
                for annotation in cached["annotations"]
                if annotation["id"].startswith("bibref_auto_")
            )
            self.assertEqual(cached_citation["paper_title"], "A Useful Result")
            self.assertEqual(cached_citation["external_url"], "https://manual.example.org/paper.pdf")
            rendered = iperpaper.render_annotations_for_html(root, cached)
            rendered_citation = next(item for item in rendered if item["id"] == cached_citation["id"])
            self.assertIn("<strong>A Useful Result</strong>", rendered_citation["tooltip_html"])

            refreshed_enrichment = mock.Mock(
                side_effect=lambda entry: entry.update(
                    {
                        "paper_title": "Fresh API Title",
                        "_paper_title_verified": True,
                        "authors": ["Fresh Author"],
                        "links": ["https://fresh.example.org/paper.pdf"],
                        "external_url": "https://fresh.example.org/paper.pdf",
                    }
                )
            )
            with mock.patch("iperpaper.enrich_bibliography_entry", refreshed_enrichment):
                _, _, _, refreshed = iperpaper.compile_and_collect_annotations(
                    root,
                    empty,
                    lookup_citation_urls=True,
                    citation_cache_path=cache_path,
                    regenerate_links=True,
                )

            refreshed_enrichment.assert_called_once()
            refreshed_citation = next(
                annotation
                for annotation in refreshed["annotations"]
                if annotation["id"].startswith("bibref_auto_")
            )
            self.assertEqual(refreshed_citation["paper_title"], "Fresh API Title")
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["citations"][0]["links"], ["https://fresh.example.org/paper.pdf"])

    def test_compiled_bibliography_entry_takes_precedence_over_tex_source(self):
        """Verify that compiled bibliography entry takes precedence over tex source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\begin{thebibliography}{9}
\bibitem{shared}Source entry.
\end{thebibliography}
""",
                encoding="utf-8",
            )
            artifact = root / "compiled.bbl"
            artifact.write_text(
                r"""\begin{thebibliography}{9}
\bibitem{shared}Entry from the current compilation.
\end{thebibliography}
""",
                encoding="utf-8",
            )

            entries = iperpaper._extract_bibliography_entries(root, [artifact])

        self.assertIn("current compilation", entries["shared"]["text"])
        self.assertNotIn("Source entry", entries["shared"]["text"])

    def test_natbib_bibliography_label_uses_rendered_number(self):
        """Verify that natbib bibliography label uses rendered number."""
        with tempfile.TemporaryDirectory() as tmp:
            aux = Path(tmp) / "main.aux"
            aux.write_text(
                r"\bibcite{silver2016alphago}{{1}{2016}{{Silver et~al.}}{{Silver et~al.}}}",
                encoding="utf-8",
            )

            _, bibliography_labels = iperpaper._parse_aux_reference_data([aux])

        self.assertEqual(bibliography_labels["silver2016alphago"], "1")

    def test_figure_aux_label_keeps_number_and_destination(self):
        """Verify that figure aux label keeps number and destination."""
        with tempfile.TemporaryDirectory() as tmp:
            aux = Path(tmp) / "main.aux"
            aux.write_text(
                r"\newlabel{fig:plot}{{3}{7}{A plot}{figure.caption.4}{}}",
                encoding="utf-8",
            )
            figures = iperpaper._parse_aux_figure_reference_data([aux])

        self.assertEqual(
            figures["fig:plot"],
            {"number": "3", "page": "7", "destination": "figure.caption.4"},
        )

    def test_table_aux_label_keeps_number_and_destination(self):
        """Verify that table aux label keeps number and destination."""
        with tempfile.TemporaryDirectory() as tmp:
            aux = Path(tmp) / "main.aux"
            aux.write_text(
                r"\newlabel{tab:results}{{2}{5}{Results}{table.caption.3}{}}",
                encoding="utf-8",
            )
            tables = iperpaper._parse_aux_table_reference_data([aux])

        self.assertEqual(
            tables["tab:results"],
            {"number": "2", "page": "5", "destination": "table.caption.3"},
        )

    @unittest.skipUnless(HAS_LATEX and shutil.which("pdftotext"), "LaTeX and Poppler are required")
    def test_native_table_reference_gets_scaled_preview_and_caption(self):
        """Verify that native table reference gets scaled preview and caption."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage[colorlinks=true]{hyperref}
\begin{document}
See Table~\ref{tab:results}.
\begin{table}[h]
\centering
\begin{tabular}{lr}
Method & Score \\\hline
Alpha & 91 \\
Beta & 87 \\
Gamma & 84 \\
Delta & 81 \\
Epsilon & 78 \\
Zeta & 74 \\
Eta & 70 \\
Theta & 66 \\
\end{tabular}
\caption{Scores for the compared methods.}
\label{tab:results}
\end{table}
\end{document}
""",
                encoding="utf-8",
            )
            empty = {"title": "Table reference", "background": {}, "annotations": []}
            _, targets, _, merged = iperpaper.compile_and_collect_annotations(root, empty)

        table = next(a for a in merged["annotations"] if a["id"].startswith("tabref_auto_"))
        self.assertEqual(table["label"], "Table 1")
        self.assertIn("Scores for the compared methods.", table["short"])
        self.assertEqual(table["figure_preview"]["scale"], iperpaper.FIGURE_TOOLTIP_SCALE)
        self.assertGreater(table["figure_preview"]["width_pt"], 100)
        self.assertGreater(table["figure_preview"]["height_pt"], 80)
        self.assertIn(table["id"], {target["id"] for target in targets})

    def test_pdf_destination_navigation_uses_vertical_coordinate(self):
        """Verify that pdf destination navigation uses vertical coordinate."""
        out = iperpaper.build_html(
            b"pdf",
            {"title": "x", "background": {}, "annotations": []},
            [],
            [{"width": 612.0, "height": 792.0}],
        )
        self.assertIn("window.scrollY+rect.top+y*rect.height-offset", out)
        self.assertNotIn("target.scrollIntoView", out)

    def test_pdf_reader_banner_is_compact_sticky_repository_link(self):
        """Verify that pdf reader banner is compact sticky repository link."""
        out = iperpaper.build_html(
            b"pdf",
            {"title": "x", "background": {}, "annotations": []},
            [],
            [{"width": 612.0, "height": 792.0}],
        )
        self.assertIn("position:sticky; top:0; z-index:30; width:100%; height:var(--ip-header-height)", out)
        self.assertIn(
            "display:flex; align-items:center; justify-content:flex-start; gap:10px; padding:0 11px; background:var(--bg); border:0; border-radius:0",
            out,
        )
        self.assertIn(
            ".brand { color:#3266C7; font-weight:750; letter-spacing:-.02em; text-decoration:none; }",
            out,
        )
        self.assertIn(
            '<header class="ip-header"><a class="brand" href="https://github.com/davidenitti/IperPaper/" target="_blank" rel="noopener noreferrer">IperPaper</a><button id="layout-toggle" class="layout-toggle" type="button" aria-pressed="false" title="Toggle split reading view">Split</button></header>',
            out,
        )
        self.assertIn("offset=(header?.getBoundingClientRect().height||0)+8", out)
        self.assertIn("top:var(--ip-header-height); bottom:0", out)
        self.assertIn("const minTop=(header?.getBoundingClientRect().bottom||0)+pad", out)
        self.assertNotIn("hover to peek", out)

    def test_extra_top_level_key_is_rejected(self):
        """Verify that extra top level key is rejected."""
        data = self.fixture_annotations()
        data["extra"] = True
        with self.assertRaisesRegex(ValueError, "unexpected keys"):
            iperpaper.validate_annotation_metadata(data)

    def test_invalid_annotation_kind_is_rejected(self):
        """Verify that invalid annotation kind is rejected."""
        data = self.fixture_annotations()
        data["annotations"][0]["kind"] = "mystery"
        with self.assertRaisesRegex(ValueError, "invalid kind"):
            iperpaper.validate_annotation_metadata(data)

    def test_main_tex_is_preferred(self):
        """Verify that main tex is preferred."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(r"\documentclass{article}\begin{document}x\end{document}")
            (root / "other.tex").write_text(r"\documentclass{article}\begin{document}y\end{document}")
            _, main = iperpaper.resolve_project(root)
            self.assertEqual(main.name, "main.tex")

    def test_ambiguous_project_requires_main(self):
        """Verify that ambiguous project requires main."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.tex").write_text(r"\documentclass{article}\begin{document}a\end{document}")
            (root / "b.tex").write_text(r"\documentclass{article}\begin{document}b\end{document}")
            with self.assertRaisesRegex(ValueError, "--main"):
                iperpaper.resolve_project(root)

    def test_split_math_segments_supports_inline_and_display_tex(self):
        """Verify that split math segments supports inline and display tex."""
        text = r"Current $a_{t-1}$, model \(p_\phi(z_t)\), and $$\mathbb E[x]$$."
        segments = iperpaper.split_math_segments(text)
        math = [(content, display) for kind, content, display in segments if kind == "math"]
        self.assertEqual(
            math,
            [("a_{t-1}", False), (r"p_\phi(z_t)", False), (r"\mathbb E[x]", True)],
        )

    def test_escaped_dollar_is_not_math(self):
        """Verify that escaped dollar is not math."""
        self.assertEqual(
            iperpaper.split_math_segments(r"cost \$5"),
            [("text", r"cost \$5", False)],
        )

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_math_and_prose_href_targets_compile(self):
        """Verify that math and prose href targets compile."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex = root / "main.tex"
            tex.write_text(
                r"""\documentclass{article}
\usepackage{hyperref}
\pdfstringdefDisableCommands{\def\hyperlink#1#2{#2}}
\begin{document}
\href{iperpaper:term}{concept} and $\href{iperpaper:phi}{\phi}$.
\end{document}""",
                encoding="utf-8",
            )
            pdf = iperpaper.compile_pdf(root)
            targets, pages = iperpaper.extract_pdf_targets(pdf)
        self.assertEqual(len(pages), 1)
        self.assertEqual({t["id"] for t in targets}, {"term", "phi"})
        self.assertTrue(all(0 <= t["x"] <= 1 for t in targets))

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_iperpaper_wrapper_styles_only_annotation_links(self):
        """Verify that iperpaper wrapper styles only annotation links."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
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
\begin{document}
\href{https://example.com}{original} \iperpaper{theta}{$\theta$} \href{https://example.org}{original two}
\end{document}""",
                encoding="utf-8",
            )
            pdf = iperpaper.compile_pdf(root)

        reader = PdfReader(io.BytesIO(pdf))
        page = reader.pages[0]
        borders = {}
        for ref in page["/Annots"]:
            annot = ref.get_object()
            uri = annot.get("/A", {}).get("/URI")
            if uri:
                borders[uri] = list(annot.get("/Border", []))
        self.assertEqual(borders["https://example.com"], [0, 0, 1])
        self.assertEqual(borders["iperpaper:theta"], [0, 0, 0])
        self.assertEqual(borders["https://example.org"], [0, 0, 1])

        content = ContentStream(page.get_contents(), reader)
        rgb_colors = [
            tuple(float(value) for value in operands)
            for operands, operator in content.operations
            if operator == b"rg" and len(operands) == 3
        ]
        expected = (0, 0, 170 / 255)
        self.assertTrue(
            any(
                all(abs(actual - target) < 0.001 for actual, target in zip(color, expected))
                for color in rgb_colors
            )
        )

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_fixture_project_compiles_and_reuses_annotation_id(self):
        """Verify that the fixture project compiles and reuses an annotation ID."""
        pdf, targets, pages = iperpaper.compile_and_validate(
            Path("tests/fixtures/annotated_project"), self.fixture_annotations()
        )
        self.assertGreater(len(pdf), 1000)
        self.assertGreaterEqual(len(pages), 1)
        theta_targets = [t for t in targets if t["id"] == "theta"]
        self.assertGreaterEqual(len(theta_targets), 2)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_automatic_equation_and_citation_links_generate_tooltips(self):
        """Verify that automatic equation and citation links generate tooltips."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{amsmath}
\usepackage[colorlinks=true]{hyperref}
\begin{document}
\begin{equation}
  a+b=c.
  \label{eq:sum}
\end{equation}
See \eqref{eq:sum} and \cite{smith}.
\begin{thebibliography}{9}
\bibitem{smith} Ada Smith. \emph{A Useful Result}. 2026.
\end{thebibliography}
\end{document}
""",
                encoding="utf-8",
            )
            empty = {"title": "Native references", "background": {}, "annotations": []}
            pdf, targets, pages, merged = iperpaper.compile_and_collect_annotations(root, empty)
            rendered = iperpaper.render_annotations_for_html(root, merged)

        self.assertGreater(len(pdf), 1000)
        self.assertEqual(len(pages), 1)
        automatic = merged["annotations"]
        equation = next(a for a in automatic if a["id"].startswith("eqref_auto_"))
        citation = next(a for a in automatic if a["id"].startswith("bibref_auto_"))
        self.assertIn("Equation (1)", equation["short"])
        self.assertIn("a+b=c", equation["short"])
        self.assertEqual(citation["kind"], "reference")
        self.assertNotIn("paper_title", citation)
        self.assertFalse(citation["paper_title_verified"])
        self.assertIn("[1] Ada Smith. A Useful Result. 2026.", citation["short"])
        self.assertEqual({target["id"] for target in targets}, {equation["id"], citation["id"]})
        rendered_citation = next(item for item in rendered if item["id"] == citation["id"])
        self.assertNotIn("<strong>", rendered_citation["tooltip_html"])

    def test_bibliography_title_is_bolded_in_tooltip_html(self):
        """Verify that a bibliography title is bolded in tooltip HTML."""
        data = {
            "title": "x",
            "background": {},
            "annotations": [
                {
                    "id": "bibref_auto_paper",
                    "kind": "reference",
                    "label": "[1]",
                    "short": "[1] Ada Smith. A Useful Result. 2026.",
                    "details": "Generated bibliography reference.",
                    "background": [],
                    "paper_title": "A Useful Result",
                    "paper_title_verified": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)

        self.assertIn("<strong>A Useful Result</strong>", rendered[0]["tooltip_html"])

    def test_bibliography_title_bolding_normalizes_dash_punctuation(self):
        """Verify that equivalent title dash punctuation still matches."""
        data = {
            "title": "x",
            "background": {},
            "annotations": [
                {
                    "id": "bibref_auto_paper",
                    "kind": "reference",
                    "label": "[8]",
                    "short": (
                        "[8] Lu Luo. Efficient Online LLM Watermark Detection via "
                        "Rao\N{EN DASH}Blackwellized E-Processes. 2026."
                    ),
                    "details": "Generated bibliography reference.",
                    "background": [],
                    "paper_title": (
                        "Efficient Online LLM Watermark Detection via "
                        "Rao-Blackwellized E-Processes"
                    ),
                    "paper_title_verified": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)

        self.assertIn(
            "<strong>Efficient Online LLM Watermark Detection via "
            "Rao\N{EN DASH}Blackwellized E-Processes</strong>",
            rendered[0]["tooltip_html"],
        )

    def test_missing_bibliography_title_verification_is_not_bolded(self):
        """Verify that an unverified bibliography title is not bolded."""
        data = {
            "title": "x",
            "background": {},
            "annotations": [
                {
                    "id": "bibref_auto_paper",
                    "kind": "reference",
                    "label": "[1]",
                    "short": "[1] Ada Smith. A Useful Result. 2026.",
                    "details": "Generated bibliography reference.",
                    "background": [],
                    "paper_title": "A Useful Result",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\begin{document}x\end{document}",
                encoding="utf-8",
            )
            rendered = iperpaper.render_annotations_for_html(root, data)

        self.assertNotIn("<strong>", rendered[0]["tooltip_html"])

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_commented_marker_does_not_count(self):
        """Verify that commented marker does not count."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{hyperref}
\begin{document}
% \href{iperpaper:ghost}{not rendered}
visible
\end{document}""",
                encoding="utf-8",
            )
            annotations = {
                "title": "x",
                "background": {},
                "annotations": [
                    {
                        "id": "ghost",
                        "kind": "concept",
                        "label": "ghost",
                        "short": "s",
                        "details": "d",
                        "background": [],
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "no compiled PDF target"):
                iperpaper.compile_and_validate(root, annotations)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_unreachable_tex_marker_does_not_count(self):
        """Verify that unreachable tex marker does not count."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\usepackage{hyperref}\begin{document}visible\end{document}",
                encoding="utf-8",
            )
            (root / "unused.tex").write_text(r"\href{iperpaper:ghost}{not included}")
            annotations = {
                "title": "x",
                "background": {},
                "annotations": [
                    {
                        "id": "ghost",
                        "kind": "concept",
                        "label": "ghost",
                        "short": "s",
                        "details": "d",
                        "background": [],
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "no compiled PDF target"):
                iperpaper.compile_and_validate(root, annotations)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_unknown_compiled_target_is_rejected(self):
        """Verify that unknown compiled target is rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"\documentclass{article}\usepackage{hyperref}\begin{document}\href{iperpaper:unknown}{x}\end{document}",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown annotation ids"):
                iperpaper.compile_and_validate(root, {"title": "x", "background": {}, "annotations": []})

    @unittest.skipUnless(HAS_MATH_RENDER, "latexmk, pdfcrop and pdftocairo are required")
    def test_annotation_math_uses_paper_preamble_and_becomes_svg(self):
        """Verify that annotation math uses paper preamble and becomes svg."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{amsmath}
\newcommand{\state}{\mathbf{s}}
\begin{document}x\end{document}""",
                encoding="utf-8",
            )
            annotations = {
                "title": "x",
                "background": {},
                "annotations": [
                    {
                        "id": "state",
                        "kind": "symbol",
                        "label": r"$\state_t$",
                        "short": r"Current state $\state_t$.",
                        "details": r"It follows $p_\phi(\state_t\mid \state_{t-1})$.",
                        "background": [],
                    }
                ],
            }
            rendered = iperpaper.render_annotations_for_html(root, annotations)
        self.assertIn("data:image/svg+xml;base64,", rendered[0]["short_html"])
        self.assertIn("data:image/svg+xml;base64,", rendered[0]["label_html"])
        self.assertNotIn("$\\state_t$", rendered[0]["short_html"])
        self.assertIn("Current state", rendered[0]["short_html"])
        label_src = re.search(r'src="([^"]+)"', rendered[0]["label_html"]).group(1)
        short_src = re.search(r'src="([^"]+)"', rendered[0]["short_html"]).group(1)
        self.assertNotEqual(label_src, short_src)

    def test_build_html_uses_paper_like_tooltip_style(self):
        """Verify that build html uses paper like tooltip style."""
        out = iperpaper.build_html(b"%PDF", {"title": "x", "background": {}, "annotations": []}, [], [])
        self.assertIn("background:#fff; color:var(--ink)", out)
        self.assertIn("font-size:15px; line-height:1.45", out)
        self.assertIn("height:auto", out)
        self.assertIn("zoom:1.1", out)
        self.assertIn(".annotation-title { color:var(--ink); font-size:15px; font-weight:700", out)
        self.assertIn("title.innerHTML=a.label_html", out)
        self.assertNotIn("k.textContent=a.kind", out)
        self.assertNotIn("height:1.22em", out)
        self.assertNotIn("filter:brightness(0) invert(1)", out)

    def test_svg_dimensions_are_preserved_as_pdf_points(self):
        """Verify that svg dimensions are preserved as pdf points."""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="131" height="19" '
            'viewBox="0 0 131 19"><path width="5"/></svg>'
        )
        converted = iperpaper._svg_dimensions_as_points(svg)
        self.assertIn('width="131pt"', converted)
        self.assertIn('height="19pt"', converted)
        self.assertIn('<path width="5"/>', converted)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_level_section_markers_create_collapsible_ranges(self):
        """Verify that level section markers create collapsible ranges."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{hyperref}
\begin{document}
Level one text.
\hypertarget{iperpaper-level-start:2:two-1}{}\subsection{\texorpdfstring{\protect\hyperlink{iperpaper-level-start:2:two-1}{Level two title}}{Level two title}}
\hypertarget{iperpaper-level-content:2:two-1}{}Level two body.
\par\hypertarget{iperpaper-level-end:2:two-1}{}
\end{document}""",
                encoding="utf-8",
            )
            pdf = iperpaper.compile_pdf(root)
            sections = iperpaper.extract_pdf_level_sections(pdf)

        self.assertEqual([(s["id"], s["level"]) for s in sections], [("two-1", 2)])
        for section in sections:
            self.assertIn("title", section)
            self.assertLessEqual(
                (section["start"]["page"], section["start"]["y"]),
                (section["content"]["page"], section["content"]["y"]),
            )
            self.assertLessEqual(
                (section["content"]["page"], section["content"]["y"]),
                (section["end"]["page"], section["end"]["y"]),
            )

        out = iperpaper.build_html(
            pdf,
            {"title": "x", "background": {}, "annotations": []},
            [],
            [{"width": 612.0, "height": 792.0}],
            level_sections=sections,
        )
        self.assertIn("const LEVEL_SECTIONS=", out)
        self.assertIn("level-accordion level-2", out)
        self.assertIn(r'content:"\25b6"', out)
        self.assertIn(r'content:"\25bc"', out)
        self.assertIn('.level-accordion[open]::before { content:"";', out)
        self.assertIn("top:0; bottom:0; width:4px; background:var(--level-color)", out)
        self.assertNotIn("box-shadow:inset 3px 0", out)
        self.assertNotIn("Click to expand", out)
        self.assertNotIn("level-plus", out)
        self.assertIn("event.preventDefault();details.open=!details.open", out)
        self.assertIn("destination.startsWith('iperpaper-level-')", out)
        self.assertIn("bottomTrim=.002", out)
        self.assertIn("margin:0 auto; background:white", out)
        self.assertIn(".page-slice.page-end { margin-bottom:0; }", out)
        self.assertIn('"id":"two-1"', out)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_nested_level_sections_are_rejected(self):
        """Verify that nested level sections are rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                r"""\documentclass{article}
\usepackage{hyperref}
\begin{document}
\hypertarget{iperpaper-level-start:2:outer}{}\subsection{Outer}
\hypertarget{iperpaper-level-content:2:outer}{}Outer body.
\hypertarget{iperpaper-level-start:2:inner}{}\subsection{Inner}
\hypertarget{iperpaper-level-content:2:inner}{}Inner body.
\par\hypertarget{iperpaper-level-end:2:inner}{}
Outer body continued.
\par\hypertarget{iperpaper-level-end:2:outer}{}
\end{document}""",
                encoding="utf-8",
            )
            pdf = iperpaper.compile_pdf(root)

        with self.assertRaisesRegex(
            ValueError,
            "Level section 'inner' overlaps or is nested inside level section 'outer'",
        ):
            iperpaper.extract_pdf_level_sections(pdf)

    @unittest.skipUnless(HAS_LATEX, "latexmk is required")
    def test_build_html_uses_pdfjs_text_annotation_and_iperpaper_layers(self):
        """Verify that build html uses pdfjs text annotation and iperpaper layers."""
        pdf, targets, pages = iperpaper.compile_and_validate(
            Path("tests/fixtures/annotated_project"), self.fixture_annotations()
        )
        out = iperpaper.build_html(pdf, self.fixture_annotations(), targets, pages)
        self.assertIn("annotation-layer", out)
        self.assertIn("page-canvas", out)
        self.assertIn("PDF_BASE64", out)
        self.assertIn(iperpaper.PDFJS_MODULE_URL, out)
        self.assertIn("devicePixelRatio", out)
        self.assertIn("IntersectionObserver", out)
        self.assertIn("new pdfjsLib.TextLayer", out)
        self.assertIn("new pdfjsLib.AnnotationLayer", out)
        self.assertIn("page.getAnnotations", out)
        self.assertIn("id.startsWith('eqref_')", out)
        self.assertIn("id.startsWith('bibref_')", out)
        self.assertIn("document.elementsFromPoint", out)
        self.assertIn("--accent:#0000AA", out)
        self.assertIn("background:rgba(0,0,170,.055)", out)
        self.assertIn(
            ".ip-target:hover { background:rgba(0,0,170,.055); outline:none; box-shadow:none; }", out
        )
        self.assertIn(
            ".ip-target:focus-visible { background:rgba(0,0,170,.055); outline:1px solid rgba(0,0,170,.35)",
            out,
        )
        self.assertNotIn("cursor:help", out)
        self.assertNotIn("PAGE_IMAGES", out)
        self.assertNotIn("data:image/png;base64", out)

    @unittest.skipUnless(HAS_MATH_RENDER, "latexmk, pdfcrop and pdftocairo are required")
    def test_write_outputs_embeds_latex_rendered_annotation_math(self):
        """Verify that write outputs embeds latex rendered annotation math."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "fixture.html"
            pdf_path = root / "fixture.pdf"
            pages, targets = iperpaper.write_outputs(
                Path("tests/fixtures/annotated_project"),
                self.fixture_annotations(),
                html_path,
                pdf_path,
            )
            self.assertTrue(html_path.is_file())
            self.assertTrue(pdf_path.is_file())
            self.assertGreater(pages, 0)
            self.assertGreater(targets, 0)
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("pdfjs-dist@", html_text)
            self.assertIn("data:image/svg+xml;base64,", html_text)
            self.assertIn("short_html", html_text)
            self.assertNotIn("katex", html_text.lower())
            self.assertNotIn("mathjax", html_text.lower())

    def test_write_outputs_can_skip_pdf_artifact(self):
        """Verify that write outputs can skip the standalone PDF artifact."""
        annotations = self.fixture_annotations()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "fixture.html"
            pdf_path = root / "fixture.pdf"
            with (
                mock.patch.object(
                    iperpaper,
                    "compile_and_collect_annotations",
                    return_value=(b"pdf", [], [], annotations),
                ),
                mock.patch.object(iperpaper, "extract_pdf_level_sections", return_value=[]),
                mock.patch.object(iperpaper, "extract_pdf_text_margins", return_value={}),
                mock.patch.object(iperpaper, "render_annotations_for_html", return_value=[]),
                mock.patch.object(iperpaper, "build_html", return_value="reader"),
            ):
                pages, targets = iperpaper.write_outputs(
                    Path("unused"), annotations, html_path, pdf_output=None
                )

            self.assertTrue(html_path.is_file())
            self.assertFalse(pdf_path.exists())
            self.assertEqual((pages, targets), (0, 0))

    def test_default_output_paths(self):
        """Verify the default output paths."""
        html_path = iperpaper.default_output_path(Path("papers/paper/annotated/paper.annotations.json"))
        self.assertEqual(html_path, Path("papers/paper/paper.html"))
        self.assertEqual(iperpaper.default_pdf_path(html_path), Path("papers/paper/paper.pdf"))
        self.assertEqual(
            iperpaper.default_citation_cache_path(Path("papers/paper/annotated/paper.annotations.json")),
            Path("papers/paper/annotated/paper.citations.json"),
        )
        self.assertEqual(
            iperpaper.default_output_path(Path("custom/paper.annotations.json")),
            Path("custom/paper.html"),
        )

    def test_annotation_free_defaults_use_canonical_paper_name(self):
        """Verify annotation-free canonical projects retain paper artifact names."""
        with tempfile.TemporaryDirectory() as tmp:
            annotated = Path(tmp) / "papers" / "example-paper" / "annotated"
            annotated.mkdir(parents=True)
            (annotated / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )

            metadata_path = iperpaper.default_metadata_path(annotated, "main.tex")
            metadata = iperpaper.empty_annotation_metadata(annotated, "main.tex")

            self.assertEqual(metadata_path, annotated / "example-paper.annotations.json")
            self.assertEqual(
                metadata,
                {"title": "example-paper", "annotations": [], "background": {}},
            )
            self.assertFalse(metadata_path.exists())
            self.assertEqual(
                iperpaper.default_output_path(metadata_path),
                annotated.parent / "example-paper.html",
            )

    def test_annotation_free_metadata_uses_tex_title(self):
        """Verify annotation-free metadata prefers the main TeX title."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "main.tex"
            source.write_text(
                "\\documentclass{article}\n"
                "% \\title{Commented title}\n"
                "\\title{\\vspace*{-2ex}\\bfseries A \\textit{Readable} Paper \\\\ Title}\n"
                "\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )

            metadata = iperpaper.empty_annotation_metadata(source)

            self.assertEqual(metadata["title"], "A Readable Paper Title")

    def test_annotation_free_metadata_prefers_pdf_title(self):
        """Verify annotation-free metadata prefers an explicit PDF title."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "main.tex"
            source.write_text(
                "\\documentclass{article}\n"
                "\\usepackage{hyperref}\n"
                "\\hypersetup{pdftitle={The Deterministic PDF Title}}\n"
                "\\title{A Different Typeset Title}\n"
                "\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )

            metadata = iperpaper.empty_annotation_metadata(source)

            self.assertEqual(metadata["title"], "The Deterministic PDF Title")

    def test_annotation_free_metadata_falls_back_without_tex_title(self):
        """Verify annotation-free metadata falls back to the source stem."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "fallback-name.tex"
            source.write_text(
                "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )

            metadata = iperpaper.empty_annotation_metadata(source)

            self.assertEqual(metadata["title"], "fallback-name")

    def test_build_cli_allows_omitting_annotations(self):
        """Verify the build CLI supplies empty in-memory annotation metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "paper.tex"
            source.write_text(
                "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )
            argv = ["iperpaper", "build", str(source), "--no-citation-link-lookup"]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(iperpaper, "write_outputs", return_value=(1, 0)) as write,
                mock.patch("builtins.print"),
            ):
                iperpaper.main()

            call = write.call_args
            self.assertEqual(
                call.args[1],
                {"title": "paper", "annotations": [], "background": {}},
            )
            self.assertEqual(call.args[2], source.with_suffix(".html"))
            self.assertFalse(call.args[7])
            self.assertEqual(call.args[8], source.with_suffix(".citations.json"))
            self.assertFalse(source.with_suffix(".annotations.json").exists())

    def test_validate_cli_allows_omitting_annotations(self):
        """Verify the validate CLI supplies empty in-memory annotation metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "paper.tex"
            source.write_text(
                "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
                encoding="utf-8",
            )
            argv = ["iperpaper", "validate", str(source)]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    iperpaper,
                    "compile_and_validate",
                    return_value=(b"pdf", [], [{"width": 1, "height": 1}]),
                ) as validate,
                mock.patch("builtins.print"),
            ):
                iperpaper.main()

            self.assertEqual(
                validate.call_args.args[1],
                {"title": "paper", "annotations": [], "background": {}},
            )
            self.assertFalse(source.with_suffix(".annotations.json").exists())

    def test_load_annotations_reports_invalid_json(self):
        """Verify that load annotations reports invalid json."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.annotations.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                iperpaper.load_annotations(path)

    def test_require_latexmk_error_is_actionable(self):
        """Verify that require latexmk error is actionable."""
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "latexmk"):
                iperpaper.require_latexmk()

    def test_require_pdftocairo_error_is_actionable(self):
        """Verify that require pdftocairo error is actionable."""
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pdftocairo"):
                iperpaper.require_pdftocairo()


if __name__ == "__main__":
    unittest.main()
