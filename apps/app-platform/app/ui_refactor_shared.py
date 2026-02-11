"""UI helpers for incremental refactors.

Rules:
- Keep output HTML/CSS semantically identical unless explicitly changing UI.
- Prefer small, testable extractions.
- Do not introduce new dependencies.
"""

from __future__ import annotations


def base_css(css: str) -> str:
    """Return CSS unchanged.

This wrapper exists to make extractions mechanical: we can move CSS into
constants without changing content or whitespace-sensitive behavior.
"""

    return css
