"""Registry of stub landing pages used by the TLS provisioner.

Each template is a single self-contained `index.html` shipped to the
node and served by Caddy as the default site for the provisioned
domain. The templates intentionally LOOK like working web apps
(file converters, image tools, etc.) but the "convert" buttons just
animate a fake progress bar and surface a generic error — there is no
real backend. The point is to give the domain a plausible reason to
exist when DPI / scrapers fingerprint it, while not actually offering a
service we'd be on the hook to operate.

To add a new template:
1. Drop `<key>/index.html` into `app/ai/templates/landings/`.
2. Append an entry to `LANDING_TEMPLATES` below with stable `key`,
   short `title`, and longer `description`.
3. Done — `tls_list_landing_templates` will pick it up automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates" / "landings"


@dataclass(frozen=True)
class LandingTemplate:
    key: str
    title: str
    description: str

    @property
    def html_path(self) -> Path:
        return TEMPLATES_DIR / self.key / "index.html"


LANDING_TEMPLATES: tuple[LandingTemplate, ...] = (
    LandingTemplate(
        key="pdf_to_word",
        title="PDF to Word converter",
        description=(
            "Online PDF→DOCX converter landing. Looks like a freemium "
            "tool — drag & drop area, fake conversion progress, "
            "feature grid, FAQ. Never actually converts anything: the "
            "submit button shows a generic 'service temporarily "
            "unavailable, retry later' toast. Best general-purpose "
            "cover."
        ),
    ),
    LandingTemplate(
        key="image_compressor",
        title="Image compressor",
        description=(
            "JPEG/PNG/WebP compressor landing. Shows a slider for "
            "quality, a fake before/after preview, and a privacy "
            "policy footer. Same pattern: upload widget is wired to a "
            "no-op error path. Believable for a single-page "
            "image-tools brand."
        ),
    ),
    LandingTemplate(
        key="qr_generator",
        title="QR code generator",
        description=(
            "QR code maker landing. Renders a static SVG sample QR, "
            "has tabs for URL / WiFi / vCard, a 'download PNG' button "
            "that shows 'maintenance mode' on click. Lightest of the "
            "five — fewer assets, faster page load."
        ),
    ),
    LandingTemplate(
        key="audio_converter",
        title="Audio format converter",
        description=(
            "MP3 / WAV / FLAC / OGG converter landing. Header with a "
            "format matrix, drop zone, side panel with bitrate and "
            "sample-rate dropdowns. Submit returns the same generic "
            "error. Pairs well with niche-looking domains."
        ),
    ),
    LandingTemplate(
        key="video_to_gif",
        title="Video to GIF maker",
        description=(
            "Short MP4 → animated GIF tool. Crop / trim controls, "
            "fps slider, looping preview that just plays a stock "
            "loop. Submit fails the same way. Most visually rich of "
            "the templates — use when you want the page to look "
            "actively maintained."
        ),
    ),
)


_BY_KEY = {t.key: t for t in LANDING_TEMPLATES}


def get_template(key: str) -> LandingTemplate | None:
    return _BY_KEY.get(key)


def template_keys() -> tuple[str, ...]:
    return tuple(t.key for t in LANDING_TEMPLATES)


def render_landing_html(key: str) -> str:
    """Return the raw HTML bytes for the given template key, decoded.

    Raises FileNotFoundError if the template was registered but its
    HTML file is missing — that is a packaging error, not a user
    error, and we want loud feedback.
    """
    tpl = get_template(key)
    if tpl is None:
        raise KeyError(f"Unknown landing template: {key!r}")
    return tpl.html_path.read_text(encoding="utf-8")
