#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download public TikTok videos using only Python's standard library.

See DOCS.md for the observed request chain, its checks, and limitations.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import http.client
import http.cookiejar
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
REFERER = "https://www.tiktok.com/"
TEST_URLS = (
    "https://www.tiktok.com/@casamentosemdividas/video/7286599702303362310?share_item_id=7286599702303362310&share_app_id=1233",
    "https://www.tiktok.com/@causanobrecerimonial/video/7502602409370307845?share_app_id=1233&share_item_id=7502602409370307845",
    "https://www.tiktok.com/@metropolesoficial/video/7562939840271076615?share_item_id=7562939840271076615&share_app_id=1233",
    "https://www.tiktok.com/@metropolesoficial/video/7544010904229252358?share_app_id=1233&share_item_id=7544010904229252358",
    "https://www.tiktok.com/@nerublanco/video/7542076400346451232?share_app_id=1233&share_item_id=7542076400346451232",
    "https://vm.tiktok.com/ZMAYuMpFQ/",
    "https://vm.tiktok.com/ZMAj83k4w/",
    "https://vm.tiktok.com/ZMA4ncut8/",
    "https://vm.tiktok.com/ZMAVwmojg/",
)


class ExtractionError(Exception):
    """The response did not provide a complete, publicly playable MP4."""


class HydrationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.found = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__":
            self.inside = self.found = True

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


def video_id(url):
    """Validate an input/page URL; short links have no ID until redirected."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "https":
        if parsed.netloc == "vm.tiktok.com" and re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path):
            return None
        match = re.fullmatch(r"/@[A-Za-z0-9_.]*/video/([0-9]+)/*", parsed.path)
        if parsed.netloc in {"www.tiktok.com", "tiktok.com"} and match:
            return match[1]
    raise ExtractionError(
        "Expected an HTTPS TikTok /@user/video/<id> URL or vm.tiktok.com short link"
    )


def parse_item(parser, expected_id):
    try:
        data = json.loads("".join(parser.parts))
        detail = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]
        if detail["statusCode"] != 0:
            raise ExtractionError(f"TikTok video-detail statusCode={detail['statusCode']!r}; unavailable")
        item = detail["itemInfo"]["itemStruct"]
        if str(item["id"]) != expected_id:
            raise ExtractionError("Hydration item ID does not match the requested video")
        if any(item.get(flag) for flag in ("privateItem", "secret", "forFriend", "isProhibited", "takeDown")):
            raise ExtractionError("TikTok marks this item as restricted or unavailable")
        video = item["video"]
        media = urllib.parse.urlsplit(video["playAddr"])
        if media.scheme != "https" or not media.hostname:
            raise ExtractionError("No HTTPS playAddr in the video metadata")
        if video.get("format") != "mp4":
            raise ExtractionError("This example supports MP4 video posts only")
        return item
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExtractionError("Malformed or changed TikTok hydration schema") from exc


class RequestCounter(urllib.request.BaseHandler):
    def __init__(self):
        self.count = 0

    def http_request(self, request):
        self.count += 1
        return request

    https_request = http_request


class Extractor:
    """One cookie jar for the page and its media; never requires browser state."""

    def __init__(self):
        self.counter = RequestCounter()
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            self.counter, urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT)]

    def open(self, url, headers, phase):
        try:
            return self.opener.open(urllib.request.Request(url, headers=headers), timeout=45)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ExtractionError(f"{phase}: HTTP {code}; access denied or resource unavailable") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExtractionError(f"{phase}: network connection failed ({type(exc).__name__})") from exc

    def resolve(self, url):
        expected_id = video_id(url)
        for attempt in range(2):
            with self.open(url, {"Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}, "page") as response:
                if response.status != 200:
                    raise ExtractionError(f"page: unexpected HTTP {response.status}")
                # The redirected response already contains the page: do not fetch it again.
                url = response.geturl()
                resolved_id = video_id(url)
                if resolved_id is None:
                    raise ExtractionError("Short link did not redirect to a video page")
                if expected_id is not None and resolved_id != expected_id:
                    raise ExtractionError("Redirect changed the requested video ID")
                expected_id = resolved_id
                parser = HydrationParser()
                html = response.read().decode("utf-8")
                parser.feed(html)
            if parser.found:
                return parse_item(parser, expected_id)
            # Observed transient HTTP-200 app shell, not an unavailable item.
            if attempt == 0 and 'data-source="downgrade-mssdk-preload"' in html:
                time.sleep(1)
                continue
            raise ExtractionError(
                "Page has no video hydration data (app shell, challenge, or changed frontend); "
                "no signed-API or browser fallback is attempted"
            )

    def download(self, item, destination):
        try:
            video = item["video"]
            url = video["playAddr"]  # Preserve the server-signed URL byte-for-byte.
            expected_size = int(video.get("size") or 0)
            expected_hash = None
            for rendition in video.get("bitrateInfo", []):
                address = rendition.get("PlayAddr", {})
                if url in address.get("UrlList", []):
                    expected_hash = address.get("FileHash") or None
                    expected_size = int(address.get("DataSize") or expected_size)
                    break
            if expected_hash and not re.fullmatch(r"[0-9a-fA-F]{32}", expected_hash):
                raise ValueError("Invalid FileHash")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ExtractionError("Malformed or changed TikTok media metadata") from exc

        # The domain-scoped tt_chain_token cookie is attached by CookieJar.
        with self.open(url, {"Referer": REFERER, "Accept": "*/*"}, "media") as response:
            if response.status != 200:
                raise ExtractionError(f"media: expected a complete HTTP 200 response, got {response.status}")
            if response.headers.get_content_type() != "video/mp4":
                raise ExtractionError("media: response is not video/mp4")
            content_length = int(response.headers.get("Content-Length", "0"))
            digest = hashlib.md5(usedforsecurity=False)
            size = 0
            prefix = b""
            # Publish only after validation; never overwrite an existing file.
            with tempfile.TemporaryFile(dir=destination.parent) as temporary:
                while chunk := response.read(256 * 1024):
                    prefix = (prefix + chunk)[:12] if len(prefix) < 12 else prefix
                    size += len(chunk)
                    digest.update(chunk)
                    temporary.write(chunk)
                if len(prefix) < 12 or prefix[4:8] != b"ftyp":
                    raise ExtractionError("media: missing MP4 ftyp box")
                if any(expected and size != expected for expected in (content_length, expected_size)):
                    raise ExtractionError("media: truncated response or metadata size mismatch")
                checksum = digest.hexdigest()
                if expected_hash and checksum != expected_hash.lower():
                    raise ExtractionError("media: FileHash checksum mismatch")
                temporary.seek(0)
                with destination.open("xb") as output:
                    shutil.copyfileobj(temporary, output)
        return {"bytes": size, "md5": checksum, "file_hash_verified": bool(expected_hash)}


def extract(url, output_dir="."):
    """Resolve a fresh URL, download its complete MP4, and return a JSON-safe result."""
    identifier = video_id(url)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if identifier is not None and (directory / f"{identifier}.mp4").exists():
        raise ExtractionError(f"Refusing to overwrite {directory / f'{identifier}.mp4'}")
    extractor = Extractor()
    item = extractor.resolve(url)
    identifier = str(item["id"])
    destination = directory / f"{identifier}.mp4"
    if destination.exists():
        raise ExtractionError(f"Refusing to overwrite {destination}")
    integrity = extractor.download(item, destination)
    video = item["video"]
    return {
        "id": identifier,
        "author": item.get("author", {}).get("uniqueId"),
        "description": item.get("desc", ""),
        "duration": video.get("duration"),
        "width": video.get("width"),
        "height": video.get("height"),
        "codec": video.get("codecType"),
        "path": str(destination),
        "requests": extractor.counter.count,
        **integrity,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="Public TikTok video URLs or vm.tiktok.com short links")
    parser.add_argument("--test", action="store_true", help="Download and verify all nine PROMPT.md URLs in separate case directories")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="Destination directory (default: current directory)")
    args = parser.parse_args()
    if bool(args.urls) == args.test:
        parser.error("Supply URL(s), or --test, but not both")
    failed = False
    for index, url in enumerate(TEST_URLS if args.test else args.urls, 1):
        # Short and full URLs can identify the same video; test each independently.
        output_dir = args.output_dir / f"case-{index:02d}" if args.test else args.output_dir
        try:
            print(json.dumps(extract(url, output_dir), ensure_ascii=False), flush=True)
        except (ExtractionError, OSError, ValueError, http.client.HTTPException) as exc:
            failed = True
            print(f"Input {index}: {exc}", file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
