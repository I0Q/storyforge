#!/usr/bin/env python3
from __future__ import annotations

"""StyleTTS2 inference runner (official repo, LibriTTS).

Used by: voicegen_styletts2.sh

Inputs:
  --text <text>
  --ref <reference wav path>
  --out <output wav path>

Env:
  STYLETT2_REPO_DIR  default /raid/styletts2/StyleTTS2
  STYLETT2_MODEL_DIR default /raid/styletts2_models/libritts_official
  STYLETT2_DEVICE    default cuda
  STYLETT2_ALPHA     default 0.3
  STYLETT2_BETA      default 0.7
  STYLETT2_STEPS     default 10
  STYLETT2_SCALE     default 1.0
"""

import argparse
import os
from pathlib import Path

_G: dict[str, object] = {}


def _init(repo_dir: Path, model_dir: Path, device: str) -> None:
    if _G.get('ready'):
        return

    import sys

    sys.path.insert(0, str(repo_dir))

    import yaml
    import torch
    import phonemizer
    from nltk.tokenize import word_tokenize

    from models import build_model, load_ASR_models, load_F0_models
    from Modules.diffusion.sampler import DiffusionSampler, ADPM2Sampler, KarrasSchedule
    from text_utils import TextCleaner
    from utils import recursive_munch, length_to_mask
    from Utils.PLBERT.util import load_plbert

    cfg_path = model_dir / 'Models' / 'LibriTTS' / 'config.yml'
    ckpt_path = model_dir / 'Models' / 'LibriTTS' / 'epochs_2nd_00020.pth'
    if not cfg_path.exists():
        raise RuntimeError('styletts2_config_missing')
    if not ckpt_path.exists():
        raise RuntimeError('styletts2_ckpt_missing')

    config = yaml.safe_load(cfg_path.read_text())

    asr_cfg = str(repo_dir / str(config.get('ASR_config')))
    asr_pth = str(repo_dir / str(config.get('ASR_path')))
    f0_pth = str(repo_dir / str(config.get('F0_path')))
    plbert_dir = str(repo_dir / str(config.get('PLBERT_dir')))

    text_aligner = load_ASR_models(asr_pth, asr_cfg)
    pitch_extractor = load_F0_models(f0_pth)
    plbert = load_plbert(plbert_dir)

    model_params = recursive_munch(config['model_params'])
    model = build_model(model_params, text_aligner, pitch_extractor, plbert)

    params_whole = torch.load(str(ckpt_path), map_location='cpu')
    params = params_whole.get('net') if isinstance(params_whole, dict) else None
    if not isinstance(params, dict):
        raise RuntimeError('styletts2_bad_checkpoint')

    for key in model:
        if key not in params:
            continue
        try:
            model[key].load_state_dict(params[key])
        except Exception:
            from collections import OrderedDict

            state_dict = params[key]
            new_state_dict = OrderedDict()
            for k, v in state_dict.items():
                name = k[7:] if str(k).startswith('module.') else k
                new_state_dict[name] = v
            model[key].load_state_dict(new_state_dict, strict=False)

    dev = torch.device(device)
    for key in model:
        model[key].eval()
        model[key].to(dev)

    sampler = DiffusionSampler(
        model.diffusion.diffusion,
        sampler=ADPM2Sampler(),
        sigma_schedule=KarrasSchedule(sigma_min=0.0001, sigma_max=3.0, rho=9.0),
        clamp=False,
    )

    textcleaner = TextCleaner()
    global_phonemizer = phonemizer.backend.EspeakBackend(language='en-us', preserve_punctuation=True, with_stress=True)

    _G.update(
        ready=True,
        model=model,
        sampler=sampler,
        model_params=model_params,
        dev=dev,
        textcleaner=textcleaner,
        global_phonemizer=global_phonemizer,
        word_tokenize=word_tokenize,
        length_to_mask=length_to_mask,
    )


def _compute_style(wav_path: Path):
    """Compute ref style embedding as in official LibriTTS demo notebook."""
    import torch
    import torchaudio
    import librosa

    model = _G['model']
    dev = _G['dev']

    # Match demo params
    to_mel = torchaudio.transforms.MelSpectrogram(n_mels=80, n_fft=2048, win_length=1200, hop_length=300).to(dev)
    mean, std = -4.0, 4.0

    wave, sr = librosa.load(str(wav_path), sr=24000)
    audio, _idx = librosa.effects.trim(wave, top_db=30)
    if sr != 24000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=24000)

    wave_tensor = torch.from_numpy(audio).float().to(dev)
    mel = to_mel(wave_tensor)
    mel = (torch.log(1e-5 + mel.unsqueeze(0)) - mean) / std

    with torch.no_grad():
        ref_s = model.style_encoder(mel.unsqueeze(1))
        ref_p = model.predictor_encoder(mel.unsqueeze(1))

    return torch.cat([ref_s, ref_p], dim=1)


def _synth(text: str, ref_s, *, alpha: float, beta: float, diffusion_steps: int, embedding_scale: float):
    import torch

    model = _G['model']
    sampler = _G['sampler']
    model_params = _G['model_params']
    dev = _G['dev']
    global_phonemizer = _G['global_phonemizer']
    textcleaner = _G['textcleaner']
    word_tokenize = _G['word_tokenize']
    length_to_mask = _G['length_to_mask']

    text = text.strip()
    ps = global_phonemizer.phonemize([text])
    ps = word_tokenize(ps[0])
    ps = ' '.join(ps)

    tokens = textcleaner(ps)
    tokens.insert(0, 0)
    tokens = torch.LongTensor(tokens).to(dev).unsqueeze(0)

    with torch.no_grad():
        input_lengths = torch.LongTensor([tokens.shape[-1]]).to(dev)
        text_mask = length_to_mask(input_lengths).to(dev)

        t_en = model.text_encoder(tokens, input_lengths, text_mask)
        bert_dur = model.bert(tokens, attention_mask=(~text_mask).int())
        d_en = model.bert_encoder(bert_dur).transpose(-1, -2)

        s_pred = sampler(
            noise=torch.randn((1, 256)).unsqueeze(1).to(dev),
            embedding=bert_dur,
            embedding_scale=embedding_scale,
            features=ref_s,
            num_steps=diffusion_steps,
        ).squeeze(1)

        s = s_pred[:, 128:]
        ref = s_pred[:, :128]
        ref = alpha * ref + (1 - alpha) * ref_s[:, :128]
        s = beta * s + (1 - beta) * ref_s[:, 128:]

        d = model.predictor.text_encoder(d_en, s, input_lengths, text_mask)
        x, _ = model.predictor.lstm(d)
        duration = model.predictor.duration_proj(x)
        duration = torch.sigmoid(duration).sum(axis=-1)
        pred_dur = torch.round(duration.squeeze()).clamp(min=1)

        pred_aln_trg = torch.zeros(input_lengths, int(pred_dur.sum().data))
        c_frame = 0
        for i in range(pred_aln_trg.size(0)):
            pred_aln_trg[i, c_frame : c_frame + int(pred_dur[i].data)] = 1
            c_frame += int(pred_dur[i].data)

        en = (d.transpose(-1, -2) @ pred_aln_trg.unsqueeze(0).to(dev))
        if model_params.decoder.type == 'hifigan':
            en2 = torch.zeros_like(en)
            en2[:, :, 0] = en[:, :, 0]
            en2[:, :, 1:] = en[:, :, 0:-1]
            en = en2

        F0_pred, N_pred = model.predictor.F0Ntrain(en, s)

        asr = (t_en @ pred_aln_trg.unsqueeze(0).to(dev))
        if model_params.decoder.type == 'hifigan':
            asr2 = torch.zeros_like(asr)
            asr2[:, :, 0] = asr[:, :, 0]
            asr2[:, :, 1:] = asr[:, :, 0:-1]
            asr = asr2

        out = model.decoder(asr, F0_pred, N_pred, ref.squeeze().unsqueeze(0))

    wav = out.squeeze().detach().cpu()
    if wav.numel() > 200:
        wav = wav[:-50]
    return wav


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--ref', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    repo_dir = Path(os.environ.get('STYLETT2_REPO_DIR', '/raid/styletts2/StyleTTS2'))
    model_dir = Path(os.environ.get('STYLETT2_MODEL_DIR', '/raid/styletts2_models/libritts_official'))
    device = os.environ.get('STYLETT2_DEVICE', 'cuda')

    alpha = float(os.environ.get('STYLETT2_ALPHA', '0.3'))
    beta = float(os.environ.get('STYLETT2_BETA', '0.7'))
    steps = int(os.environ.get('STYLETT2_STEPS', '10'))
    scale = float(os.environ.get('STYLETT2_SCALE', '1.0'))

    _init(repo_dir, model_dir, device)

    refp = Path(args.ref)
    if not refp.exists():
        raise SystemExit('ref_missing')

    ref_s = _compute_style(refp)
    wav = _synth(args.text, ref_s, alpha=alpha, beta=beta, diffusion_steps=steps, embedding_scale=scale)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)

    import torchaudio

    torchaudio.save(str(outp), wav.unsqueeze(0), 24000)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
