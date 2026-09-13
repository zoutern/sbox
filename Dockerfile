FROM alpine:3.21

ARG TARGETARCH

RUN apk add --no-cache supervisor bash openssh jq curl python3 ca-certificates tzdata

# cloudflared: Alpine armhf 无此包, 统一从官方 GitHub release 按架构下载
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) CA=amd64;; \
      arm64) CA=arm64;; \
      arm)   CA=arm;; \
      *) echo "unsupported arch $TARGETARCH" && exit 1;; \
    esac; \
    curl -fL --retry 3 -o /usr/bin/cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CA}"; \
    chmod +x /usr/bin/cloudflared

# 精简版 sing-box（vless/vmess + ws/http/httpupgrade/tcp + TLS/REALITY + 内置cloudflared隧道 + socks/http入口）
RUN set -eux; \
    ARCH="$TARGETARCH"; \
    [ "$TARGETARCH" = "arm" ] && ARCH="armv7"; \
    curl -fL --retry 3 -o /usr/local/bin/sbox "https://sb.vir.kdns.fr/sbox-${ARCH}"; \
    chmod +x /usr/local/bin/sbox; \
    /usr/local/bin/sbox version | head -1

COPY sbox_app.py /opt/sbox/sbox_app.py
COPY entrypoint.sh /entrypoint.sh
COPY svm /usr/local/bin/svm
RUN chmod +x /entrypoint.sh /usr/local/bin/svm

ENV SSH_ENABLED=false \
    SSH_PORT=2022 \
    SSH_PUBLIC_KEY="" \
    CLFL_TOKEN="" \
    SBOX_BIN=/usr/local/bin/sbox \
    FILE_PATH=/var/lib/sbox \
    PORT=3000 \
    SHOW_LOG=true \
    TZ=UTC

EXPOSE 3000 2022

ENTRYPOINT ["/entrypoint.sh"]
