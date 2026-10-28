"""Bounded CPU-only SenseVoice worker. No remote transcription or LLM calls."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse
import wave

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = ROOT / '.runtime/asr/models'
MAX_MEDIA_BYTES = 512 * 1024 * 1024
MAX_AUDIO_SECONDS = 7200


def model_paths():
    root = Path(os.environ.get('LOCAL_ASR_MODEL_DIR', DEFAULT_MODELS))
    model = root / 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'
    paths = (model / 'model.int8.onnx', model / 'tokens.txt', root / 'silero_vad.onnx')
    if not all(p.is_file() for p in paths):
        raise RuntimeError('local_asr_models_missing: run scripts/setup_local_asr.py')
    return paths


def media_url_allowed(url):
    p = urlparse(url)
    host = (p.hostname or '').lower()
    return p.scheme == 'https' and not p.username and p.port in (None, 443) and any(
        host == domain or host.endswith('.' + domain)
        for domain in ('douyinvod.com', 'douyin.com', 'bytecdn.cn', 'ibytedtos.com'))


def find_media(value, video_id):
    found = []
    if isinstance(value, dict):
        identity = str(value.get('aweme_id') or value.get('awemeId') or '')
        if identity == video_id:
            video = value.get('video') or {}
            for field in ('play_addr', 'playAddr', 'play_addr_h264'):
                addr = video.get(field) or {}
                for url in addr.get('url_list', addr.get('urlList', [])):
                    if media_url_allowed(url):
                        found.append(url)
        for item in value.values():
            if isinstance(item, (dict, list)):
                found.extend(find_media(item, video_id))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_media(item, video_id))
    return list(dict.fromkeys(found))


class MediaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not media_url_allowed(newurl):
            raise RuntimeError('local_asr_media_redirect_not_allowed')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_page_scripts(page):
    from playwright.sync_api import Error as PlaywrightError
    try:
        return page.locator('script').all_text_contents()
    except PlaywrightError as exc:
        # Douyin may navigate again after its initial HTML has loaded.
        if 'Execution context was destroyed' in str(exc) or 'Cannot find context with specified id' in str(exc):
            return []
        raise


def video_access_error(payload, video_id):
    """Only attribute a platform rejection to the requested work, never recommendations."""
    if not isinstance(payload, dict) or payload.get('aweme_detail'):
        return None
    detail = payload.get('filter_detail')
    if not isinstance(detail, dict) or str(detail.get('aweme_id') or '') != video_id:
        return None
    reason = str(detail.get('filter_reason') or '')
    # Do not forward arbitrary platform payloads, signed URLs or account data.
    if not re.fullmatch(r'[a-zA-Z0-9_]{1,80}', reason):
        reason = 'access_restricted'
    return ('local_asr_video_unavailable: 抖音拒绝提供该作品的视频，作品可能因权限受限或已被删除而无法观看'
            f'（{reason}）。请打开原视频确认；重新登录不一定能解决。')


def download_video(video_url, target):
    match = re.fullmatch(r'https://www\.douyin\.com/video/(\d+)', video_url)
    if not match:
        raise RuntimeError('local_asr_only_supports_canonical_douyin_links')
    from playwright.sync_api import sync_playwright
    from collector_douyin import launch_context
    video_id = match.group(1)
    urls = []
    access_errors = []
    profile = os.environ.get('LOCAL_ASR_BROWSER_PROFILE', str(ROOT / 'backend/.browser-profile/douyin'))
    with sync_playwright() as p:
        context = launch_context(p, profile, headless=True)
        try:
            page = context.new_page()
            def response_received(response):
                if '/aweme/' in response.url and 'json' in response.headers.get('content-type', ''):
                    try:
                        payload = response.json()
                        urls.extend(find_media(payload, video_id))
                        parsed = urlparse(response.url)
                        if (parsed.path == '/aweme/v1/web/aweme/detail/'
                                and parse_qs(parsed.query).get('aweme_id') == [video_id]):
                            error = video_access_error(payload, video_id)
                            if error:
                                access_errors.append(error)
                    except Exception:
                        pass
            page.on('response', response_received)
            page.goto(video_url, wait_until='domcontentloaded', timeout=45000)
            for _ in range(30):
                if urls or access_errors:
                    break
                for text in read_page_scripts(page):
                    for candidate in (text, unquote(text)):
                        try:
                            urls.extend(find_media(json.loads(candidate), video_id))
                        except (ValueError, TypeError):
                            pass
                if urls:
                    break
                page.wait_for_timeout(1000)
            if not urls:
                if access_errors:
                    raise RuntimeError(access_errors[-1])
                raise RuntimeError('local_asr_media_unavailable: 未取得该视频的可播放地址，可能涉及访问限制、页面加载或登录验证。'
                                   '请先打开原视频确认；此错误不代表抖音一定未登录。')
            ua = page.evaluate('navigator.userAgent')
            opener = urllib.request.build_opener(MediaRedirect())
            for url in dict.fromkeys(urls):
                cookies = '; '.join(c['name'] + '=' + c['value'] for c in context.cookies(url))
                request = urllib.request.Request(url, headers={
                    'User-Agent': ua, 'Referer': 'https://www.douyin.com/', 'Cookie': cookies})
                try:
                    started = time.monotonic()
                    with opener.open(request, timeout=30) as response, open(target, 'wb') as output:
                        if 'text/' in response.headers.get('Content-Type', ''):
                            raise RuntimeError('not_media')
                        count = 0
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            count += len(chunk)
                            if count > MAX_MEDIA_BYTES or time.monotonic() - started > 240:
                                raise RuntimeError('media_limit')
                            output.write(chunk)
                    if count < 1024:
                        raise RuntimeError('empty_media')
                    return
                except Exception:
                    Path(target).unlink(missing_ok=True)
            raise RuntimeError('local_asr_media_download_failed')
        finally:
            context.close()


def transcribe_file(source, workdir):
    import imageio_ffmpeg
    import numpy as np
    import sherpa_onnx
    model, tokens, vad_model = model_paths()
    threads = max(1, min(3, int(os.environ.get('LOCAL_ASR_THREADS', '3'))))
    ffmpeg = os.environ.get('FFMPEG_BINARY') or imageio_ffmpeg.get_ffmpeg_exe()
    wav = Path(workdir) / 'audio.wav'
    # Decode at most limit + 1 seconds so overlong inputs are rejected, not silently truncated.
    command = [ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source),
               '-t', str(MAX_AUDIO_SECONDS + 1), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError('local_asr_audio_decode_failed') from None
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=threads,
        use_itn=True, debug=False, provider='cpu', language='auto')
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(vad_model)
    config.silero_vad.min_silence_duration = 0.4
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.max_speech_duration = 25
    config.sample_rate = 16000
    config.num_threads = 1
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
    segments = []
    def drain():
        while not vad.empty():
            speech = vad.front
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, speech.samples)
            recognizer.decode_stream(stream)
            text = re.sub(r'<\|[^|]*\|>', '', stream.result.text).strip()
            if text:
                segments.append({'start': round(speech.start / 16000, 3),
                                 'end': round((speech.start + len(speech.samples)) / 16000, 3), 'text': text})
            vad.pop()
    with wave.open(str(wav), 'rb') as audio:
        duration = audio.getnframes() / 16000
        if duration > MAX_AUDIO_SECONDS:
            raise RuntimeError('local_asr_audio_too_long')
        while True:
            chunk = audio.readframes(config.silero_vad.window_size)
            if not chunk:
                break
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768
            if len(samples) < config.silero_vad.window_size:
                samples = np.pad(samples, (0, config.silero_vad.window_size - len(samples)))
            vad.accept_waveform(samples)
            drain()
        vad.flush()
        drain()
    text = '\n'.join(s['text'] for s in segments)
    if not text:
        raise RuntimeError('local_asr_no_speech_recognized')
    return {'provider': 'local_asr', 'model': 'SenseVoiceSmall-int8', 'transcript_text': text,
            'segments': segments, 'audio_seconds': duration}


def run(video_url=None, media_file=None):
    runtime = ROOT / '.runtime/asr'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Cross-process lock limits model memory and browser-profile use to one worker.
    with open(runtime / 'worker.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        model_paths()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='job-', dir=runtime) as workdir:
            source = Path(media_file) if media_file else Path(workdir) / 'video.mp4'
            if not media_file:
                download_video(video_url, source)
            result = transcribe_file(source, workdir)
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result['peak_rss_mb'] = round(rss / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)
        return result


def health_check():
    """Probe the on-demand worker without downloading media or calling remote APIs."""
    import imageio_ffmpeg
    import numpy as np
    import sherpa_onnx
    model, tokens, vad_model = model_paths()
    ffmpeg = os.environ.get('FFMPEG_BINARY') or imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, '-version'], check=True, capture_output=True, timeout=10)
    runtime = ROOT / '.runtime/asr'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(runtime / 'worker.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ready': False, 'status': 'busy', 'message': '本地 worker 正忙，暂无法执行推理检测；请稍后重试，原转写方式保持不变。'}
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model), tokens=str(tokens), num_threads=1,
            use_itn=True, debug=False, provider='cpu', language='auto')
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
        recognizer.decode_stream(stream)
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(vad_model)
        config.sample_rate = 16000
        config.num_threads = 1
        sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=10)
    return {'ready': True, 'status': 'ready', 'message': '本地 ASR 就绪，模型推理和音轨解码检测通过；任务到来时按需启动。'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--video-url')
    group.add_argument('--media-file')
    group.add_argument('--health-check', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(health_check() if args.health_check else run(args.video_url, args.media_file), ensure_ascii=False))
    except Exception as exc:
        # Do not expose signed CDN URLs or browser cookies in API/log errors.
        message = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith('local_asr_') else 'local_asr_worker_failed:' + type(exc).__name__
        print(json.dumps({'error': message}), file=sys.stderr)
        sys.exit(1)
