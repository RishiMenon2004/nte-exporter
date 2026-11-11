"""The tracker sites offered as buttons in the Captured header.

The page only passes a site's key, so it can't open anything not listed here. A
site with "drop" can receive a capture directly; see docs/direct-import.md.
"""

from __future__ import annotations

import os

from nte_history_exporter.constants import MYSTERY_BOX_BANNER_ID

# Set NTE_CHIZ_PINK_URL=http://localhost:3000 to test against a local dev server.
CHIZ_PINK_URL = os.environ.get("NTE_CHIZ_PINK_URL", "https://chiz.pink").rstrip("/")

SITES = {
    "chiz_pink": {
        "label": "Chiz.Pink",
        "url": f"{CHIZ_PINK_URL}/pulls",
        "drop": {
            "upload_url": f"{CHIZ_PINK_URL}/api/import-drop",
            "open_url": f"{CHIZ_PINK_URL}/pulls/import-external",
            "skip_banners": (MYSTERY_BOX_BANNER_ID,),  # The site doesn't track these.
        },
    },
    "ntewiz": {"label": "NTEWiz", "url": "https://www.ntewiz.xyz/"},
}
