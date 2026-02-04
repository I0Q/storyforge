#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

OPENCLAW_CFG = Path(os.path.expanduser('~/.openclaw/openclaw.json'))

LICENSE_CC0 = 'CC0'
LICENSE_CCBY = 'CC-BY'


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip('-')
    return s or 'asset'


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_openclaw_profile(profile_name: str) -> dict:
    cfg = json.loads(OPENCLAW_CFG.read_text())
    prof = cfg.get('auth', {}).get('profiles', {}).get(profile_name)
    if not prof:
        raise SystemExit(f"Missing OpenClaw auth profile: {profile_name}")
    return prof


def allowed_license(license_url: str, allowed: List[str]) -> bool:
    s = (license_url or '').lower()
    allowed_norm = {a.lower() for a in allowed}
    if 'creativecommons.org/publicdomain/zero' in s or s.endswith('/zero/1.0/'):
        return LICENSE_CC0.lower() in allowed_norm or 'cc0' in allowed_norm
    if 'creativecommons.org/licenses/by/' in s:
        return LICENSE_CCBY.lower() in allowed_norm or 'cc-by' in allowed_norm
    return False


def normalize_license(license_url: str) -> str:
    s = (license_url or '').lower()
    if 'publicdomain/zero' in s or s.endswith('/zero/1.0/'):
        return 'CC0'
    if 'licenses/by/' in s:
        return 'CC-BY'
    return license_url or 'UNKNOWN'


def http_download(url: str, out: Path, timeout: int = 60) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = out.with_suffix(out.suffix + '.part')
        with tmp.open('wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
        tmp.replace(out)


def search_freesound(token: str, query: str, max_duration: int, page: int, page_size: int = 50) -> dict:
    # Freesound pagination uses /apiv2/search/ ("text" endpoint's next links currently point there)
    url = 'https://freesound.org/apiv2/search/'
    params = {
        'query': query,
            # Freesound's /apiv2/search/ endpoint expects a weights param (even empty) for pagination.
        'weights': '',
        'page': page,
        'page_size': page_size,
        'fields': 'id,name,username,license,duration,filesize,tags,url,previews',
        'sort': 'created_desc',
        'filter': f'(license:"Creative Commons 0" OR license:"Attribution") duration:[0 TO {max_duration}]',
    }
    headers = {
        'Authorization': f'Token {token}',
        'User-Agent': 'storyforge-assets-sync/0.1',
    }

    # Freesound sometimes returns 404 for /apiv2/search/ unless certain params are present.
    # Fallback to the legacy /apiv2/search/text/ endpoint if needed.
    def _try(fetch_url: str) -> dict:
        r = requests.get(fetch_url, params=params, headers=headers, timeout=30)
        if r.status_code == 429:
            raise RuntimeError('Freesound rate limited (429). Try again later or reduce requests.')
        if r.status_code == 404:
            raise FileNotFoundError(f"HTTP 404 for {r.url}")
        r.raise_for_status()
        return r.json()

    last_exc: Exception | None = None
    for attempt in range(1, 6):
        try:
            try:
                return _try(url)
            except FileNotFoundError:
                return _try('https://freesound.org/apiv2/search/text/')
        except Exception as e:
            last_exc = e
            time.sleep(min(6.0, 0.7 * attempt))

    raise last_exc  # type: ignore[misc]


@dataclass
class Record:
    kind: str
    source: str
    id: str
    title: str
    creator: str
    license: str
    license_url: str
    source_url: str
    download_url: str
    local_path: str
    sha256: str
    tags: List[str]
    fetched_at: str


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', default='manifests/assets.yaml')
    ap.add_argument('--outdir', default='assets/sfx')
    ap.add_argument('--index', default='assets/credits/index.jsonl')
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--max-pages', type=int, default=20, help='Max pages to scan per query (50 results/page)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path.cwd()
    manifest = yaml.safe_load((root / args.manifest).read_text())

    prof_name = manifest['freesound']['auth_profile']
    prof = load_openclaw_profile(prof_name)
    token = prof.get('provider')
    if not token:
        raise SystemExit(f'OpenClaw profile {prof_name} missing provider token')

    allowed = manifest['freesound'].get('allowed_licenses', ['CC0', 'CC-BY'])
    prefer = manifest['freesound'].get('prefer_previews', ['preview-hq-mp3'])
    max_duration = int(manifest['freesound'].get('max_duration_sec', 20))
    per_query_limit = int(manifest['freesound'].get('per_query_limit', 50))

    queries = manifest.get('queries', [])
    outdir = root / args.outdir
    index_path = root / args.index
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing index to avoid re-downloading and to dedupe by sha/id.
    seen_ids: set[str] = set()
    seen_sha: set[str] = set()
    if index_path.exists():
        with index_path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('source') == 'freesound' and obj.get('id'):
                        seen_ids.add(str(obj['id']))
                    if obj.get('sha256'):
                        seen_sha.add(str(obj['sha256']))
                except Exception:
                    continue

    downloaded = 0
    for q in queries:
        if downloaded >= args.limit:
            break
        qid = q['id']
        qtxt = q['query']
        got = 0

        for page in range(1, args.max_pages + 1):
            if downloaded >= args.limit or got >= per_query_limit:
                break

            try:
                res = search_freesound(token, qtxt, max_duration=max_duration, page=page)
            except FileNotFoundError:
                # Freesound intermittently returns 404 for deeper pages; treat as end of pagination.
                break

            results = res.get('results') or []
            if not results:
                break

            for snd in results:
                if downloaded >= args.limit or got >= per_query_limit:
                    break

            lic_url = snd.get('license') or ''
            if not allowed_license(lic_url, allowed):
                continue

            previews = snd.get('previews') or {}
            dl = None
            for k in prefer:
                if k in previews:
                    dl = previews[k]
                    break
            if not dl:
                continue

            sid = str(snd.get('id'))
            if sid in seen_ids:
                continue

            title = snd.get('name') or f'freesound-{sid}'
            user = snd.get('username') or 'unknown'

            ext = '.mp3' if 'mp3' in (dl or '') else '.ogg'
            fname = f"fs-{sid}__{slug(title)}__{slug(user)}__{normalize_license(lic_url).lower()}{ext}"
            dest = outdir / fname

            if dest.exists() and dest.stat().st_size > 0:
                got += 1
                seen_ids.add(sid)
                continue

            if args.dry_run:
                print('DRY', qid, sid, title, dl)
                got += 1
                continue

            try:
                http_download(dl, dest)
            except Exception as e:
                print('WARN download failed', sid, e, file=sys.stderr)
                continue

            h = sha256_file(dest)
            if h in seen_sha:
                # Duplicate content; keep filesystem clean.
                try:
                    dest.unlink()
                except Exception:
                    pass
                continue

            rec = Record(
                kind='sfx',
                source='freesound',
                id=sid,
                title=title,
                creator=user,
                license=normalize_license(lic_url),
                license_url=lic_url,
                source_url=snd.get('url') or f'https://freesound.org/s/{sid}/',
                download_url=dl,
                local_path=str(dest.relative_to(root)),
                sha256=h,
                tags=list(set((q.get('tags') or []) + (snd.get('tags') or [])))[:40],
                fetched_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            )
            index_path.open('a', encoding='utf-8').write(json.dumps(rec.__dict__) + '\n')

            downloaded += 1
            got += 1
            seen_ids.add(sid)
            seen_sha.add(h)
            print(f"OK {downloaded}/{args.limit} {qid} p{page} {sid} {dest.name}")

            time.sleep(0.10)

        time.sleep(0.35)

    print(f"Done. Downloaded {downloaded} assets.")


if __name__ == '__main__':
    main()
