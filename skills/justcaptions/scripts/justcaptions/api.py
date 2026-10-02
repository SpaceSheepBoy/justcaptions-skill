"""Client for the Just Captions API (https://justcaptions.com/api/).

Standard library only, so the skill installs with nothing but Pillow.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Dict, List, Optional, Tuple

DEFAULT_BASE = "https://api.justcaptions.com/v1"
MAX_AUDIO_BYTES = 12_000_000
TEXT_BATCH = 400
EMOJI_BATCH = 1000
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class APIError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{message} ({status} {code})")
        self.status = status
        self.code = code


def api_key() -> Optional[str]:
    key = os.environ.get("JUSTCAPTIONS_API_KEY", "").strip()
    return key or None


def base_url() -> str:
    return os.environ.get("JUSTCAPTIONS_API_BASE", DEFAULT_BASE).rstrip("/")


def build_multipart(fields: Dict[str, str], files: Dict[str, Tuple[str, bytes, str]]) -> Tuple[bytes, str]:
    """fields: name → value. files: name → (filename, bytes, content type).
    Returns (body, Content-Type header)."""
    boundary = "jc-" + uuid.uuid4().hex
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, data, ctype) in files.items():
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        parts.append(head + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _request(method: str, path: str, body: Optional[bytes] = None, content_type: Optional[str] = None, timeout=180):
    key = api_key()
    if not key:
        raise APIError(401, "invalid_api_key", "JUSTCAPTIONS_API_KEY is not set")
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "justcaptions-skill/1.0"}
    if content_type:
        headers["Content-Type"] = content_type
    for attempt in range(4):
        req = urllib.request.Request(base_url() + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"error": raw[:200] or e.reason}
            # A monthly quota will not reset on retry; a daily abuse cap or a
            # provider hiccup might.
            if e.code in RETRY_STATUSES and payload.get("code") != "quota_exceeded" and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise APIError(e.code, payload.get("code", "error"), payload.get("error", "request failed")) from None
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise APIError(0, "network_error", str(e.reason)) from None


def _json(path: str, payload: dict) -> dict:
    return _request("POST", path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")


def transcribe(audio: bytes, filename: str = "audio.m4a", language: Optional[str] = None, glossary: Optional[List[str]] = None) -> dict:
    fields = {"format": "json"}
    if language:
        fields["language"] = language
    if glossary:
        fields["glossary"] = ", ".join(glossary)
    body, ctype = build_multipart(fields, {"file": (filename, audio, "audio/mp4")})
    return _request("POST", "/transcribe", body, ctype, timeout=600)


def _batched(path: str, key: str, captions: List[str], size: int, extra: dict) -> list:
    out: list = []
    for i in range(0, len(captions), size):
        result = _json(path, {"captions": captions[i : i + size], **extra})
        out.extend(result[key])
    return out


def correct(captions: List[str], language: Optional[str] = None, glossary: Optional[List[str]] = None) -> List[str]:
    extra = {k: v for k, v in {"language": language, "glossary": glossary}.items() if v}
    return _batched("/correct", "captions", captions, TEXT_BATCH, extra)


def translate(captions: List[str], target_language: str, glossary: Optional[List[str]] = None) -> List[str]:
    extra = {"target_language": target_language}
    if glossary:
        extra["glossary"] = glossary
    return _batched("/translate", "captions", captions, TEXT_BATCH, extra)


def emoji(captions: List[str], language: Optional[str] = None) -> List[Optional[str]]:
    extra = {"language": language} if language else {}
    return _batched("/emoji", "emojis", captions, EMOJI_BATCH, extra)


def usage() -> dict:
    return _request("GET", "/usage")
