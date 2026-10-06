ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG DEBIAN_SNAPSHOT
ARG RUST_VERSION
ARG LIBUSB_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ trixie main\n' "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s/ trixie-security main\n' "$DEBIAN_SNAPSHOT" >> /etc/apt/sources.list
# The digest-pinned base may not have CA certificates yet; use signed apt
# repository metadata over HTTP only for the initial package installation.
RUN sed -i 's|https://snapshot|http://snapshot|g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates build-essential python3 \
      cargo="$RUST_VERSION" rustc="$RUST_VERSION" libusb-1.0-0="$LIBUSB_VERSION" && \
    rm -rf /var/lib/apt/lists/*
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC USER=builder LOGNAME=builder
WORKDIR /src
