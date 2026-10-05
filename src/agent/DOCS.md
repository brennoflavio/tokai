<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# TikTok public video and profile extraction without a browser

## Status — 2026-10-05 UTC

**Video extraction is verified. Profile extraction is incomplete against the requested live test set.** Do not read the existence of the profile script as an all-tests-pass claim.

| Deliverable | Implemented and observed | Remaining limitation |
| --- | --- | --- |
| [`example-video.py`](example-video.py) | Full/short URL → fresh public document → metadata → cookie-bound signed media URL → verified MP4. **9/9 exact video URLs passed.** | Public MP4 posts only; no browser/API signer required on this route. |
| [`example-profile.py`](example-profile.py) | Profile document → account metadata; creator-embed document → a **partial video preview** when available; canonical video URLs feed the video script. | All four profiles returned metadata, but all four final preview requests returned HTTP 503. **0/4 complete profile tests passed.** No working desktop API signer or pagination implementation was recovered. |

One earlier, live `metropolesoficial` creator-embed response contained ten videos. Its captured schema passes the parser, and its first video was subsequently downloaded and fully decoded through `example-video.py`. This is evidence for the preview route and the interface between the scripts, **not** a successful final four-profile run. An earlier `casamentosemdividas` embed response had an empty `videoList` despite a positive post count; the script deliberately rejects that as an unverified listing.

The requirement in [`PROMPT.md`](PROMPT.md) to pass **all** supplied URLs therefore remains unmet. Desktop post-list signing/security checks, stable preview availability, and a complete profile archive are unresolved. No CAPTCHA solver, imported browser cookies, third-party scraper, signing service, hardcoded video list, or silent success on empty/denied responses is used.

## Running the standalone examples

Both scripts use only Python's standard library, Python 3.10+. This audit ran them with Python 3.14.4. Browser tools and FFmpeg were investigation/validation tools, not runtime dependencies.

```sh
# From the repository root; quote URLs containing '&'.
python src/agent/example-video.py 'https://vm.tiktok.com/ZMAYuMpFQ/' \
  --output-dir /tmp/my-tiktok-video

python src/agent/example-video.py --test \
  --output-dir /tmp/my-tiktok-video-tests

python src/agent/example-profile.py 'https://www.tiktok.com/@metropolesoficial'

# Tests every profile independently, continuing after errors.
# This exited 1 in the final audit: metadata succeeded, previews were denied.
python src/agent/example-profile.py --test
```

Video extraction refuses to overwrite `<output-dir>/<video-id>.mp4`. Use a fresh directory. `--test` uses independent `case-01` through `case-09` directories so full and short links to the same post each exercise the complete chain. Each case has a new cookie jar. Successful results are JSON lines on stdout; any failure makes the exit code nonzero.

The profile script prints JSON only for successful metadata-plus-list results. On a listing failure, stderr contains an error record with `profile_metadata` when already retrieved; stdout does **not** present this as a successful empty list. Callers must check the exit code. HTTP 403/429/503 and empty previews are not automatically retried. Respect any rate limit and defer another attempt; repeated requests are not a reliable cure for an unavailable upstream service.

### Reuse and profile → video interface

The requested filenames contain hyphens, so use `runpy` or `importlib`, not `from example-profile import ...`:

```python
import runpy

profile_api = runpy.run_path("src/agent/example-profile.py")
video_api = runpy.run_path("src/agent/example-video.py")

# Raises ExtractionError if the listing cannot be verified.
profile = profile_api["extract"]("https://www.tiktok.com/@metropolesoficial")
print(profile["nickname"], profile["statistics"])
print(profile["listing"])  # complete is deliberately False

for url in profile["video_urls"][:1]:
    result = video_api["extract"](url, "/tmp/profile-video")
    print(result["path"])  # Play this local MP4 in VLC, ffplay, etc.
```

`video.Extractor.resolve(url)` returns the raw `itemStruct`; `download(item, Path(...))` retrieves its MP4. Use the **same Extractor instance** for both. The convenience `extract()` manages this automatically. Profile results expose `videos` (ID, canonical URL, description, play count), `video_urls`, account metadata, `listing`, and the actual request count. They do not expose embed media URLs as durable playback links. A newly fetched video document, with its own fresh cookies and media URL, is the authoritative availability check.

## 1. Investigation environment and source evidence

Investigation used the skill's `playwright-safe` wrapper attached to the **shared** CDP Chromium browser. A dedicated tab was created, closed, and the CLI session detached afterward. A named session is not an isolated browser profile. No browser cookies/storage were exported, reset, or used by the Python implementations. The TikTok UI showed a login prompt and reported region `BR`; this does not establish an isolated/fresh browser identity.

The public `nerublanco` test video actively played: `readyState=4`, `paused=false`, and `currentTime` advanced from 3.836794 to 5.836825 seconds over two seconds. `currentSrc` was a `blob:` URL, not a directly fetchable media address. The page title was “Log in | TikTok” during playback: a title alone is not a playback test.

Opening the `casamentosemdividas` and `nerublanco` desktop profiles produced a slider CAPTCHA and no video links. Waiting and one reload of the first profile did not resolve it. No CAPTCHA interaction was attempted. Browser requests to `/api/post/item_list/` contained `msToken`, `X-Dynosaur`, `X-Bogus`, and `X-Gnarly`; the captured post-list response body was empty. HTTP 200 alone is not a valid JSON/list result.

### Bundles inspected afresh

The desktop assets were under:

```text
https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/
  tiktok/webapp/main/react-v18/webapp-desktop/
```

Paths below are relative to that desktop base unless stated otherwise. Offsets are zero-based character offsets in the downloaded, decoded JavaScript, not stable API contracts.

| Asset | Evidence |
| --- | --- |
| `static/js/webapp-desktop.815f179f.js` | Hydration marker at 246163; parses script `textContent` as JSON and reads `__DEFAULT_SCOPE__`. |
| `user-prefetch.e4a973fd.js` | At 103385, builds the post-list query from profile `secUid`, `aid:1988`, `count` (16 or 24 in this prefetch branch), `cursor:"0"`, language, cover format, and video encoding; requests `/api/post/item_list/`. Also requests `/api/user/playlist/` independently. |
| `static/js/async/user.4af5a065.js` | Reads `detailInfo.user.secUid` and invokes the item-list loader. Profile metadata and the post feed are distinct data paths. |
| `static/js/player.init.16cea91e.js` | `PlayAddrStruct` at 196975; builds rendition data from `playAddr`, size, format, codec and `bitrateInfo`. MediaSource checks at 226256; `x-tos-expires` at 226596. Recognizes expiry fields `expire`, `x-tos-expires`, `x-expires`, and a hexadecimal path component. |
| `webmssdk/1.0.0.417/webmssdk.js` (static root) | Obfuscated browser security bundle. No complete signature algorithm was recovered. |
| `ttweb_webmssdk_ex/1.0.0.2901/webmssdk_ex.js` (static root) | Current extended bundle loaded by the browser; visible state names include `bogusIndex` (157364), `WEBGL` (157442), `msToken` (157461), `fetchSignTime` (157534), and `XHRSignTime` (157550). These names do not establish an algorithm. |
| `embed/static/tiktok-embed.module.1f1ab0fbe45bcde2a3be.js` (static root) | Creator handler uses `/embed/api/profile/getUserInfo` (2196658) and `/embed/api/profile/getItemList` (2196810). At 2196962, sets `const b=10,m="/embed/@"`; stores `userInfo` and `videoList` in Frontity state at 2198772. |
| `embed/static/playlistCard.module.7b78dcaf255541a4659d.js` (static root) | Renders creator metadata and maps preview entries into canonical author/video links. It does not provide evidence for complete archive pagination. |

The embed document referenced older `webmssdk/1.0.0.223/webmssdk.js`; it is a separate frontend build, not proof that the desktop SDK can be omitted for desktop API calls. Asset names and A/B variants can change; neither script hardcodes or downloads these bundles.

## 2. Video: minimal end-to-end request chain

```text
Full /@handle/video/<id> URL                  vm.tiktok.com/<code>/
            │                                        │
            │                              GET → HTTP 302 Location
            └───────────────────┬────────────────────┘
                                ▼
                    GET the public video document
                    retain domain-scoped Set-Cookie
                    parse hydration from THIS response
                                │
                    identity/availability/format checks
                                │
                    GET unchanged video.playAddr
                    same cookie jar + TikTok Referer
                                │
                    size/container/hash checks → MP4
```

**Two GETs per full URL, three per tested short URL.** No homepage warmup, HEAD, oEmbed, item-detail API, security report, signature service, quality probe, or preliminary range request is needed. The redirected response already contains the document; do not fetch its final URL again.

### Short links and identity

| Short URL | Resolved video ID | Hydrated author |
| --- | --- | --- |
| `https://vm.tiktok.com/ZMAYuMpFQ/` | 7542076400346451232 | nerublanco |
| `https://vm.tiktok.com/ZMAj83k4w/` | 7544010904229252358 | metropolesoficial |
| `https://vm.tiktok.com/ZMA4ncut8/` | 7562939840271076615 | metropolesoficial |
| `https://vm.tiktok.com/ZMAVwmojg/` | 7286599702303362310 | casamentosemdividas |

`urllib` follows Location and retains cookies automatically. Empty handles in `/@/video/<id>` redirects are valid. The path ID, not `share_item_id`, is authoritative. The final URL must identify a supported video; full input URLs must preserve their ID through redirects. There is no short-code lookup table in the implementation.

The page request uses a Chrome/146 Linux user agent, `Accept: text/html`, and `Accept-Language: en-US,en;q=0.9`. Queries are retained, including share parameters. Supported inputs are HTTPS `tiktok.com`/`www.tiktok.com` video URLs and `vm.tiktok.com` alphanumeric short links, not arbitrary hosts, live streams, or photo posts.

### Hydration and checks

```text
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
  __DEFAULT_SCOPE__
    webapp.video-detail
      statusCode
      itemInfo.itemStruct
        id / author / desc / createTime / stats
        privateItem / secret / forFriend / isProhibited / takeDown
        video
          playAddr / downloadAddr / format / size / duration
          width / height / codecType
          bitrateInfo[].PlayAddr
            UrlList[] / DataSize / FileHash
```

Parse JSON, never execute it. JSON decoding handles `\u002F`/`\u0026`; do not additionally HTML-unescape or rebuild the signed URL. Require status zero, matching ID, no active restriction flags above, an HTTPS play address, and MP4 format. These are conservative local checks, not a reconstruction of all server-side moderation/authorization rules.

A hydration-free HTTP-200 document containing exactly `data-source="downgrade-mssdk-preload"` gets **one** delayed retry (one second), using the already resolved page URL and existing cookies. No current video test needed it; offline tests cover this branch. Repeated shells, arbitrary challenges, unavailable items, or HTTP failures are errors, not reasons to loop or switch to another service. Actual redirects/retries are included in request counts.

## 3. Media cookies, signatures, and integrity

### Server-issued playback capability

The media URL is already signed in raw HTML, before any page JavaScript executes. A redacted, nonfunctional shape is:

```text
https://v16-webapp-prime.tiktok.com/video/tos/<region>/<object>/
?a=1988&bti=<opaque>&&bt=<rate>&ft=<opaque>&mime_type=video_mp4
&rc=<opaque>&expire=<epoch>&l=<context>&ply_type=2&policy=2
&signature=<32-hex>&tk=tt_chain_token&btag=<opaque>
```

Preserve host, path, query ordering, values, and even repeated separators. `tk=tt_chain_token` names a cookie; it is **not** the cookie's value. Keep the page-issued HttpOnly `.tiktok.com` cookie in a `CookieJar`, so normal domain/path/secure matching attaches it to the appropriate media host. Do not put browser cookies into a global Cookie header.

| Cookie | Evidence-supported role |
| --- | --- |
| `tt_chain_token` | Required for the tested media request; the chain-cookie-only control succeeds. |
| `ttwid` | Visitor state. Not necessary in the chain-only media control. |
| `tt_csrf_token` | Page-issued CSRF state. Not necessary for that read-only media request. |
| `msToken` | Browser security/session state, also used in API queries. Not necessary for that media GET. |

A 32-hex signature does not prove MD5, HMAC, the signed fields, or the server key. Its generation algorithm and exact IP/session bindings remain unknown. Fetch fresh metadata rather than storing media URLs as permanent identifiers. `expire` resembles an epoch expiry and the player classifies expirations, but changing it also invalidates potentially signed data; this experiment cannot distinguish those rejection causes.

Some rendition lists include alternative `/aweme/v1/play/` addresses with `signaturev3`. These are not prerequisite endpoints. The script chooses the supplied default `video.playAddr`, not a synthesized alternative, arbitrary MP4-looking request, `downloadAddr`, thumbnail, subtitle, or blob URL.

### Controlled experiments, repeated 2026-10-05

Fresh Python metadata for video `7544010904229252358` was used. Research probes alone used `Range: bytes=0-1023`; the actual extractor does not probe first.

| Variation | Result |
| --- | --- |
| Page cookies + Chrome UA + TikTok Referer + untouched URL | 206, video/mp4, 1,024 bytes, MP4 `ftyp` |
| Only `tt_chain_token`, same UA/Referer | Same success |
| Other cookies, no `tt_chain_token` | 403 |
| Page cookies, no Referer | 403 |
| Python urllib UA for media, page cookies and Referer | Same success |
| Signature replaced with zeros | 403 |
| `expire` replaced with `1` | 403 |

These establish conditions for this tested URL/session, not a universal CDN policy. The default-UA experiment concerns **media**, not the page request.

### Complete media retrieval

The extractor sends one GET with `Accept: */*`, `Referer: https://www.tiktok.com/`, the unchanged signed URL, and its cookie jar. It does not need Origin, Sec-Fetch headers, client hints, a CORS preflight, or JavaScript. `urllib` requests identity encoding by default. CORS is a browser restriction, not a requirement to emulate OPTIONS in Python.

The response must be a complete HTTP 200 `video/mp4`. Download into a temporary file, checking:

1. Initial MP4 `ftyp` box, not an HTML denial.
2. Actual size versus Content-Length and metadata size when present.
3. MD5 versus the matching rendition's `FileHash` when supplied. Locate the rendition by **exactly matching** the chosen URL against `PlayAddr.UrlList` and use its `DataSize`.
4. Exclusive creation of the destination only after validation.

MD5 checks integrity, not authenticity or the URL signature. Validation is not a codec decoder; FFmpeg separately decoded the live outputs. Final copying is not crash-atomic: an I/O failure during publication can leave a partial destination. Existing files are never overwritten and such failures are not reported as success.

## 4. Profiles: desktop metadata versus the video list

### Desktop profile document — working

```text
GET https://www.tiktok.com/@<handle>
  __UNIVERSAL_DATA_FOR_REHYDRATION__
    __DEFAULT_SCOPE__.webapp.user-detail
      statusCode / statusMsg
      userInfo
        user: id, uniqueId, secUid, nickname, signature, createTime,
              verified, privateAccount, secret, avatar*, profileTab, ...
        stats / statsV2
        itemList: []
```

The account `signature` field here is **biography text**, not a cryptographic signature. `secUid` is a public opaque account identifier used by the desktop post-list endpoint. `statsV2` contained decimal-string counters; the script prefers these over the rounded legacy `stats` and converts them to integers.

The script validates the requested handle, numeric account ID, status zero, nonnegative counts, and privacy flags. It keeps account metadata without printing session cookies or signed avatar/media URLs. Allowed redirects stay on the requested TikTok profile/embed paths, not external hosts or other accounts. The same recognized-shell-only retry as the video example is supported for the desktop document.

All four requested profiles returned account metadata in fresh Python sessions. **Their `userInfo.itemList` was empty, not proof of zero posts.** The frontend subsequently loads posts separately.

### Desktop post list — observed, not implemented successfully

The source prefetch builds:

```text
GET /api/post/item_list/
  aid=1988
  secUid=<from profile hydration>
  count=16 (or 24 for one layout branch)
  cursor=0
  language=<UI language>
  coverFormat=<cover setting>
  video_encoding=<capability-dependent encoding>
```

The browser adds environment/common fields including `device_id`, `WebIdLastTime`, `odinId`, region/language, browser/platform/version, viewport, timezone, visibility/focus, cookie state, login state, referer, and channel. The observed security query fields were:

| Field | What was established |
| --- | --- |
| `msToken` | Browser security/session token; a page-issued token alone did not make the Python post-list request work. |
| `X-Dynosaur` | Opaque browser-added value; generation not recovered. |
| `X-Bogus` | Literal `1` in the inspected request, not an assumed historical signer format. Adding `1` alone with a token did not work. |
| `X-Gnarly` | Opaque browser-added value; generation not recovered. |

Minimal unsigned, `device_platform=webapp`, expanded environment-field, and fresh-page-token variants all returned HTTP 200 with **zero response bytes**. The browser-signed request also yielded no usable list and the page displayed a CAPTCHA. These observations do not establish which checks rejected a particular request or whether signatures alone would suffice. SDK state names are not enough to port an algorithm.

There is no justified claim of recovered signature formulas, complete fingerprint emulation, cursor semantics, or working pagination. Replaying one captured signed request would not be a reusable, independent Python implementation. Consequently the example does not send these known-unsuccessful API probes on every extraction, invent tokens, or import browser state.

### Creator-embed preview — implemented, currently unreliable upstream

The other inspected TikTok frontend is `https://www.tiktok.com/embed/@<handle>`. Its raw HTML can supply a first-party preview without a client-side post-list API request:

```text
__FRONTITY_CONNECT_STATE__
  router.link: /embed/@<handle>
  source.data[router.link]
    isError / errorCode / pageName: creator
    userInfo: id, uniqueId, nickname, signature, privateAccount, counts, ...
    videoList[]
      id / authorUniqueId / desc / playCount
      playAddr / coverUrl / width / height / privateItem
```

The creator handler requests user data using `uniqueID`, then requests ten items using the numeric `userId` and `count:10`. Its service calls carry `x-tt-webid`; the captured server configuration uses a `consul://tiktok.embed.api` prefix. These are frontend/server implementation details, **not** evidence that the same bare API paths are working public endpoints. Direct public GET probes returned 503. The Python script only requests the rendered embed document and parses its state; it does not try to contact internal service addresses.

Implemented chain:

```text
profile URL → GET desktop document → validated rich account metadata
                                      │ positive videoCount
                                      ▼
                              GET /embed/@handle
                              parse creator state
                              cross-check account ID and handle
                              reject denial or unexplained empty list
                              skip private/photo/no-playback entries
                              deduplicate numeric post IDs
                                      │
                                      ▼
                        canonical /@handle/video/<id> URLs
                                      │
                                      ▼
                        example-video.py's fresh extraction
```

Normally **two GETs**: one for rich desktop metadata (`secUid`, creation time, post count, less-rounded counters), one for the preview. No oEmbed, redundant metadata endpoint, thumbnails, media probes, SDK resource calls, or desktop post-list failure precedes the preview. If the document reports `videoCount == 0`, the script makes no preview request. Redirects or a recognized shell can add requests.

Cross-check both account ID and handle between documents; never treat unrelated recommendations as the profile's posts. Each preview entry must identify the same author. Photo/private/no-playback entries are omitted. A positive post count with no usable preview entries is an error, not a verified empty result.

**This is a preview, not a full archive or guaranteed chronological list.** The observed handler requests ten entries and exposes no recovered pagination interface. `listing.complete` is always `false`; no cursor/has-more value is invented. A successful video URL can still become unavailable before its fresh extraction. The embed's media addresses are not reused for download.

In the final run each embed request returned HTTP 503; separate direct probes showed body `overload-protect triggered`, and some research/browser requests returned 429. The initial successful ten-item response does not override these later failures. Preview availability must be revalidated before relying on this route.

## 5. Validation results

All exact test URLs are constants in the corresponding scripts; their equality to the URLs in `PROMPT.md` was checked offline. No test substitutes a related URL for a supplied case.

### Full live video extraction, fresh session for each input

| Case | Input from PROMPT.md | Video ID | Bytes | GETs | Result |
| --- | --- | --- | --- | --- | --- |
| 01 | Full, casamentosemdividas | 7286599702303362310 | 1,686,277 | 2 | PASS |
| 02 | Full, causanobrecerimonial | 7502602409370307845 | 3,370,911 | 2 | PASS |
| 03 | Full, metropolesoficial | 7562939840271076615 | 3,559,532 | 2 | PASS |
| 04 | Full, metropolesoficial | 7544010904229252358 | 6,475,232 | 2 | PASS |
| 05 | Full, nerublanco | 7542076400346451232 | 7,515,994 | 2 | PASS |
| 06 | ZMAYuMpFQ | 7542076400346451232 | 7,515,994 | 3 | PASS |
| 07 | ZMAj83k4w | 7544010904229252358 | 6,475,232 | 3 | PASS |
| 08 | ZMA4ncut8 | 7562939840271076615 | 3,559,532 | 3 | PASS |
| 09 | ZMAVwmojg | 7286599702303362310 | 1,686,277 | 3 | PASS |

Each matched its fresh server FileHash. All nine MP4s passed `ffprobe` and full `ffmpeg -xerror` audio/video decoding (H.264/AAC, 576×1024). The video extraction algorithm did not need replacement in this audit; its docstring now identifies the profile URL interface.

### Final live profile test

| Profile | Desktop metadata | Preview request | Complete extraction |
| --- | --- | --- | --- |
| https://www.tiktok.com/@casamentosemdividas | PASS | HTTP 503 | FAIL |
| https://www.tiktok.com/@causanobrecerimonial | PASS | HTTP 503 | FAIL |
| https://www.tiktok.com/@metropolesoficial | PASS | HTTP 503 | FAIL |
| https://www.tiktok.com/@nerublanco | PASS | HTTP 503 | FAIL |

Separately, the earlier saved `metropolesoficial` response supplied ten verified-schema candidates. Its first, `7693027940526853384`, passed a **live** video extraction: two GETs, 7,476,553 bytes, matching fresh FileHash, and successful full FFmpeg decode. The profile parser used a saved live capture for that integration check, not a new successful profile request.

### Local checks

- **56 temporary offline pytest cases passed**: URL validation; profile identity/privacy/counts; embed identity, schema, emptiness, filtering and deduplication; cookie retention; request counts; bounded shell recovery; redirect restrictions; error continuation and partial metadata on stderr; exact input lists; captured embed parsing; profile-to-video integration; video integrity and no-overwrite behavior.
- **100 repository tests passed** with `uv run --no-sync pytest -q`; two upstream dependency deprecation warnings. These existing tests do not establish live profile availability.
- Syntax compilation and both CLIs' help, missing arguments, mutually exclusive inputs, and unsupported-URL checks passed; these checks do not establish network availability.
- The seven fresh media controls above and full decoding of all nine supplied-video outputs plus the preview-derived video passed.

One reviewer pass found that truncated/reset/non-UTF-8 embed responses could lose already-fetched account metadata. Expected transport/decoding failures now become `ExtractionError`, preserving metadata; three additional regression cases passed. The review also correctly identified the unresolved live profile requirement as a completion blocker. Fixing local error handling does not resolve that upstream blocker.

Temporary captures, probes, tests, and downloads are under `/tmp/tokai-audit-20261005`, outside the repository. They are diagnostic artifacts, not runtime dependencies or committed fixtures. Raw cookies/signed media URLs are not included in these deliverables. The temporary regression suite can be rerun in this environment with:

```sh
uv run --no-sync pytest -q /tmp/tokai-audit-20261005/test_examples.py
```

Reproduce media decoding after a new successful `--test` run:

```sh
for file in /tmp/my-tiktok-video-tests/case-*/*.mp4; do
  ffprobe -v error -show_entries \
    'format=duration,size:stream=codec_name,codec_type,width,height' -of json "$file" || exit 1
  ffmpeg -nostdin -v error -xerror -i "$file" \
    -map 0:v:0 -map 0:a:0 -f null - || exit 1
done
```

## 6. Boundaries and next work

| Symptom | Meaning/action |
| --- | --- |
| Nonzero detail status, private flags, mismatched identity | Stop; do not substitute another user/post or bypass access restrictions. |
| Missing hydration, repeated shell, CAPTCHA | Stop after the narrowly recognized shell retry. A browser challenge is not solved by parsing arbitrary HTML. |
| HTTP-200 empty API response | Failure, not valid empty JSON/list. Desktop API signing remains unresolved. |
| Embed HTTP 429/503 | Report failure with already-fetched metadata; no automated retry loop or service switch. |
| Empty creator preview with positive post count | Listing unverified; do not emit a successful empty profile. |
| Media 403 | Check fresh URL/cookies, Referer, unchanged signed fields; changed CDN policy needs reinvestigation. |
| Container/size/hash mismatch | No successful output; investigate transfer or schema changes. |
| Existing MP4 destination | Use a new directory; do not overwrite the file. |

To finish the original request, a reliably successful profile-list response must first be observed for **each** target, then its independent Python chain must be implemented and retested. A claim of full desktop API reproduction additionally requires recovering the current signing/environment checks and validating pagination, not merely documenting parameter names. The present code does neither and does not pretend otherwise.

All observations are specific to this date, network, region, public content, and frontend versions. These are local examples, not hardened network services for untrusted input. Use only content you are authorized to access and retain. No files outside the three requested deliverable paths were edited in the repository; pre-existing unrelated changes were preserved.
