FROM alpine:3.21

ARG TARGETARCH

RUN apk add --no-cache openssh jq curl python3 ca-certificates tzdata

# 精简版 sing-box（vless/vmess + ws/http/httpupgrade/tcp + TLS/REALITY + cloudflared隧道 + socks/http入口）
# 构建时按目标架构从发布站拉取裸二进制
RUN set -eux; \
    ARCH="$TARGETARCH"; \
    [ "$TARGETARCH" = "arm" ] && ARCH="armv7"; \
    curl -fL --retry 3 -o /usr/local/bin/sbox "https://sb.vir.kdns.fr/sbox-${ARCH}"; \
    chmod +x /usr/local/bin/sbox; \
    /usr/local/bin/sbox version | head -1

COPY sbox_app.py /opt/sbox/sbox_app.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ---- 环境变量 ----
# SSH_ENABLED=true 时启动 sshd
ENV SSH_ENABLED=false \
    SSH_PORT=2022 \
    SSH_PUBLIC_KEY="" \
    SBOX_BIN=/usr/local/bin/sbox \
    FILE_PATH=/var/lib/sbox \
    PORT=3000 \
    SHOW_LOG=true \
    TZ=UTC

EXPOSE 22 3000

ENTRYPOINT ["/entrypoint.sh"]
