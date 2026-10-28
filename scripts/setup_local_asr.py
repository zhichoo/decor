#!/usr/bin/env python3
"""Download only official INT8 weights, tokens, and VAD; no runtime network needed."""
import os
import hashlib
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'
DEST = Path(os.environ.get('LOCAL_ASR_MODEL_DIR', ROOT / '.runtime/asr/models'))
HASHES = {
    'model.int8.onnx': 'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51',
    'tokens.txt': 'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc',
    'silero_vad.onnx': '9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6',
}
BASE = os.environ.get('LOCAL_ASR_DOWNLOAD_BASE', 'https://huggingface.co/csukuangfj/' + NAME + '/resolve/main').rstrip('/')


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    files = {NAME + '/model.int8.onnx': BASE + '/model.int8.onnx',
             NAME + '/tokens.txt': BASE + '/tokens.txt',
             'silero_vad.onnx': 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx'}
    with tempfile.TemporaryDirectory(dir=DEST) as tmp:
        for relative, url in files.items():
            target = DEST / relative
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == HASHES[target.name]:
                continue
            download = Path(tmp) / target.name
            print('Downloading ' + relative, flush=True)
            with urllib.request.urlopen(url, timeout=60) as source, open(download, 'wb') as output:
                size = 0
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > 400 * 1024 * 1024:
                        raise RuntimeError('Unexpected model size')
                    output.write(chunk)
            if hashlib.sha256(download.read_bytes()).hexdigest() != HASHES[target.name]:
                raise RuntimeError('Model checksum mismatch: ' + target.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(download, target)
    print('Local ASR models ready: ' + str(DEST))


if __name__ == '__main__':
    main()
