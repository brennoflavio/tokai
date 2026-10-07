<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Reverse Engineer task

You are an Engineer reverse engineering TikTok's frontend request signing, with the goal of creating a reusable Python signer outside browser context.

Understand how the necessary signatures, fingerprints, and session checks work, document them, and reproduce the signing behavior for `GET https://www.tiktok.com/api/post/item_list/`.
Investigate `X-Gnarly`, `X-Dynosaur`, `X-Bogus`, and other required fields so `src/agent/timeline` can construct fresh first-page and continuation requests.

Your output will be two files in `src/agent/sign`, alongside `PROMPT.md`:

- `DOCS.md` -> Full documentation of signing inputs, algorithms, session requirements, source provenance, validation, usage, and future updates.
- `example.py` -> A self-contained, importable Python signer with a CLI and repeatable offline self-tests.

Read [DOCS.md](DOCS.md), [SDK documentation](../sdk/DOCS.md), the deobfuscated scripts in `src/agent/sdk`, and [timeline documentation](../timeline/DOCS.md) before implementing.

Check whether the files already exist. If so, inspect the previous implementation and validation, then update only outdated behavior from fresh evidence.
Only replace `src/agent/sign/DOCS.md` and `src/agent/sign/example.py`; preserve the last validated implementation if an update cannot be verified.
Do not delete, move, or modify SDK files, timeline code, root captures, or unrelated files.

Use available browser tooling according to its instructions to discover current signing sources and compare fresh browser-generated requests with Python results.
Browser tools are investigation/validation aids, not runtime dependencies. Follow the SDK documentation's restrictions on executing complete SDKs locally.

Example public profiles for validation:
- https://www.tiktok.com/@laila_verissimo
- https://www.tiktok.com/@metropolesoficial

## Requirements

- Generate verified fields, not guessed values or replayed signatures; do not assume every captured field needs an algorithm.
- Keep signing inputs and session/token acquisition explicit, preserve required serialization, and expose an API usable by timeline.
- Validate against independent signing outputs and accepted requests across two fresh sessions and two public targets, including pagination.
- Require successful JSON status, expected author/items, and cursor progress; HTTP 200 alone is insufficient.
- Normal signing must not require a browser, JavaScript runtime, remote signing service, or hidden imported browser state.
- Keep captures and secrets private, minimize requests/files, and document tested defaults, dependencies, and unresolved limitations in `DOCS.md`.
- If blocked, report the missing evidence or unsupported behavior instead of claiming a working signer.
