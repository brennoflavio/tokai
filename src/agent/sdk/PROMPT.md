<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Reverse Engineer task

You are an Engineer with the task of reverse engineer Tiktok frontend website, with the goal of creating a deobfuscated copy of their SDK.

You'll understand how the signature and checks are performaed in the browser, document them, create/update two javascript files, that shows in code how they work.

Your output will be four files, in `src/agent/sdk`, alongside `PROMPT.md`:

- `core_sdk.deobfuscated.js` -> Deobfusctaed copy of `core_sdk.js`.
- `security_extension.deobfuscated.js` -> Deobfusctaed copy of `security_extension.js`.
- `DOCS.md` -> Documentation detailing how you deobfuscated the files and how to repeat the process in case we need to regenerate the files if they change the scripts upstream.
- `SHA256SUMS` -> Reference SHA or the original files so you can compare to see if they changed the files upstream

Check if the files exist. If so, means that you already did this task in the past. It might be incomplete as Tiktok changes its API often, redo the task and
update the files with the latest discovery. Only replace outdated `src/agent/sdk/core_sdk.deobfuscated.js`, `src/agent/sdk/security_extension.deobfuscated.js`,
`src/agent/sdk/DOCS.md` and `src/agent/sdk/SHA256SUMS`; do not delete, move, or relocate files outside those intended paths.

To be able to do this, you have full access to a Playwright environment in this computer, check the skill to learn how to operate it.

Grab the latest tiktok SDK files from a fresh frontend call, here is a link as an example:
- https://www.tiktok.com/@casamentosemdividas/video/7286599702303362310?share_item_id=7286599702303362310&share_app_id=1233

## Requeriments
- Make sure your implementation documents how tiktok signs urls and which fingerprint are collected
- This is not meant to be fully working code, but bases to understand how their frontend work
- Don't include more data and files than necessary

Last note: You're in a headless environment, so getting back to the user is not possible. Do all of it by yourself
