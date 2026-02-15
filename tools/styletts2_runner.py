"""StyleTTS2 runner (v0 scaffold).

Goal: provide a stable CLI entrypoint for voicegen_styletts2.sh.

This is intentionally minimal: we validate environment + import paths.
Next step: wire official StyleTTS2 inference.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, help='Path to official StyleTTS2 repo')
    ap.add_argument('--text', required=True)
    ap.add_argument('--voice_ref', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    repo = Path(args.repo)
    if not repo.exists():
        raise SystemExit('styletts2_repo_missing')

    # Put repo on sys.path
    import sys

    sys.path.insert(0, str(repo))

    # Validate torch/cuda
    import torch

    if not torch.cuda.is_available():
        # StyleTTS2 might run on CPU, but we expect GPU on Tinybox.
        pass

    # TODO: implement real inference.
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    # Create a short silent file as placeholder to prove plumbing.
    import torchaudio

    wav = torch.zeros(int(24000 * 0.5), dtype=torch.float32)
    torchaudio.save(str(outp), wav.unsqueeze(0), 24000)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
