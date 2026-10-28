#!/usr/bin/env python3
"""Read-only replay of latest saved videos. Never writes business tables."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import server
import local_asr


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def snapshot():
    with server.connect() as conn:
        return {table: digest(conn.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall())
                for table in ('videos', 'claims', 'extraction_runs')}


def normalize(text):
    return ''.join(re.findall(r'[\w]', text.lower()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    out = ROOT / '.runtime/asr/benchmark'
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out, 0o700)
    before = snapshot()
    with server.connect() as conn:
        rows = conn.execute("""SELECT * FROM videos WHERE deleted_at IS NULL
            AND length(btrim(coalesce(transcript_text,'')))>0
            ORDER BY published_at_ts DESC NULLS LAST, created_at DESC, id DESC LIMIT %s""", (args.limit,)).fetchall()
    results = []
    for row in rows:
        item = {'id': row['id'], 'title': row['title'], 'original_length': len(row['transcript_text'])}
        media = out / (row['id'] + '.mp4')
        started = time.monotonic()
        try:
            if not media.exists():
                local_asr.download_video(server.canonical_video_url(row['share_url'] or row['source_url']), media)
            if args.download_only:
                item.update(state='downloaded', bytes=media.stat().st_size)
            else:
                command = [sys.executable, str(ROOT / 'backend/local_asr.py'), '--media-file', str(media)]
                process = subprocess.run(command, capture_output=True, text=True, timeout=3600)
                if process.returncode:
                    raise RuntimeError(process.stderr.splitlines()[-1][:1000])
                result = json.loads(process.stdout)
                (out / (row['id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
                (out / (row['id'] + '.original.txt')).write_text(row['transcript_text'])
                a, b = normalize(row['transcript_text']), normalize(result['transcript_text'])
                item.update(state='succeeded', local_length=len(result['transcript_text']),
                            audio_seconds=result['audio_seconds'], inference_seconds=result['elapsed_seconds'],
                            peak_rss_mb=result.get('peak_rss_mb'),
                            reference_similarity=round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4),
                            local_preview=result['transcript_text'][:220])
        except Exception as exc:
            item.update(state='failed', error=str(exc)[:1000])
        item['wall_seconds'] = round(time.monotonic() - started, 3)
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    after = snapshot()
    report = {'results': results, 'before': before, 'after': after, 'business_data_unchanged': before == after,
              'note': 'Reference is previous provider output, not ground truth; similarity is not ASR accuracy.'}
    (out / ('downloads.json' if args.download_only else 'report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if before != after:
        raise RuntimeError('Business data changed during read-only replay; inspect concurrent activity')
    if any(item['state'] == 'failed' for item in results):
        sys.exit(1)


if __name__ == '__main__':
    main()
