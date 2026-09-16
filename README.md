<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Tokai

Privacy respecting frontend for TikTok. Inspired by Nitter, Proxitok, OffTikTok

## Public instances

| URL | CDN | Country |
| --- | --- | --- |
| [tokai.brennoflavio.com.br](https://tokai.brennoflavio.com.br) | No | BR |

The same list is available in [instances.json](instances.json).

## AI disclaimer and policy

In short:
- AI for coding: ok
- AI for writing: bad

This project makes use of AI in the following forms:
- The reverse engineer work of TikTok API's is fully automated by an AI agent, without human supervision.
  It publishes documentation and examples of how to extract videos from TikTok frontend.
  Check `src/agent` for more info
- From there, the rest of the codebase is either fully coded by humans or AI assisted (with human review).

The thesis of this project is that capable AI agents can keep up an-up-to-date documentation of how TikTok
works, so it's more maintainable than previous solutions. A weekly job runs and if any drift is found by AI,
the changes are incorporated into the scraper code.

## License

Tokai is AGPL software. You're free to host and modify it, providded you publish your modifications. See [LICENSE](LICENSE)
for more information
