<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# TikTok public-video playback without a browser

## Result and scope

`example.py` implements **full or short URL → public video document → metadata → signed media request → verified MP4** using only Python's standard library. All **nine exact URLs in `PROMPT.md` passed two fresh-session end-to-end runs** on 2026-09-14 UTC. They identify five distinct videos.

The essential finding is that **the server-rendered document already contains signed media URLs**. Preserve the chosen URL and retain the page-issued **`tt_chain_token` cookie plus `Referer: https://www.tiktok.com/`** for its media request. No browser, JavaScript runtime, imported browser state, credentials, third-party extractor, or signing service is needed by the script.

This documents the observed public-video playback chain, not a recovered implementation of TikTok's entire obfuscated anti-bot SDK. Server signing keys, signature formulas, and exact token bindings remain unknown. Obtaining a fresh signed URL and its cookies from the public document makes those algorithms unnecessary for this route.

## Run and reuse

The two deliverables live in `src/agent`, the requested working directory. The standalone example requires Python 3.10+; both current live runs used Python 3.14.7. It needs no third-party packages. The extraction chain remains valid without changes to `example.py`.

For the **Tokai application**, use the repository's Python 3.14 and locked dependencies (including the development test group). With `uv` installed; validated with uv 0.12.6:

```sh
# From the repository root; uv downloads Python 3.14 if needed:
uv sync --frozen --all-groups
uv run --no-sync pytest -q
uv run --no-sync python -m web.main
```

The server defaults to `http://127.0.0.1:8000`, with `TOKAI_LOG_LEVEL=info`. Override `TOKAI_HOST`, `TOKAI_PORT`, and `TOKAI_LOG_LEVEL` in the environment if needed; no credentials or `.env` file are required. The browser and FFmpeg are investigation/validation tools, not application or example runtime dependencies.

```sh
cd src/agent

python3 example.py 'https://vm.tiktok.com/ZMAYuMpFQ/' \
  --output-dir /tmp/tiktok-video

# Independently download and verify every exact PROMPT.md URL:
python3 example.py --test --output-dir /tmp/tiktok-regression

# Use the repository's Python version without building its package:
uv run --no-project --python 3.14 example.py --test \
  --output-dir /tmp/tiktok-regression-314
```

Use a new output directory for each run. Normal extraction creates `<output-dir>/<video-id>.mp4` and refuses to overwrite existing files. `--test` creates `case-01/` through `case-09/` beneath the output directory: short links duplicate four full URLs, so each case needs its own destination to test the entire chain independently, without caching or skipping downloads.

Quote URLs containing `&`. Multiple positional URLs are supported; positional URLs and `--test` are mutually exclusive. Successful extractions print one JSON record with ID, author, description, duration, dimensions, codec, path, HTTP request count, byte count, MD5, and `file_hash_verified`. Failures go to stderr and make the final exit code nonzero; later inputs are still attempted. Signed URLs and cookie values are not printed.

From Python, with `src/agent` on the import path:

```python
from example import extract

result = extract("https://vm.tiktok.com/ZMAYuMpFQ/", "/tmp/my-video")
print(result["path"])  # Local MP4, playable in ffplay, VLC, etc.
```

`Extractor.resolve(url)` returns `itemStruct`; `Extractor.download(item, Path(...))` downloads the media. **Use the same Extractor instance for both** so the cookie jar survives. `extract()` does this automatically with a fresh session for each input. `video_id(url)` validates supported input URLs and returns the numeric path ID, or `None` for an unresolved short link.

## 1. Browser investigation and frontend source

Investigated on **2026-09-14 UTC**, using an isolated, logged-out Playwright Chromium session with the skill's stealth configuration. The page reported region `BR`. Browser investigation and plain Python requests used the same machine/network; no browser cookies were exported to the implementation.

Observed for `https://vm.tiktok.com/ZMAYuMpFQ/`:

1. The browser reached video `7542076400346451232` and displayed the actual caption and author. Its address ultimately contained `@nerublanco`, while the plain HTTP redirect target had an empty handle (`/@/video/...`). The script does not need the browser's later address normalization.
2. `__UNIVERSAL_DATA_FOR_REHYDRATION__` contained `webapp.video-detail.statusCode == 0` and the complete video object.
3. The video was actively playing: `readyState == 4`, `paused == false`, and `currentTime` advanced. Its `currentSrc` was a `blob:` URL, not a remotely fetchable media address.
4. Initial captured media requests returned `200`, `Content-Type: video/mp4`, with a full content length and no Range header. Matching their URLs against the document's `bitrateInfo` identified **H.264 `lower_540_0`, 697,930 bits/s, 4,466,758 bytes**, not the default `playAddr` (7,515,994 bytes). A later request sent `Range: bytes=4143469-` and received `206`, `Content-Range: bytes 4143469-4466757/4466758`, and 323,289 bytes. The browser can request partial media too; this does not establish its precise seeking/adaptation algorithm. Browser quality selection must not be conflated with the script's fixed default-rendition choice.
5. Recommendation, login, analytics, subtitle, and security traffic continued separately. A login UI later changed the document title to “Log in | TikTok” while the video was still playing; a title alone does not establish playback failure.
6. The browser loaded the two security bundles below and contacted `mssdk-sg.tiktok.com/web/resource` and `/web/report`. These requests are omitted from the verified Python chain.

### Source inspected afresh

The desktop asset base was:

```text
https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/tiktok/webapp/main/react-v18/webapp-desktop/static/js/
```

Offsets below are zero-based character offsets in the freshly fetched, decoded JavaScript, not stable API locations.

| Asset | Relevant evidence |
| --- | --- |
| `webapp-desktop.2e529377.js` | Hydration marker at offset 244104: reads `document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__").textContent`, parses JSON, and looks up the requested key under `__DEFAULT_SCOPE__`. |
| `player.init.b4c53adc.js` | Near 196850, consumes `playAddr`, bitrate, size, format, codec, duration, `bitrateInfo`, audio variants, and optional `PlayAddrStruct`. Uses `i=H?G(H):{url:p}`: an address struct if present, otherwise the default play address. Builds a rendition list from that metadata. |
| `player.init.b4c53adc.js` | Near 226259, checks MediaSource/WebKitMediaSource and availability of `isTypeSupported`, recognizes blob URLs, and contains an expiry classifier for `expire`, `x-tos-expires`, `x-expires`, or a hexadecimal path component. It compares parsed expiry to current UTC time; this does not reveal the server signature algorithm. |
| `biz.common.lib.f35e4b90.js` | At 256750, uses `MediaSource.isTypeSupported` for HEVC codec strings. Playback is capability-dependent. |
| `webmssdk/1.0.0.417/webmssdk.js` | Under `/obj/tiktok_web_login_static/`, not the desktop base. At 26281–26619, exposes state names including `bogusIndex`, `WEBGL`, `envcode`, `msToken`, `fetchSignTime`, and `XHRSignTime`, followed by extended-proof state. The algorithmic implementation is obfuscated. |
| `ttweb_webmssdk_ex/1.0.0.2858/webmssdk_ex.js` | Extended obfuscated security bundle, also under `/obj/tiktok_web_login_static/`. The same state names and extended-proof fields are visible near 55212–55500. |

These observations do not recover the whole media engine, its precise SourceBuffer append/range logic, or adaptive-quality decision algorithm. The Python implementation downloads a complete default MP4 instead of reproducing in-browser rendering, adaptation, or seeking.

## 2. Minimal request chain, including short links

```text
Input full video URL                         Input vm.tiktok.com/<code>/
         │                                              │
         │                                      GET short URL → HTTP 302
         │                                              │ Location
         └─────────────────────┬────────────────────────┘
                               ▼
                GET /@handle/video/<id>?share_...
                (handle may be empty: /@/video/<id>)
                  ├─ retain Set-Cookie in CookieJar
                  └─ parse hydration from THIS response
                               │
                local availability / identity / format checks
                               │
                GET unchanged video.playAddr, same cookie jar
                  Referer: https://www.tiktok.com/
                               │
                complete MP4 → size/container/hash checks → file
```

**Normally two GETs for full URLs, three for the tested short URLs.** There is no homepage warmup, HEAD, oEmbed call, item-detail API, signature endpoint, canonical-page refetch, alternate-quality probe, or preliminary range request.

### Short-link resolution

The accepted short-link form is `https://vm.tiktok.com/<alphanumeric-code>/` (final slash optional). The four supplied links each returned a **302** to an HTTPS video document on `www.tiktok.com`:

| Short code | Redirect path | Hydrated author |
| --- | --- | --- |
| `ZMAYuMpFQ` | `/@/video/7542076400346451232` | `nerublanco` |
| `ZMAj83k4w` | `/@/video/7544010904229252358` | `metropolesoficial` |
| `ZMA4ncut8` | `/@/video/7562939840271076615` | `metropolesoficial` |
| `ZMAVwmojg` | `/@/video/7286599702303362310` | `casamentosemdividas` |

The inspected Location query included `_d`, `_r`, `share_app_id`, `share_item_id`, `timestamp`, `u_code`, `utm_campaign`, and `utm_source`. It is followed as supplied, not synthesized from the short code. There is no hardcoded mapping in the extractor.

`urllib` follows redirects and retains cookies automatically. **The final response already is the video page**: parse it, do not fetch its URL a second time. The final URL must be a supported full TikTok video URL, and its path ID must match hydration. For a full input URL, redirects must also preserve the original video ID. Never use `share_item_id` as the authoritative ID or require a nonempty username to identify the video.

### Video-document request

```http
GET /@handle/video/<id>?share_... HTTP/1.1
Host: www.tiktok.com
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36
Accept: text/html
Accept-Language: en-US,en;q=0.9
```

The same headers are used for short-link resolution. Full input URLs may use `www.tiktok.com` or `tiktok.com`, HTTPS, and `/@handle/video/<numeric-id>`; an empty handle is accepted for share redirects. Queries are preserved. Photo posts, feeds, live streams, other short-link hosts, and non-video destinations are outside this interface.

A successful document contains:

```text
__UNIVERSAL_DATA_FOR_REHYDRATION__
└── __DEFAULT_SCOPE__
    └── webapp.video-detail
        ├── statusCode: 0
        └── itemInfo.itemStruct
            ├── id / author / desc
            ├── privateItem / secret / forFriend / isProhibited / takeDown
            └── video
                ├── playAddr / downloadAddr
                ├── size / duration / width / height / codecType / format
                └── bitrateInfo[]
                    ├── CodecType / Bitrate / Format / GearName
                    └── PlayAddr
                        ├── UrlList[]
                        ├── DataSize
                        └── FileHash
```

The parser treats the script text as JSON, not executable JavaScript. JSON decoding handles escaped slashes and `\u002F`/`\u0026`; do not HTML-unescape it again or decode/re-encode the signed query. HTTP 200 is insufficient: require `statusCode == 0`, matching IDs, no active restriction flags listed above, an HTTPS play address, and MP4 format. These flag checks are conservative local checks; the server status and metadata remain authoritative.

### Conditional HTTP-200 app-shell recovery

The implementation recognizes a hydration-free app shell by this exact marker:

```html
data-source="downgrade-mssdk-preload"
```

The implementation waits one second and retries **only that document once**, in the same session, if hydration is absent and this marker exists. For a short input, it retries the **resolved video URL**, not the short link. This avoids paying for the same redirect again.

No such shell occurred in either current live run, so recovery was not demonstrated live in this audit. Offline tests verify the bounded retry and final-page-only behavior. Repeated shells, arbitrary challenges, HTTP errors, and unavailable items are not retried. No CAPTCHA/WAF solver or signed-API/browser fallback is implemented.

Both live runs used exactly **2 GETs per full URL and 3 per short URL**. A recognized-shell retry adds one GET, yielding **2–3 for a full URL, 3–4 for a short URL** with the observed redirect topology. Additional real redirects, if TikTok introduces them, also count. `RequestCounter` counts actual requests, including redirects and the bounded retry.

## 3. Cookies, signatures, and checks

### Page-issued cookie chain

| Cookie | Evidence-supported role |
| --- | --- |
| `tt_chain_token` | HttpOnly, scoped to `.tiktok.com`; required for the tested media URL. An HTTP cookie jar can use it even though page JavaScript cannot read it. |
| `ttwid` | Visitor/session state; not needed in the chain-cookie-only media control. |
| `tt_csrf_token` | Page-issued CSRF state; not needed for this read-only chain. |
| `msToken` | Security/session state, also seen in browser API queries; not needed for the tested media GET with chain cookie and Referer. |

The returned media query contains `tk=tt_chain_token`: this is the **cookie name**, not its value. Leave it untouched. `CookieJar` sends domain/path/secure-matching cookies to the CDN; do not copy browser cookies into a global Cookie header or insert token values into the URL. Tokens and media URLs are obtained together for each extraction, without importing another session.

### Server-issued media signature — used

A redacted, nonfunctional URL shape:

```text
https://v16-webapp-prime.tiktok.com/video/tos/<region>/<object>/
?a=1988&bti=<opaque>&&bt=<rate>&ft=<opaque>&mime_type=video_mp4
&rc=<opaque>&expire=<unix-seconds>&l=<request-context>
&ply_type=2&policy=2&signature=<32-hex-value>&tk=tt_chain_token&btag=<opaque>
```

The URL and `signature` appear in raw HTTP HTML before JavaScript executes. The client obtains this freshly signed media capability; it does not calculate one.

- Preserve the host, path, complete query, ordering, repeated separators, and parameter values. The script does not reconstruct the URL.
- `expire` is an epoch-looking expiry. The player has expiry-classification code, but no fixed lifetime should be assumed. Obtain fresh metadata instead of storing media URLs as permanent identifiers.
- A 32-hex `signature` does **not** establish MD5, HMAC, which fields are signed, or the signing secret.
- Replacing the signature produced 403. Setting `expire=1` also produced 403, which does not distinguish expiry rejection from signed-field tampering.
- Exact session/IP/path binding and server validation internals remain unknown.

Some rendition metadata also offers a `www.tiktok.com/aweme/v1/play/` URL with fields such as `file_id`, `video_id`, `item_id`, `pt`, and `signaturev3`. It is an alternative address, not a required preliminary endpoint. The example uses the supplied default CDN URL, not a synthesized play endpoint.

### Browser API signatures — observed, not required

Captured `/api/related/item_list/` requests included desktop context such as `aid=1988`, `device_platform=web_pc`, browser/language/region fields, device/session identifiers, and:

| Field | Observation |
| --- | --- |
| `X-Dynosaur` | Long varying query value. |
| `msToken` | Security/session query value; absent from an initial captured request and present in a later one. |
| `X-Bogus` | Literal `1` in captured related-item requests; not an assumed historical signature format. |
| `X-Gnarly` | Long varying query value. |

The SDK bundles, environment/signing state names, resource requests, and report traffic establish an active security subsystem. They do **not** establish a recovered algorithm or identical checks across all endpoints. The Python script does not call these APIs, replay their signatures, invent device IDs, or reproduce browser fingerprints. Initial-video metadata is already in hydration; its media URL uses a separate server-issued signature/cookie chain.

### Controlled media experiments

Repeated during this investigation using fresh Python metadata for `7544010904229252358`. Each probe requested `Range: bytes=0-1023` solely to reduce research traffic; the extraction script does not perform these probes.

| Variation | Result |
| --- | --- |
| All page cookies + Chrome UA + TikTok Referer + unchanged URL | `206`, `video/mp4`, 1,024 bytes, MP4 `ftyp` |
| Only `tt_chain_token`, same UA/Referer/URL | Same successful `206` |
| Other cookies without `tt_chain_token` | `403` |
| Chain cookie and UA without Referer | `403` |
| Page cookies and Referer, Python urllib UA for media only | Successful `206` |
| Signature replaced with zeros | `403` |
| `expire` replaced with `1` | `403` |

These show necessary conditions for the tested combination, not universal policy across every region or future CDN version. The document request still uses the Chrome-like UA; the default-UA control concerns only media.

## 4. Media retrieval and integrity

The script selects **`video.playAddr`**, not an arbitrary MP4-looking string or the first bitrate entry. All five tested defaults were MP4/H.264, with muxed AAC audio, 576 × 1024. Browser adaptation can select another rendition, as observed above; highest-quality or browser-identical selection is not claimed.

`bitrateInfo` supplies alternative addresses and integrity metadata. Matching the chosen URL exactly against `PlayAddr.UrlList` yields its `DataSize` and `FileHash`, without extra requests. `downloadAddr` is a distinct asset; it is not needed for playback and its name alone does not prove a watermark policy. Covers and subtitles are not media candidates.

```http
GET /video/tos/<exact-path>/?<unchanged-signed-query> HTTP/1.1
Host: v16-webapp-prime.tiktok.com
User-Agent: <same as the document request>
Accept: */*
Referer: https://www.tiktok.com/
Cookie: <automatically domain-scoped page cookies>
```

No Range header or OPTIONS preflight is sent. The captured CDN responses advertised byte ranges and browser CORS headers (`Access-Control-Allow-Origin: https://www.tiktok.com`, credentials support). CORS is enforced by browsers, not a requirement to emulate preflights in Python. The working requests require no Origin, client hints, or Sec-Fetch headers.

Validation before publishing a file:

1. Complete HTTP `200`, not `206`, and `Content-Type: video/mp4`.
2. MP4 `ftyp` at the beginning, not an HTML denial under an MP4 filename.
3. Actual byte count matches Content-Length and fresh metadata size when present.
4. MD5 matches the chosen rendition's `FileHash` when present. This matched every live extraction. MD5 here checks integrity, not authenticity or the media URL signature.

The response streams to a temporary file before validation and exclusive creation of the destination. Existing files are preserved. Transfer/validation failures do not publish that temporary media. Final copying is **not crash-atomic**: a disk/write failure during publication can leave a partial destination; an errored extraction is never success. These checks are not a codec decoder; full decoding was separately validated below.

## 5. Live validation results

Both runs used Python 3.14.7 from the repository's uv-created `.venv` on 2026-09-14 UTC. Every case used a fresh Extractor/cookie jar, fetched fresh metadata, and downloaded the entire MP4. Case order is exactly `PROMPT.md` order. Request counts include all redirects; neither run needed shell retries.

| Case | Input | Video ID | Bytes | Run 1 GETs | Run 2 GETs | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | Full, `casamentosemdividas` | 7286599702303362310 | 1,686,277 | 2 | 2 | PASS |
| 02 | Full, `causanobrecerimonial` | 7502602409370307845 | 3,370,911 | 2 | 2 | PASS |
| 03 | Full, `metropolesoficial` | 7562939840271076615 | 3,559,532 | 2 | 2 | PASS |
| 04 | Full, `metropolesoficial` | 7544010904229252358 | 6,475,232 | 2 | 2 | PASS |
| 05 | Full, `nerublanco` | 7542076400346451232 | 7,515,994 | 2 | 2 | PASS |
| 06 | `vm.tiktok.com/ZMAYuMpFQ/` | 7542076400346451232 | 7,515,994 | 3 | 3 | PASS |
| 07 | `vm.tiktok.com/ZMAj83k4w/` | 7544010904229252358 | 6,475,232 | 3 | 3 | PASS |
| 08 | `vm.tiktok.com/ZMA4ncut8/` | 7562939840271076615 | 3,559,532 | 3 | 3 | PASS |
| 09 | `vm.tiktok.com/ZMAVwmojg/` | 7286599702303362310 | 1,686,277 | 3 | 3 | PASS |

All copies of each video, including full/short inputs, matched these hashes and the **fresh server FileHash**:

```text
7286599702303362310  0ec4ec2f47fb8c1ab4ed2fa729c7f918
7502602409370307845  6f72036ef200462416acf8bf95aa80d7
7562939840271076615  99d152615736924bbeb3950460235fe2
7544010904229252358  ddf05108de1ddbfee96113ac9ec48120
7542076400346451232  186c3d2051d39111c4d8775030bd7641
```

These hashes are evidence, not hardcoded expectations: future legitimate transcodes can change them.

Validation performed:

- Compilation with `py_compile`; CLI help, missing arguments, mutually exclusive inputs, and unsupported-URL checks.
- 16 temporary offline unittest cases for `example.py`: the exact nine-URL list, URL validation, no duplicate page GET, empty handles, ID mismatches, bounded final-page-only shell recovery, availability/schema checks, signature preservation, media integrity, no overwrite, and independent test destinations/error continuation. These use mocked responses; actual redirects/cookies were exercised by the live runs and controls.
- All **58 repository pytest tests passed**, covering the application, scraper, environment, and URL helpers. Two upstream dependency deprecation warnings were emitted; no failures.
- Both complete live `--test` runs above, plus the seven controlled media variants in section 3.
- Actual Tokai server smoke test: homepage, video page, and `/media/7542076400346451232` all returned HTTP 200. The served MP4 was byte-identical to the standalone example's download.
- `ffprobe` 5.1.9 on all nine Run 1 files: H.264/AAC, 576 × 1024. Reported container durations for cases 01–05 were 68.367000, 22.434000, 12.634000, 73.067000, and 51.200000 seconds; short-link copies matched.
- Full `ffmpeg -xerror` audio/video decoding of **all nine Run 1 files**: exit 0, empty stderr.

Research captures, the offline test harness, and downloaded videos were kept outside the repository in `/tmp/tokai-audit-research`, preserving the two-file deliverable. They are temporary local artifacts, not required dependencies or committed fixtures.

Reproduce live media checks from `src/agent` (FFmpeg is optional validation tooling, not a script dependency):

```sh
python3 example.py --test --output-dir /tmp/tiktok-new-run
for file in /tmp/tiktok-new-run/case-*/*.mp4; do
  ffprobe -v error -show_entries \
    'format=duration,size:stream=codec_name,codec_type,width,height' -of json "$file" || exit 1
  ffmpeg -nostdin -v error -xerror -i "$file" \
    -map 0:v:0 -map 0:a:0 -f null - || exit 1
done
```

## 6. Boundaries and failure diagnosis

| Symptom | Interpretation/action |
| --- | --- |
| Short link no longer redirects to a supported video page | Expired/changed link or unsupported destination; extraction stops. |
| Redirect or hydration ID mismatch | Response does not identify the requested video; no media is saved. |
| Missing hydration after the recognized-shell retry | Repeated shell, challenge, or changed frontend. No challenge solver or alternate API is attempted. |
| Nonzero detail status or restriction flag | Content unavailable/restricted in this context; no login, private-content, CAPTCHA, or geographic-restriction bypass. |
| CDN 403 | Check same-session fresh URL/cookies, Referer, and unchanged signed fields. Changed CDN policy may require reinvestigation. |
| Container/size/hash failure | Transfer or metadata mismatch; do not count the attempt as successful. |
| Destination exists | Use a fresh output directory. Short inputs need resolution before the target filename is known, but no media request is made after that collision is detected. |

All live claims are limited to the observed date, machine/network, public content, and frontend version. The script relies on TikTok-issued redirects and media addresses; it is a local example, not a hardened server-side fetch service for untrusted users. Availability, signatures, cookie policy, and screening can change. Use only content you are authorized to access and retain. Cookie values, signed URLs, and raw captures are not included in the deliverables.
