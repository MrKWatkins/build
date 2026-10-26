# syntax=docker/dockerfile:1
# SPDX-License-Identifier: GPL-3.0-only
FROM node:26-bookworm-slim AS dependencies
WORKDIR /opt/docs/tooling
COPY docs/tooling/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM node:26-bookworm-slim AS styles
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip hunspell-en-gb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /downloads
RUN curl -fsSL https://github.com/vale-cli/vale/releases/download/v3.24.0/vale_3.24.0_Linux_64-bit.tar.gz -o vale.tar.gz \
    && echo '867534ddb678abca7f214bc4706ead0922bd5252ffe8035fc227013f66c8b214  vale.tar.gz' | sha256sum -c - \
    && tar -xzf vale.tar.gz \
    && curl -fsSL https://github.com/vale-cli/Microsoft/releases/download/v0.15.1/Microsoft.zip -o Microsoft.zip \
    && echo '0b37660b244a9399d7f10225895773291d27b2967ed0d239a1d379b633e8cd16  Microsoft.zip' | sha256sum -c - \
    && curl -fsSL https://github.com/vale-cli/write-good/releases/download/v0.4.1/write-good.zip -o write-good.zip \
    && echo '2960ef10861ddc7dc76292a4967eb3789bf05ca24f862042f6d15f53332887f0  write-good.zip' | sha256sum -c - \
    && mkdir -p /styles/config/dictionaries /licenses \
    && unzip -q Microsoft.zip -d /styles && unzip -q write-good.zip -d /styles \
    && cp /usr/share/hunspell/en_GB.aff /usr/share/hunspell/en_GB.dic /styles/config/dictionaries/ \
    && cp /usr/share/doc/hunspell-en-gb/copyright /licenses/en_GB.txt \
    && cp LICENSE /licenses/Vale.txt \
    && curl -fsSL https://raw.githubusercontent.com/vale-cli/Microsoft/v0.15.1/LICENSE -o /licenses/Microsoft.txt \
    && curl -fsSL https://raw.githubusercontent.com/vale-cli/write-good/v0.4.1/LICENSE -o /licenses/write-good.txt

FROM node:26-bookworm-slim
LABEL org.opencontainers.image.title="Shared documentation toolchain" \
      org.opencontainers.image.source="https://github.com/MrKWatkins/build" \
      org.opencontainers.image.licenses="GPL-3.0-only"
ENV HOME=/tmp DOTNET_NOLOGO=1
COPY --from=dependencies /opt/docs/tooling/node_modules /opt/docs/tooling/node_modules
COPY --from=styles /downloads/vale /usr/local/bin/vale
COPY --from=styles /styles /opt/docs/vale/styles
COPY --from=styles /licenses /opt/docs/licenses
COPY LICENSE /opt/docs/LICENSE
COPY docs /opt/docs
RUN printf '#!/bin/sh\ncat /opt/docs/versions.txt\nexec node /opt/docs/tooling/docs.mjs "$@"\n' > /usr/local/bin/docs \
    && chmod +x /usr/local/bin/docs \
    && printf 'Node %s\nVitePress 1.6.4\nVue 3.5.44\nVale 3.24.0\nMicrosoft styles 0.15.1\nwrite-good styles 0.4.1\n' "$(node --version)" > /opt/docs/versions.txt
WORKDIR /workspace
ENTRYPOINT ["docs"]
