import logging

import uvicorn

from app.core.settings import settings

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)
handler = logging.StreamHandler()
formatter = uvicorn.logging.ColourizedFormatter(
    "{levelprefix:<8} @{name}: {message}", style="{", use_colors=True
)
handler.setFormatter(formatter)
logger.addHandler(handler)
