# 服务器基础环境与 Codex 安装手册

## 1. 目标

本手册用于把一台新的腾讯云 Ubuntu 服务器配置成可长期试验的开发/部署环境，并让服务器上的 Codex 能读取本项目文档，继续实现飞书接入、Hermes/OpenClaw 集成和后续工程改造。

当前推荐路线：

```text
腾讯云国内轻量服务器
+ Ubuntu 24.04 LTS
+ 国内模型/API
+ 飞书作为第一交互入口
+ GLaDOS/mihomo 仅作为按需代理
+ Codex CLI 作为服务器上的工程执行助手
```

## 2. 总体顺序

不要一上来装 Hermes/OpenClaw。先把服务器底座、网络、安全、Codex 跑通。

推荐顺序：

```text
1. 购买服务器并选择干净 Ubuntu 镜像
2. 完成 SSH 登录和基础安全设置
3. 安装系统基础工具
4. 可选：配置 GLaDOS/mihomo 本地代理
5. 安装 Git、Docker、Node.js、npm
6. 安装 Codex CLI
7. 配置 Codex 中转 API
8. 拉取 ai-reading-coach 项目
9. 让 Codex 阅读 docs/engineering 并执行阶段 2：飞书初版通道
10. 后续再接 Hermes / OpenClaw
```

## 3. 购买服务器前置选择

推荐配置：

```text
云厂商：腾讯云轻量应用服务器
地域：北京 / 上海 / 广州 / 成都，优先离国内 API 最近
规格：2 核 4G
硬盘：70GB SSD
系统：Ubuntu 24.04 LTS
镜像：linux 类干净系统镜像
```

不要选：

```text
OpenClaw 应用镜像
Hermes Agent 应用镜像
宝塔面板
WordPress
其他预装黑盒应用
```

理由：

- 当前目标是搭一个可控底座。
- Hermes/OpenClaw 后续用 Docker 或源码方式接入。
- 干净系统更容易排错、升级和迁移。

## 4. 本地准备

你在本地电脑准备好：

```text
1. 腾讯云服务器公网 IP
2. root 初始密码或 SSH 密钥
3. GitHub 仓库地址
4. GLaDOS Clash/mihomo 订阅链接
5. Codex 中转 API 地址
6. Codex 中转 API Key
7. 飞书自定义机器人 Webhook，后续阶段使用
```

安全要求：

```text
不要把 GLaDOS 订阅链接发给 Codex
不要把 API Key 提交到 GitHub
不要把 .env 提交到 GitHub
不要把代理端口暴露到公网
```

## 5. 第一次登录服务器

本地 PowerShell 或终端：

```bash
ssh root@你的服务器IP
```

登录后先更新系统：

```bash
apt update
apt upgrade -y
```

安装基础工具：

```bash
apt install -y git curl wget ca-certificates gnupg lsb-release unzip tar vim ufw htop build-essential
```

设置时区：

```bash
timedatectl set-timezone Asia/Shanghai
timedatectl
```

## 6. 创建普通用户

不要长期用 root 跑项目。

```bash
adduser deploy
usermod -aG sudo deploy
```

切换用户：

```bash
su - deploy
```

后续项目目录建议放在：

```text
/home/deploy/repos/ai-reading-coach
/home/deploy/apps/ai-reading-coach-prod
```

## 7. 防火墙和安全组

腾讯云控制台安全组/防火墙先只放行：

```text
22/tcp SSH
80/tcp HTTP，只有需要反馈链接或证书申请时开放
443/tcp HTTPS，正式反馈入口建议开放
```

服务器内启用 UFW：

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

暂时不要开放：

```text
Docker daemon
SQLite
Redis
任何未鉴权后台
7890 代理端口
9090 mihomo 控制端口
```

## 8. 可选：配置 GLaDOS/mihomo 本地代理

这一节是可选，但建议配置。它主要用于：

```text
安装 Codex
访问 GitHub
安装 npm 包
未来测试 Telegram
```

它不应该影响：

```text
飞书
国内模型 API
你的生产服务常规调用
```

### 8.1 安装 mihomo

如果服务器能访问 GitHub，可以直接下载 mihomo Linux amd64 release。

如果服务器访问 GitHub 不稳定，建议在本地电脑下载 mihomo Linux amd64 版本，然后上传：

```bash
scp mihomo-linux-amd64 root@你的服务器IP:/tmp/mihomo
```

服务器上安装：

```bash
sudo mv /tmp/mihomo /usr/local/bin/mihomo
sudo chmod +x /usr/local/bin/mihomo
sudo mkdir -p /etc/mihomo
```

### 8.2 保存订阅配置

方式 A：服务器直接拉订阅：

```bash
sudo curl -L "你的GLaDOS订阅链接" -o /etc/mihomo/config.yaml
```

方式 B：本地下载配置后上传：

```bash
scp config.yaml root@你的服务器IP:/tmp/config.yaml
sudo mv /tmp/config.yaml /etc/mihomo/config.yaml
```

检查配置里必须满足：

```yaml
mixed-port: 7890
allow-lan: false
bind-address: 127.0.0.1
mode: rule
log-level: info
```

关键安全点：

- `allow-lan` 必须是 `false`。
- `bind-address` 必须是 `127.0.0.1`。
- 不要把 `7890` 开到腾讯云安全组。
- 不要把 `external-controller` 绑定到 `0.0.0.0`。

### 8.3 创建 systemd 服务

```bash
sudo tee /etc/systemd/system/mihomo.service >/dev/null <<'EOF'
[Unit]
Description=mihomo proxy service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo -f /etc/mihomo/config.yaml
Restart=on-failure
RestartSec=5s
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo
sudo systemctl status mihomo --no-pager
```

测试代理：

```bash
curl -x http://127.0.0.1:7890 https://github.com -I
```

### 8.4 按需使用代理

不要做全局永久代理。只在需要的命令前临时加。

临时环境：

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export ALL_PROXY=socks5h://127.0.0.1:7890
```

取消：

```bash
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
```

单条命令用代理：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 curl -I https://github.com
```

Git 单次代理：

```bash
git -c http.proxy=http://127.0.0.1:7890 clone https://github.com/你的账号/ai-reading-coach.git
```

## 9. 安装 Docker

如果网络正常：

```bash
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
```

让 `deploy` 用户能用 Docker：

```bash
sudo usermod -aG docker deploy
```

重新登录后生效：

```bash
exit
ssh deploy@你的服务器IP
docker ps
```

注意：

```text
不要开放 Docker 2375 端口
不要把 /var/run/docker.sock 暴露给不可信容器
```

## 10. 安装 Node.js 和 npm

Codex CLI 官方支持 npm 安装。推荐 Node.js LTS。

如果网络正常：

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
node -v
npm -v
```

如果访问慢，可临时使用代理：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
```

可选：设置 npm 镜像源。

```bash
npm config set registry https://registry.npmmirror.com
npm config get registry
```

如果你追求最小供应链风险，优先使用 npm 官方源；如果服务器网络很慢，再使用镜像源。

## 11. 安装 Codex CLI

OpenAI 官方 Codex CLI 支持 Linux，可通过 npm 安装。

```bash
sudo npm i -g @openai/codex
codex --version
```

如果安装慢：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 sudo -E npm i -g @openai/codex
```

升级：

```bash
sudo npm i -g @openai/codex@latest
```

## 12. 配置 Codex 中转 API

如果你的中转 API 是 OpenAI-compatible，先用环境变量快速测试。

```bash
export OPENAI_API_KEY="你的中转API_KEY"
export OPENAI_BASE_URL="https://你的中转域名/v1"
codex
```

如果能进入 Codex 交互界面并正常回答，说明可用。

长期建议写入 `~/.codex/config.toml`。

```bash
mkdir -p ~/.codex
vim ~/.codex/config.toml
```

示例：

```toml
model = "你的模型名"
model_provider = "relay"
approval_policy = "untrusted"
model_reasoning_effort = "medium"

[model_providers.relay]
name = "Relay OpenAI Compatible"
base_url = "https://你的中转域名/v1"
env_key = "RELAY_API_KEY"
```

把 key 放进 shell 环境，不要写进 Git：

```bash
echo 'export RELAY_API_KEY="你的中转API_KEY"' >> ~/.bashrc
source ~/.bashrc
```

测试：

```bash
cd ~
codex
```

在 Codex 里输入：

```text
请只回答“Codex 已可用”。
```

如果失败，重点检查：

- 中转 API 是否支持 OpenAI-compatible。
- 是否支持 Codex 使用的接口、流式输出和工具调用。
- `base_url` 是否带 `/v1`。
- `env_key` 对应的环境变量是否存在。
- 模型名是否正确。

## 13. 拉取项目代码

```bash
mkdir -p ~/repos
cd ~/repos
git clone https://github.com/你的账号/ai-reading-coach.git
cd ai-reading-coach
```

如果 GitHub 访问慢：

```bash
git -c http.proxy=http://127.0.0.1:7890 clone https://github.com/你的账号/ai-reading-coach.git
```

检查文档：

```bash
ls docs/engineering
```

初始化环境文件：

```bash
cp .env.example .env
chmod 600 .env
```

## 14. 先让 Codex 处理什么

第一阶段不要让服务器上的 Codex 直接接 Hermes/OpenClaw。先让它实现飞书初版通道。

进入项目：

```bash
cd ~/repos/ai-reading-coach
codex
```

给 Codex 的第一条指令：

```text
请先阅读以下文档：
- docs/README.md
- docs/engineering/README.md
- docs/engineering/00_project_charter.md
- docs/engineering/01_system_architecture.md
- docs/engineering/04_implementation_roadmap.md
- docs/engineering/06_lark_first_integration.md

当前目标：
实现 docs/engineering/04_implementation_roadmap.md 的阶段 2：新增飞书初版通道。

具体要求：
1. 暂时不要接 Hermes/OpenClaw。
2. 不要继续完善 Telegram。
3. 新增飞书自定义机器人发送能力。
4. 新增反馈链接或 feedback endpoint 的最小实现。
5. 反馈必须写入 SQLite。
6. 增加必要配置项：CHANNEL、LARK_WEBHOOK_URL、PUBLIC_BASE_URL、FEEDBACK_SECRET。
7. 保留现有测试，并新增飞书相关测试。
8. 修改完成后运行测试并说明如何本地/服务器验证。

请先给出实现计划，再开始修改代码。
```

## 15. 交给 Codex 后的人审流程

不要让 Codex 改完就直接上生产。

每次改完：

```bash
git status
git diff
python -m unittest discover -s tests
```

确认后提交：

```bash
git add .
git commit -m "Add Lark channel MVP"
```

部署前：

```bash
cp .env.example .env
vim .env
chmod 600 .env
docker compose up --build -d
docker compose logs -f
```

## 16. 当前不建议做的事

初期不要做：

- 在国内服务器上强依赖 Telegram。
- 把代理端口开放公网。
- 把 GLaDOS 订阅链接提交到仓库。
- 把 API Key 写进代码。
- 直接选 OpenClaw/Hermes 预装镜像作为主系统。
- 一上来让 Codex 同时改飞书、Hermes、OpenClaw、数据库大改。
- 让 Codex 自动修改 Skill 后直接上线。

## 17. 故障排查

### Codex 安装失败

尝试：

```bash
node -v
npm -v
npm config get registry
HTTPS_PROXY=http://127.0.0.1:7890 sudo -E npm i -g @openai/codex
```

### Codex 无法调用中转 API

检查：

```bash
echo $RELAY_API_KEY
cat ~/.codex/config.toml
curl -H "Authorization: Bearer $RELAY_API_KEY" https://你的中转域名/v1/models
```

如果 `/v1/models` 不支持，不一定代表不可用，但至少说明该中转兼容性需要确认。

### mihomo 代理不可用

检查：

```bash
sudo systemctl status mihomo --no-pager
sudo journalctl -u mihomo -n 100 --no-pager
curl -x http://127.0.0.1:7890 https://github.com -I
```

### 飞书推送失败

检查：

```text
LARK_WEBHOOK_URL 是否正确
飞书机器人是否启用签名校验
服务器是否能访问 open.feishu.cn
消息格式是否符合飞书要求
```

## 18. 参考资料

- OpenAI Codex CLI 官方安装说明：https://developers.openai.com/codex/cli
- Codex CLI 配置参考：https://www.mintlify.com/openai/codex/configuration/reference
- mihomo 通用配置说明：https://wiki.metacubex.one/en/config/general/

