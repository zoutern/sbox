# sbox (Docker image)

精简版 sing-box + OpenSSH 的多架构 Docker 镜像。

- **sbox** = sing-box 1.14.0 定制编译：vless / vmess（ws / http / httpupgrade / tcp，TLS + REALITY）、
  **内置 Cloudflare Tunnel（cloudflared 入口，无需另装）**、socks / http 入口、direct / block / 分组出口、全套 DNS。
  不含：TUIC / Hysteria / Trojan / SS / AnyTLS / QUIC / TUN / WireGuard / Tailscale。
- 启动逻辑由内置 `sbox_app.py`（纯标准库）完成：生成配置 → 拉起 sbox → 订阅 HTTP 服务。
- `SSH_ENABLED=true` 时同时跑 sshd（公钥登录，方便进容器排查）。

镜像：`ghcr.io/momomov/sbox:latest`（amd64 / arm64 / armv7）

## 环境变量

### SSH
| 变量 | 说明 |
|---|---|
| `SSH_ENABLED` | `true` 开启 sshd，默认 `false` |
| `SSH_PORT` | sshd 端口，默认 `2022` |
| `SSH_PUBLIC_KEY` | root 授权公钥（`ssh-ed25519 AAAA... user@host` 整行）|

### 节点（sbox_app.py）
| 变量 | 说明 |
|---|---|
| `UUID` | 节点 UUID，留空自动生成 |
| `CF_TOKEN` | Cloudflare 隧道 Token（配合 `CF_DOMAIN` 开启隧道）|
| `CF_DOMAIN` | 隧道 vless 域名（ingress service 填 `http://localhost:8585`）|
| `CF_VMESS_DOMAIN` | 可选，vmess 第二域名（service 填 `http://localhost:8586`）|
| `VLESS_PORT` | 直连 vless-ws 端口（默认 `8585`）|
| `REALITY_PORT` | 直连 REALITY 端口，留空不开 |
| `S5_PORT` | Socks5 端口（账密=UUID派生），留空不开 |
| `CFIP` / `CFPORT` | 订阅里客户端连接的优选 IP/端口，默认 `shop.glico.com:443` |
| `NAME` | 节点名前缀 |
| `PORT` | 订阅 HTTP 服务端口（默认 `3000`，路径 `/$SUB_PATH`）|
| `SUB_PATH` | 订阅路径 token，默认 `amm` |
| `FILE_PATH` | 工作目录，默认 `/var/lib/sbox` |
| `SHOW_LOG` | `false` 静默 |

## 跑起来

```bash
docker run -d --name sbox \
  -p 2022:2022 -p 3321:8585 -p 3000:3000 \
  -e SSH_ENABLED=true \
  -e SSH_PORT=2022 \
  -e SSH_PUBLIC_KEY="ssh-ed25519 AAAAC3... you@laptop" \
  -e UUID=7c9e6679-7425-40de-944b-e07fc1f90ae7 \
  -e VLESS_PORT=8585 \
  -e CF_TOKEN='eyJhbGci...（可选）' \
  -e CF_DOMAIN='tunnel.example.com' \
  ghcr.io/momomov/sbox:latest
```

订阅：`http://<host>:3000/amm`（或容器内 `/var/lib/sbox/sub.txt`，base64）。

## Pterodactyl 用法

egg 的 `docker_image` 填 `ghcr.io/momomov/sbox:latest`，环境变量在面板 Variables/Environment 里注入即可；
分配端口映射到容器 `8585`（vless-ws）或走 CF 隧道（零端口）。

## 备注

- 明文 ws（`VLESS_PORT`/隧道回环）仅供测试或套 TLS 场景；公网直连建议 `REALITY_PORT` 或 CF 隧道。
- 容器内 sbox 配置/日志在 `FILE_PATH`，脚本 90 秒后自动清理 config 与 boot 日志（stealth），`sub.txt`、`key.txt` 保留。
- 构建时从 `https://sb.vir.kdns.fr/sbox-<arch>` 拉二进制；改源用 Actions 里改 Dockerfile ARG 即可。
