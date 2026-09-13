#!/bin/sh
# shulker/Pterodactyl python容器专用: 装 supervisord 管理栈(与镜像同一套逻辑)
# 用法(面板控制台执行):  curl -s https://raw.githubusercontent.com/zotenr/sbox/main/shulker-setup.sh | sh
# 之后把面板【启动命令】改为:  sh /opt/entrypoint.sh
set -eu

apk add --no-cache supervisor >/dev/null 2>&1 || apk add supervisor

cat > /opt/entrypoint.sh <<'ENTRY'
#!/bin/sh
set -eu
CONF=/opt/supervisord.conf
SSH_ENABLED_L=$(printf '%s' "${SSH_ENABLED:-false}" | tr 'A-Z' 'a-z')
SSH_PORT="${SSH_PORT:-2022}"
CT="${CLFL_TOKEN:-}"; [ "$CT" = "empty" ] && CT=""
mkdir -p /var/log/sup /run/sshd /root/.ssh "${FILE_PATH:-/opt/sboxapp}"

if [ "$SSH_ENABLED_L" = "true" ]; then
    [ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A >/dev/null 2>&1
    if grep -q '^# sbox-managed' /etc/ssh/sshd_config 2>/dev/null; then
        sed -i '/^# sbox-managed/,/^# end-sbox-managed/d' /etc/ssh/sshd_config
    fi
    printf '\n# sbox-managed\nPort %s\nPermitRootLogin prohibit-password\nPasswordAuthentication no\nUsePAM no\n# end-sbox-managed\n' "$SSH_PORT" >> /etc/ssh/sshd_config
    if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
        grep -qxF "$SSH_PUBLIC_KEY" /root/.ssh/authorized_keys 2>/dev/null \
            || printf '%s\n' "$SSH_PUBLIC_KEY" >> /root/.ssh/authorized_keys
        chmod 700 /root/.ssh; chmod 600 /root/.ssh/authorized_keys
    fi
fi

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
startsecs=3
priority=30
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

if [ "$SSH_ENABLED_L" = "true" ]; then
    printf '\n[program:sshd]\ncommand=/usr/sbin/sshd -D -e\nautostart=true\nautorestart=true\nstartsecs=2\npriority=0\nstdout_logfile=/var/log/sup/sshd.log\nstderr_logfile=/var/log/sup/sshd.log\n' >> "$CONF"
fi

if [ -n "$CT" ]; then
    printf '\n[program:clfl]\ncommand=sh -c "${CLFL_BIN:-cloudflared} tunnel run --token \"$CLFL_TOKEN\" 2>&1 | tee -a /var/log/sup/clfl.log"\nautostart=true\nautorestart=true\nstartsecs=5\npriority=10\nstdout_logfile=/dev/stdout\nstdout_logfile_maxbytes=0\nstderr_logfile=/dev/stderr\nstderr_logfile_maxbytes=0\n' >> "$CONF"
fi

echo "[entrypoint] supervisord: sbox$( [ "$SSH_ENABLED_L" = true ] && echo ' + sshd' )$( [ -n "$CT" ] && echo ' + clfl' )"
exec supervisord -c "$CONF"
ENTRY
chmod +x /opt/entrypoint.sh

cat > /usr/local/bin/svm <<'SVM'
#!/bin/sh
CONF=/opt/supervisord.conf; [ -f /etc/supervisord.conf ] || CONF=/etc/supervisord.conf
CTL="supervisorctl -c $CONF"
progs() { $CTL status | awk '{print $1}'; }
while :; do
    clear 2>/dev/null || true
    echo "═══════════ Supervisor 服务管理 (svm) ═══════════"
    $CTL status | awk '{printf "  %d) %-8s %s %s\n", NR, $1, $2, $3}'
    n=$(progs | wc -l | tr -d ' ')
    echo
    echo "  a) start全部  x) stop全部  r) restart全部  g) 原生命令  q) 退出"
    printf "输入编号[1-%s]或字母: " "$n"; read -r c
    case "$c" in
        q|Q) break;;
        a) $CTL start all;;
        x) $CTL stop all;;
        r) $CTL restart all;;
        g) printf "supervisorctl> "; read -r sc; eval "$CTL $sc"; sleep 1;;
        *[!0-9]*|"") ;;
        *) p=$(progs | sed -n "${c}p" 2>/dev/null)
           [ -n "$p" ] && { echo; echo "── [$p]  1)start 2)stop 3)restart 4)日志 5)tail -f 0)返回"
             printf "选择: "; read -r a
             case "$a" in
               1) $CTL start "$p";; 2) $CTL stop "$p";; 3) $CTL restart "$p";;
               4) tail -n 40 /var/log/sup/"$p".log 2>/dev/null || echo "(输出在控制台)";;
               5) tail -f /var/log/sup/"$p".log;; esac; };;
    esac
    printf "\n(回车继续)"; read -r _
done
SVM
chmod +x /usr/local/bin/svm

echo "✔ 安装完成: /opt/entrypoint.sh + svm"
echo "→ 面板【启动命令】改成: sh /opt/entrypoint.sh   然后重启容器"
