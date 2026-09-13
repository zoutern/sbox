# sbox (Docker image)

精简版 sing-box + OpenSSH + cloudflared 的多架构镜像，**supervisord 作为 PID 1** 托管全部服务，容器内敲 `svm` 弹交互管理菜单。

- **sbox** = sing-box 1.14.0 定制编译：vless / vmess（ws / http / httpupgrade / tcp，TLS + REALITY）、
  内置 Cloudflare Tunnel 入口、socks / http 入口、direct / block / 分组出口、全套 DNS。
  不含：TUIC / Hysteria / Trojan / SS / AnyTLS / QUIC / TUN / WireGuard / Tailscale。
- 启动逻辑由 `sbox_app.py`（纯标准库）完成：生成配置 → 拉起 sbox → 订阅 HTTP 服务。
- 服务拓扑（supervisord 程序，按 priority）：

| 程序 | 何时启用 | 说明 |
|---|---|---|
| `sshd` | `SSH_ENABLED=true` | 公钥登录，端口 `SSH_PORT` |
| `clfl` | `CLFL_TOKEN` 非空 | 官方 cloudflared，跑 SSH/HTTP 隧道（与 sbox 内置隧道无关） |
| `sbox` | 总是 | sbox_app.py 前台跑，日志双写控制台+文件 |

镜像：`ghcr.io/zotenr/sbox:latest`（amd64 / arm64 / armv7）

## 环境变量

### SSH
`SSH_ENABLED=true` / `SSH_PORT=2022` / `SSH_PUBLIC_KEY="ssh-ed25519 AAAA... 备注"`

### 外部 cloudflared（可选，比如给 SSH 配隧道）
`CLFL_TOKEN='eyJhbGci...'`（cloudflared tunnel run --token 的 token）

### 节点（sbox_app.py）
| 变量 | 说明 |
|---|---|
| `UUID` | 节点 UUID，留空自动生成 |
| `CF_TOKEN` + `CF_DOMAIN` | sbox 内置隧道（vless 域名，ingress service 填 `http://localhost:8585`）|
| `CF_VMESS_DOMAIN` | 可选 vmess 第二域名（service `http://localhost:8586`）|
| `VLESS_PORT` | 直连 vless-ws 端口，默认 `8585`（**与隧道回环口相同会冲突，走隧道时务必改，如 2052**）|
| `REALITY_PORT` / `S5_PORT` | 直连 REALITY / Socks5 端口，留空不开 |
| `CFIP` / `CFPORT` | 订阅链接的优选 IP/端口，默认 `shop.glico.com:443` |
| `NAME` `SUB_PATH` `PORT` `FILE_PATH` `SHOW_LOG` | 节点名 / 订阅路径 / 订阅端口 / 工作目录 / 日志 |

## svm 菜单

```bash
docker exec -it sbox svm        # 或容器内直接敲
#  1) sbox     RUNNING ...
#  2) sshd     RUNNING ...
#  编号→start/stop/restart/日志/tail -f；a全启 x全停 r全重启 g原生命令
```

## 跑起来

```bash
docker run -d --name sbox \
  -p 2022:2022 -p 3321:2052 -p 3000:3000 \
  -e SSH_ENABLED=true -e SSH_PUBLIC_KEY="ssh-ed25519 AAAA... me@pc" \
  -e CLFL_TOKEN='' \
  -e UUID=xxx -e CF_TOKEN='eyJ...' -e CF_DOMAIN=tunnel.example.com \
  -e VLESS_PORT=2052 \
  ghcr.io/zotenr/sbox:latest
```

Pterodactyl / shulker 面板：`docker_image` 填镜像，启动命令留默认 entrypoint 即可；
不能自定义镜像的环境，把 `entrypoint.sh` 里的 supervisord 段落改造成一行启动命令也可。

## 备注

- 明文 ws 仅供测试/套CDN场景，公网直连建议 REALITY 或 CF 隧道。
- 90 秒后自动清理 config/boot 日志（stealth），`sub.txt`、`key.txt` 保留在 `FILE_PATH`。
- sbox 二进制构建时从 `https://sb.vir.kdns.fr/sbox-<arch>` 拉取。
