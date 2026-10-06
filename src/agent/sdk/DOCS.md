<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# TikTok SDK — acquisition and future updates

Start here when running an agent in this folder. Preserve the current results until a candidate update has been analyzed and validated. Do not execute complete SDKs: they include browser instrumentation, device collection, and network requests.

## Folder contents

Only these four deliverables are retained:

- `core_sdk.deobfuscated.js`: current best-effort readable core SDK.
- `security_extension.deobfuscated.js`: current best-effort readable security extension.
- `SHA256SUMS`: SHA-256 baseline of the **original obfuscated downloads**, not the readable files.
- `DOCS.md`: acquisition procedure, update guidance, evidence, and limitations.

The original downloads, generator, tests, expanded VM listings, and JSON sidecars were deliberately removed for a minimal folder. **The old generation pipeline cannot be rerun from this folder alone.** Future agents must obtain fresh originals and recreate analysis tooling in scratch space, or recover the previous tooling from a separately available copy. Do not assume those removed files exist or are available in Git history.

Keep downloads, dependencies, scripts, tests, captures, and intermediate results outside this folder. Commands below start **inside `src/agent/sdk`**, using Bash and Python 3; JavaScript syntax validation uses Node.js 24 or newer.

## Current snapshot and provenance

| Original download (not retained) | Bytes | SHA-256 |
| --- | ---: | --- |
| `core_sdk.js` | 243,702 | `6625c4fd90012eb2b6166002b278ac99ba2a2495325590f8eda9071544a814c8` |
| `security_extension.js` | 345,870 | `2a4c099f6d6deed0a1dedd14a8a5375942d7f0f7cc118583073d95c20c22d64b` |

Each readable SDK's header records its original SHA-256. The repository's [video documentation](../video/DOCS.md) records these asset paths from a 2026-09-28 browser capture:

- Core: `https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/webmssdk/1.0.0.417/webmssdk.js`
- Extension: `https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/ttweb_webmssdk_ex/1.0.0.2888/webmssdk_ex.js`

Direct retrieval on **2026-10-06 UTC** returned HTTP 200 JavaScript for both URLs. The core matched the baseline exactly. **The extension did not match**: that URL returned 344,493 bytes with SHA-256 `0ebd0bb8b7071b59b22ca38c88c0df433bee540928cbf626177540660875607a`. The original URL/version of the retained extension result is not established. Do not label it version `1.0.0.2888` or replace it merely to match this historical URL.

Versioned URLs are historical evidence, **not latest-version endpoints**. A successful fetch from an old URL does not establish that TikTok's current page uses it. Hosts, asset paths, bundle roles, and obfuscation can change; discover what a fresh page actually loads.

## 1. Discover current SDK URLs from TikTok

1. Open a fresh, logged-out browser session on a currently accessible public TikTok video page (for example, a URL from the [video prompt](../video/PROMPT.md)) or `https://www.tiktok.com/`.
2. Open Developer Tools → Network, enable **Disable cache** and **Preserve log**, then reload and wait for security scripts to load. Filter for `webmssdk`, `webmssdk_ex`, or JavaScript. Inspect successful JavaScript responses, not reporting endpoints such as `/web/report` or `/web/resource`.
3. Record the exact full request URLs for the core and extension, including host, version path, and any query string. Copy the URL, or use **Copy as cURL** if plain downloads are blocked. Keep copied cookies/tokens private and temporary; never commit them.
4. If names change, inspect script URLs and initiators and confirm bundle roles from their contents. If a challenge/login page loads or one SDK is missing, record that the check is incomplete; do not claim the old snapshot is current or guess a version number.

An agent with browser tools can enumerate resource URLs and script tags with this read-only expression in the page context:

```js
[...new Set([
  ...performance.getEntriesByType('resource').map(entry => entry.name),
  ...Array.from(document.scripts, script => script.src).filter(Boolean),
])].filter(url => /webmssdk|ttweb_webmssdk_ex/i.test(url))
```

Network inspection remains authoritative: resource buffers can omit earlier requests, bundles may load dynamically, and requests may be in another frame. Do not rely only on static page HTML or the desktop application's `static/js/` directory—the historical security bundles were outside it.

## 2. Download candidates and compare exact bytes

Create a scratch directory; **do not run `sha256sum --check SHA256SUMS` in this folder**, because the originals are intentionally absent.

```sh
sdk_dir="$PWD"
work_dir="$(mktemp -d /tmp/tiktok-sdk-update.XXXXXX)"
export work_dir

# Replace these values with URLs observed in the fresh browser session.
export CORE_URL='PASTE_CURRENT_CORE_URL'
export EXTENSION_URL='PASTE_CURRENT_EXTENSION_URL'
```

Download exact response bytes without text normalization, require successful JavaScript responses, and record acquisition evidence:

```sh
python3 - <<'PY'
import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

out = Path(os.environ['work_dir'])
records = {}
for name, variable in [('core_sdk', 'CORE_URL'), ('security_extension', 'EXTENSION_URL')]:
    url = os.environ[variable]
    if not url.startswith('https://'):
        raise SystemExit(f'Set {variable} to the HTTPS URL observed in the browser')
    request = urllib.request.Request(url, headers={'Referer': 'https://www.tiktok.com/'})
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get('Content-Type', '')
        data = response.read()
        if response.status != 200 or 'javascript' not in content_type.lower() or not data:
            raise SystemExit(f'{name}: expected nonempty HTTP 200 JavaScript; got {response.status}, {content_type}')
        records[name] = {
            'requested_url': url,
            'response_url': response.url,
            'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
            'content_type': content_type,
            'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }
    (out / f'{name}.js').write_bytes(data)
(out / 'acquisition.json').write_text(json.dumps(records, indent=2) + '\n')
print(json.dumps(records, indent=2))
PY

(cd "$work_dir" && sha256sum --check "$sdk_dir/SHA256SUMS")
```

Checksum failure is **expected for changed candidates**, not a reason to overwrite the baseline. Inspect each result separately. If retrieval is blocked or returns a challenge/non-JavaScript response, stop and use the browser's captured response/download with approval where required; never silently hash an HTML error page. Inspect downloaded source statically before continuing.

- Same SHA-256: exact same bundle bytes; preserve that readable result.
- Different SHA-256: bundle bytes changed; investigate. Re-obfuscation, packaging, or version text can change a hash without changing the signing algorithm.
- Changed bytecode, opcode behavior, decoded strings, signing entry points, request fields, or schema: evidence to investigate algorithm/schema changes, not proof of a recovered signature formula.

If both match, update the check date/current observed URLs here without rewriting readable SDKs or hashes. Do not update `SHA256SUMS` merely to make a candidate comparison pass.

## 3. Analyze and validate changed SDKs in scratch space

Create or recover static analysis tooling **outside this folder**. The previous pipeline used Node.js 24+, Babel parser/traverse/generator/types `8.0.6`, and Prettier `3.9.9`. These tools alone do not deobfuscate the SDK; custom interpreter and string-decoder analysis is required.

The previous analysis provides an approach, not a guarantee for new SDK versions:

1. Parse the source without executing it. Conservatively simplify constants and property access; respect aliases, mutation, scope, and captured callback writes.
2. Identify the interpreter, bytecode, opcode handlers, register helpers, and string decoders. The old core used raw-DEFLATE bytecode; the extension used a substitution-encoded string table. Do not assume new versions keep those formats.
3. Unpack bytecode without changing bytes, recover strings according to actual decoder semantics, and name helpers by evidenced operations rather than guessed application intent.
4. Retain the interpreter structure in the readable result. Use expanded instruction listings and string tables as scratch analysis aids. Reject ambiguous operand reads, invalid instructions, and uncertain function boundaries rather than guessing.
5. Validate source hashes, byte-for-byte payload recovery, instruction coverage and function-entry boundaries, recovered string triples, and synthetic transformation fixtures. Isolated pure-opcode tests can compare original and expanded behavior; do not execute the complete SDK.
6. Parse the candidate readable files, run `node --check`, review changes, and compare against the retained readable results. Investigate `frontierSign`, initialization, request instrumentation, token handling, signing fields, and schema changes where supported by evidence.

If analysis fails or is incomplete, keep the retained result and hash for that bundle and report the blocker. Do not invent names, remove checks, or label prettified obfuscated code as a fully recovered algorithm. Static tests do not establish browser-level signing equivalence.

## 4. Promote only validated, reviewed results

For **each successfully updated bundle**, copy only its candidate `.deobfuscated.js` into this folder and replace only its matching `SHA256SUMS` entry with the hash of the candidate **obfuscated original**. Preserve the existing result/hash for any unchanged or unvalidated bundle. Keep the original hash in each readable file's header consistent with the baseline.

If both bundles were successfully analyzed and are ready for promotion, the following example updates both:

```sh
node --check "$work_dir/core_sdk.deobfuscated.js" &&
node --check "$work_dir/security_extension.deobfuscated.js" &&
cp "$work_dir/core_sdk.deobfuscated.js" "$work_dir/security_extension.deobfuscated.js" "$sdk_dir/" &&
(cd "$work_dir" && printf '# SPDX-License-Identifier: AGPL-3.0-or-later\n\n' &&
  sha256sum core_sdk.js security_extension.js) > "$sdk_dir/SHA256SUMS"
```

Update this document in the same change: acquisition/check date in UTC, observed page/region or material context, exact requested/final URLs, versions only when evidenced, original byte counts and hashes, recovery statistics, analysis method, schema/algorithm findings, validation results, and unresolved limitations. Use scratch acquisition records as evidence, but do not copy credentials or captures here. Keep exactly the four deliverables listed above.

## Current analysis and limitations

Before the minimal cleanup on **2026-10-06 UTC**, the original pipeline passed **16 regression tests**, verified both original hashes, and reproduced all eight then-existing analysis outputs byte-for-byte in scratch space. Those tests and companion artifacts are no longer retained; this is historical validation, not a runnable test suite in this folder.

| SDK | Bytecode bytes | Opcode handlers | Expanded instructions (historical) | Recovered XOR string/key pairs |
| --- | ---: | ---: | ---: | ---: |
| Core | 98,961 | 365 | 8,515 | 1,042 |
| Security extension | 86,573 | 340 | 7,312 | 1,001 |

Helper names describe observed operations. `runBytecode(address, parentFrame, receiver, arguments, unused, boxedRegisterStart)` enters a VM function. The current frame fields are:

| Frame field | Core | Security extension |
| --- | --- | --- |
| Program counter | `I` | `A` |
| Registers | `o` | `B` |
| Parent frame | `u` | `C` |
| First boxed register | `L` | `u` |
| Exception handlers | `A` | `I` |
| Pending completions | `O` | `o` |

Common registers are `0 = null`, `1 = undefined`, `2 = true`, `3 = false`, `4 = return value`, `5 = this`, and `6 = arguments`. Registers at or above the boxed-register threshold hold `{ v: value }` cells shared with closures. The core exposes names including `frontierSign`, `init`, `report`, `registerWsSigner`, and web-ID setters. The extension includes request instrumentation, browser/device collection, and WebGL inspection.

This is **not a reconstruction of the original source**. VM registers, many application-local identifiers, function boundaries, and flattened control flow remain. Two core string-table entries and five extension entries depend on runtime initialization and remain unresolved. A string/key pair count is not a count of unique plaintext strings.

The readable files retain the interpreter structure. Browser-level behavioral equivalence has **not** been established. Full SDK initialization, signing, device collection, and network requests were not executed during this work. The removed expanded listings exposed additional VM logic; future agents must reconstruct that analysis if needed. Exact reproduction of the old extension input may be impossible without a separate original copy because its acquisition provenance is unknown.
