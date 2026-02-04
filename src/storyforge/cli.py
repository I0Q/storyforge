from __future__ import annotations

import argparse
from pathlib import Path

from .audio import ProducerConfig, render

def _parse_ref_kv(items: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--ref expects SPEAKER=/path/to/ref.wav, got: {it}")
        k, v = it.split("=", 1)
        out[k] = Path(v)
    return out



def cmd_render(args: argparse.Namespace) -> int:
    sfml_text = Path(args.story).read_text()

    repo_root = Path(args.repo_root).resolve()
    assets_dir = Path(args.assets_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    voicegen = Path(args.voicegen).resolve()
    speaker_refs = _parse_ref_kv(args.ref or [])

    cfg = ProducerConfig(
        repo_root=repo_root,
        assets_dir=assets_dir,
        out_dir=out_dir,
        speaker_refs=speaker_refs,
        voicegen=voicegen,
    )

    out_mp3 = render(sfml_text, cfg)
    print(out_mp3)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="storyforge")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="Render a SFML script to a mixed MP3")
    r.add_argument("--story", required=True, help="Path to .sfml")
    r.add_argument("--repo-root", default=str(Path.cwd()))
    r.add_argument("--assets-dir", default="assets")
    r.add_argument("--out-dir", default="out")
    r.add_argument("--voicegen", default="tools/voicegen_xtts.sh")
    r.add_argument(
        "--ref",
        action="append",
        help="Speaker reference mapping, e.g. --ref Ruby=assets/voices/refs/cmu_arctic/slt/ref.wav",
    )
    r.set_defaults(func=cmd_render)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
