#!/bin/sh
# sbox 镜像入口: supervisord 作为 PID1, 托管 sbox / sshd / cloudflared(可选)
# 交互菜单: 容器里敲 svm
set -eu

CONF=/etc/supervisord.conf
SSH_ENABLED_L=$(printf '%s' "${SSH_ENABLED:-false}" | tr 'A-Z' 'a-z')
SSH_PORT="${SSH_PORT:-2022}"
mkdir -p /var/log/sup /run/sshd /root/.ssh

# ---------- sshd 预备(程序块是否生成由 SSH_ENABLED 决定) ----------
if [ "$SSH_ENABLED_L" = "true" ]; then
    [ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A >/dev/null 2>&1
    if grep -q '^# sbox-managed' /etc/ssh/sshd_config; then
        sed -i '/^# sbox-managed/,/^# end-sbox-managed/d' /etc/ssh/sshd_config
    fi
    printf '\n# sbox-managed\nPort %s\nPermitRootLogin prohibit-password\nPasswordAuthentication no\nUsePAM no\n# end-sbox-managed\n' "$SSH_PORT" >> /etc/ssh/sshd_config
    if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
        grep -qxF "$SSH_PUBLIC_KEY" /root/.ssh/authorized_keys 2>/dev/null \
            || printf '%s\n' "$SSH_PUBLIC_KEY" >> /root/.ssh/authorized_keys
        chmod 700 /root/.ssh; chmod 600 /root/.ssh/authorized_keys
    fi
fi

# ---------- 生成 supervisord 配置 ----------
cat > "$CONF" <<'EOF'
[supervisord]
nodaemon=true
logfile=/dev/stdout
logfile_maxbytes=0
pidfile=/run/supervisord.pid
user=root

[unix_http_server]
file=/run/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///run/supervisor.sock

[program:sbox]
command=sh -c "python3 /opt/sbox/sbox_app.py 2>&1 | tee -a /var/log/sup/sbox.log"
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
startsecs=3
priority=30
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

if [ "$SSH_ENABLED_L" = "true" ]; then
    cat >> "$CONF" <<'EOF'

[program:sshd]
command=/usr/sbin/sshd -D -e
autostart=true
autorestart=true
startsecs=2
priority=0
stdout_logfile=/var/log/sup/sshd.log
stderr_logfile=/var/log/sup/sshd.log
EOF
fi

if [ -n "${CLFL_TOKEN:-}" ]; then
    cat >> "$CONF" <<'EOF'

[program:clfl]
command=sh -c "cloudflared tunnel run --token \"$CLFL_TOKEN\" 2>&1 | tee -a /var/log/sup/clfl.log"
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
startsecs=5
priority=10
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF
fi

echo "[entrypoint] supervisord 启动: sbox$( [ "$SSH_ENABLED_L" = true ] && echo ' + sshd' )$( [ -n "${CLFL_TOKEN:-}" ] && echo ' + clfl' )"
exec supervisord -c "$CONF"
