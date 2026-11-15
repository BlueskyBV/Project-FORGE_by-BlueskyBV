#!/bin/sh
# A Docker base image for Forge made from Ubuntu 24.04's own archive (docs/V2-stage3.md, 2.6).
#
#   sudo scripts/docker_base_from_archive.sh            # makes forge-base:noble
#   docker build --network host --build-arg BASE=forge-base:noble --target solvers -t forge:solvers .
#
# For a machine whose network reaches Ubuntu's archive and PyPI but no container
# registry, so `python:3.12-slim` can't be pulled. Anywhere a registry is reached,
# the Dockerfile's default base needs none of this.
#
# 1. debootstrap a minimal Ubuntu 24.04 root (kept, so it is made once);
# 2. import it as an image;
# 3. add Python 3, pip and certificates to it, pip allowed to install into the
#    system Python (the image has no other use for it).
#
# Behind a proxy that re-signs TLS, give its certificate bundle as CA_BUNDLE: it
# becomes the trust store pip uses in the image (nothing else changes).
#
# It reads no key and needs none.

set -eu

ROOT=${ROOT:-/opt/roots/noble}
MIRROR=${MIRROR:-http://archive.ubuntu.com/ubuntu}
TAG=${TAG:-forge-base:noble}

if [ ! -x "$ROOT/bin/sh" ]; then
    debootstrap --variant=minbase --components=main,universe noble "$ROOT" "$MIRROR"
fi

tar -C "$ROOT" -c . | docker import - "$TAG-raw"

CONTEXT=$(mktemp -d)
trap 'rm -rf "$CONTEXT"' EXIT
TRUST=""
if [ -n "${CA_BUNDLE:-}" ]; then
    cp "$CA_BUNDLE" "$CONTEXT/ca-bundle.crt"
    TRUST="COPY ca-bundle.crt /etc/forge/ca-bundle.crt
ENV PIP_CERT=/etc/forge/ca-bundle.crt SSL_CERT_FILE=/etc/forge/ca-bundle.crt"
fi

cat > "$CONTEXT/Dockerfile" <<END
FROM $TAG-raw
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 PIP_BREAK_SYSTEM_PACKAGES=1 PIP_ROOT_USER_ACTION=ignore
RUN printf 'deb $MIRROR noble main universe\\ndeb $MIRROR noble-updates main universe\\n' > /etc/apt/sources.list \\
 && apt-get update \\
 && apt-get install --no-install-recommends -y python3 python3-pip ca-certificates make \\
 && ln -sf /usr/bin/python3 /usr/local/bin/python \\
 && rm -rf /var/lib/apt/lists/*
$TRUST
CMD ["python3"]
END

docker build --network host -t "$TAG" "$CONTEXT"
echo "made $TAG"
