ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG SDRCONNECT_BUILD
ARG SDRCONNECT_SHA256_AMD64
ARG SDRCONNECT_SHA256_AARCH64

ENV LANG=C.UTF-8

# The official Linux package is a plain tarball -- SDRconnect, its headless
# twin, and the handful of shared libraries they need.  There is nothing to
# install: the SDRplay API is statically linked into swig_bindings.so, so unlike
# most SDR software there is no separate sdrplay_apiService to run alongside it.
#
# The download happens here, at build time on the user's own machine, rather
# than in a published image, because the SDRplay licence covers running and
# displaying the software but not redistributing it.
#
# The package list comes from the DT_NEEDED entries of what the tarball ships:
# swig_bindings.so wants libasound2, libusb, libuuid and libstdc++, and
# libSkiaSharp.so -- which draws the interface headless mode serves -- wants
# libfontconfig.  The two executables themselves are self-contained .NET
# single-file apps that need only libc, but their runtime dlopens libicu and
# libssl, and neither shows up in ldd.
RUN set -eux; \
    case "${BUILD_ARCH}" in \
        amd64)   SDR_ARCH="x64";   SDR_SHA256="${SDRCONNECT_SHA256_AMD64}" ;; \
        aarch64) SDR_ARCH="arm64"; SDR_SHA256="${SDRCONNECT_SHA256_AARCH64}" ;; \
        *) echo "unsupported architecture: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libasound2 \
        libfontconfig1 \
        libicu72 \
        libssl3 \
        libstdc++6 \
        libusb-1.0-0 \
        libuuid1; \
    curl -fsSL -o /tmp/sdrconnect.tar.gz \
        "https://sdrplay.com/software/sdrconnect_linux-${SDR_ARCH}_${SDRCONNECT_BUILD}.tar.gz"; \
    echo "${SDR_SHA256}  /tmp/sdrconnect.tar.gz" | sha256sum -c -; \
    mkdir -p /opt/sdrconnect; \
    tar -xzf /tmp/sdrconnect.tar.gz -C /opt/sdrconnect; \
    rm -f /tmp/sdrconnect.tar.gz; \
    rm -rf /var/lib/apt/lists/*; \
    for lib in /opt/sdrconnect/*.so /opt/sdrconnect/SDRconnect /opt/sdrconnect/SDRconnect_headless; do \
        if ldd "${lib}" | grep -q 'not found'; then \
            echo "missing library for ${lib}:" >&2; \
            ldd "${lib}" >&2; \
            exit 1; \
        fi; \
    done

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
