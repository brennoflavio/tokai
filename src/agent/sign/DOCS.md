<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Browser-free profile-list request signing

## Status and scope

**Implemented and live-validated for `GET https://www.tiktok.com/api/post/item_list/` in the documented SDK initialization mode.** `example.py` generates fresh X-Dynosaur and X-Gnarly, appends the evidenced `X-Bogus=1`, initializes/advances the recovered RNG, and exposes explicit signing state. Its optional Python HTTP/2 helper acquires visitor IDs, target IDs, scoped cookies and msToken, then handles response token updates.

Two fresh Python sessions each retrieved an initial page and a continuation for **both** `laila_verissimo` and `metropolesoficial`. All eight listing requests returned HTTP 200 over HTTP/2, JSON with both status fields zero, expected authors/items, and cursor progress. Each continuation supplied 16 new post IDs. **No browser cookies, captured signatures, remote signer, or JavaScript runtime were used by those Python sessions.**

Those are initial bounded validation results, not a continuing reliability guarantee. Later checks included accepted requests through both httpx and wreq, missing initial tokens and empty HTTP-200 refusals; [follow-up experiments](#follow-up-dtk-and-transport-experiments-2026-10-07-utc) record the current evidence.

This is not a port of the whole security SDK or a universal TikTok client. The supported mode uses source-defined initial collector state, the missing-canvas branch, and no initialized security extension. The extension's populated proof mode is not implemented; its absent-state branch is generated from source defaults, not replayed proof values. Acceptance is established for this endpoint/mode and test matrix, not every region, network, account, SDK version, or future server policy.

Files:

- `PROMPT.md`: task contract, unchanged.
- `example.py`: self-contained signing implementation, optional HTTP/2 acquisition helper, CLI and offline tests.
- `DOCS.md`: supported inputs/algorithms, provenance, usage, validation and maintenance.

SDK files, timeline code, dependency manifests and root captures were not modified. [Timeline documentation](../timeline/DOCS.md) remains the historical endpoint/schema evidence; this document supplies the subsequent signing experiments. Follow the [SDK restrictions](../sdk/DOCS.md): never execute complete downloaded/retained SDKs as local analysis programs.

## Runtime and quick start

- Signing and offline tests: Python **3.14+**, standard library only.
- `ProfileSession` and `--validate-live`: **`httpx[http2]>=0.28,<1`**. Tested with httpx `0.28.1` and h2 `4.4.1`, on Python `3.14.3`; offline checks also ran on Python `3.14.4`.
- Browser tooling, Node.js, cURL, raw captures, scratch files and the investigation add-on are **not runtime dependencies**.
- TLS certificate verification remains enabled. Redirects are not followed. The helper advertises only identity response encoding.

Optional HTTP dependency installation, in your chosen environment:

```sh
python3 -m pip install 'httpx[http2]>=0.28,<1'
```

From the repository root:

```sh
python3 src/agent/sign/example.py --self-test
python3 src/agent/sign/example.py --sign /path/to/private-request.json
python3 src/agent/sign/example.py --sign -     # JSON on stdin
# Explicitly performs network requests: two fresh sessions × two targets × two pages.
python3 src/agent/sign/example.py --validate-live
```

`--validate-live` prints only redacted counts/status/progress. `--sign` deliberately emits sensitive signed URLs, fields and updated state: keep stdout private. Errors are fixed redacted JSON on stderr with a nonzero exit status; they do not include input values, URLs, private paths or JSON parser excerpts. Do not put cookies/tokens in shell arguments or history.

## API and ownership boundaries

### Pure signing

```python
from src.agent.sign.example import Environment, create_state, sign

state = create_state(issued_ms_token)  # local entropy; no network or browser read
request = sign(
    unsigned_url,                     # exact serialized endpoint URL
    state,
    Environment(user_agent, public_profile_url),
)
# Send request.url unchanged with the corresponding User-Agent, Referer and
# domain/path-scoped cookie jar. Process token updates before signing again.
```

`sign(unsigned_url, state, environment, *, timestamp_ms=None) -> SigningResult` supports an **empty-body GET only**. It does not send a request. The absolute input must have the exact HTTPS origin/path above, an ASCII/percent-encoded query, and no fragment or preexisting X-Dynosaur/msToken/X-Bogus/X-Gnarly parameters. It preserves query ordering, duplicates, emptiness, escaping and percent-escape spelling. There is no dictionary-based decode/re-encode step. Use `build_unsigned_url()` for the tested query profile or supply your own exact serialization.

The result provides `url` and `fields`. Sending code must not rebuild/modify the URL afterward. A target, cursor, query, token, time, environment or relevant state change requires a new signature.

**Stateful behavior:** signing increments total/intercepted request counts and consumes 24 RNG words (12 per generated signature). These mutations are intentional. Serialize access to a state object; do not share one concurrently between requests or unrelated sessions. A failed transport does not justify rewinding counters/RNG or replaying the prior signed URL.

### SigningState

`SigningState` contains:

| Field | Meaning |
| --- | --- |
| `ms_token` | Server-issued current query token; not synthesized. |
| `gnarly_seed`, `dynosaur_seed` | Separately initialized fingerprint seeds from the recovered time/random formula. |
| `rng_words`, `rng_index` | Sixteen-word RNG state and output index, not a captured encryption key/signature. |
| `total_requests`, `intercepted_requests` | Counts for this helper's intercepted listing requests; zero before the first sign. |

`create_state(token, timestamp_ms=...)` initializes seeds/RNG from current time and fresh local entropy using the recovered initialization structure. The three random uint32 initialization words and four random fractions replace the SDK's initialization calls to Math.random, **not** its recovered subsequent PRNG. Normal signing generates new encryption words from the ported PRNG; callers no longer need browser-provided words.

For deterministic comparison, construct `SigningState` with explicit seeds/RNG/counters and pass `timestamp_ms`. The low-level `generate_x_gnarly()` API remains available with explicit `GnarlyState`, timestamp and twelve words; `--input FILE` exposes that older component-only interface and marks its output `complete_signer: false`.

### Environment and tested defaults

`Environment(user_agent, page_url, env_code=0, interaction_code=0, canvas_hash=-1)` is explicit and independent of installed browser state.

- `env_code=0` and `interaction_code=0` are the core's initial collector values. They do **not** claim that the Python process has a real browser's measured environment.
- `canvas_hash=-1` is the source's canvas-unavailable/error result. The earlier field named `performance_value` in `GnarlyState` is actually sourced from a cached canvas hash; it is not a performance timer. Negative tag omission and associated bitwise/checksum behavior are implemented.
- The supported clock-selection branch is `2`, with no forced timestamp override or timing guard. Other low-level clock/guard modes explicitly fail; there is no guessed approximation.
- `page_url` supplies `host + pathname`, truncated to 50 characters as in the source. It is distinct from the API URL and from the `referer` query parameter.
- The HTTP helper's tested query profile is desktop Linux, Firefox 157 User-Agent, English, 1280×720, UTC, `count=16`, and data collection disabled. Region/visitor IDs/creation time come from the fresh profile response, not constants. These are tested client defaults, not a reconstructed native device fingerprint.

The successful Python requests omit `verifyFp` and do not create/import `s_v_web_id` or CAPTCHA cookies. This establishes that those fields are not necessary **for this tested mode/session bootstrap**, not a universal parameter-removal result. No minimal query/header/cookie set or universal token lifetime is claimed.

## Explicit session and token acquisition

The optional helper keeps network operations separate from `sign()`:

```python
from src.agent.sign.example import ProfileSession

with ProfileSession() as session:
    profile = session.bootstrap_profile("laila_verissimo")
    first = session.fetch_page(profile)
    if first["hasMore"]:
        second = session.fetch_page(profile, cursor=first["cursor"])
```

`bootstrap_profile()` performs a public-profile GET and parses `__UNIVERSAL_DATA_FOR_REHYDRATION__`, without executing page code. It validates application status/identity and rejects private/unavailable profiles. From `webapp.app-context` it obtains `wid`, `odinId`, `webIdCreatedTime`, and region; `webapp.user-detail` supplies the target secUid and canonical handle. Visitor and target identities remain distinct.

In the successful fresh Python bootstraps, response cookies included `ttwid`, `tt_csrf_token`, `tt_chain_token` and `msToken`. Their **actual** server-provided domain/path/expiry/secure attributes are retained in the HTTP client's jar. Cookies are not flattened into a name/value dictionary, imported from root captures, or forwarded to arbitrary redirects/CDNs. `bootstrap_profile()` is not a claim that these are the minimal required cookies.

After bootstrap/listing responses, `_refresh_token()` consumes `x-ms-token` or a unique response-issued msToken cookie. If both are present they must agree. It updates query-signing state separately from the cookie jar, which processes Set-Cookie normally and retains scopes/duplicates. Missing initial tokens and conflicting updates fail explicitly; there is no synthetic-token fallback. Subsequent signatures use the updated token.

A valid HTML page alone does not prove API access. `fetch_page()` separately requires HTTP/2, HTTP 200, JSON with integer `statusCode == status_code == 0`, the expected author uniqueId/secUid and string post IDs, and a progressing cursor when `hasMore` is true. Empty/non-JSON bodies and challenge/error responses are not converted into successful empty timelines. The live validator additionally requires actual initial/continuation items and new post IDs; pinned overlap is allowed.

This helper is bounded acquisition/validation infrastructure for the signer, **not** an implementation of bulk timeline extraction, media downloading, private-account access, or a CAPTCHA solver. If access is challenged, stop and report it; do not silently switch to a browser or remote signer at runtime.

## CLI schemas

Full `--sign` JSON has exactly four keys:

```text
{
  "unsigned_url": "<exact unsigned GET URL>",
  "state": {<all SigningState fields>},
  "environment": {<Environment fields>},
  "timestamp_ms": <integer, or null for current time>
}
```

Use `dataclasses.asdict()` to serialize the state/environment obtained through the API. This JSON contains credentials/fingerprint state and must be private. Output contains `signed_url`, `fields`, updated `state`, and `complete_signer: true` for the documented mode. Persist the returned state if using separate CLI processes; do not reuse the original pre-sign state on continuation.

Low-level `--input` retains the previous X-Gnarly-only schema: `query`, `user_agent`, `timestamp` (seconds), `state` (GnarlyState fields), and `key_words`. Its query must already include freshly generated X-Dynosaur and the correct msToken, but not X-Bogus/X-Gnarly. It is intended for independent fixtures/diagnostics, not as a substitute for the full signer.

## Algorithms and serialization

All offsets below refer to the recorded **core SDK hash**, not a stable external API.

### Field assembly and X-Bogus

The URL security-field assembly starts at VM offset **61636**. Core string/key pairs decode to `(684,3) = X-Dynosaur`, `(685,1) = msToken`, `(686,5) = X-Bogus`, `(688,5) = X-Gnarly`.

1. Compute X-Dynosaur from the unsigned serialized query and explicit state/context.
2. Append X-Dynosaur and current msToken in that order.
3. Compute X-Gnarly over that resulting query.
4. Append literal **`X-Bogus=1`**, then X-Gnarly.

The literal `1` is recovered from `(687,1)` and observed in accepted requests; a historical X-Bogus algorithm is not substituted. Exported `frontierSign` at **72103** is a different wrapper returning an X-Bogus property, not the endpoint URL assembler.

### X-Dynosaur: producer 57757

The request/body/User-Agent hash starts at **51033**: UTF-8 bytes, initial value `2166136260`; for each byte, XOR, multiply by `16777619`, then multiply by `33`, reducing modulo `2**32`; output four big-endian bytes. This is not ordinary FNV-1a with its usual offset/multiplication alone.

String encoding at **34001** operates on UTF-16 code units with position-dependent XOR/addition, byte rotation and constants. It pads to at least six bytes and stores the original length in the last two big-endian bytes. The checksum record uses a related, distinct transform at **60091**. See the direct Python operations for exact constants and ordering; it is not Base64 or encryption by itself.

The payload has **no record-count prefix**. It serializes tags 32–56 as one-byte tag, two-byte big-endian length, and bytes:

| Tags | Contents in the supported mode |
| --- | --- |
| 32 | Encoded decimal XOR of the second byte of each pre-checksum record. |
| 33, 34 | Source marker bytes `(94, 222, 223, 224, 0, 1)`. |
| 35, 41, 45, 55 | Source-initialized encoded `"0"` fields; further semantics not claimed. |
| 36 | Encoded signed time/seed/environment half-word proof. |
| 37, 47 | Encoded intercepted/total request counts. |
| 38, 54 | Encoded environment/interaction codes. |
| 39, 44 | Encoded Unix seconds and canvas result. |
| 40, 50, 51 | Encoded `"0"` for absent computed extension proof/version/extension-seed hash. |
| 42, 49 | Encoded source versions `5.3.2` and `1.0.0.417`. |
| 43, 46, 48 | Four-byte hashes of empty body, unsigned query, and User-Agent. |
| 52, 53 | Encoded Dynosaur seed and truncated page host/path context. |
| 56 | Four-byte hash of empty absent extension proof. |

The source's initialized-extension branch has additional seed/proof/callback inputs. One accepted browser fixture used the absent-extension branch and matched Python exactly. More importantly, **all eight Python listing requests in the live matrix generated this branch afresh and were accepted**. Unknown initialized-extension behavior is not replayed or hidden in input constants.

### X-Gnarly: producer 51455

This branch uses a one-byte record count followed by the same tag/length/value framing. Integers use two bytes through 65535, otherwise four; negative/out-of-uint32 numeric records are omitted. Text is UTF-8.

| Tags | Values |
| --- | --- |
| 0 | XOR checksum with JavaScript numeric coercion, including tag 16. |
| 1, 2 | Environment and interaction codes. |
| 3 | Lowercase MD5 hex of the exact query **including X-Dynosaur and msToken**. |
| 4, 5 | MD5 hex of the empty body and explicit User-Agent. |
| 6, 7, 8 | Unix seconds, canvas result, Gnarly seed. |
| 9, 10, 11 | Source constants `5.3.2`, `1.0.0.417`, integer `1`. |
| 12, 13 | Effective total/intercepted request counts. |
| 14 | Signed time/seed half-word XOR combined with `envcode << 16`. |
| 15 | Low half: timestamp XOR seed; high half: canvas result XOR seed's high half. Envcode bit 32 selects source constant `1767225600` for the low-half timestamp. |
| 16 | XOR using numeric values directly and up to the first four UTF-8 bytes of strings as a big-endian word. |

Records are shuffled by the source LCG (`1664525`, `1013904223`, modulus `2**32`) seeded by the Gnarly seed. Entries **51453**, **53427** and **53602** cover checksums, shuffle and serialization. The port preserves 32-bit signed/unsigned behavior and JS Number coercion, including decimal/scientific-looking digest strings. Unpaired Unicode surrogates are explicitly unsupported.

### Shared envelope and RNG

Both implemented signature paths call **8193** with compression disabled and mode 1:

- Twelve encryption words plus source constants `(1196819126, 600974999, 3863347763, 1451689750)` initialize a modified ChaCha-like cipher.
- It is **not standard ChaCha**: two diagonal tuples are `(2,7,12,13)` and `(3,4,13,14)`. Round count is `5 + (sum(words) & 15)`; state word 12 increments between blocks.
- Serialize the twelve words little-endian. Insert their 48 bytes at `(sum(ciphertext) + sum(key_bytes)) % (len(ciphertext) + 1)`.
- Prefix `0x4b` and encode using the source `s3` alphabet. Neither signature length nor alphabet membership is an acceptance check.

The RNG at **78927** uses an eight-round block with different initial constants, a timestamp word and three random uint32 words. It combines a raw block result and 21 bits of another into a 53-bit fraction, advancing its index and counter. **Raw JS additions must not be prematurely truncated** in this RNG; doing so changes the stream even though modular truncation is safe for cipher byte output. Forty-word independent source vectors exercise multiple counter advances.

Separate fingerprint seeds at **50799** use `floor(abs(1000 * (Date.now() + random1 + random2) % 2**31))`, preserving binary64 operation order. Explicit synthetic source vectors verify the formula. No token, device ID, canvas fingerprint or reusable proof value from a capture is hardcoded as a live default.

## Source provenance and investigation

Observed in both browser investigations; separate cookie-free HTTPS retrieval at **2026-10-06 23:17:52 UTC** returned HTTP 200 `application/javascript`, identity encoding, unchanged final URLs:

- Core: `https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/webmssdk/1.0.0.417/webmssdk.js`
- Extension: `https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/ttweb_webmssdk_ex/1.0.0.2904/webmssdk_ex.js`

| Asset | Bytes | SHA-256 of original download |
| --- | ---: | --- |
| Core | 243,702 | `6625c4fd90012eb2b6166002b278ac99ba2a2495325590f8eda9071544a814c8` |
| Extension | 345,870 | `2a4c099f6d6deed0a1dedd14a8a5375942d7f0f7cc118583073d95c20c22d64b` |

Both match the retained SDK baseline/header hashes. The extension URL establishes a matching public source location, not the unknown original acquisition history. The older `1.0.0.2888` mismatch in SDK documentation remains valid historical evidence. These hashes are of separate downloads, not independently captured browser response bytes; versioned paths are not latest-version guarantees.

Static extraction reconstructed 98,961 core bytecode bytes and a linear 8,515-instruction listing in private scratch. Only selected signing/encoding/RNG paths were executed as an isolated JS reference: 160 selected opcode handlers, explicit state/time/entropy, no process/require/network API exposed, dynamic code generation disabled. **No complete SDK initialization was executed locally.** Standard MD5/Base64 adapters were used at those primitive boundaries. The Python implementation does not contain or run the VM.

Browser observations were investigation aids only. Initial Firefox connectivity failure led to a user-approved Playwright attempt, which encountered a CAPTCHA/login screen. Restored Firefox later produced five accepted request fixtures in one existing session without a CAPTCHA. A user-approved temporary, TikTok-limited add-on subsequently captured exact headers and scoped cookies from its own isolated investigation session. After its initial empty response, the user was asked to check/solve any CAPTCHA and reported “done”; subsequent captures contained accepted pages. A tab-enumeration limitation prevented the agent from independently confirming the visible challenge. No challenge was solved automatically. Captures were encrypted across the page bridge and stored privately outside the repository. None entered the Python runtime/bootstrap. Cleanup removed the add-on's two investigation tabs and its one container, then uninstalled the temporary add-on; existing user containers were not removed.

A fresh browser-request replay less than five seconds old returned empty HTTP 200 through Python HTTP/1.1, but valid JSON/items through cURL HTTP/2. This was a **diagnostic replay**, not signer validation. Subsequent **fresh Python-generated** requests through httpx HTTP/2 passed. This establishes a tested transport choice, not proof that HTTP version alone explains every acceptance difference or that TLS/header differences never matter.

## Validation

Offline:

- Original download SHA-256 checks and `node --check` passed during acquisition.
- Existing X-Gnarly source vectors remain unchanged and pass.
- Five private browser X-Gnarly reconstructions match exactly with explicit fixture time/state/words; one absent-extension browser X-Dynosaur reconstruction matches exactly. Hidden inputs recovered from outputs are comparison evidence, not an acquisition method.
- Two independent extracted-source **complete** signature vectors cover both producers, the RNG, missing canvas, uint32/seed limits, Unicode User-Agent, escaping, duplicates and emptiness. Source-derived RNG-stream hashes and fingerprint-seed outputs are embedded as synthetic fixtures only.
- Twenty offline self-tests cover these vectors, state continuation/serialization, invalid inputs/unsupported paths, CLI redaction, response validation, bootstrap parsing and token conflict handling. Self-tests need neither network nor httpx.

Live, **2026-10-07 UTC**, complete Python signing and bootstrap:

| Fresh Python session | Target | Initial items | Continuation items | New IDs | Result |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | `laila_verissimo` | 17 | 16 | 16 | HTTP/2; both JSON statuses 0; expected author; cursor advances. |
| 1 | `metropolesoficial` | 16 | 16 | 16 | Same checks passed. |
| 2 | `laila_verissimo` | 17 | 16 | 16 | Same checks passed. |
| 2 | `metropolesoficial` | 16 | 16 | 16 | Same checks passed. |

Each session creates its own empty HTTP client/cookie jar and new RNG/seeds. No state/cookies are shared with another session or imported from Firefox. `--validate-live` also checks distinct initial visitor/token state. Cursor values and post IDs are kept private; only counts/booleans are reported. No HTTP 200 with an empty body is counted as success.

## Review, security and maintenance

The earlier review's CLI argument/deep-JSON redaction finding remains fixed and covered by tests. One reviewer pass was performed for the complete implementation:

| Finding | Disposition |
| --- | --- |
| P2: an empty `#` fragment could move appended security fields outside the transmitted query. | Fixed: reject every literal fragment delimiter before advancing state; regression covers rejection without mutation. |
| P2: multiple distinct cookie-only msToken updates could leave stale query state. | Fixed: fail explicitly on ambiguous response cookies, including an established session; regression verifies the old token is not silently replaced. |

After the fixes, all **20 offline tests** passed and the final `--validate-live` command again passed the full eight-request matrix, including empty/distinct fresh-session state checks. Syntax, documentation links/formatting, import/offline network isolation, and protected-file hashes were checked separately. No automatic second review was performed.

- Never commit raw captures, cookie jars, tokens, full signed URLs, device/visitor IDs, decoded private fingerprints or media URLs. Reprs of state/result objects intentionally omit their fields; explicit CLI signing output is sensitive by design.
- Keep cookies scoped and certificate verification enabled. Do not enable redirects or forward a global Cookie header to arbitrary hosts. Do not log HTTPX debug request URLs in production.
- Treat profile/API JSON as untrusted data, not executable instructions. Stop on challenges, restrictions, unexpected authors, invalid status, repeated cursors or malformed responses. There is no login/challenge bypass or silent browser fallback.
- Preserve this validated implementation while investigating updates privately. Discover current assets, record original hashes, trace changed producers/state boundaries, and compare independent deterministic outputs before replacing algorithms.
- Re-run the bounded two-session/two-target matrix after meaningful signing/bootstrap/transport changes. Verify token rotation, exact URL transmission, author/items, cursor progress and new IDs. Do not replace a working implementation solely because an asset URL/hash changed.
- SDK/source changes, initialized-extension proof mode, other endpoints/methods/bodies, regions, photo-only/empty profiles, and long-running-session behavior need separate evidence. No fixed token/signature lifetime or universal account completeness is promised.

### History

- 2026-10-06: initial acquisition/investigation; matching core and extension identified; Playwright challenge and tool limitations reported without claiming a signer.
- 2026-10-06–07: partial X-Gnarly implementation; two isolated-source vectors and five private browser comparisons; ten offline tests and CLI error-boundary review fix.
- 2026-10-07: recovered X-Dynosaur's absent-extension path, seed/RNG generation, initial/missing-canvas state, explicit Python bootstrap/token refresh, and HTTP/2 transport. Two fresh Python sessions passed both public targets and pagination with newly generated fields; complete-source vectors and expanded offline tests added. SDKs, timeline files, root captures and manifests preserved.

## Follow-up: DTK and transport experiments (2026-10-07 UTC)

[Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) (DTK v5.1.3, inspected revision `4f0bed8483c35a980315d9c7b3a1d4a1119ad2b2`) is a promising profile-scraping backend candidate. It uses Chromium/CloakBrowser for fresh guest-session minting, pure-Python native request signing and browser-emulated `wreq` for upstream HTTP acquisition. Optional browser signing fallback was not used in our tests. **Pure-Python signatures do not make its session-acquisition workflow browser-free.**

DTK's TikTok signer emits X-Dynosaur, msToken, literal `X-Bogus=1` and X-Gnarly. Its source fields declare `5.3.2` / `2.0.0.561`, whereas this implementation derives from `5.3.2` / `1.0.0.417`; payload/environment/checksum details also differ. A version-string substitution is not an algorithm update, and these differences are not established as the cause of our refusals.

### Accepted signatures do not guarantee stable acquisition

The DTK source-level pipeline fetched two pages for both public profiles in each of two fresh browser-minted sessions: 33 distinct posts for Laila and 32 for Metrópoles per session, with parsing and cursor progress verified. This tested native signing, not the full REST/database deployment, complete account histories or sustained reliability.

A separate matched-context crossover preserved the exact signed URL, explicit headers and cookies within transport pairs. The interpretable DTK-query phase yielded 8 accepted `wreq` requests and 8 empty HTTP-200 `httpx` responses across both profiles, both signers and HTTP/browser-acquired credentials. Refusals carried `tt_orcas_res`. Thus our local signer produced accepted requests; replacing its algorithm is not yet justified by these observations.

This did **not** isolate TLS from HTTP/2 settings, header ordering, connection reuse/history or other client behavior. The shared wreq client began with browser-session controls. Later query comparisons lost positive controls, and standalone HTTP-only follow-ups also failed their controls and stopped. Browser minting failed once too. Session validity, network/exit policy and time-varying protection remain unresolved; do not claim proven rate limiting, a universal token-length threshold or a reliable transport-only fix.

### Tests of the original examples with wreq

A temporary adapter preserved original request serialization, headers, scoped cookies/response updates, query builders, signing state and validation. It changed network acquisition only. No browser, imported cookies, DTK signer or JavaScript runtime was used. Original Firefox 157 User-Agents were retained; the installed wreq had only Firefox151 desktop emulation, which is a known mismatch.

| Original sign example | Emulated wreq | httpx | wreq without explicit browser profile |
| --- | --- | --- | --- |
| `laila_verissimo` | 17 + 16 items; 33 distinct posts | Same | Same |
| `metropolesoficial` | Empty HTTP 200 | Same | Same |

Laila's application status, author identity and continuation/new-ID checks passed in every mode. This helper validates **post lists**, not video-only normalization, so do not report all 33 items as confirmed videos. The timeline example also obtained valid listing pages but failed with `unsupported video metadata`. A later inspection attempt was refused before data arrived; the rejected schema field/media type is unknown.

**The TLS-only hypothesis is not confirmed.** Explicit browser emulation was neither necessary nor sufficient in this run. The results support browser-free signing/retrieval feasibility, not consistent access or DTK's proven long-term superiority.

### Evidence and maintenance

Full endpoint/pagination/normalization findings and the cross-example result table are in [timeline section 10](../timeline/DOCS.md#10-dtk-backend-and-transport-comparison-2026-10-07-utc). Tracking: [Forgejo issue #11](https://git.brennoflavio.com.br/brennoflavio/tokai/issues/11).

The 20 signer and 18 timeline offline tests passed; the temporary transport adapter's cookie-scope/header/HTTP2 regression passed. Scratch reports are `/tmp/tiktok-api-inspect-karoVc/ISOLATION_FINDINGS.md` and `/tmp/tokai-wreq-examples-CQ7Uud/FINDINGS.md`, with redacted results alongside them. These ephemeral artifacts contain no cookie/token values or signed URLs and are not runtime dependencies.

The repository examples and manifests were not changed by the experiments; wreq is not an implemented example option. Preserve the signer while investigating transport/session conditions independently, retain failed controls, and resolve video-only normalization separately from acceptance. An eventual Chromium-minted DTK integration would require an explicit decision to change the browser-free requirement.
