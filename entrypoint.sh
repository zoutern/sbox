#!/bin/sh
# sbox 镜像入口: 可选 sshd + sbox_app.py(生成配置/起sbox/订阅服务)
set -eu

SSH_ENABLED_L=$(printf '%s' "${SSH_ENABLED:-false}" | tr 'A-Z' 'a-z')
SSH_PORT="${SSH_PORT:-2022}"

if [ "$SSH_ENABLED_L" = "true" ]; then
    mkdir -p /run/sshd /root/.ssh
    [ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A >/dev/null 2>&1

    # 幂等写入受管配置块(删旧块再追加, 支持改端口)
    if grep -q '^# sbox-managed' /etc/ssh/sshd_config; then
        sed -i '/^# sbox-managed/,/^# end-sbox-managed/d' /etc/ssh/sshd_config
    fi
    printf '\n# sbox-managed\nPort %s\nPermitRootLogin prohibit-password\nPasswordAuthentication no\nUsePAM no\n# end-sbox-managed\n' "$SSH_PORT" >> /etc/ssh/sshd_config

    if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
        grep -qxF "$SSH_PUBLIC_KEY" /root/.ssh/authorized_keys 2>/dev/null \
            || printf '%s\n' "$SSH_PUBLIC_KEY" >> /root/.ssh/authorized_keys
        chmod 700 /root/.ssh
        chmod 600 /root/.ssh/authorized_keys
    fi

    /usr/sbin/sshd -f /etc/ssh/sshd_config
    echo "[entrypoint] sshd on :$SSH_PORT (root pubkey login)"
fi

# 至少给一个默认入口，保证容器能起
: "${VLESS_PORT:=8585}"
export VLESS_PORT

echo "[entrypoint] sbox_app starting | VLESS_PORT=$VLESS_PORT CF_TOKEN=${CF_TOKEN:+yes} CF_DOMAIN=${CF_DOMAIN:-none} REALITY_PORT=${REALITY_PORT:-none} S5_PORT=${S5_PORT:-none}"
exec python3 /opt/sbox/sbox_app.py
