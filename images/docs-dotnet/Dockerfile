# syntax=docker/dockerfile:1
# SPDX-License-Identifier: GPL-3.0-only
ARG BASE_IMAGE=docs-base:local
FROM mcr.microsoft.com/dotnet/sdk:10.0.403-noble AS tool
ARG SESHARP_VERSION=1.17.0
RUN dotnet tool install MrKWatkins.Sesharp.Tool --version "$SESHARP_VERSION" --tool-path /opt/sesharp \
    && mkdir -p /tool \
    && cp -a /opt/sesharp/.store/mrkwatkins.sesharp.tool/"$SESHARP_VERSION"/mrkwatkins.sesharp.tool/"$SESHARP_VERSION"/tools/net10.0/any/. /tool/ \
    && mkdir -p /reference-xml \
    && cp -a /usr/share/dotnet/packs/Microsoft.NETCore.App.Ref /reference-xml/ \
    && find /reference-xml -type f ! -name '*.xml' -delete \
    && find /reference-xml -type d -empty -delete

FROM mcr.microsoft.com/dotnet/runtime:10.0.14-noble AS runtime
FROM ${BASE_IMAGE}
ARG SESHARP_VERSION=1.17.0
RUN apt-get update && apt-get install -y --no-install-recommends libicu72 libssl3 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*
ENV DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1
COPY --from=runtime /usr/share/dotnet /usr/share/dotnet
COPY --from=tool /reference-xml /usr/share/dotnet/packs
COPY --from=tool /tool /opt/sesharp
RUN ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet \
    && printf '#!/bin/sh\nexec dotnet /opt/sesharp/MrKWatkins.Sesharp.Tool.dll "$@"\n' > /usr/local/bin/sesharp \
    && chmod +x /usr/local/bin/sesharp \
    && test -n "$(find /usr/share/dotnet/packs/Microsoft.NETCore.App.Ref -type d -path '*/ref/net10.0' -print -quit)" \
    && test ! -d /usr/share/dotnet/sdk \
    && printf 'Sesharp %s\n.NET runtime %s\n' "$SESHARP_VERSION" \
        "$(dotnet --list-runtimes | awk '$1 == "Microsoft.NETCore.App" {print $2}')" >> /opt/docs/versions.txt
LABEL org.opencontainers.image.title="Shared .NET documentation toolchain"
