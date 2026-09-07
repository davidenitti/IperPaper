"""Packaged HTML templates used by IperPaper reader builders."""

from html import escape
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def reader_version() -> str:
    """
    Read the current source version or the installed distribution version.

    Returns:
        str: IperPaper version used to generate the reader.
    """
    project_file = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if project_file.is_file():
        with project_file.open("rb") as source:
            project = tomllib.load(source).get("project", {})
        if project.get("name") == "iperpaper":
            return project["version"]
    return version("iperpaper")


def read_template(name: str) -> str:
    """
    Read a reader template and insert the current version and reading guide.

    Args:
        name: Template file name within this package.

    Returns:
        str: Template content with the version and escaped plain-text guide.
    """
    template = files(__name__).joinpath(name).read_text(encoding="utf-8").removesuffix("\n")
    guide = files(__name__).joinpath("guide.txt").read_text(encoding="utf-8").strip()
    return template.replace("__IP_VERSION__", escape(reader_version())).replace(
        "__IP_GUIDE_HTML__", escape(guide)
    )


def resource_path(name: str) -> Path:
    """
    Return a packaged resource's filesystem path.

    Args:
        name: Resource file name within this package.

    Returns:
        Path: Filesystem path to the resource.
    """
    return Path(__file__).parent / name
