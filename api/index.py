from collections import deque
from datetime import datetime, timezone
import ipaddress
import socket
from urllib.parse import urlparse

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024

# Vercel instances can be recycled, so this lightweight history is best-effort
# and is not a permanent, cross-instance database.
_HISTORY = deque(maxlen=30)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _platform_for(url):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host == "fb.watch" or host == "facebook.com" or host.endswith(".facebook.com"):
        return "Facebook"
    if host in {"x.com", "twitter.com", "t.co"}:
        return "X / Twitter"
    if host == "pin.it" or host == "pinterest.com" or host.endswith(".pinterest.com") or host.endswith(".pinterest.co.uk"):
        return "Pinterest"
    if host in {"youtu.be", "youtube.com", "m.youtube.com", "music.youtube.com"} or host.endswith(".youtube.com"):
        return "YouTube"
    return "Any link"


def _normalise_media_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _validate_public_http_url(value):
    """Reject malformed/local URL targets before using this server as a proxy."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP/HTTPS URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing login credentials are not supported.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        raise ValueError("That URL host is not allowed.")
    if hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("That URL host is not allowed.")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Resolve hostnames too, to reject obvious DNS names pointing to a private IP.
        try:
            addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            # Let requests provide the normal connection error for transient DNS failures.
            return
        for address in addresses:
            candidate = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            if not candidate.is_global:
                raise ValueError("That URL host is not publicly routable.")
    else:
        if not ip.is_global:
            raise ValueError("That URL host is not publicly routable.")


def _append_history(item):
    _HISTORY.appendleft({
        "title": item.get("title") or "Untitled video",
        "thumbnail": item.get("thumbnail") or "",
        "uploader": item.get("uploader") or "Unknown creator",
        "platform": item.get("platform") or "Any link",
        "url": item.get("source_url") or "",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "is_no_watermark": bool(item.get("is_no_watermark")),
    })


def _extract_tiktok_with_tikwm(source_url):
    api_url = "https://www.tikwm.com/api/"
    payload = {"url": source_url, "count": 12, "cursor": 0, "web": 1, "hd": 1}
    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://www.tikwm.com/",
        "Accept": "application/json, text/plain, */*",
    }
    response = requests.post(api_url, data=payload, headers=headers, timeout=(8, 20))
    response.raise_for_status()
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None

    direct_url = _normalise_media_url(data.get("hdplay") or data.get("play"))
    if not direct_url:
        return None

    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    return {
        "success": True,
        "title": data.get("title") or "TikTok video",
        "thumbnail": data.get("cover") or data.get("origin_cover") or "",
        "uploader": author.get("nickname") or author.get("unique_id") or "TikTok creator",
        "direct_url": direct_url,
        "watermark_url": _normalise_media_url(data.get("wmplay")) or direct_url,
        "platform": "TikTok",
        "is_no_watermark": True,
        "watermark_removed": True,
        "source_url": source_url,
    }


def _extract_with_ytdlp(source_url, platform):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "format": "best[ext=mp4]/best",
        "socket_timeout": 20,
        "http_headers": {"User-Agent": _USER_AGENT},
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(source_url, download=False)

    if not isinstance(info, dict):
        raise ValueError("The page did not provide a downloadable video.")

    direct_url = _normalise_media_url(info.get("url"))
    if not direct_url:
        formats = info.get("formats") or []
        candidates = [
            fmt for fmt in formats
            if fmt.get("url") and fmt.get("vcodec") != "none"
            and fmt.get("acodec") != "none"
        ]
        candidates.sort(
            key=lambda fmt: (
                fmt.get("ext") == "mp4",
                fmt.get("height") or 0,
                fmt.get("tbr") or 0,
            ),
            reverse=True,
        )
        for fmt in candidates:
            direct_url = _normalise_media_url(fmt.get("url"))
            if direct_url:
                break
    if not direct_url:
        raise ValueError("No direct video stream was found for this link.")

    # The generic fallback does not prove that a watermark was removed.
    is_no_watermark = False
    result = {
        "success": True,
        "title": info.get("title") or "Video",
        "thumbnail": info.get("thumbnail") or "",
        "uploader": info.get("uploader") or info.get("channel") or "Unknown creator",
        "direct_url": direct_url,
        "watermark_url": direct_url,
        "platform": platform,
        "is_no_watermark": is_no_watermark,
        "watermark_removed": is_no_watermark,
        "source_url": source_url,
    }
    return result


@app.route("/api/download", methods=["POST", "OPTIONS"])
def download_info():
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(silent=True) or {}
    source_url = _normalise_media_url(payload.get("url"))
    if not source_url:
        return jsonify({"success": False, "error": "Enter a valid http or https video URL."}), 400

    try:
        _validate_public_http_url(source_url)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    platform = _platform_for(source_url)
    if platform == "TikTok":
        try:
            result = _extract_tiktok_with_tikwm(source_url)
            if result:
                result["uploader"] = result.get("uploader") or "TikTok creator"
                _append_history(result)
                return jsonify(result)
        except (requests.RequestException, ValueError, TypeError) as exc:
            app.logger.info("TikWM extraction did not work; trying yt-dlp: %s", exc)

    try:
        result = _extract_with_ytdlp(source_url, platform)
        _append_history(result)
        return jsonify(result)
    except Exception as exc:
        app.logger.warning("Video extraction failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Could not extract this video. The link may be private, expired, unsupported, or temporarily blocked.",
        }), 422


@app.route("/api/proxy-download", methods=["GET"])
def proxy_download():
    source_url = _normalise_media_url(request.args.get("url", ""))
    if not source_url:
        return jsonify({"success": False, "error": "A valid video URL is required."}), 400
    try:
        _validate_public_http_url(source_url)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    filename = secure_filename(request.args.get("filename", "phantom_video.mp4")) or "phantom_video.mp4"
    if not filename.lower().endswith(".mp4"):
        filename += ".mp4"

    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://www.tiktok.com/",
        "Accept": "video/*,application/octet-stream;q=0.9,*/*;q=0.8",
    }
    try:
        upstream = requests.get(
            source_url,
            stream=True,
            headers=headers,
            allow_redirects=True,
            timeout=(10, 30),
        )
    except requests.RequestException:
        return jsonify({"success": False, "error": "Could not reach the video host. Try extracting the link again."}), 502

    content_type = (upstream.headers.get("Content-Type") or "").lower()
    if "text/html" in content_type:
        upstream.close()
        return jsonify({"success": False, "error": "Link expired. Extract the video again and retry."}), 410
    if upstream.status_code >= 400:
        status_code = upstream.status_code
        upstream.close()
        if status_code in {401, 403, 404, 410, 416}:
            return jsonify({"success": False, "error": "Link expired. Extract the video again and retry."}), 410
        return jsonify({"success": False, "error": "The video host could not provide this file."}), 502

    def stream_video():
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = Response(
        stream_with_context(stream_video()),
        content_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        direct_passthrough=True,
    )
    length = upstream.headers.get("Content-Length")
    if length and length.isdigit():
        response.headers["Content-Length"] = length
    return response


@app.route("/api/history", methods=["GET"])
def history():
    return jsonify({"success": True, "history": list(_HISTORY)})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"success": True, "service": "Phantom TT Hub", "status": "ok"})


# Vercel's Python runtime discovers this module-level Flask application as `app`.
