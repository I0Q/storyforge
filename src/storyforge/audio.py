from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .sfml import SfmlEvent, SfmlPause, SfmlSfx, SfmlUtterance, get_directive, parse_sfml


@dataclass
class ProducerConfig:
    repo_root: Path
    assets_dir: Path
    out_dir: Path
    # Speaker -> reference wav path (local)
    speaker_refs: Dict[str, Path]

    # Path to voicegen wrapper (XTTS docker)
    voicegen: Path

    # Mix gains (dB)
    music_gain_db: float = -18.0
    ambience_gain_db: float = -22.0
    narration_gain_db: float = 0.0


def _run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)


def _ffprobe_duration_s(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.check_output(cmd)
    data = json.loads(out)
    return float(data["format"]["duration"])


def _resolve_asset(assets_dir: Path, asset_id: str) -> Path:
    # Convention: asset_id corresponds to a filename relative to assets_dir.
    # If user passes a bare filename, try common subfolders.
    p = assets_dir / asset_id
    if p.exists():
        return p

    for sub in ["sfx", "music", "ambience"]:
        pp = assets_dir / sub / asset_id
        if pp.exists():
            return pp

    raise FileNotFoundError(f"Asset not found: {asset_id} (looked under {assets_dir})")


def synthesize_utterance(cfg: ProducerConfig, speaker: str, text: str, out_wav: Path) -> None:
    ref = cfg.speaker_refs.get(speaker)
    if not ref:
        raise KeyError(
            f"No reference configured for speaker {speaker!r}. "
            f"Provide --ref SPEAKER=/path/to/ref.wav"
        )

    cmd = [
        str(cfg.voicegen),
        "--text",
        text,
        "--ref",
        str(ref),
        "--out",
        str(out_wav),
        "--device",
        "cuda",
    ]
    _run(cmd)


def render(sfml_text: str, cfg: ProducerConfig) -> Path:
    """Render SFML to a single mixed MP3.

    Strategy:
      1) Parse events.
      2) Synthesize each utterance as wav.
      3) Build a narration track by concatenating wavs and silences.
      4) Schedule SFX with adelay relative to narration anchors.
      5) Mix narration + optional music/ambience + sfx into final MP3.

    This is a pragmatic first pass (local-only, ffmpeg-based).
    """

    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    events = parse_sfml(sfml_text)
    title = get_directive(events, "title") or "story"

    music = get_directive(events, "music")
    ambience = get_directive(events, "ambience")

    # temp workspace
    with tempfile.TemporaryDirectory(prefix="storyforge-") as td:
        tdir = Path(td)
        narr_dir = tdir / "narr"
        narr_dir.mkdir()

        # Build narration segment list and keep anchors
        concat_list: List[Path] = []
        current_time = 0.0
        last_start = 0.0
        last_end = 0.0
        sfx_schedule: List[Tuple[Path, float]] = []  # (path, time_s)

        seg_idx = 0
        for ev in events:
            if isinstance(ev, SfmlUtterance):
                seg_idx += 1
                out_wav = narr_dir / f"seg_{seg_idx:04d}_{ev.speaker}.wav"
                synthesize_utterance(cfg, ev.speaker, ev.text, out_wav)
                dur = _ffprobe_duration_s(out_wav)
                last_start = current_time
                current_time += dur
                last_end = current_time
                concat_list.append(out_wav)
            elif isinstance(ev, SfmlPause):
                # generate silence wav
                seg_idx += 1
                sil = narr_dir / f"sil_{seg_idx:04d}.wav"
                _run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"anullsrc=r=48000:cl=mono",
                        "-t",
                        str(ev.seconds),
                        str(sil),
                    ]
                )
                current_time += ev.seconds
                last_end = current_time
                concat_list.append(sil)
            elif isinstance(ev, SfmlSfx):
                t_anchor = {
                    "now": current_time,
                    "last_start": last_start,
                    "last_end": last_end,
                }.get(ev.at)
                if t_anchor is None:
                    raise ValueError(f"Unknown SFX anchor: {ev.at}")
                sfx_path = _resolve_asset(cfg.assets_dir, ev.asset)
                sfx_schedule.append((sfx_path, max(0.0, t_anchor + ev.offset_s)))
            else:
                # directives ignored here
                pass

        if not concat_list:
            raise ValueError("No narration utterances found in SFML")

        # Create narration concat file
        concat_txt = tdir / "concat.txt"
        concat_txt.write_text("\n".join([f"file {shlex.quote(str(p))}" for p in concat_list]) + "\n")

        narration_wav = tdir / "narration.wav"
        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                str(narration_wav),
            ]
        )

        # Build ffmpeg filter graph
        inputs: List[str] = ["-i", str(narration_wav)]
        labels = {"narr": "0:a"}
        idx = 1
        music_idx = None
        amb_idx = None

        if music:
            music_path = _resolve_asset(cfg.assets_dir, music)
            inputs += ["-i", str(music_path)]
            music_idx = idx
            idx += 1
        if ambience:
            amb_path = _resolve_asset(cfg.assets_dir, ambience)
            inputs += ["-i", str(amb_path)]
            amb_idx = idx
            idx += 1

        sfx_indices: List[Tuple[int, float]] = []
        for sfx_path, t_s in sfx_schedule:
            inputs += ["-i", str(sfx_path)]
            sfx_indices.append((idx, t_s))
            idx += 1

        # Filters:
        # - apply gains
        # - loop music/ambience to narration length
        # - delay sfx
        # - mix all
        filter_lines: List[str] = []

        # narration gain
        filter_lines.append(f"[0:a]volume={cfg.narration_gain_db}dB[narr]")

        mix_inputs = ["[narr]"]

        if music_idx is not None:
            # loop + trim to narration
            filter_lines.append(
                f"[{music_idx}:a]aloop=loop=-1:size=2e+09,volume={cfg.music_gain_db}dB,atrim=0:{current_time}[music]"
            )
            mix_inputs.append("[music]")

        if amb_idx is not None:
            filter_lines.append(
                f"[{amb_idx}:a]aloop=loop=-1:size=2e+09,volume={cfg.ambience_gain_db}dB,atrim=0:{current_time}[amb]"
            )
            mix_inputs.append("[amb]")

        for j, (sfx_i, t_s) in enumerate(sfx_indices, start=1):
            ms = int(t_s * 1000)
            filter_lines.append(f"[{sfx_i}:a]adelay={ms}|{ms}[sfx{j}]")
            mix_inputs.append(f"[sfx{j}]")

        filter_lines.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[mix]")

        out_mp3 = cfg.out_dir / ("".join([c if c.isalnum() or c in "-_" else "_" for c in title]) + ".mp3")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_lines),
            "-map",
            "[mix]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "160k",
            str(out_mp3),
        ]
        _run(cmd)

        return out_mp3
