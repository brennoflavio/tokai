<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Tokai

Privacy-respecting frontend for TikTok. Inspired by Nitter, Proxitok, and OffTikTok.

## Public instances

| URL | CDN | Country |
| --- | --- | --- |
| [tokai.brennoflavio.com.br](https://tokai.brennoflavio.com.br) | No | BR |

The same list is available in [instances.json](instances.json).

## Self-hosting

Only Docker installations are supported at the moment. You can build the image yourself or use one of our pre-built images.

### Pre-built image

You can run Tokai in Docker directly with the following command:

```
docker run --detach \
     --name tokai \
     --restart unless-stopped \
     --publish 127.0.0.1:8000:8000 \
     --env TOKAI_HOST=0.0.0.0 \
     --env TOKAI_PORT=8000 \
     --env TOKAI_LOG_LEVEL=info \
     --env TOKAI_APP_URL=https://tokai.example.com \
     ghcr.io/brennoflavio/tokai:v0.0.2
```

Replace the environment variable values with the ones that better suit your use case.

### Build yourself and run with Docker Compose

First, clone the repository.

```
git clone https://github.com/brennoflavio/tokai
```

Then run:

```
docker-compose up
```

You can change the environment variables in the `docker-compose.yaml` file.


## AI disclaimer and policy

In short:
- AI for coding: ok
- AI for writing: bad

This project makes use of AI in the following forms:
- The reverse-engineering work of TikTok APIs is fully automated by an AI agent, without human supervision.
  It publishes documentation and examples of how to extract videos from the TikTok front end.
  Check `src/agent` for more information.
- From there, the rest of the codebase is either fully coded by humans or AI-assisted (with human review).

The thesis of this project is that capable AI agents can keep up-to-date documentation of how TikTok
works, so it's more maintainable than previous solutions. A weekly job runs and if any drift is found by AI,
the changes are incorporated into the scraper code.

## License

Tokai is AGPL software. You're free to host and modify it, provided you publish your modifications. See [LICENSE](LICENSE)
for more information.
