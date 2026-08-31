"""Packaged HTML templates used by IperPaper reader builders."""

from importlib.resources import files
from pathlib import Path


def read_template(name: str) -> str:
    """
    Read a named HTML reader template from this resource package.

    Args:
        name: Template file name within this package.

    Returns:
        str: Template content without one trailing newline.
    """
    return files(__name__).joinpath(name).read_text(encoding="utf-8").removesuffix("\n")


def resource_path(name: str) -> Path:
    """
    Return a packaged resource's filesystem path.

    Args:
        name: Resource file name within this package.

    Returns:
        Path: Filesystem path to the resource.
    """
    return Path(__file__).parent / name
