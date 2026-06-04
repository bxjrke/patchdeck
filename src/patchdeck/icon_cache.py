from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .models import ServiceConfig

ICON_SOURCES = (
    "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{slug}.svg",
    "https://cdn.jsdelivr.net/gh/selfhst/icons/svg/{slug}.svg",
    "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/{slug}.png",
    "https://cdn.jsdelivr.net/gh/selfhst/icons/png/{slug}.png",
)
LOCAL_ICON_PREFIX = "/api/icons/"
ICON_ALIASES = {
    "adguard": ("adguard-home", "adguardhome"),
    "homeassistant": ("home-assistant",),
}


def cache_service_icon(service: ServiceConfig, data_dir: Path) -> ServiceConfig:
    if is_external_override(service.logo_url):
        return service
    if not service.icon_slug:
        return service.model_copy(update={"logo_url": None}) if is_local_icon(service.logo_url) else service

    icon_dir = data_dir / "icons"
    cached = cached_icon_for_slug(icon_dir, service.icon_slug)
    if cached:
        return service.model_copy(update={"logo_url": LOCAL_ICON_PREFIX + quote(cached.name)})

    downloaded = download_icon(icon_dir, service.icon_slug)
    if downloaded:
        return service.model_copy(update={"logo_url": LOCAL_ICON_PREFIX + quote(downloaded.name)})
    return service


def is_local_icon(value: str | None) -> bool:
    return bool(value and value.startswith(LOCAL_ICON_PREFIX))


def is_external_override(value: str | None) -> bool:
    return bool(value and not is_local_icon(value))


def cached_icon_for_slug(icon_dir: Path, slug: str) -> Path | None:
    safe_slug = safe_icon_slug(slug)
    for suffix in (".svg", ".png"):
        candidate = icon_dir / f"{safe_slug}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def download_icon(icon_dir: Path, slug: str) -> Path | None:
    safe_slug = safe_icon_slug(slug)
    icon_dir.mkdir(parents=True, exist_ok=True)
    for source_slug in icon_source_slugs(safe_slug):
        for template in ICON_SOURCES:
            url = template.format(slug=quote(source_slug))
            suffix = ".png" if url.endswith(".png") else ".svg"
            target = icon_dir / f"{safe_slug}{suffix}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "patchdeck/0.1"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    content_type = response.headers.get("content-type", "").lower()
                    data = response.read(512_000)
                if not data or b"404: Not Found" in data[:80]:
                    continue
                if suffix == ".svg" and b"<svg" not in data[:512].lower():
                    continue
                if suffix == ".png" and not (content_type.startswith("image/") or data.startswith(b"\x89PNG")):
                    continue
                target.write_bytes(data)
                return target
            except Exception:
                continue
    return None


def icon_source_slugs(slug: str) -> tuple[str, ...]:
    aliases = ICON_ALIASES.get(slug, ())
    return (slug, *aliases)


def safe_icon_slug(slug: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", slug.lower()).strip(".-_")
    return normalized[:96] or "icon"
