"""Bibliography URL extraction and conservative direct-PDF enrichment."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

CROSSREF_WORKS_URL = "https://api.crossref.org/works?rows=5&select=DOI,title,author,link&query.title="
CROSSREF_DOI_URL = "https://api.crossref.org/works/"
OPENALEX_WORK_URL = "https://api.openalex.org/works/https://doi.org/"
OPENALEX_SEARCH_URL = "https://api.openalex.org/works?per-page=5&select=id,doi,title,authorships,open_access,best_oa_location,locations&filter=title.search:"
SEMANTIC_SCHOLAR_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search?limit=5&fields=title,authors,externalIds,openAccessPdf&query="
ARXIV_API_URL = "https://export.arxiv.org/api/query?id_list="
CITATION_LOOKUP_TIMEOUT_SECONDS = 5
SEMANTIC_SCHOLAR_REPOSITORY_STATUSES = {"GOLD", "GREEN", "HYBRID"}


def find_bibliography_urls(text: str) -> list[str]:
    """
    Return explicit HTTP(S) URLs in bibliography-entry order.

    Args:
        text: TeX source for one bibliography entry.

    Returns:
        list[str]: Explicit URLs without duplicates.
    """
    urls: list[str] = []
    for command in ("href", "url"):
        urls.extend(re.findall(rf"\\{command}\s*\{{\s*(https?://[^\s{{}}]+)", text))
    urls.extend(re.findall(r"(?<![\\{])\b(https?://[^\s{}]+)", text))
    return list(dict.fromkeys(urls))


def find_bibliography_url(text: str) -> str | None:
    """
    Return the first explicit HTTP(S) URL in a bibliography entry.

    Args:
        text: TeX source for one bibliography entry.

    Returns:
        str | None: The explicit URL, when one is present.
    """
    urls = find_bibliography_urls(text)
    return urls[0] if urls else None


def is_pdf_url(url: str) -> bool:
    """
    Check whether a URL directly targets a PDF file.

    Args:
        url: HTTP(S) URL to classify.

    Returns:
        bool: Whether the URL path ends with ``.pdf``.
    """
    return urlsplit(url).path.lower().endswith(".pdf")


def landing_page_pdf_url(urls: list[str]) -> str | None:
    """
    Find a verified direct PDF advertised by an explicit landing page.

    Args:
        urls: Explicit HTTP(S) bibliography URLs in source order.

    Returns:
        str | None: Verified direct PDF URL, or ``None`` when none is discoverable.
    """
    for url in urls:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if not path or path.lower().endswith(".pdf"):
            continue
        suffix = ".html" if path.lower().endswith(".html") else ".htm"
        candidate_path = (
            path[: -len(suffix)] + ".pdf" if path.lower().endswith(suffix) else path + ".pdf"
        )
        candidate = urlunsplit((parts.scheme, parts.netloc, candidate_path, parts.query, ""))
        if remote_url_is_pdf(candidate):
            return candidate

        html = load_remote_text(url)
        if html is None:
            continue
        for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE):
            attributes = {
                name.lower(): value
                for name, value in re.findall(
                    r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']",
                    tag,
                    flags=re.IGNORECASE,
                )
            }
            if attributes.get("name", "").lower() != "citation_pdf_url":
                continue
            advertised = urljoin(url, attributes.get("content", ""))
            if re.fullmatch(r"https?://[^\s]+", advertised) and remote_url_is_pdf(advertised):
                return advertised
    return None


def arxiv_pdf_url(text: str) -> str | None:
    """
    Convert a bare arXiv identifier in a bibliography entry to its PDF URL.

    Args:
        text: TeX source or plain text for one bibliography entry.

    Returns:
        str | None: Canonical arXiv PDF URL, when an identifier is present.
    """
    identifier = arxiv_identifier(text)
    if not identifier:
        return None
    return f"https://arxiv.org/pdf/{identifier}"


def arxiv_identifier(text: str) -> str | None:
    """
    Extract a modern arXiv identifier from a bibliography entry.

    Args:
        text: TeX source or plain text for one bibliography entry.

    Returns:
        str | None: arXiv identifier, including an optional version suffix.
    """
    match = re.search(r"\barXiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", text, re.IGNORECASE)
    return match.group(1) if match else None


def titles_reliably_match(reference: str, candidate: str) -> bool:
    """
    Check whether a remote title is a strong match for a bibliography entry.

    Args:
        reference: Local bibliography entry text.
        candidate: Title returned by a bibliographic service.

    Returns:
        bool: Whether the titles agree sufficiently for automatic linking.
    """
    normalized_reference = " ".join(re.findall(r"[a-z0-9]+", reference.lower()))
    normalized_candidate = " ".join(re.findall(r"[a-z0-9]+", candidate.lower()))
    if normalized_reference == normalized_candidate and normalized_candidate:
        return True
    ignored = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "via", "with"}
    reference_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", reference.lower())
        if len(token) > 1 and token not in ignored
    }
    candidate_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", candidate.lower())
        if len(token) > 1 and token not in ignored
    }
    if len(candidate_tokens) < 4:
        return False
    return len(reference_tokens & candidate_tokens) / len(candidate_tokens) >= 0.8


def authors_reliably_match(reference: list[str], candidate: list[str]) -> bool:
    """
    Check whether two author lists have sufficient family-name overlap.

    Args:
        reference: Trusted local author names.
        candidate: Author names returned by a bibliographic service.

    Returns:
        bool: Whether the candidate authors are consistent with the local list.
    """
    if not reference:
        return True

    def family_names(names: list[str]) -> set[str]:
        """
        Extract normalized final name tokens.

        Args:
            names: Personal or corporate author names.

        Returns:
            set[str]: Normalized final tokens.
        """
        families: set[str] = set()
        for name in names:
            tokens = re.findall(r"[a-z0-9]+", name.lower())
            if tokens:
                families.add(tokens[-1])
        return families

    reference_families = family_names(reference)
    candidate_families = family_names(candidate)
    if not reference_families or not candidate_families:
        return False
    required = max(1, (min(len(reference_families), len(candidate_families)) + 1) // 2)
    return len(reference_families & candidate_families) >= required


def load_remote_json(url: str) -> dict[str, Any] | None:
    """
    Fetch JSON from a bibliographic service without failing a paper build.

    Args:
        url: HTTP(S) endpoint returning a JSON object.

    Returns:
        dict[str, Any] | None: Decoded response object, or ``None`` on network or data errors.
    """
    text = load_remote_text(url)
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def load_remote_text(url: str) -> str | None:
    """
    Fetch text from a remote bibliography service without failing a paper build.

    Args:
        url: HTTP(S) endpoint returning text.

    Returns:
        str | None: Decoded response body, or ``None`` on network or encoding errors.
    """
    request = Request(
        url,
        headers={
            "Accept-Language": "en",
            "User-Agent": "IperPaper/0.2.1 (citation-link-enrichment)",
        },
    )
    try:
        with urlopen(request, timeout=CITATION_LOOKUP_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def remote_url_is_pdf(url: str) -> bool:
    """
    Verify that an unauthenticated URL returns actual PDF bytes.

    Args:
        url: Candidate direct full-text URL.

    Returns:
        bool: Whether the response begins with a PDF file signature.
    """
    request = Request(
        url,
        headers={
            "Accept": "application/pdf",
            "Range": "bytes=0-1023",
            "User-Agent": "IperPaper/0.2.1 (citation-link-enrichment)",
        },
    )
    try:
        with urlopen(request, timeout=CITATION_LOOKUP_TIMEOUT_SECONDS) as response:
            return b"%PDF-" in response.read(1024)
    except (HTTPError, URLError, OSError):
        return False


def _crossref_authors(work: dict[str, Any]) -> list[str]:
    """
    Extract author display names from a Crossref work.

    Args:
        work: Crossref work metadata.

    Returns:
        list[str]: Author names in source order.
    """
    authors: list[str] = []
    raw_authors = work.get("author")
    if not isinstance(raw_authors, list):
        return authors
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if isinstance(name, str) and name.strip():
            authors.append(name.strip())
            continue
        given = author.get("given")
        family = author.get("family")
        if isinstance(given, str) and isinstance(family, str):
            authors.append(f"{given.strip()} {family.strip()}".strip())
        elif isinstance(family, str) and family.strip():
            authors.append(family.strip())
    return authors


def _crossref_work(
    reference: str,
    title: str = "",
    authors: list[str] | None = None,
    doi: str | None = None,
) -> dict[str, Any] | None:
    """
    Resolve trusted local metadata to a matching Crossref work.

    Args:
        reference: Locally extracted bibliography entry text.
        title: Trusted local paper title, when available.
        authors: Trusted local author names, when available.
        doi: Explicit DOI from source metadata, when available.

    Returns:
        dict[str, Any] | None: Normalized matched work metadata.
    """
    authors = authors or []
    if doi:
        response = load_remote_json(CROSSREF_DOI_URL + quote(doi, safe=""))
        message = response.get("message") if response else None
        candidates = [message] if isinstance(message, dict) else []
    else:
        query_title = title or reference
        url = CROSSREF_WORKS_URL + quote(query_title, safe="")
        if authors:
            url += "&query.author=" + quote(" ".join(authors), safe="")
        response = load_remote_json(url)
        items = response.get("message", {}).get("items", []) if response else []
        candidates = items if isinstance(items, list) else []
    for work in candidates:
        if not isinstance(work, dict):
            continue
        titles = work.get("title")
        candidate_title = (
            titles[0]
            if isinstance(titles, list) and titles and isinstance(titles[0], str)
            else ""
        )
        candidate_doi = work.get("DOI")
        candidate_authors = _crossref_authors(work)
        if not isinstance(candidate_doi, str):
            continue
        if not titles_reliably_match(title or reference, candidate_title):
            continue
        if not authors_reliably_match(authors, candidate_authors):
            continue
        links = work.get("link")
        return {
            "doi": candidate_doi,
            "title": candidate_title,
            "authors": candidate_authors,
            "links": links if isinstance(links, list) else [],
        }
    return None


def _crossref_pdf_url(work: dict[str, Any]) -> str | None:
    """
    Find a Crossref full-text link that returns actual PDF bytes.

    Args:
        work: Normalized Crossref work metadata.

    Returns:
        str | None: Verified direct PDF URL.
    """
    links = work.get("links")
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("URL")
        content_type = link.get("content-type")
        if not isinstance(url, str):
            continue
        if content_type != "application/pdf" and not is_pdf_url(url):
            continue
        if remote_url_is_pdf(url):
            return url
    return None


def _arxiv_work(identifier: str) -> tuple[str, list[str]] | None:
    """
    Resolve an arXiv identifier to its title and author names.

    Args:
        identifier: Modern arXiv identifier, optionally including a version.

    Returns:
        tuple[str, list[str]] | None: Canonical title and author names.
    """
    response = load_remote_text(ARXIV_API_URL + quote(identifier, safe=""))
    if response is None:
        return None
    try:
        root = ElementTree.fromstring(response)
    except ElementTree.ParseError:
        return None
    namespace = "{http://www.w3.org/2005/Atom}"
    title_node = root.find(f"{namespace}entry/{namespace}title")
    if title_node is None or not isinstance(title_node.text, str):
        return None
    title = " ".join(title_node.text.split())
    if not title:
        return None
    authors: list[str] = []
    for author_node in root.findall(f"{namespace}entry/{namespace}author"):
        name_node = author_node.find(f"{namespace}name")
        if name_node is not None and isinstance(name_node.text, str) and name_node.text.strip():
            authors.append(name_node.text.strip())
    return title, authors


def _openalex_authors(work: dict[str, Any]) -> list[str]:
    """
    Extract author display names from an OpenAlex work.

    Args:
        work: OpenAlex work metadata.

    Returns:
        list[str]: Author names in source order.
    """
    authors: list[str] = []
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return authors
    for authorship in authorships:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = author.get("display_name") if isinstance(author, dict) else None
        if isinstance(name, str) and name.strip():
            authors.append(name.strip())
    return authors


def _openalex_works(
    title: str,
    authors: list[str],
    doi: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield OpenAlex works matching a DOI or verified title and authors.

    Args:
        title: Trusted local paper title.
        authors: Trusted local author names.
        doi: DOI from local or Crossref metadata, when available.

    Returns:
        Iterator[dict[str, Any]]: Matching OpenAlex works in API order.
    """
    seen: set[str] = set()
    candidates: list[Any] = []
    if doi:
        response = load_remote_json(OPENALEX_WORK_URL + quote(doi, safe=""))
        if isinstance(response, dict):
            candidates.append(response)
    for work in candidates:
        if not isinstance(work, dict):
            continue
        candidate_title = work.get("title")
        candidate_authors = _openalex_authors(work)
        if not isinstance(candidate_title, str):
            continue
        if not titles_reliably_match(title, candidate_title):
            continue
        if not authors_reliably_match(authors, candidate_authors):
            continue
        identifier = work.get("id")
        if isinstance(identifier, str):
            seen.add(identifier)
        yield work
    if title:
        response = load_remote_json(OPENALEX_SEARCH_URL + quote(title, safe=""))
        results = response.get("results", []) if response else []
        candidates = results if isinstance(results, list) else []
    for work in candidates:
        if not isinstance(work, dict):
            continue
        identifier = work.get("id")
        if isinstance(identifier, str) and identifier in seen:
            continue
        candidate_title = work.get("title")
        candidate_authors = _openalex_authors(work)
        if not isinstance(candidate_title, str):
            continue
        if not titles_reliably_match(title, candidate_title):
            continue
        if not authors_reliably_match(authors, candidate_authors):
            continue
        if isinstance(identifier, str):
            seen.add(identifier)
        yield work


def _openalex_work(
    title: str,
    authors: list[str],
    doi: str | None = None,
) -> dict[str, Any] | None:
    """
    Return the first OpenAlex work matching trusted local metadata.

    Args:
        title: Trusted local paper title.
        authors: Trusted local author names.
        doi: DOI from local or Crossref metadata, when available.

    Returns:
        dict[str, Any] | None: First matching OpenAlex work.
    """
    return next(_openalex_works(title, authors, doi), None)


def _openalex_pdf_url_from_work(openalex: dict[str, Any]) -> str | None:
    """
    Extract an explicitly open PDF location from an OpenAlex work.

    Args:
        openalex: Verified OpenAlex work metadata.

    Returns:
        str | None: Open PDF URL, or ``None``.
    """
    open_access = openalex.get("open_access")
    oa_status = open_access.get("oa_status") if isinstance(open_access, dict) else None
    if isinstance(oa_status, str) and oa_status.lower() in {"bronze", "closed"}:
        return None
    locations = [openalex.get("best_oa_location")]
    candidate_locations = openalex.get("locations")
    if isinstance(candidate_locations, list):
        locations.extend(candidate_locations)
    for location in locations:
        if not isinstance(location, dict) or location.get("is_oa") is not True:
            continue
        pdf_url = location.get("pdf_url")
        if isinstance(pdf_url, str) and re.fullmatch(r"https?://[^\s]+", pdf_url):
            return pdf_url
    return None


def _openalex_pdf_url(doi: str) -> str | None:
    """
    Find an explicitly open PDF location in OpenAlex metadata.

    Args:
        doi: DOI resolved from local metadata or Crossref.

    Returns:
        str | None: OpenAlex PDF URL marked as open access, or ``None``.
    """
    openalex = load_remote_json(OPENALEX_WORK_URL + quote(doi, safe=""))
    return _openalex_pdf_url_from_work(openalex) if openalex else None


def _semantic_scholar_authors(work: dict[str, Any]) -> list[str]:
    """
    Extract author names from a Semantic Scholar work.

    Args:
        work: Semantic Scholar paper metadata.

    Returns:
        list[str]: Author names in source order.
    """
    authors: list[str] = []
    raw_authors = work.get("authors")
    if not isinstance(raw_authors, list):
        return authors
    for author in raw_authors:
        name = author.get("name") if isinstance(author, dict) else None
        if isinstance(name, str) and name.strip():
            authors.append(name.strip())
    return authors


def _semantic_scholar_works(
    title: str,
    authors: list[str],
    doi: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield Semantic Scholar works matching a DOI or verified title and authors.

    Args:
        title: Trusted local paper title.
        authors: Trusted local author names.
        doi: DOI from local or resolved metadata, when available.

    Returns:
        Iterator[dict[str, Any]]: Matching papers in API order.
    """
    seen: set[str] = set()
    candidates: list[Any] = []
    if doi:
        response = load_remote_json(
            SEMANTIC_SCHOLAR_PAPER_URL
            + quote(doi, safe="")
            + "?fields=title,authors,externalIds,openAccessPdf"
        )
        if isinstance(response, dict):
            candidates.append(response)
    for work in candidates:
        if not isinstance(work, dict):
            continue
        candidate_title = work.get("title")
        candidate_authors = _semantic_scholar_authors(work)
        if not isinstance(candidate_title, str):
            continue
        if not titles_reliably_match(title, candidate_title):
            continue
        if not authors_reliably_match(authors, candidate_authors):
            continue
        identifier = work.get("paperId")
        if isinstance(identifier, str):
            seen.add(identifier)
        yield work
    if title:
        query = " ".join([title, *authors])
        response = load_remote_json(SEMANTIC_SCHOLAR_SEARCH_URL + quote(query, safe=""))
        data = response.get("data", []) if response else []
        candidates = data if isinstance(data, list) else []
    for work in candidates:
        if not isinstance(work, dict):
            continue
        identifier = work.get("paperId")
        if isinstance(identifier, str) and identifier in seen:
            continue
        candidate_title = work.get("title")
        candidate_authors = _semantic_scholar_authors(work)
        if not isinstance(candidate_title, str):
            continue
        if not titles_reliably_match(title, candidate_title):
            continue
        if not authors_reliably_match(authors, candidate_authors):
            continue
        if isinstance(identifier, str):
            seen.add(identifier)
        yield work


def _semantic_scholar_work(
    title: str,
    authors: list[str],
    doi: str | None = None,
) -> dict[str, Any] | None:
    """
    Return the first Semantic Scholar work matching trusted local metadata.

    Args:
        title: Trusted local paper title.
        authors: Trusted local author names.
        doi: DOI from local or resolved metadata, when available.

    Returns:
        dict[str, Any] | None: First matching Semantic Scholar paper.
    """
    return next(_semantic_scholar_works(title, authors, doi), None)


def _semantic_scholar_pdf_url_from_work(work: dict[str, Any]) -> str | None:
    """
    Extract a recognized open-access PDF from Semantic Scholar metadata.

    Args:
        work: Verified Semantic Scholar paper metadata.

    Returns:
        str | None: Direct open-access PDF URL.
    """
    open_access_pdf = work.get("openAccessPdf")
    if not isinstance(open_access_pdf, dict):
        return None
    if open_access_pdf.get("status") not in SEMANTIC_SCHOLAR_REPOSITORY_STATUSES:
        return None
    pdf_url = open_access_pdf.get("url")
    if isinstance(pdf_url, str) and re.fullmatch(r"https?://[^\s]+", pdf_url) and is_pdf_url(pdf_url):
        return pdf_url
    return None


def semantic_scholar_pdf_url(doi: str, title: str) -> str | None:
    """
    Find a repository PDF reported by Semantic Scholar.

    Args:
        doi: DOI resolved from local metadata or Crossref.
        title: Trusted or remotely matched title.

    Returns:
        str | None: Repository PDF URL with a recognized open-access status, or ``None``.
    """
    work = _semantic_scholar_work(title, [], doi)
    return _semantic_scholar_pdf_url_from_work(work) if work else None


def _repository_pdf_url(doi: str, title: str) -> str | None:
    """
    Find a reliable repository PDF for a resolved scholarly work.

    Args:
        doi: DOI resolved by Crossref.
        title: Crossref title matched to the bibliography entry.

    Returns:
        str | None: OpenAlex or Semantic Scholar repository PDF URL.
    """
    pdf_url = _openalex_pdf_url(doi)
    if pdf_url:
        return pdf_url
    return semantic_scholar_pdf_url(doi, title)


def _store_bibliography_links(entry: dict[str, Any], primary_url: str | None, links: list[str]) -> None:
    """
    Store a selected bibliography URL before its alternate links.

    Args:
        entry: Parsed bibliography entry to update in place.
        primary_url: URL that should be used as the entry's external target.
        links: Additional HTTP(S) URLs associated with the entry.
    """
    ordered = [url for url in [primary_url, *links] if isinstance(url, str) and url]
    ordered = list(dict.fromkeys(ordered))
    if ordered:
        entry["links"] = ordered
        entry["external_url"] = ordered[0]


def crossref_pdf_url(reference: str) -> str | None:
    """
    Find a verified PDF URL through Crossref and scholarly full-text services.

    Args:
        reference: Locally extracted bibliography entry text.

    Returns:
        str | None: A direct PDF URL when bibliographic services agree on the title.
    """
    work = _crossref_work(reference)
    if not work:
        return None
    crossref_pdf = _crossref_pdf_url(work)
    if crossref_pdf:
        return crossref_pdf
    return _repository_pdf_url(work["doi"], work["title"])


def _normalized_doi(value: Any) -> str | None:
    """
    Normalize a DOI value from local or remote metadata.

    Args:
        value: Candidate DOI string.

    Returns:
        str | None: Bare DOI, or ``None`` when unavailable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE)


def _apply_remote_metadata(
    entry: dict[str, Any],
    title: Any,
    authors: list[str],
    source: str,
) -> None:
    """
    Apply verified remote title and author metadata to an entry.

    Args:
        entry: Bibliography entry to update.
        title: Candidate verified title.
        authors: Verified author names.
        source: Metadata service name.
    """
    if isinstance(title, str) and title:
        entry["paper_title"] = title
        entry["_paper_title_verified"] = True
        entry["_paper_title_source"] = source
    if authors:
        entry["authors"] = authors


def enrich_bibliography_entry(entry: dict[str, Any]) -> None:
    """
    Add an external target to a bibliography entry only when it is reliable.

    Args:
        entry: Parsed bibliography entry to update in place.
    """
    source = entry.get("_lookup_source", entry["source"])
    explicit_urls = find_bibliography_urls(source)
    explicit_pdf = next((url for url in explicit_urls if is_pdf_url(url)), None)
    if explicit_pdf:
        _store_bibliography_links(entry, explicit_pdf, explicit_urls)
        return
    arxiv_pdf = arxiv_pdf_url(source)
    if arxiv_pdf:
        _store_bibliography_links(entry, arxiv_pdf, explicit_urls)
        identifier = arxiv_identifier(source)
        if identifier:
            work = _arxiv_work(identifier)
            if work:
                entry["paper_title"], entry["authors"] = work
                entry["_paper_title_verified"] = True
                entry["_paper_title_source"] = "arxiv"
        return
    landing_pdf = landing_page_pdf_url(explicit_urls)
    if landing_pdf:
        _store_bibliography_links(entry, landing_pdf, explicit_urls)
        return
    title = entry.get("paper_title") if isinstance(entry.get("paper_title"), str) else ""
    authors = entry.get("authors") if isinstance(entry.get("authors"), list) else []
    authors = [author for author in authors if isinstance(author, str)]
    doi = _normalized_doi(entry.get("_doi"))

    crossref = _crossref_work(entry["text"], title, authors, doi)
    if crossref:
        _apply_remote_metadata(
            entry,
            crossref.get("title"),
            crossref.get("authors", []),
            "crossref",
        )
        title = entry.get("paper_title", title)
        authors = entry.get("authors", authors)
        doi = _normalized_doi(crossref.get("doi")) or doi
        crossref_pdf = _crossref_pdf_url(crossref)
        if crossref_pdf:
            _store_bibliography_links(entry, crossref_pdf, explicit_urls)
            return

    for openalex in _openalex_works(title, authors, doi):
        openalex_authors = _openalex_authors(openalex)
        _apply_remote_metadata(entry, openalex.get("title"), openalex_authors, "openalex")
        title = entry.get("paper_title", title)
        authors = entry.get("authors", authors)
        doi = _normalized_doi(openalex.get("doi")) or doi
        openalex_pdf = _openalex_pdf_url_from_work(openalex)
        if openalex_pdf:
            _store_bibliography_links(entry, openalex_pdf, explicit_urls)
            return

    for semantic_scholar in _semantic_scholar_works(title, authors, doi):
        semantic_authors = _semantic_scholar_authors(semantic_scholar)
        _apply_remote_metadata(
            entry,
            semantic_scholar.get("title"),
            semantic_authors,
            "semantic_scholar",
        )
        semantic_pdf = _semantic_scholar_pdf_url_from_work(semantic_scholar)
        if semantic_pdf:
            _store_bibliography_links(entry, semantic_pdf, explicit_urls)
            return

    if explicit_urls:
        cached_links = entry.get("links", [])
        cached_links = cached_links if isinstance(cached_links, list) else []
        cached_primary = entry.get("external_url")
        primary_url = cached_primary if isinstance(cached_primary, str) else explicit_urls[0]
        _store_bibliography_links(entry, primary_url, [*cached_links, *explicit_urls])
