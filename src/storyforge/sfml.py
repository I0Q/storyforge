from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class SfmlLine:
    raw: str


@dataclass(frozen=True)
class SfmlDirective:
    key: str
    value: str


@dataclass(frozen=True)
class SfmlUtterance:
    speaker: str
    text: str


@dataclass(frozen=True)
class SfmlSfx:
    asset: str
    at: str = "last_end"  # now|last_start|last_end
    offset_s: float = 0.0


@dataclass(frozen=True)
class SfmlPause:
    seconds: float


SfmlEvent = SfmlDirective | SfmlUtterance | SfmlSfx | SfmlPause


def parse_sfml(text: str) -> List[SfmlEvent]:
    """Parse SFML v0.1.

    Supported:
      - @key: value directives
      - SPEAKER: text utterances
      - PAUSE: 0.5
      - SFX: <asset> [at=<now|last_start|last_end>] [offset=0.3]

    Lines beginning with # are comments.
    """

    events: List[SfmlEvent] = []
    for i, line in enumerate(text.splitlines(), start=1):
        raw = line
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("@"):  # directive
            if ":" not in line:
                raise ValueError(f"SFML parse error line {i}: directive missing ':' -> {raw!r}")
            key, value = line[1:].split(":", 1)
            events.append(SfmlDirective(key.strip(), value.strip()))
            continue

        if line.upper().startswith("PAUSE:"):
            _, val = line.split(":", 1)
            events.append(SfmlPause(float(val.strip())))
            continue

        if line.upper().startswith("SFX:"):
            _, rest = line.split(":", 1)
            parts = rest.strip().split()
            if not parts:
                raise ValueError(f"SFML parse error line {i}: SFX missing asset id")
            asset = parts[0]
            at = "last_end"
            offset_s = 0.0
            for p in parts[1:]:
                if p.startswith("at="):
                    at = p.split("=", 1)[1]
                elif p.startswith("offset="):
                    offset_s = float(p.split("=", 1)[1])
            events.append(SfmlSfx(asset=asset, at=at, offset_s=offset_s))
            continue

        if ":" in line:
            speaker, text_ = line.split(":", 1)
            speaker = speaker.strip()
            text_ = text_.strip()
            if not speaker or not text_:
                raise ValueError(f"SFML parse error line {i}: bad utterance -> {raw!r}")
            events.append(SfmlUtterance(speaker=speaker, text=text_))
            continue

        raise ValueError(f"SFML parse error line {i}: unrecognized line -> {raw!r}")

    return events


def get_directive(events: Iterable[SfmlEvent], key: str) -> Optional[str]:
    key_l = key.lower()
    for ev in events:
        if isinstance(ev, SfmlDirective) and ev.key.lower() == key_l:
            return ev.value
    return None
