#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sbox_app.py —— 精简版 sing-box (sbox) 一键部署脚本
参考 app1.py(Xray版) 改写，适配我们自己编译的精简版 sing-box：
  · 协议: vless / vmess (ws) + REALITY + Socks5 + Cloudflare Tunnel
  · 隧道: 用 sbox 内置 cloudflared 入口(固定隧道token)，不再单独下载 cloudflared
  · 回环: CF ingress service -> http://localhost:<本地ws端口>，direct 出口回环进 vless/vmess 入口
  · 依赖: 纯 Python 标准库(无需 pip install requests/cryptography)
  · 密钥: reality 密钥对由 sbox 二进制自身生成

用法(免费机/容器一行跑):
  python3 sbox_app.py
环境变量(全部可选，留空即关闭对应功能):
  SBOX_DOWNLOAD_BASE  下载地址前缀，默认 https://sb.vir.kdns.fr/sbox (自动拼 -amd64/-arm64)
  SBOX_BIN            指定已装好的二进制(如 /opt/sbox/sbox)，指定后不下载
  UUID                节点UUID，留空自动生成(固定建议填)
  CF_TOKEN            Cloudflare 隧道 Token(Zero Trust 创建) —— 开了才有隧道
  CF_DOMAIN           隧道绑定的 vless 域名，如 a.example.com
  CF_VMESS_DOMAIN     隧道绑定的 vmess 域名(可选，需第二条 ingress hostname)
  ARGO_PORT           隧道回环 vless-ws 本地端口，默认 8585
  VMESS_PORT          隧道回环 vmess-ws 本地端口，默认 8586
  VLESS_PORT          直连 vless-ws 端口(NAT机用映射端口段)，留空不开
  REALITY_PORT        直连 vless-reality(tcp) 端口，留空不开
  S5_PORT             Socks5 端口(用户名=UUID前8位)，留空不开
  CFIP / CFPORT       订阅里客户端连接的优选IP/端口(走CF时)，默认 shop.glico.com:443
  NAME                节点名称前缀
  CHAT_ID / BOT_TOKEN Telegram 推送
  UPLOAD_URL          订阅面板地址(增删节点API，同app1)
  PROJECT_URL         本项目访问URL(自动保活/订阅上传)
  AUTO_ACCESS         true=向 oooo.serv00.net 添加保活
  SUB_PATH            订阅token路径，默认 amm
  PORT                订阅HTTP服务端口，默认 3000
  FILE_PATH           工作目录，默认 .cache
  SHOW_LOG            false/no/disable 静默(仍打印订阅)，默认显示
  NEZHA_SERVER/NEZHA_PORT/NEZHA_KEY   哪吒监控(v0带端口/v1用config.yaml)
"""

import os
import sys
import re
import json
import time
import base64
import uuid as uuidlib
import random
import string
import shutil
import signal
import platform
import threading
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# =========================== 环境变量 ===========================
SBOX_DL = os.environ.get('SBOX_DOWNLOAD_BASE', 'https://sb.vir.kdns.fr/sbox')
SBOX_BIN = os.environ.get('SBOX_BIN', '')
UUID = os.environ.get('UUID', '') or str(uuidlib.uuid4())
CF_TOKEN = os.environ.get('CF_TOKEN', '')
CF_DOMAIN = os.environ.get('CF_DOMAIN', '')
CF_VMESS_DOMAIN = os.environ.get('CF_VMESS_DOMAIN', '')
ARGO_PORT = int(os.environ.get('ARGO_PORT', '8585'))
VMESS_PORT = int(os.environ.get('VMESS_PORT', '8586'))
VLESS_PORT = os.environ.get('VLESS_PORT', '')
REALITY_PORT = os.environ.get('REALITY_PORT', '')
S5_PORT = os.environ.get('S5_PORT', '')
CFIP = os.environ.get('CFIP', 'shop.glico.com')
CFPORT = int(os.environ.get('CFPORT', '443'))
NAME = os.environ.get('NAME', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
UPLOAD_URL = os.environ.get('UPLOAD_URL', '')
PROJECT_URL = os.environ.get('PROJECT_URL', '')
AUTO_ACCESS = os.environ.get('AUTO_ACCESS', '').lower() == 'true'
SUB_PATH = os.environ.get('SUB_PATH', 'amm')
PORT = int(os.environ.get('PORT') or '3000')
FILE_PATH = os.environ.get('FILE_PATH', '.cache')
SHOW_LOG = os.environ.get('SHOW_LOG', 'false').lower() not in ('false', 'disable', 'no')
NEZHA_SERVER = os.environ.get('NEZHA_SERVER', '')
NEZHA_PORT = os.environ.get('NEZHA_PORT', '')
NEZHA_KEY = os.environ.get('NEZHA_KEY', '')
NEZHA_DL_BASE = os.environ.get('NEZHA_DL_BASE', '')  # 留空则跳过哪吒(自行填v0/v1下载地址)

# Reality 伪装目标(可env覆盖)
REALITY_DEST = os.environ.get('REALITY_DEST', 'www.iij.ad.jp')
REALITY_PORT_DEST = int(os.environ.get('REALITY_PORT_DEST', '443'))

# =========================== 路径/全局 ===========================
FILE_PATH = Path(FILE_PATH).resolve()
sbox_path = FILE_PATH / 'sbox'
config_path = FILE_PATH / 'config.json'
key_path = FILE_PATH / 'key.txt'
sub_path = FILE_PATH / 'sub.txt'
boot_log_path = FILE_PATH / 'boot.log'
nezha_config_path = FILE_PATH / 'config.yaml'
nezha_bin = FILE_PATH / 'agent'
private_key = ''
public_key = ''
sub_txt_content = ''
sbox_proc = None
nezha_proc = None
sbox_downloaded = False

def log(msg):
    if SHOW_LOG:
        print(msg, flush=True)

def log_error(msg):
    if SHOW_LOG:
        print(msg, file=sys.stderr, flush=True)

def always_log(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()

def rand_suffix(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def is_valid_port(p):
    try:
        return 1 <= int(p) <= 65535
    except (ValueError, TypeError):
        return False

# =========================== HTTP 工具(替代requests) ===========================
def http_get(url, timeout=10, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

def http_post_json(url, payload, timeout=10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method='POST',
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode('utf-8', 'replace')

def http_post_form(url, params, timeout=10):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method='POST',
                                 headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode('utf-8', 'replace')

# =========================== 架构/二进制 ===========================
def get_arch():
    a = platform.machine().lower()
    return {'aarch64': 'arm64', 'arm64': 'arm64', 'armv7l': 'armv7',
            'x86_64': 'amd64', 'amd64': 'amd64', 'i386': '386', 'i686': '386'}.get(a, a)

def locate_sbox():
    """优先用现成的: env SBOX_BIN > /opt/sbox/sbox > 工作目录 > 下载"""
    global sbox_downloaded
    for cand in (SBOX_BIN, '/opt/sbox/sbox', str(sbox_path)):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    arch = get_arch()
    tmp = sbox_path.with_suffix('.tmp')
    for url in (f'{SBOX_DL}-{arch}', SBOX_DL):   # 先试架构后缀，再回退单文件
        try:
            log(f'下载 {url} ...')
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, 'wb') as f:
                shutil.copyfileobj(r, f, 8192)
            os.chmod(tmp, 0o755)
            tmp.rename(sbox_path)
            sbox_downloaded = True
            return str(sbox_path)
        except Exception as e:
            log_error(f'下载失败 {url}: {e}')
    try:
        tmp.unlink()
    except OSError:
        pass
    return None

# =========================== Reality 密钥对(sbox自身生成) ===========================
def generate_or_load_keypair(binpath):
    global private_key, public_key
    FILE_PATH.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        c = key_path.read_text()
        m = re.search(r'PrivateKey:\s*(\S+)', c)
        p = re.search(r'PublicKey:\s*(\S+)', c)
        if m and p:
            private_key, public_key = m.group(1), p.group(1)
            log(f'Reality 私钥/公钥已复用')
            return True
    out = subprocess.run([binpath, 'generate', 'reality-keypair'],
                         capture_output=True, text=True, timeout=30).stdout
    m = re.search(r'PrivateKey:\s*(\S+)', out)
    p = re.search(r'PublicKey:\s*(\S+)', out)
    if m and p:
        private_key, public_key = m.group(1), p.group(1)
        key_path.write_text(f'PrivateKey: {private_key}\nPublicKey: {public_key}\n')
        log(f'Reality 密钥对已生成')
        return True
    log_error('Reality 密钥对生成失败')
    return False

# =========================== 生成 sing-box 配置 ===========================
def generate_sbox_config():
    FILE_PATH.mkdir(parents=True, exist_ok=True)
    inbounds = []
    outbounds = [{'type': 'direct', 'tag': 'direct'}]
    rules = []

    if CF_TOKEN:
        # 隧道回环入口: CF ingress service 填 http://localhost:<端口>
        inbounds.append({
            'type': 'vless', 'tag': 'vl-ws-tunnel', 'listen': '127.0.0.1', 'listen_port': ARGO_PORT,
            'users': [{'uuid': UUID}],
            'transport': {'type': 'ws', 'path': '/vless-argo'}})
        if CF_VMESS_DOMAIN:
            inbounds.append({
                'type': 'vmess', 'tag': 'vm-ws-tunnel', 'listen': '127.0.0.1', 'listen_port': VMESS_PORT,
                'users': [{'uuid': UUID, 'alterId': 0}],
                'transport': {'type': 'ws', 'path': '/vmess-argo'}})
        inbounds.append({'type': 'cloudflared', 'tag': 'cf-tunnel',
                         'token': CF_TOKEN, 'ha_connections': 4})

    if is_valid_port(VLESS_PORT):
        p = rand_suffix()
        inbounds.append({
            'type': 'vless', 'tag': 'vl-ws-direct', 'listen': '::', 'listen_port': int(VLESS_PORT),
            'users': [{'uuid': UUID}],
            'transport': {'type': 'ws', 'path': f'/{p}'}})
        globals()['direct_ws_path'] = f'/{p}'

    if is_valid_port(REALITY_PORT) and private_key:
        inbounds.append({
            'type': 'vless', 'tag': 'vl-reality', 'listen': '::', 'listen_port': int(REALITY_PORT),
            'users': [{'uuid': UUID, 'flow': 'xtls-rprx-vision'}],
            'tls': {'enabled': True, 'server_name': REALITY_DEST,
                    'reality': {'enabled': True,
                                'handshake': {'server': REALITY_DEST, 'server_port': REALITY_PORT_DEST},
                                'private_key': private_key, 'short_id': ['']}}})

    if is_valid_port(S5_PORT):
        inbounds.append({
            'type': 'socks', 'tag': 's5-in', 'listen': '::', 'listen_port': int(S5_PORT),
            'users': [{'username': UUID[:8], 'password': UUID[-12:]}]})

    if not inbounds:
        return None

    cfg = {
        'log': {'level': 'info', 'output': str(boot_log_path)},
        'dns': {'servers': [{'type': 'local', 'tag': 'local'}], 'final': 'local'},
        'inbounds': inbounds,
        'outbounds': outbounds,
        'route': {'rules': rules, 'final': 'direct'}}
    config_path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    return cfg

# =========================== 哪吒(可选) ===========================
def generate_nezha_config():
    if not (NEZHA_SERVER and NEZHA_KEY and NEZHA_DL_BASE):
        return False
    try:
        req = urllib.request.Request(NEZHA_DL_BASE, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as r, open(nezha_bin, 'wb') as f:
            shutil.copyfileobj(r, f, 8192)
        os.chmod(nezha_bin, 0o755)
    except Exception as e:
        log_error(f'哪吒agent下载失败: {e}')
        return False
    if not NEZHA_PORT:
        nzport = NEZHA_SERVER.split(':')[-1] if ':' in NEZHA_SERVER else ''
        tls = 'true' if nzport in {'443', '8443', '2096', '2087', '2083', '2053'} else 'false'
        nezha_config_path.write_text(
            f'client_secret: {NEZHA_KEY}\ndebug: false\ndisable_auto_update: true\n'
            f'insecure_tls: true\nreport_delay: 4\nserver: {NEZHA_SERVER}\n'
            f'skip_connection_count: true\nskip_procs_count: true\ntls: {tls}\nuuid: {UUID}',
            encoding='utf-8')
    return True

def run_nezha():
    global nezha_proc
    if not nezha_bin.exists():
        return
    if NEZHA_PORT:
        cmd = [str(nezha_bin), '-s', f'{NEZHA_SERVER}:{NEZHA_PORT}', '-p', NEZHA_KEY,
               '--disable-auto-update', '--report-delay', '4', '--skip-conn', '--skip-procs']
    else:
        cmd = [str(nezha_bin), '-c', str(nezha_config_path)]
    nezha_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
    log('nezha-agent 已启动')

# =========================== 启动 sbox ===========================
def run_sbox(binpath):
    global sbox_proc
    sbox_proc = subprocess.Popen([binpath, 'run', '-D', str(FILE_PATH), '-c', str(config_path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
    log(f'sbox 已启动 (pid {sbox_proc.pid})')
    time.sleep(4)
    if sbox_proc.poll() is not None:
        log_error('sbox 启动失败，日志尾部:')
        try:
            print(boot_log_path.read_text()[-800:])
        except Exception:
            pass
        return False
    if CF_TOKEN:
        try:
            c = boot_log_path.read_text()
            conns = len(re.findall(r'connected to [a-z0-9]+ \(connection', c))
            if conns:
                log(f'隧道已连接 CF 边缘 x{conns}')
            else:
                log_error('隧道暂未连上，检查 CF_TOKEN/域名/网络')
        except Exception:
            pass
    return True

# =========================== 公网信息 ===========================
def get_server_ip():
    for u in ('http://ipv4.ip.sb', 'https://api.ipify.org'):
        try:
            ip = http_get(u, timeout=5).strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                return ip
        except Exception:
            continue
    try:
        ip = http_get('http://ipv6.ip.sb', timeout=5).strip()
        if ':' in ip:
            return f'[{ip}]'
    except Exception:
        pass
    return ''

def get_meta_info():
    try:
        d = json.loads(http_get('https://api.ip.sb/geoip', timeout=5))
        if d.get('country_code') and d.get('isp'):
            return f"{d['country_code']}-{d['isp']}".replace(' ', '_')
    except Exception:
        pass
    try:
        d = json.loads(http_get('http://ip-api.com/json', timeout=5))
        if d.get('status') == 'success':
            return f"{d['countryCode']}-{d['org']}".replace(' ', '_')
    except Exception:
        pass
    return 'Unknown'

# =========================== 订阅链接 ===========================
def generate_links():
    global sub_txt_content
    isp = get_meta_info()
    node = f'{NAME}-{isp}' if NAME else isp
    server_ip = get_server_ip()
    sub = ''

    if CF_TOKEN and CF_DOMAIN:
        sub += (f'\nvless://{UUID}@{CFIP}:{CFPORT}?encryption=none&security=tls'
                f'&sni={CF_DOMAIN}&host={CF_DOMAIN}&fp=chrome&type=ws'
                f'&path={urllib.parse.quote("/vless-argo")}&alpn=h3#{node}-VL')
    if CF_TOKEN and CF_VMESS_DOMAIN:
        vj = {'v': '2', 'ps': f'{node}-VM', 'add': CFIP, 'port': str(CFPORT), 'id': UUID,
              'aid': '0', 'scy': 'auto', 'net': 'ws', 'type': 'none', 'host': CF_VMESS_DOMAIN,
              'path': '/vmess-argo', 'tls': 'tls', 'sni': CF_VMESS_DOMAIN, 'fp': 'chrome'}
        sub += '\nvmess://' + base64.b64encode(
            json.dumps(vj, separators=(',', ':')).encode()).decode()
    if is_valid_port(VLESS_PORT) and server_ip:
        p = globals().get('direct_ws_path', '/ws')
        sub += (f'\nvless://{UUID}@{server_ip}:{VLESS_PORT}?encryption=none&security=none'
                f'&fp=chrome&type=ws&path={urllib.parse.quote(p)}#{node}-VL-Direct')
    if is_valid_port(REALITY_PORT) and server_ip and public_key:
        sub += (f'\nvless://{UUID}@{server_ip}:{REALITY_PORT}?encryption=none'
                f'&flow=xtls-rprx-vision&security=reality&sni={REALITY_DEST}&fp=chrome'
                f'&pbk={public_key}&type=tcp#{node}-VL-Reality')
    if is_valid_port(S5_PORT) and server_ip:
        auth = base64.b64encode(f'{UUID[:8]}:{UUID[-12:]}'.encode()).decode()
        sub += f'\nsocks://{auth}@{server_ip}:{S5_PORT}#{node}-S5'

    if not sub.strip():
        log_error('没有任何可用入口，检查 CF_TOKEN/端口 环境变量')
        return
    b64 = base64.b64encode(sub.encode()).decode()
    sub_txt_content = b64
    sub_path.write_text(b64, encoding='utf-8')
    if SHOW_LOG:
        print(f'\033[32m{b64}\033[0m')
        print('\033[35m90秒后日志清理，请尽快复制上方订阅\033[0m')
    log('sub.txt 已保存')

# =========================== TG/面板/保活 ===========================
def send_telegram():
    if not (BOT_TOKEN and CHAT_ID):
        return
    try:
        msg = sub_path.read_text()
        esc = re.sub(r'[_*\[\]()~`>#+=|{}.!-]', r'\\\g<0>', NAME or 'sbox')
        http_post_form(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                       {'chat_id': CHAT_ID,
                        'text': f'**{esc}节点推送**\n```{msg}```',
                        'parse_mode': 'MarkdownV2'})
        log('TG 推送成功')
    except Exception as e:
        log_error(f'TG 推送失败: {e}')

def delete_nodes():
    if not (UPLOAD_URL and sub_path.exists()):
        return
    try:
        content = base64.b64decode(sub_path.read_text()).decode()
        nodes = [l for l in content.split('\n') if re.match(r'(vless|vmess|socks)://', l)]
        if nodes:
            http_post_json(f'{UPLOAD_URL}/api/delete-nodes', {'nodes': nodes})
    except Exception:
        pass

def upload_nodes():
    if not UPLOAD_URL:
        return
    try:
        if PROJECT_URL:
            http_post_json(f'{UPLOAD_URL}/api/add-subscriptions',
                           {'subscription': [f'{PROJECT_URL}/{SUB_PATH}']})
            log('订阅已上传')
        elif sub_path.exists():
            content = base64.b64decode(sub_path.read_text()).decode()
            nodes = [l for l in content.split('\n') if re.match(r'(vless|vmess|socks)://', l)]
            if nodes:
                http_post_json(f'{UPLOAD_URL}/api/add-nodes', {'nodes': nodes})
                log('节点已上传')
    except Exception as e:
        log_error(f'上传失败: {e}')

def add_visit_task():
    if not (AUTO_ACCESS and PROJECT_URL):
        return
    try:
        http_post_json('https://oooo.serv00.net/add-url', {'url': PROJECT_URL})
        log('保活任务已添加')
    except Exception as e:
        log_error(f'保活添加失败: {e}')

# =========================== 清理 ===========================
def clean_files():
    def worker():
        time.sleep(90)
        for f in (boot_log_path, config_path, nezha_config_path):
            try:
                f.unlink()
            except OSError:
                pass
        if sbox_downloaded:            # 下载来的才删，系统里现成的不动
            try:
                sbox_path.unlink()
            except OSError:
                pass
        if NEZHA_DL_BASE:
            try:
                nezha_bin.unlink()
            except OSError:
                pass
        always_log('App is running')
    threading.Thread(target=worker, daemon=True).start()

# =========================== 订阅HTTP服务 ===========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == f'/{SUB_PATH}':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(sub_txt_content.encode())
        elif path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f'Hello! 访问 /{SUB_PATH} 获取订阅'.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass

# =========================== 优雅退出 ===========================
def stop_all(signum=None, frame=None):
    global sbox_proc, nezha_proc
    for p in (sbox_proc, nezha_proc):
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
    time.sleep(1)
    os._exit(0)

# =========================== 主流程 ===========================
def start_server():
    FILE_PATH.mkdir(parents=True, exist_ok=True)
    delete_nodes()

    binpath = locate_sbox()
    if not binpath:
        log_error('找不到也下载不到 sbox 二进制，退出')
        sys.exit(1)
    log(f'sbox: {binpath}')

    if is_valid_port(REALITY_PORT):
        generate_or_load_keypair(binpath)

    if not generate_sbox_config():
        log_error('无入口配置(端口/CF都没开)，退出')
        sys.exit(1)

    if not run_sbox(binpath):
        sys.exit(1)

    if NEZHA_SERVER and NEZHA_KEY:
        if generate_nezha_config():
            run_nezha()

    generate_links()
    send_telegram()
    upload_nodes()
    add_visit_task()
    clean_files()

def main():
    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)
    if not (CF_TOKEN or is_valid_port(VLESS_PORT) or is_valid_port(REALITY_PORT) or is_valid_port(S5_PORT)):
        print('提示: 至少设置 CF_TOKEN+CF_DOMAIN 或 VLESS_PORT/REALITY_PORT/S5_PORT 之一')
        sys.exit(1)
    threading.Thread(target=start_server, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    always_log(f'server is running on {PORT}!')
    server.serve_forever()

if __name__ == '__main__':
    main()
