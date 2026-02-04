from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StoryGenConfig:
    title: str
    seed: int = 0
    minutes: float = 3.0
    narrator: str = "Ruby"
    music_asset: Optional[str] = None
    ambience_asset: Optional[str] = None


def generate_sfml(cfg: StoryGenConfig) -> str:
    """Deterministic bedtime-story SFML generator.

    This is intentionally non-LLM: it produces a safe, predictable structure
    (intro -> 3 beats -> gentle outro), with space for SFX/music.

    Output is SFML v0.1.
    """

    rng = random.Random(cfg.seed)

    # Keep things calm and understandable.
    places = [
        "a quiet lantern shop",
        "a sleepy library",
        "a warm kitchen at night",
        "a moonlit garden",
        "a tiny train station",
    ]
    objects = [
        "a pocket watch",
        "a paper umbrella",
        "a small music box",
        "a wind-up bird",
        "a map with silver ink",
    ]
    place = rng.choice(places)
    obj = rng.choice(objects)

    # Simple cast.
    # (Voices are resolved later by the audio subsystem.)
    char_f = rng.choice(["Pearl", "Violet", "Opal", "Iris", "Jade", "Rose", "Amber"])
    char_m = rng.choice(["Onyx", "Slate", "Moss", "Copper", "Ember"])

    lines: List[str] = []
    lines.append(f"@title: {cfg.title}")
    lines.append("@lang: en")
    if cfg.music_asset:
        lines.append(f"@music: {cfg.music_asset}")
    if cfg.ambience_asset:
        lines.append(f"@ambience: {cfg.ambience_asset}")

    lines.append("")
    lines.append(f"{cfg.narrator}: Tonight, we visit {place}, where everything is soft and unhurried.")
    lines.append("PAUSE: 0.35")

    # Intro beat
    lines.append(f"{cfg.narrator}: On the counter rests {obj}. It seems ordinary, until it makes the faintest, friendliest sound.")
    lines.append("SFX: sfx_soft_chime at=last_end offset=0.0")
    lines.append("PAUSE: 0.35")

    lines.append(f"{char_f}: Hello? I thought I heard something.")
    lines.append("PAUSE: 0.25")
    lines.append(f"{char_m}: Me too. But it sounds… polite.")
    lines.append("PAUSE: 0.35")

    # Beat 1
    lines.append(f"{cfg.narrator}: Together, they lean closer. The {obj} clicks once, as if asking permission.")
    lines.append("SFX: sfx_soft_click at=last_end offset=0.0")
    lines.append("PAUSE: 0.30")
    lines.append(f"{char_f}: You can help us fall asleep, can’t you?")
    lines.append("PAUSE: 0.25")

    # Beat 2
    lines.append(f"{cfg.narrator}: A gentle breeze moves through the room, though no windows are open.")
    lines.append("SFX: sfx_gentle_wind at=last_end offset=0.0")
    lines.append("PAUSE: 0.35")
    lines.append(f"{char_m}: If you tell us a story, we’ll listen quietly.")
    lines.append("PAUSE: 0.25")

    # Beat 3
    lines.append(f"{cfg.narrator}: The {obj} answers with a tiny melody—three notes, then a pause—like a lullaby learning your name.")
    lines.append("SFX: sfx_musicbox_three_notes at=last_end offset=0.0")
    lines.append("PAUSE: 0.45")

    # Outro
    lines.append(f"{cfg.narrator}: And as the last note fades, the whole {place} feels lighter. Breathing becomes easy. Eyes grow heavy.")
    lines.append("PAUSE: 0.45")
    lines.append(f"{cfg.narrator}: Goodnight. Sleep deeply, and let the quiet keep watch.")

    return "\n".join(lines) + "\n"
