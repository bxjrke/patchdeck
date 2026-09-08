"""Patchdeck backend package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("patchdeck")
except PackageNotFoundError:  # Source tree imported before installation.
    __version__ = "0.0.0+local"
