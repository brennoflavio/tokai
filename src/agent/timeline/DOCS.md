<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# TikTok profile-video timeline: `/api/post/item_list/`

## Scope, evidence, and result

**This endpoint returns a page of a user's own profile posts, with enough metadata to build a video publication timeline.** It is an internal TikTok web endpoint, not a documented, stable public API contract.

**Current implementation:** [`example.py`](example.py) implements a bounded, deduplicated, newest-first video timeline using fresh Python-only sessions and a local port of the signer. Initial live first-page/continuation validation passed on **2026-10-07 UTC**, but subsequent checks encountered empty HTTP-200 listing responses, including with the original fixed-context signer. Python-only retrieval is demonstrated, not consistently reliable access; see [implementation and validation](#9-python-only-timeline-example) below. The capture analysis that follows is historical evidence, not the current implementation status.

Evidence inspected in the original offline investigation:

- Repository-root `curl.txt`: a browser-copied GET request.
- Repository-root `www.tiktok.com_api_post_item_list__Archive [26-10-06 18-53-22].har`: HAR 1.2 exported by Firefox 157.0, containing one request/response entry.
- The URL in the cURL command exactly matches the HAR request URL.
- HAR request time: **2026-10-06 18:52:54.019−03:00**, or **21:52:54.019 UTC**. Response `Date` agrees to the second.
- Response: HTTP **200**, JSON, `statusCode == 0`, `status_code == 0`, empty `status_msg`.
- `itemList` contains **17 video objects**, all with `author.uniqueId == "laila_verissimo"` and the same `author.secUid` as the request's `secUid`.
- The request asks for `count=16`. The response contains **one pinned video plus 16 regular videos**; this is an observation, not a universal page-size rule.
- The regular videos are newest-first, September 29 through September 9, 2026. The pinned August 19 video is first, breaking global chronological order.
- Returned pagination state: `cursor == "1788996990819"`, `hasMore == true`.

**The original offline investigation did not perform live replay, pagination, parameter/cookie-removal experiments, or signing implementation.** The later Python implementation validates one signing/session mode, not a minimal required-field set, universal token lifetime, or every signature binding. Statements labeled “possible,” “likely,” or “interpretation” remain unestablished server behavior unless explicitly superseded by the later validation.

This folder contains the standalone example and endpoint documentation. [Signer documentation](../sign/DOCS.md) records the algorithm and prior experiments; [video playback documentation](../video/DOCS.md) and [security SDK documentation](../sdk/DOCS.md) supply related evidence, not interchangeable endpoint requirements.

## 1. Request contract

```text
Method: GET
Origin: https://www.tiktok.com
Path:   /api/post/item_list/
Body:   none
Target: secUid query parameter
Paging: count and cursor query parameters
```

The HAR has no `request.postData`; the cURL has no `--data` or upload option. All captured inputs are in the query string and headers/cookies. Do not invent a JSON POST body or a required request `Content-Type`.

A deliberately incomplete, nonfunctional request shape:

```http
GET /api/post/item_list/?secUid=<target-secUid>&count=16&cursor=0&<environment-and-security-fields> HTTP/2
Host: www.tiktok.com
User-Agent: <consistent browser user agent>
Accept: */*
Accept-Language: en-US,pt-BR;q=0.9,en;q=0.8
Referer: https://www.tiktok.com/@<target-handle>
Cookie: <private session cookies>
```

### Target identity

- `secUid` identifies the **profile being listed**; it is not the username, numeric `author.id`, or the visitor's `device_id`.
- The response supplies `author.secUid`, `author.id`, `author.uniqueId` (handle), and `author.nickname` (display name). All items match the captured target.
- `secUid` is an opaque account identifier, not evidence of authentication or permission to access private posts. Treat it as identifying data rather than a password.
- A handle-to-`secUid` lookup is **not documented or tested by this capture**. The later Python example obtains `secUid` from profile-page hydration, not by substituting a handle into this endpoint.

### Complete captured query inventory

Values below are historical observations, **not defaults to hardcode**. Empty strings were explicitly present. The table preserves captured query order. Sensitive/session-identifying values are redacted.

| Parameter | Captured value or shape | Interpretation / replication concern |
| --- | --- | --- |
| `WebIdLastTime` | `1789708530` | Epoch-seconds-looking visitor timing state; not the request time. Exact source and validation unknown. |
| `aid` | `1988` | Web application identifier; necessity untested. |
| `app_language` | `en` | Application language. |
| `app_name` | `tiktok_web` | Application context. |
| `browser_language` | `en-US` | Reported browser language; should be considered with Accept-Language. |
| `browser_name` | `Mozilla` | Reported browser label, not proof of a specific engine by itself. |
| `browser_online` | `true` | Browser connectivity state, serialized as text. |
| `browser_platform` | `Linux x86_64` | Reported platform; spaces are URL-encoded in the captured URL. |
| `browser_version` | `5.0 (X11; Ubuntu)` | Browser environment string, distinct from full User-Agent and Firefox version. |
| `channel` | `tiktok_web` | Web distribution/context label. |
| `cookie_enabled` | `true` | Reported cookie capability; sending this does not create a cookie jar. |
| `count` | `16` | Requested page size; actual response length was 17. Allowed range unknown. |
| `coverFormat` | `0` | Cover-format selector by name; enum semantics unknown. |
| `cursor` | `0` | Initial-page value. Use returned cursor unchanged for continuation; do not increment it. |
| `data_collection_enabled` | `false` | Reported collection setting; does not prove the security SDK collected no signals. |
| `device_id` | Redacted, 19 decimal characters | Visitor/device-looking identifier, not target user ID. Issuance and binding unknown. |
| `device_platform` | `web_pc` | Desktop-web context. |
| `focus_state` | `true` | Reported page focus. |
| `history_len` | `2` | Browser-history-looking state; exact origin unverified. |
| `is_fullscreen` | `false` | Reported fullscreen state. |
| `is_page_visible` | `true` | Reported page visibility. |
| `language` | `en` | Additional language field; not necessarily interchangeable with app/browser language. |
| `odinId` | Redacted, 19 decimal characters | Opaque visitor/security identifier. Do not assume equivalence to `device_id`. |
| `os` | `linux` | Reported operating system. |
| `priority_region` | Empty string | Separate region preference; retain emptiness when investigating exact replay. |
| `referer` | Empty string | Query field, **not** HTTP Referer; the actual Referer header is nonempty. |
| `region` | `BR` | Reported region. Whether server policy also uses IP geography is unknown. |
| `root_referer` | Empty string | Separate navigation/context field. |
| `screen_height` | `1440` | Reported screen geometry; unit/source not independently verified. |
| `screen_width` | `2560` | Reported screen geometry. |
| `secUid` | Redacted, 76 characters | Target profile's opaque account identifier. |
| `tz_name` | `America/Sao_Paulo` | Reported timezone; slash is percent-encoded in the request. |
| `user_is_login` | `false` | Client reports a logged-out visitor; not an independent authentication audit. |
| `verifyFp` | Redacted, 52 characters, `verify_...` | Fingerprint/verification-looking identifier; equals captured `s_v_web_id` cookie. |
| `video_encoding` | `dash` | Requested media encoding context. Does not establish that every returned address is a DASH manifest. |
| `webcast_language` | `en` | Additional language context. |
| `X-Dynosaur` | Redacted, 424 opaque characters | Security/signing-looking field; generation and validation unknown. |
| `msToken` | Redacted, 156 opaque characters | Security/session token also present in cookies; details below. |
| `X-Bogus` | Literal `1` | Preserve this observation. Do not substitute a historical X-Bogus algorithm merely because of the name. |
| `X-Gnarly` | Redacted, 332 opaque characters | Security/signing-looking field; generation and validation unknown. |

The capture does not establish a minimal parameter set. In particular, UI state and language parameters cannot be declared optional just because they look informational.

### Headers and transport

| Header / cURL option | Captured value | Python concern |
| --- | --- | --- |
| `User-Agent` | `Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0` | Browser identity is richer than this string. Copying it does not reproduce JavaScript, TLS, or HTTP/2 behavior. |
| `Accept` | `*/*` | Response was JSON; do not infer JSON from this header alone. |
| `Accept-Language` | `en-US,pt-BR;q=0.9,en;q=0.8` | Consider consistency with reported languages and region. |
| `Accept-Encoding` | `gzip, deflate, br, zstd` | Only advertise encodings the chosen HTTP client can decode. This response used Brotli (`br`). |
| `Referer` | `https://www.tiktok.com/@laila_verissimo` | Profile-page request context; necessity and target matching checks untested. |
| `Sec-Fetch-Dest` | `empty` | Browser fetch metadata, not actual browser execution. |
| `Sec-Fetch-Mode` | `cors` | Browser context. Python is not subject to browser CORS enforcement. |
| `Sec-Fetch-Site` | `same-origin` | Reported origin relationship; forging it does not reproduce a browser session. |
| `Connection` | `keep-alive` | Present in the export, but connection-specific headers are not valid HTTP/2 wire headers. Do not blindly force this into an HTTP/2 client. |
| `Cookie` | Redacted; inventory below | Use a domain/path-scoped cookie jar, not a globally forwarded Cookie header. |
| `Priority` | `u=4` | HTTP priority hint; necessity untested. |
| `TE` | `trailers` | Transport hint, not an API business input. |
| `Host` | `www.tiktok.com` in HAR | Normally managed by the HTTP client; HTTP/2 uses authority pseudoheaders. |
| `--compressed` | Enabled in cURL | Requests compression and automatic decoding; not a request-body flag. Python client behavior depends on installed codec support. |

HAR records `HTTP/2`; `X-Firefox-Spdy: h2` appears in response metadata. Browser-exported headers are not a byte-for-byte description of HTTP/2 framing, pseudoheaders, TLS ClientHello, or browser header compression. No transport-fingerprint dependency was tested.

## 2. Cookies, token refresh, and fingerprints

### Complete captured Cookie header inventory

These are cookies sent by the browser, **not a proven list of required cookies**. A Cookie request header does not reveal original Domain, Path, expiry, HttpOnly, or SameSite attributes.

| Cookie | Observation / interpretation | Replication concern |
| --- | --- | --- |
| `ttwid` | Opaque visitor-state cookie with pipe-separated components in encoded form. | Issuance, lifetime, and relationship to visitor IDs unverified. Do not synthesize or edit its parts. |
| `tt_chain_token` | Opaque chain/session token. | Required for media in separate video experiments; requirement for this listing endpoint **not tested**. |
| `tiktok_webapp_theme_source` | `auto` | UI preference; omission not tested. |
| `tiktok_webapp_theme` | `dark` | UI preference; omission not tested. |
| `delay_guest_mode_vid` | `8` | Guest-mode-looking state; semantics and necessity unknown. |
| `msToken` (first occurrence) | Opaque value A; differs from query token. | Duplicate cookie name is important; provenance/domain/path are unavailable in request header. |
| `oec_lucifer` | Opaque value. | Purpose, issuer, and necessity are not established; do not infer behavior from the name. |
| `msToken` (second occurrence) | Opaque value B; **equals query `msToken`**. | A dictionary collapses duplicate names and loses evidence. Which value the server reads is unknown. |
| `tt_csrf_token` | CSRF-named token. | This is a read-only GET, but omission has not been tested. No separate CSRF request header was captured. |
| `s_v_web_id` | `verify_...` identifier; **equals query `verifyFp`**. | A plausible consistency relationship, not proof of how either value is generated or validated. |

Cookie order above matches the export. Two same-name cookies can arise from different scopes or other client state; **the reason for this duplicate is unknown**. Do not assume first-wins or last-wins server parsing. A real cookie jar preserves scope and lets cookie policy decide what to send; an imported name/value dictionary cannot reconstruct missing scope attributes.

### Response token update: observed

The successful response supplies both:

```text
x-ms-token: <new opaque token>
Set-Cookie: msToken=<same new token>; expires=Fri, 16 Oct 2026 21:52:54 GMT;
            domain=tiktok.com; path=/; secure; SameSite=None
```

- The response header token equals the newly set cookie value.
- It **differs from the request query token**.
- This cookie's expiry is ten days after the captured response date. That is a cookie storage expiry, **not proof that signatures or server-side token validity last ten days**.
- No `HttpOnly` attribute appears on this particular Set-Cookie.
- A Python cookie jar can process Set-Cookie automatically; it does not automatically update a future `msToken` **query parameter** or reproduce SDK state.
- Whether the next request should use this token, the SDK's current token, or another refreshed value is not demonstrated by the single response. Nor is consuming `x-ms-token` separately proven necessary.

### What a fingerprint value does not prove

`verifyFp` and `s_v_web_id` visibly agree. That does not mean generating any matching pair is sufficient. The server may also consider reported device IDs, cookies, signing state, navigation history, IP, or browser-collected signals; their actual use/binding here is unknown.

The related SDK documentation describes browser/device collection and WebGL inspection in retained security source. It does not establish that all such signals are inputs to this endpoint's signatures. A Python script lacks DOM, navigator, storage, WebGL, and browser request instrumentation unless those are independently supplied or implemented. Merely copying `screen_width`, a Firefox User-Agent, and a `verify_` string is not evidence of an equivalent environment.

## 3. Security/signing fields: hardest replication boundary

| Field | Established fact | Not established |
| --- | --- | --- |
| `X-Dynosaur` | Long opaque query value present in this successful request. | Algorithm, keys, signed inputs, expiry, browser/session binding, whether mandatory. |
| `X-Gnarly` | Long opaque query value present in this successful request. | Same unknowns; no recovered generator or validated Python implementation. |
| `X-Bogus` | Exactly `1`. | Whether placeholder, mode marker, compatibility field, or checked value. |
| `msToken` | Present in query and twice in cookies; response issues a different token. | Issuance protocol, validation rules, rotation schedule, binding to other fields. |
| `verifyFp` / `s_v_web_id` | Equal values in this capture. | Fingerprint-generation algorithm and server acceptance conditions. |
| `device_id`, `odinId`, `WebIdLastTime` | Visitor-looking values distinct from target identity/request time. | Their source, stability, interdependence, and role in signing. |

### URL construction and potential signed-input changes

The copied request contains percent-encoded spaces/parentheses and opaque values containing URL punctuation. Their alphabets and lengths do not prove Base64, encryption, a hash function, or a fixed schema.

For exact replay analysis, retain the original request URL rather than rebuilding it. A decode/re-encode round trip can change `%20` to `+`, encode `/` differently, reorder keys, drop empty fields, or accidentally double-encode `%`. A literal `+` interpreted by query parsing as a space can also corrupt an opaque value.

**Whether any of those differences invalidate TikTok's signatures is unknown.** They are potential byte-level differences to control during experiments, not recovered signing rules.

For a new target/page, inputs must change (`secUid`, `cursor`, possibly Referer and session state). **Do not assume old `X-Dynosaur`/`X-Gnarly` values remain valid after changes.** Target, cursor, query serialization, body, User-Agent, token, timestamp, session, or environment could participate in signing; this capture identifies none of the exact signed inputs.

The endpoint path or historical SDK versions are not a signing specification. See [SDK acquisition and limitations](../sdk/DOCS.md) before analyzing source: the retained SDKs are partially deobfuscated, have provenance/coverage limitations, and have not been validated as a complete Python signer. Executing full security SDKs can collect device information and make network requests.

### Replay, generation, and independent implementation are different claims

1. **Captured request succeeded:** established by this HAR.
2. **Unchanged captured request succeeds later in Python/cURL:** not tested; tokens, server state, network context, and signed values may no longer be accepted.
3. **Fresh browser session can generate another working request:** not tested in this investigation.
4. **Changing cursor with refreshed browser signing yields older posts:** conventional pagination interpretation, not live-tested here.
5. **Pure Python can acquire session state and generate accepted signatures/fingerprints:** not established.

A browser-assisted request and a browser-free Python implementation are different architectures. The fact that existing public-video extraction can use server-rendered metadata without browser API signing does **not** establish the same route for this paginated timeline API.

## 4. Response headers, encoding, and token-bearing content

| Header / metadata | Captured observation | Meaning / limitation |
| --- | --- | --- |
| HTTP status | `200` | Transport success; must inspect JSON/application status. |
| `content-type` | `application/json; charset=utf-8` | JSON encoded as UTF-8. |
| `content-encoding` | `br` | Brotli on the network. |
| `content-length` | `37115` | Encoded response size; not decoded JSON size. |
| HAR `content.text` | 377,534 characters; 378,014 UTF-8 bytes | Already decoded JSON text; no HAR `content.encoding` value in this capture. Do **not** Brotli-decompress it again. |
| `bd-tt-error-code` | `0` | Additional success-looking diagnostic; semantics not recovered. |
| `tt_stable` | `1` | Opaque diagnostic/flag. |
| `tt-ticket-guard-result` | `0` | Security-related diagnostic by name; not proof that every security check was skipped. |
| `x-ms-token`, `set-cookie` | New matching token | Private session update; see previous section. |
| `cache-control` | `max-age=0, no-cache, no-store` | Server discourages caching this response. |
| `pragma`, `expires` | `no-cache`; expiry equal to response Date | Additional cache metadata. |
| `strict-transport-security` | `max-age=31536000; includeSubDomains` | HSTS browser policy. |
| `access-control-expose-headers` | `x-tt-traceflag,x-tt-logid` | Exposes these headers to permitted browser code; not an authentication grant or complete CORS policy. |

Other captured headers are `x-tt-logid`, `x-envoy-response-flags`, `x-tt-trace-host`, `x-tt-trace-id`, `x-tt-trace-tag`, `server`, `date`, two `server-timing` entries, `x-cache`, `x-origin-response-time`, `x-akamai-request-id`, and `X-Firefox-Spdy`. They provide transport/routing/timing/correlation evidence, not known inputs required to generate the next request. Request/trace IDs should be redacted when sharing diagnostics; timings/edge routing are not a stable API contract.

## 5. Response body

### Top-level shape

Sanitized, abbreviated structure; angle-bracket values are placeholders:

```text
{
  "cursor": "1788996990819",
  "extra": {
    "fatal_item_ids": [],
    "logid": "<request-correlation-id>",
    "now": 1791323574000
  },
  "hasMore": true,
  "itemList": [<17 post objects>],
  "log_pb": {"impr_id": "<impression-correlation-id>"},
  "statusCode": 0,
  "status_code": 0,
  "status_msg": ""
}
```

| Field | Observed type | Use / caution |
| --- | --- | --- |
| `itemList` | Array of objects | Page of profile posts. All 17 are videos here; photo-post behavior is not evidenced. |
| `cursor` | String | Next-page continuation value. Treat as opaque and preserve type/text. |
| `hasMore` | Boolean | More pages indicated; not a count of remaining posts. |
| `statusCode`, `status_code` | Integers | Both zero here. Keep status-field naming differences in mind; failure variants not captured. |
| `status_msg` | String | Empty here. No failure-message catalog is available. |
| `extra.fatal_item_ids` | Array, empty | Item-failure-looking diagnostic; element type/semantics unverified because empty. |
| `extra.logid`, `log_pb.impr_id` | Strings | Correlation/tracking identifiers, not pagination cursors. |
| `extra.now` | Integer | Milliseconds-looking timestamp matching response time, not publication time. |

The returned cursor resembles epoch milliseconds near the final regular post's time: `1788996990819` versus `createTime == 1788996991`. This resemblance **does not justify calculating cursors from timestamps**, rounding them, or inventing arbitrary date filters.

### Timeline-relevant post data

| Field | Observed type | Use |
| --- | --- | --- |
| `id` | String | Stable post identifier for deduplication and video-page URLs; keep as string. |
| `createTime` | Integer | Publication time in Unix seconds; convert with an explicit timezone. |
| `desc` | String | Caption, including text/hashtags; preserve Unicode. |
| `author` | Object | Owner identity and display metadata. |
| `isPinnedItem` | Boolean, only present on one item | True on the first item; missing on 16 others. Do not require this field. |
| `video` | Object | Duration, dimensions, playback/rendition/thumbnail/subtitle metadata. |
| `stats`, `statsV2` | Objects | Engagement snapshots, not historical time series. |
| `authorStats`, `authorStatsV2` | Objects | Repeated account-stat snapshots; not a guaranteed pagination total. |

Construct the observed kind of public video page as:

```text
https://www.tiktok.com/@{author.uniqueId}/video/{id}
```

This construction applies to the captured video items, not unverified photo posts. A page URL/post ID is a better durable reference than a signed media URL.

### Complete observed post-field inventory

This is the **union across these 17 objects**, not a guarantee every field is always present or that all future posts use this schema. Integer enum meanings and undocumented flags are not reverse-engineered here. Spelling/case follows the response, including `officalItem`.

| Group | Observed fields and types |
| --- | --- |
| Identity/content | `id` string; `createTime` integer; `desc`, `textLanguage` strings; `textTranslatable` boolean; `contents`, `textExtra`, `challenges` arrays |
| Owner/account | `author`, `authorStats`, `authorStatsV2` objects |
| Media | `video`, `music` objects; `stickersOnItem`, `anchors` arrays |
| Engagement/visitor state | `stats`, `statsV2` objects; `collected`, `digged` booleans |
| Availability/context | `privateItem`, `secret`, `forFriend`, `isProhibited`, `isReviewing`, `isAd`, `originalItem`, `officalItem` booleans; `isPinnedItem` boolean when present |
| Interaction policy | `duetEnabled`, `stitchEnabled`, `shareEnabled` booleans; `duetDisplay`, `stitchDisplay`, `itemCommentStatus` integers; `item_control` object |
| AI/content classification | `AIGCDescription` string; `CategoryType` integer; `IsHDBitrate`, `ShowAIGC` booleans; `creatorAIComment` object |
| Internal/moderation | `backendSourceEventTracking` string; `diversificationId` integer; `penaltyContext` object |

Presence differences observed: `isPinnedItem` on 1/17, `anchors` on 5/17, `stickersOnItem` on 1/17, `diversificationId` on 16/17. Other listed top-level post fields occur on all 17; nested fields still vary. No `imagePost` field was present. All items have false `privateItem`, `secret`, `forFriend`, `isProhibited`, `isReviewing`, and `isAd`; this does not describe behavior for restricted accounts/posts.

### Author and engagement objects

- `author` strings: `id`, `secUid`, `uniqueId`, `nickname`, `signature`, `avatarLarger`, `avatarMedium`, `avatarThumb`. **`author.signature` is profile biography text, not the API request signature.**
- `author` booleans: `verified`, `privateAccount`, `secret`, `ftc`, `isADVirtual`, `isEmbedBanned`, `openFavorite`.
- `author` integers: `UserStoryStatus`, `commentSetting`, `downloadSetting`, `duetSetting`, `stitchSetting`, `relation`. `shortDramaCreator` is an empty object in the inspected sample.
- `authorStats`: integer `diggCount`, `followerCount`, `followingCount`, `friendCount`, `heart`, `heartCount`, `videoCount`. `authorStatsV2` uses the same keys with decimal-string values.
- `stats`: integer `collectCount`, `commentCount`, `diggCount` (likes), `playCount` (views), `shareCount`.
- `statsV2`: those keys as decimal strings, plus string `repostCount`.

Keep IDs and V2 decimal strings intact when serializing for clients that cannot represent large integers exactly. Stats record the state returned at collection time; they do not reveal likes/views on each past date.

### Video object and separate media signatures

| Fields | Observed structure |
| --- | --- |
| Basic media properties | `duration`, `width`, `height`, `size`, `bitrate` integers; `id`, `videoID`, `codecType`, `format`, `definition`, `ratio`, `encodedType`, `encodeUserTag`, `videoQuality`, `VQScore` strings |
| Main addresses | `playAddr`, `downloadAddr`, `cover`, `originCover`, `dynamicCover` strings |
| `zoomCover` | Object mapping `240`, `480`, `720`, `960` to URL strings |
| `PlayAddrStruct` | Object with `DataSize`, `Height`, `Width` integers; `FileCs`, `FileHash`, `Uri`, `UrlKey` strings; `UrlList` array of strings |
| `bitrateInfo[]` | Objects with `Bitrate`, `BitrateFPS`, `QualityType` integers; `CodecType`, `Format`, `GearName`, `MVMAF`, `VideoExtra` strings; nested `PlayAddr` with the address-struct fields above |
| `subtitleInfos[]` | When present: `Format`, `LanguageCodeName`, `LanguageID`, `Source`, `Url`, `Version` strings; `Size`, `UrlExpire` integers |
| `claInfo` | Caption metadata: `captionInfos[]`, integer `captionsType`, booleans `enableAutoCaption`, `hasOriginalAudio`, object `originalLanguageInfo` |
| `volumeInfo` | Numeric `Loudness`, `Peak` |

`claInfo.captionInfos[]` includes `captionFormat`, `claSubtitleID`, `expire`, `language`, `languageCode`, `languageID`, `subID`, `subtitleType`, `translationType`, `url`, `variant` strings; boolean `isAutoGen`, `isOriginalCaption`; and `urlList` strings. `originalLanguageInfo` includes language identifiers and boolean `canTranslateRealTimeNoCheck`. Not every post supplies subtitle information.

Captured `playAddr`/`downloadAddr` hosts are `v16-webapp-prime.tiktok.com`. Their queries include `a`, `bt`, `btag`, `bti`, `expire`, `ft`, `l`, `mime_type`, `ply_type`, `policy`, `rc`, `signature`, `tk`; download addresses also include `eid`. Cover hosts are `p16-common-sign.tiktokcdn.com` and `p19-common-sign.tiktokcdn.com`, with `dr`, `idc`, `ps`, `shcp`, `shp`, `t`, `x-expires`, `x-signature`.

These **server-returned media/cover signatures are separate from the listing request's `X-Gnarly`/`X-Dynosaur` fields**. Treat full media, image, and subtitle URLs as potentially expiring access capabilities; preserve them unchanged for use and redact them from public diagnostics. No download, playback, expiry, or cookie requirement was tested for the URLs in this HAR. Refer to the separate video documentation for experiments on other captures; do not infer identical requirements from host names alone.

### Remaining nested content/policy inventory

- `music`: string `id`, `title`, `authorName`, `album`, `playUrl`, `coverLarge`, `coverMedium`, `coverThumb`; integer `duration`, `shoot_duration`; boolean `original`, `private`, `isCopyrighted`, `is_commerce_music`, `is_unlimited_music`; `tt2dsp` object (empty in inspected sample).
- `contents[]`: inspected element has `desc` string; do not assume it exhausts possible element schemas.
- `textExtra[]`: inspected hashtag element has string `awemeId`, `hashtagName`; integer `start`, `end`, `subType`, `type`; boolean `isCommerce`. Offset units and mention variants were not established.
- `challenges[]`: string `id`, `title`, `desc`, `coverLarger`, `coverMedium`, `coverThumb`, `profileLarger`, `profileMedium`, `profileThumb`.
- `anchors[]`: string `description`, `id`, `keyword`, `logExtra`, `schema`; integer `type`; `extraInfo` with string `subtype`; `icon.urlList`; `thumbnail` with integer `height`, `width` and URL list. Treat `schema`/URLs as data, not executable navigation instructions.
- `stickersOnItem[]`: integer `stickerType`; `stickerText` string array.
- `creatorAIComment`: boolean `eligibleVideo`, `hasAITopic`; integer `notEligibleReason`.
- `item_control`: boolean `can_repost`.
- `penaltyContext`: integer `arb_content_safety_status`, `display_penalty_type`, `display_policy`, `display_ui_type`, `ec_global_verdict`, `reviewed`, `status`, `tns_status`, `video_status`. No enum interpretation is established.

## 6. Building a publication timeline

Once a client can obtain **fresh, accepted requests**, the data-processing plan is:

1. Resolve the target `secUid` through a separately verified mechanism.
2. Request the initial page with `cursor=0` and a supported page size.
3. Validate HTTP status, response type, application status, and expected target identity. Distinguish an empty successful page from an error/challenge/non-JSON response.
4. Collect `itemList` and deduplicate by string `id`. Do not assume a fixed page length or that pinned items appear only once.
5. If `hasMore` is true, use the **exact returned cursor** in the next fresh request. Signing/token/session state must remain valid; editing only the captured cURL's cursor is not a proven solution.
6. Stop when `hasMore` is false or the chosen collection limit is reached. Treat a missing/repeated cursor or repeated pages as a failure to make progress rather than loop forever.
7. Sort collected records by `createTime` for a strict timeline. Optionally display pinned items separately; keep `isPinnedItem` as metadata, not as publication-order evidence.
8. Store post ID, publication time, handle, caption, and page URL as durable metadata. Record collection time separately for stats/media snapshots.

This is a **publication timeline**, not the user's For You feed, liked-video list, watch history, repost timeline, or historical engagement timeline. No date-range filter or random-access time cursor is established. Pagination may be needed to reach older dates.

Completeness is limited to posts accessible to the requesting session. Private/deleted/unavailable/region-restricted content, list changes during traversal, and non-video post variants can affect results. One page cannot prove complete account history; `authorStats.videoCount` does not prove every counted item can be retrieved. Tie ordering and snapshot consistency across pages are unknown.

## 7. Historical Python feasibility and validation plan

### Straightforward once accepted JSON is available

- UTF-8 JSON parsing, preserving IDs/cursors as strings and optional fields.
- Unicode caption handling, timezone-aware `createTime` conversion, deduplication, chronological sorting.
- Domain/path-scoped cookie management and response Set-Cookie handling.
- Compression decoding **when the selected library and installed codecs support the advertised encodings**. Standard-library `urllib` is not a drop-in replacement for cURL's Brotli/zstd `--compressed` handling.

### Boundaries unresolved in the original capture investigation

- Acquiring fresh `ttwid`, `msToken`, fingerprint/visitor IDs, and any other required state without importing a browser session.
- Generating valid `X-Gnarly`/`X-Dynosaur` values, including discovering signed inputs and serialization rules.
- Preserving consistency between query, cookies, SDK state, and environment while the response refreshes tokens.
- Establishing whether TLS/HTTP version/header/browser characteristics or network context affect acceptance.
- Handling consent/login/challenge paths and failure variants without mistaking HTTP 200 for a valid empty timeline.

`requests`, `httpx`, or `urllib` can send HTTP requests; none inherently implements TikTok's security SDK. Changing the library, User-Agent, or cookie dictionary alone is not an established solution. Fingerprint-oriented transports likewise do not by themselves generate JavaScript security tokens or signatures.

### Evidence needed before claiming a working client

Future live investigation should use approved access and private captures, with one controlled change at a time:

1. Capture a fresh successful first-page response and a browser-generated continuation response for the same target/session. Verify different IDs, cursor progress, status, and `hasMore` behavior.
2. Compare redacted query/header/cookie changes between those requests, including the response-issued token. Establish the refresh/signing sequence rather than guessing it.
3. Test unchanged fresh replay in the intended Python transport. Record status, content type, application status, and whether returned IDs match; do not log credentials/full signed URLs.
4. Establish target changes separately from pagination changes. Both can require fresh signing.
5. Only then isolate candidate optional headers/parameters/cookies and serialization effects. A failed request may reflect stale state, not the field being tested.
6. Inspect current SDK/signing call sites if pure Python generation is required. Validate with multiple fresh sessions/pages, not one replayed signature. Respect service restrictions and do not attempt to bypass access controls.

These experiments were not run in the original capture investigation. Later signing research is documented in `../sign/DOCS.md`; the standalone timeline example's actual scope and live results are in section 9. The historical plan itself is not a claim of acceptance.

## 8. Security and storage precautions

- **Do not commit or publish the raw cURL/HAR.** At inspection time both root evidence files were untracked; they contain reusable-looking cookies/tokens, identifiers, and signed response URLs. This document intentionally does not copy those values.
- Redact query tokens/signatures, Cookie/Set-Cookie, `x-ms-token`, fingerprint/device identifiers, trace IDs, and complete signed media/cover/subtitle URLs in logs and shared examples. URLs can leak through shell history, exception strings, proxy logs, and analytics.
- Treat `secUid` and handles as account-identifying data, even when public. Request/response stats and captions are collected user data, not just transport artifacts.
- Use HTTPS with certificate validation. Keep cookie jars private and scoped; do not forward TikTok Cookie headers to arbitrary CDN/redirect hosts. Handle redirects and media destinations with explicit trust boundaries.
- Do not render captions, author text, anchors, or other response content as trusted HTML or execute returned strings/SDK code as part of parsing.
- Do not promise private/deleted-content access, fixed token lifetimes, or indefinite reuse of signed media URLs.
- This successful capture and the later bounded validation are historical snapshots. Endpoint schemas, SDK bundles, token formats, and security policy may change independently.

## 9. Python-only timeline example

### Runtime and usage

`example.py` is self-contained: it ports the required signing/RNG/encoding methods locally from `../sign/example.py`. It does **not import that module**, read the root captures, load SDK scripts, or call a browser, Node.js, cURL, or a remote signing service at runtime. It fixes the reviewed RNG-prefix type-validation issue in its local port without modifying the original signer.

- Python **3.14+**.
- Signing and `--self-test`: standard library only, no network.
- Fetching and `--validate-live`: `httpx[http2]>=0.28,<1`. Tested with Python 3.14.3, httpx 0.28.1, h2 4.4.1; offline tests also ran on Python 3.14.4.
- The repository's plain httpx dependency does not include h2. Use an isolated `uv` environment to avoid changing project manifests or `.venv`:

```sh
# From the repository root:
python3 src/agent/timeline/example.py --self-test
uv run --no-project --python 3.14 --with 'httpx[http2]==0.28.1' \
  python src/agent/timeline/example.py @laila_verissimo --pages 2
uv run --no-project --python 3.14 --with 'httpx[http2]==0.28.1' \
  python src/agent/timeline/example.py --validate-live
```

The username is positional, optionally prefixed with `@`; `--pages` defaults to **2**, must be positive, and is a collection bound rather than a claim of complete history. The normal CLI emits JSON; errors are fixed redacted JSON with a nonzero exit status. There are no automatic retries or browser fallbacks. HTTPS certificate validation is enabled, redirects are not followed, cookies remain domain/path-scoped, and only identity response encoding is advertised.

From Python, with the repository root on the import path:

```python
from src.agent.timeline.example import fetch_timeline

result = fetch_timeline("laila_verissimo", pages=2)
for video in result["videos"]:
    print(video["published_at"], video["url"])
```

### Fresh request chain and generated fields

```text
New HTTP/2 client + empty cookie jar + generated browser-like context
  → GET public profile HTML
  → parse target secUid/canonical handle and visitor wid/odinId/creation time/region
  → retain actual Set-Cookie attributes and server-issued msToken
  → initialize local signing seeds, RNG and counters
  → build unsigned item_list query, cursor=0
  → locally generate X-Dynosaur, append current msToken
  → locally generate X-Gnarly, append X-Bogus=1 and X-Gnarly
  → GET the exact signed URL with corresponding User-Agent and profile Referer
  → verify JSON status, target identity, items, pagination state; refresh token
  → repeat with the exact returned cursor until the page bound or hasMore=false
  → deduplicate by post ID and sort by publication time, newest first
```

Two pages normally cost **three GETs per profile**: one bootstrap and two listing requests. Sessions do not import or persist browser cookies. `validate_live()` begins with two independently empty Python clients; each visits both test profiles, with no signing state/cookies shared between clients.

| Inputs | How the example obtains them |
| --- | --- |
| User-Agent version | Random choice of Firefox 156 or 157, consistently reported in the generated Linux/Ubuntu UA and query. |
| Language / locale / Accept-Language / timezone | One coherent random English/UTC or Portuguese/São Paulo preset per session. |
| Screen dimensions | Random choice of 1280×720, 1366×768, 1920×1080, or 2560×1440. |
| History length | Random integer 1–3, stable for the session. |
| `device_id`, `odinId`, `WebIdLastTime`, region, target `secUid` | Fresh profile hydration; not invented, randomized arbitrarily, or copied from the HAR. |
| Cookies and `msToken` | Server-issued profile/API responses; scoped cookie jar and explicit query-token refresh. |
| Signing seeds, initial RNG entropy, timestamps | Fresh local entropy/time and the ported initialization/PRNG algorithm. |
| `X-Dynosaur`, `X-Gnarly` | Generated locally for every page from its exact serialized query and current state. |
| `X-Bogus`, app/channel IDs, enum selectors, SDK versions | Recovered protocol constants, not random fields. `X-Bogus` remains the evidenced literal `1`. |
| Security collector/canvas/extension state | The supported initial collector, missing-canvas, absent-extension branch; not arbitrary fabricated proofs. |

The generated properties are reported browser-like inputs, **not a real measured browser fingerprint**. Randomization is deliberately limited to coherent client properties. Server-issued identifiers/tokens must remain valid, and protocol constants cannot be randomized indiscriminately. This test does not establish that every possible combination or future SDK mode will work.

`verifyFp` is omitted, and the example does not invent `s_v_web_id` or CAPTCHA state. It does not recreate every header/cookie of the historical cURL. It reproduces the endpoint operation with fresh accepted inputs, not a byte-identical replay of that capture.

### Timeline output and limits

The output includes `author`, `videos`, `pages_fetched`, per-page item/new-ID counts, `has_more`, `complete`, and UTC `collected_at`. Each normalized video includes its string ID, Unix-seconds publication time, UTC timestamp, caption, pinned flag, duration, engagement snapshot and public video page URL.

Raw API bodies, visitor IDs, cursors, tokens, signatures, cookies, and signed media/cover URLs are not emitted. Public captions/stats/page references are intentional timeline output and should still be handled as collected user data.

Pinned videos are sorted by actual publication time rather than kept at the front. Duplicate IDs retain the first fetched snapshot. Continued pages must make cursor/ID progress; terminal pinned-only overlap is allowed. Video metadata is checked explicitly; a non-null `imagePost` is rejected even when it accompanies a placeholder `video` object. Photo/non-video variants are unsupported rather than silently reported as videos or dropped.

`complete=true` means the endpoint reported no more pages for this session—not proof that private, deleted, restricted, or otherwise inaccessible posts were collected. Stopping at `--pages` with `has_more=true` produces `complete=false`. Long-running sessions, every region/network, empty/photo-only accounts, initialized extension proofs, other methods/endpoints, and new SDK versions are not validated by this example.

### Validation on 2026-10-07 UTC

The **initial** bounded live command passed with locally generated browser profiles that differed between sessions. Initial visitor IDs **and** initial tokens were distinct; cookies started empty and no captured state was imported. These results precede the terminal-overlap and explicit-photo review fixes; subsequent checks of the final build are recorded below rather than reported as another pass.

| Fresh Python session | Target | Page items | New IDs per page | Unique videos | Requests / result |
| --- | --- | --- | --- | ---: | --- |
| 1 | `laila_verissimo` | 17, 16 | 17, 16 | 33 | 3 GETs; HTTP/2; both JSON status fields 0. |
| 1 | `metropolesoficial` | 16, 16 | 16, 16 | 32 | Same checks passed. |
| 2 | `laila_verissimo` | 17, 16 | 17, 16 | 33 | Same checks passed. |
| 2 | `metropolesoficial` | 16, 16 | 16, 16 | 32 | Same checks passed. |

This is **eight newly signed listing requests plus four profile bootstraps**. The public CLI also ran from `/tmp` using the example's absolute path, returning 33 sorted, deduplicated videos over two pages for `laila_verissimo`, with `has_more=true` and `complete=false`, and no session/signed-media fields in output. The latter is an additional three-GET run, not part of the matrix.

Final offline validation passed **18 timeline self-tests**, **20 original-signer self-tests**, and **100 repository pytest cases** (two pre-existing dependency deprecation warnings). The local port also matched the original signer's complete signed URLs, fields and state transitions across **100 synthetic cases**. AST/format/link checks passed, and protected signer/SDK/cURL hashes remained unchanged.

Timeline tests cover both independent synthetic source-signature vectors, source RNG vectors, seed initialization, serialization/state continuation, malformed RNG/URL rejection before state mutation, generated browser/query consistency, bootstrap/token refresh, invalid/empty JSON responses, chronological deduplication, bounded traversal, terminal pinned overlap, repeated-page/cursor errors, unsupported media, transport normalization/HTTP version, and CLI redaction. These fixtures originated in the signer investigation; tests do not regenerate expected signatures from the timeline port itself.

### Follow-up live failures and review

A repeat of the matrix after metadata/progress fixes exited nonzero. A diagnostic run established that profile HTML arrived over HTTP/2, but the first listing returned HTTP 200, `application/json`, and **zero body bytes**. A separate fresh-session control using `src/agent/sign/example.py` with its original fixed browser context failed with the same empty/invalid-JSON condition. This does not prove rate limiting, a randomization defect, or a particular signature/transport cause. No more requests were made after the failed control, and no browser/replay fallback or relaxed validation was introduced.

The final build is offline-validated, while renewed live acceptance is **blocked by an unresolved empty-response condition**. Earlier successful Python-only retrieval remains evidence of feasibility; it is not a promise of stable access or a final-build live pass. The CLI reports `timeline_failed` and exits 2 instead of treating empty response bytes as an empty timeline. Any further live investigation should be bounded and record the actual response condition without leaking tokens or signed URLs.

One reviewer pass produced one finding:

| Finding | Disposition | Validation |
| --- | --- | --- |
| P2: `imagePost` plus a placeholder `video.duration=0` could be misclassified as a video. | Fixed: reject non-null explicit photo metadata; null/absent `imagePost` remains valid for videos. | Regression covers populated/empty photo objects and a null video-side field; all 18 offline tests pass. |

No automatic second review was performed. SDK/signing constants were not changed to mask the live rejection.

When the signer or SDK changes, compare this intentional local port against the updated signer and independent reference vectors before promotion, then rerun bounded fresh-session acceptance checks. Do not silently replace failed signing with replayed fields or another runtime workflow.
