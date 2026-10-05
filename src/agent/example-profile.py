#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extract public TikTok profile metadata and a creator-embed video preview.

Uses only Python's standard library. This is NOT a complete/paginated archive.
TikTok may deny the preview even when profile metadata is public; see DOCS.md.
The video_urls in a successful result are inputs to example-video.py.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import http.client
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
TEST_URLS = (
    "https://www.tiktok.com/@casamentosemdividas",
    "https://www.tiktok.com/@causanobrecerimonial",
    "https://www.tiktok.com/@metropolesoficial",
    "https://www.tiktok.com/@nerublanco",
)
HYDRATION_ID = "__UNIVERSAL_DATA_FOR_REHYDRATION__"
EMBED_ID = "__FRONTITY_CONNECT_STATE__"


class ExtractionError(Exception):
    """No verified profile/list result; profile holds metadata if already fetched."""

    def __init__(self, message, profile=None):
        super().__init__(message)
        self.profile = profile


class ScriptParser(HTMLParser):
    def __init__(self, script_id):
        super().__init__(convert_charrefs=False)
        self.script_id = script_id
        self.inside = False
        self.found = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == self.script_id:
            self.inside = self.found = True

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


def profile_handle(url):
    """Accept an HTTPS profile URL, not a post, credentialed URL, or arbitrary host."""
    try:
        parsed = urllib.parse.urlsplit(url)
        match = re.fullmatch(r"/@([A-Za-z0-9_.]+)/?", parsed.path)
        if parsed.scheme == "https" and parsed.netloc in {"www.tiktok.com", "tiktok.com"} and match:
            return match[1]
    except ValueError:
        pass
    raise ExtractionError("Expected an HTTPS TikTok /@handle profile URL")


def parse_profile(data, expected_handle):
    try:
        detail = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        if detail["statusCode"] != 0:
            raise ExtractionError(f"TikTok user-detail statusCode={detail['statusCode']!r}; unavailable")
        info = detail["userInfo"]
        user = info["user"]
        handle = user["uniqueId"]
        if not re.fullmatch(r"[A-Za-z0-9_.]+", handle) or handle.casefold() != expected_handle.casefold():
            raise ExtractionError("Hydration handle does not match the requested profile")
        identifier = str(user["id"])
        if not re.fullmatch(r"[0-9]+", identifier):
            raise ValueError("Invalid user ID")
        if user.get("privateAccount") or user.get("secret"):
            raise ExtractionError("TikTok marks this profile as private or restricted")
        stats = info.get("statsV2") or info["stats"]
        stats = {key: int(value) for key, value in stats.items()}
        if "videoCount" not in stats or any(value < 0 for value in stats.values()):
            raise ValueError("Missing or invalid profile counts")
        return {
            "profile_url": f"https://www.tiktok.com/@{handle}",
            "id": identifier,
            "handle": handle,
            "nickname": user.get("nickname", ""),
            "bio": user.get("signature", ""),
            "verified": bool(user.get("verified")),
            "created_at": user.get("createTime"),
            "sec_uid": user.get("secUid"),
            "statistics": stats,
        }
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExtractionError("Malformed or changed TikTok profile hydration schema") from exc


def parse_preview(data, profile):
    """Validate the creator route, not an unrelated/recommended video list."""
    try:
        link = data["router"]["link"]
        if link.rstrip("/").casefold() != f"/embed/@{profile['handle']}".casefold():
            raise ExtractionError("Embed route does not match the requested profile")
        page = data["source"]["data"][link]
        if page["isError"] or page["pageName"] != "creator":
            raise ExtractionError(f"Creator embed unavailable (errorCode={page.get('errorCode')!r})")
        user = page["userInfo"]
        if str(user["id"]) != profile["id"] or user["uniqueId"].casefold() != profile["handle"].casefold():
            raise ExtractionError("Embed author does not match the profile metadata")
        if user.get("privateAccount"):
            raise ExtractionError("Creator embed marks this profile as private")
        items = page["videoList"]
        if not isinstance(items, list):
            raise ValueError("Invalid videoList")
        videos = []
        seen = set()
        for item in items:
            if item.get("privateItem") or item.get("imagePost") or item.get("imagePostInfo"):
                continue
            # Covers and photo entries without a playback address are not MP4 candidates.
            if not item.get("playAddr"):
                continue
            identifier = str(item["id"])
            if not re.fullmatch(r"[0-9]+", identifier):
                raise ValueError("Invalid video ID")
            if item["authorUniqueId"].casefold() != profile["handle"].casefold():
                raise ExtractionError("Creator preview contains a different author's video")
            if identifier in seen:
                continue
            seen.add(identifier)
            videos.append({
                "id": identifier,
                "url": f"{profile['profile_url']}/video/{identifier}",
                "description": item.get("desc", ""),
                "play_count": item.get("playCount"),
            })
        if not videos:
            raise ExtractionError(
                "Creator embed returned no playable video entries; this does not prove the profile is empty"
            )
        return videos
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExtractionError("Malformed or changed TikTok creator-embed schema") from exc


class RequestCounter(urllib.request.BaseHandler):
    def __init__(self):
        self.count = 0

    def http_request(self, request):
        self.count += 1
        return request

    https_request = http_request


class ProfileRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, handle):
        self.handle = handle.casefold()

    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        allowed_paths = {f"/@{self.handle}", f"/embed/@{self.handle}"}
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"www.tiktok.com", "tiktok.com"}
            or parsed.path.rstrip("/").casefold() not in allowed_paths
        ):
            raise ExtractionError("Redirect left the requested TikTok profile")
        return super().redirect_request(request, fp, code, message, headers, newurl)


class Extractor:
    def __init__(self, handle):
        self.counter = RequestCounter()
        self.opener = urllib.request.build_opener(
            self.counter,
            ProfileRedirects(handle),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT)]

    def document(self, url, script_id):
        for attempt in range(2):
            request = urllib.request.Request(url, headers={
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "identity",
            })
            try:
                with self.opener.open(request, timeout=45) as response:
                    if response.status != 200:
                        raise ExtractionError(f"document: unexpected HTTP {response.status}")
                    url = response.geturl()
                    html = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                raise ExtractionError(f"document: HTTP {code}; profile/list unavailable (no automatic retry)") from exc
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                raise ExtractionError(f"document: network response failed ({type(exc).__name__})") from exc
            except UnicodeError as exc:
                raise ExtractionError("Document is not valid UTF-8") from exc
            parser = ScriptParser(script_id)
            parser.feed(html)
            if parser.found:
                try:
                    return json.loads("".join(parser.parts))
                except ValueError as exc:
                    raise ExtractionError("Document contains malformed hydration JSON") from exc
            if script_id == HYDRATION_ID and attempt == 0 and 'data-source="downgrade-mssdk-preload"' in html:
                time.sleep(1)
                continue
            raise ExtractionError("Document has no expected hydration (challenge, denial, or changed frontend)")


def extract(url):
    """Return metadata plus a partial video preview; never claim a complete archive."""
    handle = profile_handle(url)
    extractor = Extractor(handle)
    profile = parse_profile(extractor.document(url, HYDRATION_ID), handle)
    # A zero server-reported post count needs no listing request.
    videos = []
    source = "profile_post_count"
    if profile["statistics"]["videoCount"]:
        try:
            data = extractor.document(f"https://www.tiktok.com/embed/@{profile['handle']}", EMBED_ID)
            videos = parse_preview(data, profile)
        except ExtractionError as exc:
            exc.profile = profile
            raise
        source = "creator_embed_preview"
    return {
        **profile,
        "videos": videos,
        "video_urls": [video["url"] for video in videos],
        "listing": {"source": source, "complete": False},
        "requests": extractor.counter.count,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="Public HTTPS TikTok /@handle profile URLs")
    parser.add_argument("--test", action="store_true", help="Independently test all four PROMPT.md profiles")
    args = parser.parse_args()
    if bool(args.urls) == args.test:
        parser.error("Supply URL(s), or --test, but not both")
    failed = False
    for index, url in enumerate(TEST_URLS if args.test else args.urls, 1):
        try:
            print(json.dumps(extract(url), ensure_ascii=False), flush=True)
        except (ExtractionError, OSError, ValueError, http.client.HTTPException) as exc:
            failed = True
            error = {"input": index, "error": str(exc)}
            if isinstance(exc, ExtractionError) and exc.profile is not None:
                error["profile_metadata"] = exc.profile
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr, flush=True)
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
