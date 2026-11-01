# 帮用户部署 Eidolon-SC

读者是替用户部署的 Agent。用户多半是新手：会照着做，但看不懂报错，也不知道该申请哪些服务。你负责判断和执行，用户只做必须由本人做的事：注册账号、申请 key、把 key 填进 `.env`、在浏览器里试用。

几条贯穿始终的做法：

- **key 由用户自己填进 `.env`**，去哪申请、怎么填、你怎么确认，见「申请和填写 key」。让用户别把 key 贴进对话：对话记录会留在 Agent 的服务商那里。
- **命令按用户的系统给**。Windows 用 PowerShell，`.sh` 脚本用 Git Bash 跑（装 Git 时自带）；macOS 和 Linux 用终端。PowerShell 里给一条命令设环境变量要写成 `$env:名字="值"; 命令`，不能写 `名字=值 命令`。
- **变量的含义以 `.env.example` 为准**，每一项的注释都写在那里。这份指南只讲流程、选哪家服务、哪里容易踩坑。功能的细节见 `docs/configuration.md`，服务器部署的细节见 `docs/deploy.md`。
- **出错先跑 doctor**（见「排障」），照它的提示改；doctor 说不清时，再看后端的输出。

## 1. 先问用户三件事

1. **在自己电脑上试，还是部署到服务器给别人用？** 前者走「本机体验」，后者走「公网部署」。没把握时先做本机体验，跑通以后再上服务器。部署到服务器的，再问一句：**只给认识的人用，还是谁都能来？** 只给认识的人用，就从第一天起只让受邀的人注册（见「公网部署」）；否则找到网址的陌生人也能注册，花的是用户的钱。
2. **电脑或服务器在中国大陆吗？** 这决定了推荐哪几家服务，以及要不要配代理（见「网络和代理」）。
3. **想要哪些功能？** 文字聊天必须有，其余按需：语音通话、剧情回忆和记忆、照片、通话立绘。每多一项功能就多申请一两个服务，有的按量收费，先把这一点告诉用户。

三个问题都有了答案，这一步才算完。

## 三种跑法

本机体验默认用**直接跑**：在 Windows、macOS、Linux 上都一样，只要装 Git、uv 和 Node.js 这三个普通程序，不用开虚拟化、不用装 WSL。用户已经装好、并且用惯了 Docker 时，可以改用 **Docker 跑**。公网部署用**服务器**这一列。

| | 直接跑 | Docker 跑 | 服务器 |
|---|---|---|---|
| doctor | 在 `backend/` 下：`uv run --env-file=../.env eidolon doctor` | `docker compose run --rm backend eidolon doctor` | `docker compose -f docker-compose.prod.yml run --rm backend eidolon doctor` |
| 改了 `.env` 以后 | 在后端的终端按 Ctrl+C，再运行一次 `eidolon serve` | `docker compose up -d` | `docker compose -f docker-compose.prod.yml up -d` |
| 后端的输出 | 后端那个终端 | `docker compose logs backend` | `docker compose -f docker-compose.prod.yml logs backend` |
| 代理地址里的主机 | `127.0.0.1` | `host.docker.internal` | `127.0.0.1` |

只 `restart` 读不到新的 `.env`，一定要用上表的写法。doctor 加 `--json` 输出 JSON，你读那个更方便。

## 2. 本机体验

### 2.1 直接跑：装 Git、uv、Node.js

- **Windows**：在 PowerShell 里依次运行 `winget install --id Git.Git -e`、`winget install --id astral-sh.uv -e`、`winget install --id OpenJS.NodeJS.LTS -e`。没有 winget 的老系统，就去 git-scm.com、docs.astral.sh/uv、nodejs.org 下载安装程序。装完要**关掉 PowerShell 再重新打开**，新装的命令才找得到。
- **macOS**：有 Homebrew 就 `brew install git uv node`；没有的话 Git 用 `xcode-select --install`，uv 用 `curl -LsSf https://astral.sh/uv/install.sh | sh`，Node.js 从 nodejs.org 下载。
- **Linux**：Git 用发行版的包管理器装，uv 用上面那条 `curl` 命令，Node.js 用 nvm 或 NodeSource 装（发行版自带的 Node 往往太旧）。

`git --version`、`uv --version` 能运行，`node --version` 是 22.18 以上，才算装好。Python 不用自己装，uv 会自动装好 3.11。

### 2.1 Docker 跑：装 Docker

- **Windows / macOS**：装 Docker Desktop。Windows 要开 WSL2，打不开时多半是 BIOS 里没开虚拟化；这一步卡住，就改用直接跑。
- **Linux**：装 Docker Engine 和 compose 插件，按 Docker 官方文档的步骤装。

`docker compose version` 能运行、`docker run --rm hello-world` 能跑完，才算装好。

### 2.2 克隆和最小配置

```sh
git clone https://github.com/Sallyn0225/eidolon-sc.git
cd eidolon-sc
cp .env.example .env        # PowerShell：Copy-Item .env.example .env
```

让用户在 `.env` 里填好对话模型的三项：`CHAT_LLM_BASE_URL`、`CHAT_LLM_API_KEY`、`CHAT_LLM_MODEL`（选哪家见「服务一览」，怎么申请和填见「申请和填写 key」）。另外加一行 `EIDOLON_DEV_LOGIN=1`，本机体验不用配 GitHub 或 Google 登录。

**在中国大陆**：第一次下载依赖、构建前端时要连 GitHub、PyPI、npm 和 Google Fonts（前端构建时要从 Google Fonts 下载字体，连不上就构建失败）。用户有代理软件时，在接下来运行命令的那个终端里先设上代理（`HTTPS_PROXY` 的写法见「网络和代理」），依赖装好、前端构建完之后就不需要了。Docker 跑的，还要在 Docker Desktop 的 Settings → Resources → Proxies 里填代理（Linux 上配 docker 守护进程的代理），构建时拉镜像、装依赖、下载字体都走它。

### 2.3 启动

**直接跑**：开两个终端，都在仓库根目录。你自己操作时，就把两条命令放到后台运行（Windows 上用 `Start-Process` 时写 `npm.cmd`，原因见「拉取剧情和立绘」）。

```sh
# 终端一：后端（:8000）
cd backend
uv run --env-file=../.env eidolon serve
```

```sh
# 终端二：前端（:3000）
cd frontend
npm ci
npm run build
BACKEND_URL=http://localhost:8000 npm run start
# PowerShell：$env:BACKEND_URL="http://localhost:8000"; npm run start
```

两个终端都一直开着，关掉终端就停了。停前端时，只关掉命令还不够：`next start` 的子进程还占着 3000 端口，要按端口找到进程再结束（PowerShell：`Get-NetTCPConnection -LocalPort 3000 -State Listen` 拿到 `OwningProcess`，再 `Stop-Process -Id <它>`；macOS/Linux：`lsof -ti:3000 | xargs kill`）。

**Docker 跑**：

```sh
docker compose up -d --build
```

两种跑法接下来都一样：跑 doctor（命令见「三种跑法」），退出码是 0、最后一行是「全部正常」，才算这一步完成；不是 0 就看「排障」。然后让用户打开 <http://localhost:3000>，点「登录」→「开发登录」，随便填一个名字，点一位偶像发一句话。她回复了，就说明文字聊天跑通了。

开发登录下所有人都是管理者，后台在 <http://localhost:3000/admin>（设置的「登录与数据」里也有「进入后台」），模型、key、限额等可以在那里改。告诉用户：后台改过的项优先于 `.env`，之后再改 `.env` 里的同一项不会生效，要先在后台把它恢复成 `.env` 的值。

后端起不来时，看后端的输出（位置见「三种跑法」）：最后几行会写明是哪一项配置不对。

### 2.4 按功能加服务

用户要哪项功能，就照「服务一览」申请对应的服务、填进 `.env`，再按「三种跑法」里「改了 `.env` 以后」那一行重启后端，然后跑 doctor。每加一项都跑一次 doctor，全部正常了再加下一项。

**本机的语音通话**：浏览器在 `localhost` 下允许用麦克风。直接跑时，本机通话能打通。Docker Desktop 的容器网络可能让 WebRTC 连不上，表现是一直「接通中」然后失败，这种情况还没有实际验证过；碰到时改用直接跑。

### 2.5 剧情和立绘

用户想要剧情回忆或通话立绘时，由你按「拉取剧情和立绘」拉取，跑到全部拉完。

## 3. 公网部署

完整步骤在 `docs/deploy.md`，照着做。要点和容易漏的地方：

- 要有一台 Linux 服务器（有公网 IPv4）和一个域名。国内的服务器要求域名已备案，否则 80、443 端口会被拦截。云厂商的安全组按 `docs/deploy.md`「准备」那张表放行端口。
- 生产配置只能在 Linux 上用（host 网络）。前后端镜像从 GHCR 拉，只有 amd64 一种；arm64 的服务器要用 `up -d --build` 在服务器上构建。国内的服务器拉 GHCR 的镜像经常超时，要给 docker 守护进程配代理。
- 你多半是通过 SSH 在服务器上操作。key 同样让用户自己填：让用户在服务器上用 `nano .env` 之类的编辑器填，或者在本地填好再用 `scp` 传上去。
- `EIDOLON_TURN_SECRET`、`EIDOLON_SECRET_KEY` 用 `openssl rand -hex 32` 生成，可以由你生成并写入。**`EIDOLON_SECRET_KEY` 一旦填了就不要再换**，告诉用户把它备份好。
- 登录要配 GitHub 或 Google 的 OAuth 应用，至少一家。见 `docs/deploy.md`「配置 OAuth 应用」，也可以用 `scripts/setup-oauth.sh`，这是一个交互式脚本，让用户自己在终端里运行。
- 公网部署不能留 `EIDOLON_DEV_LOGIN`。它让任何人都能冒充任何用户，配置了 `EIDOLON_DOMAIN` 时后端会拒绝启动。
- 只给认识的人用的，`.env` 里设 `EIDOLON_REGISTRATION=invite`，并且一定要配好管理者名单：邀请链接只能在后台生成。顺序是：用户自己先登录一次（第一位用户不用邀请），你用 `eidolon user list` 查到他的标识填进 `EIDOLON_ADMINS`，`up -d`；然后告诉用户在后台配置页「注册」里生成邀请链接，复制发给朋友。见 `docs/deploy.md`「开启后台」「只让受邀的人注册」。
- 之后的命令都带 `-f docker-compose.prod.yml`，或者先 `export COMPOSE_FILE=docker-compose.prod.yml`。`.env` 缺了 `EIDOLON_DOMAIN`、`EIDOLON_TURN_SECRET` 时，compose 自己会先报「请在 .env 里填写 …」，所有命令（包括 doctor）都跑不起来，先补上。
- 用 `https://域名` 能打开网站、用户能登录、doctor 全部正常，才算部署完成。接着建议用户配好每天的备份（`docs/deploy.md`「备份」）和每周的剧情同步（「每周自动同步」）。

## 服务一览

| 功能 | 要申请的服务 | 填哪些变量 | 中国大陆 |
|---|---|---|---|
| 文字聊天（必填） | 任何支持**流式输出和工具调用**的对话模型，三种接口任选 | `CHAT_LLM_*` | 选国内能直连的 OpenAI 兼容服务（DeepSeek、硅基流动、阿里云百炼等）；OpenAI、Anthropic、Gemini 要代理 |
| 语音通话：合成 | Fish Audio（fish.audio 的 API Keys 页面） | `FISH_AUDIO_API_KEY` | 通常要代理 |
| 语音通话：识别 | Soniox（console.soniox.com），或者阿里云百炼（bailian.console.aliyun.com，北京地域有免费额度，要先开通识别模型） | `SONIOX_API_KEY`；或 `STT_PROVIDER=bailian` 加 `DASHSCOPE_API_KEY` | 推荐百炼，能直连 |
| 剧情回忆、记忆：向量化和重排 | 硅基流动（cloud.siliconflow.cn），向量化和重排一个 key 就够 | `SILICONFLOW_API_KEY` | 能直连。Gemini 向量化不对中国大陆、香港、澳门开放 |
| 剧情回忆、记忆：判断模型 | 三家选一家：Jev（经 OpenRouter，`JEV_API_KEY`）、Cloudflare Workers AI（每天有免费额度）、阿里云百炼的决策模型 | 见 `.env.example`「判断模型」 | 推荐百炼；OpenRouter 要代理 |
| 照片 | NovelAI，或者兼容的中转；还要配好判断模型 | `NOVELAI_*` | 要代理 |
| 朋友圈无人配图（可选） | OpenAI 的 GPT Image（gpt-image-2 或更新），或者兼容的中转；要先配好照片那一行 | `GPT_IMAGE_*` | OpenAI 要代理（`EIDOLON_PROXY_SERVICES` 的 `gpt_image`） |
| 通话立绘 | 不用申请服务，见「立绘」 | `EIDOLON_STAND_ASSETS_URL` | |

- 对话模型必须支持工具调用，否则后端拒绝启动，doctor 会报「模型不对」。模型名以服务商文档为准，填进去以后由 doctor 实测。
- 后台模型（`BACKGROUND_LLM_*`，用来提炼记忆和起标题）不填就沿用对话模型。想省钱可以只填 `BACKGROUND_LLM_MODEL`，在同一家换一个便宜的模型。
- Fish Audio 的默认模型 `s2.1-pro-free` 不消耗 API 额度，但它的免费期限以 Fish Audio 的公告为准。到期后改用付费模型，要充值。
- 每一家怎么申请、填哪几行，见下一节「申请和填写 key」。
- 「中国大陆」这一列只是起点。哪一项到底要不要代理，以 doctor 在用户机器上的实测为准。

## 申请和填写 key

### 怎么填

每个服务都按同一个顺序来：

1. 你把下面这家的申请步骤转述给用户，用户在浏览器里注册、生成 key。很多控制台的 key **只在生成时完整显示一次**，提醒用户当场复制。
2. 让用户用编辑器打开仓库根目录的 `.env`：Windows 是 `notepad .env`，macOS 是 `open -e .env`，Linux 和服务器上是 `nano .env`。你把要填的那几行（下面每家的代码块）告诉用户，让用户找到 `.env` 里同名的那一行，把值写在 `=` 后面。不加引号，也不留空格。接口地址、模型名这类不是密钥的项，可以由你直接写进 `.env`。
3. 用户保存并说「填好了」以后，你确认这一行有值，但不把值打出来（PowerShell：`(Select-String -Path .env -Pattern '^CHAT_LLM_API_KEY=.').Count`；macOS/Linux：`grep -c '^CHAT_LLM_API_KEY=.' .env`；是 1 就是填上了）。然后重启后端、跑 doctor。

doctor 对这一项显示 ✓，这家才算配好。

### 每一家

**DeepSeek（对话模型，国内能直连）**：在 platform.deepseek.com 注册，到 platform.deepseek.com/api_keys 点「创建 API key」。要先充值，余额是 0 时 key 能通过认证，但一回复就会失败（doctor 报「余额不足」）。

```sh
CHAT_LLM_BASE_URL=https://api.deepseek.com/v1
CHAT_LLM_API_KEY=用户的 key
CHAT_LLM_MODEL=deepseek-flash
```

模型名以 DeepSeek 文档（api-docs.deepseek.com）当时的说法为准，填进去以后 doctor 会实测。想让通话里开口快些，可以按 `.env.example` 的说明设 `CHAT_LLM_CALL_REASONING_EFFORT`。

**其他对话模型**：`CHAT_LLM_PROTOCOL` 要和服务对上：OpenAI 兼容的填 `chat-completions`（也可以不填），Anthropic 的填 `anthropic`，OpenAI Responses 的填 `responses`。`CHAT_LLM_BASE_URL` 填到 `/v1` 这一级，比如硅基流动是 `https://api.siliconflow.cn/v1`，阿里云百炼北京地域是 `https://dashscope.aliyuncs.com/compatible-mode/v1`。

**硅基流动（向量化和重排，国内能直连）**：在 cloud.siliconflow.cn 注册，左侧「API 密钥」→「新建 API 密钥」。有些模型要实名认证才能用，赠送额度以官网为准。

```sh
SILICONFLOW_API_KEY=用户的 key
```

**Fish Audio（语音合成）**：在 fish.audio 注册并验证邮箱，到 fish.audio/app/api-keys 点「Create New Key」。默认模型 `s2.1-pro-free` 不扣额度，不用充值。国内通常要代理（见「网络和代理」）。

```sh
FISH_AUDIO_API_KEY=用户的 key
```

**阿里云百炼（语音识别，国内能直连）**：用阿里云账号登录 bailian.console.aliyun.com，**账号要先完成实名认证**。第一次进入时按提示开通服务，然后把右上角的地域切到「华北2（北京）」（免费额度只在北京地域），打开「API-Key」页面创建 key，业务空间选默认的就行。还要在模型广场里开通语音识别模型 `qwen-audio-3.1-asr-flash-streaming`：没开通时 doctor 和后端都会说明。

```sh
STT_PROVIDER=bailian
DASHSCOPE_API_KEY=用户的 key
```

**Soniox（语音识别，另一个选择）**：在 console.soniox.com 注册，进入项目（默认叫 My First Project）→「API Keys」→「Create API key」。

```sh
SONIOX_API_KEY=用户的 key
```

**判断模型（三选一）**：

- 阿里云百炼的决策模型（国内推荐）：要业务空间的 key 和业务空间 ID。key 要在那个业务空间下创建，ID 在控制台「业务空间管理」里看，形如 `llm-xxxx`。这个 key 和上面语音识别的 key 分开填。

  ```sh
  JUDGE_PROVIDER=bailian
  BAILIAN_JUDGE_API_KEY=用户的 key
  BAILIAN_JUDGE_WORKSPACE_ID=llm-xxxx
  ```

- Cloudflare Workers AI（每天有免费额度）：在 dash.cloudflare.com 打开 Workers AI，选「Use REST API」，创建 token（要 Workers AI 的 Read 和 Edit 权限），再复制 Account ID。

  ```sh
  JUDGE_PROVIDER=cloudflare
  CLOUDFLARE_API_TOKEN=用户的 token
  CLOUDFLARE_ACCOUNT_ID=用户的 account id
  ```

- Jev（经 OpenRouter，要先在 OpenRouter 充值，国内要代理）：在 openrouter.ai 注册，到 Settings → Keys 创建 key。

  ```sh
  JEV_API_KEY=用户的 key
  ```

**Gemini（向量化的另一个选择，不对中国大陆、香港、澳门开放）**：在 aistudio.google.com/apikey 创建 key，填 `EMBEDDING_PROVIDER=gemini` 和 `GEMINI_API_KEY`，重排照样要硅基流动。公开部署要开通计费，见 `.env.example`。

**生图（NovelAI）、登录（GitHub、Google 的 OAuth 应用）、存储桶**：步骤分别在 `.env.example`「生图」、`docs/deploy.md`「配置 OAuth 应用」和「立绘素材」里，照着带用户做。

## 网络和代理

最常见的问题：电脑或服务器在中国大陆，连不上海外的服务。表现是 doctor 报「连不上（network）」，或者「地区不支持（region）」。

1. **问用户有没有代理软件**（Clash、mihomo、v2rayN 等）、HTTP 或 SOCKS 端口是多少。常见端口有 7890、7897、10808、1080；你也可以在本机查一下哪个端口在监听（PowerShell：`Get-NetTCPConnection -State Listen`；macOS/Linux：`lsof -iTCP -sTCP:LISTEN`）。
2. **写 `EIDOLON_PROXY_URL`**：`http://主机:端口`，SOCKS 写成 `socks5h://主机:端口`。主机按「三种跑法」那张表填。Docker 跑时，容器里的 `127.0.0.1` 是容器自己，所以要写 `host.docker.internal`；Linux 上还要在代理软件里打开「允许局域网连接」。
3. `EIDOLON_PROXY_SERVICES` 先空着，重启后端再跑 doctor。连不上的服务它会经代理再试一次，最后打印「建议把 .env 里的这一行改成：EIDOLON_PROXY_SERVICES=…」。照抄进 `.env`，再重启后端。
4. doctor 报「✗ 代理：连不上代理」时，先解决代理本身的问题（代理软件没开、端口不对、Docker 跑时没用 `host.docker.internal`），它的提示里写了原因。

**`EIDOLON_PROXY_*` 和 `HTTPS_PROXY` 管的不是同一批东西。** 后端连各项服务只认 `EIDOLON_PROXY_*`，不认 `HTTPS_PROXY`。装依赖（uv、npm）、构建前端、git，以及下载剧情和立绘的命令（`eidolon story sync`、`eidolon stand fetch`），反过来只认 `HTTPS_PROXY`，连不上时在那个终端里先设上：

```sh
export HTTPS_PROXY=http://127.0.0.1:7890     # macOS、Linux、Git Bash
$env:HTTPS_PROXY="http://127.0.0.1:7890"     # PowerShell
```

git 也可以单独设代理：`git config --global http.https://github.com.proxy http://127.0.0.1:端口`。

## 拉取剧情和立绘

用户问起剧情或立绘，或者一开始就说想要这两项功能时，**下载由你来执行，跑到全部拉完**，用户不碰命令行。两项都很耗时，按这个顺序做：

1. **先说清楚再开始**：要多久、占多大空间、花不花钱（见下面两节），用户同意了再开始。
2. **确认前提**：拉剧情要 doctor 里的「向量化」是 ✓。在中国大陆连不上 GitHub、ShinyColorsDB 时，先在你启动脚本的那个终端里设上 `HTTPS_PROXY`（见「网络和代理」），脚本会继承它。
3. **用独立的进程在后台跑**，这样你的会话结束了它也照常跑完。两个脚本自己会把输出写进 `logs/` 下的日志，你只管启动：
   - Windows（PowerShell，在仓库根目录）。`.sh` 要交给 Git 自带的 `sh.exe`：

     ```powershell
     $sh = Join-Path (Split-Path (Split-Path (Get-Command git).Source)) "bin\sh.exe"
     $env:EIDOLON_SYNC_DIRECT = "1"   # 按下面各节设对应的变量
     Start-Process -WindowStyle Minimized -FilePath $sh -ArgumentList "deploy/story-sync.sh"
     ```

   - macOS、Linux：`EIDOLON_SYNC_DIRECT=1 nohup sh deploy/story-sync.sh >/dev/null 2>&1 &`
   - Windows 上用 `Start-Process` 启动 Node 的命令时，要写 `npm.cmd`、`npx.cmd`。只写 `npm`、`npx`，它会用记事本打开同名的脚本文件，什么也不启动。
4. **隔一阵看一次日志的最后几行**，用一句话把进度告诉用户，比如「剧情已经下载了 1200 个剧本」。
5. **日志最后一行「结束：退出码 N（含义）」不是 0，就再启动一次**。脚本会接着上次的进度做，已经下载的不会重下。退出码 5 表示上一次还没跑完，等着就行。

两个脚本退出码的含义，见 `docs/deploy.md`「每周自动同步」和「同步素材」那两张表。

## 剧情库

用户常问：「为什么仓库里没有剧情？」这样回答：剧情文本的版权不属于本项目，所以不随仓库分发（`docs/adr/0003-corpus-and-voices-stay-private.md`），仓库里只有同步工具。没同步之前，角色只凭人设回复，不会回忆原作剧情。

- **要告诉用户的**：第一次要下载几千个剧本，镜像要求逐个下载、间隔约一秒，所以要一到两个小时，另加向量化的时间。向量化按量计费，费用见服务商的价格页。
- **脚本**：`deploy/story-sync.sh`，日志在 `logs/story-sync.log`。它会先克隆（以后是更新）汉化版 SCTranslationData，再从镜像补齐还缺的原文剧情。
  - 直接跑：设 `EIDOLON_SYNC_DIRECT=1`。不经过 Docker，后端开着、停着都行。
  - Docker 跑：设 `COMPOSE_FILE=docker-compose.yml`，后端要在运行。
  - 服务器：什么都不用设。
- **镜像连不上时**（退出码 2，日志里是连接错误）：直接跑时，设上 `HTTPS_PROXY` 再启动一次。Docker 跑和服务器上，脚本不会把 `HTTPS_PROXY` 带进容器，改成直接在容器里运行：`docker compose exec -e HTTPS_PROXY=http://host.docker.internal:端口 backend eidolon story sync`（服务器上加 `-f docker-compose.prod.yml`，主机写 `127.0.0.1`）。
- **完成的标准**：日志最后一行是「结束：退出码 0」，doctor 显示「剧情库：N 段剧情」，N 有几千。告诉用户可以去和她聊聊原作的事了。
- 之后要更新，再启动一次脚本就行，通常几分钟就跑完。

## 立绘

用户常问：「为什么通话时只有背景图，没有会动的立绘？」这样回答：立绘是原作的 Spine 素材，同样不随仓库分发，要从 ShinyColorsDB 拉取。落地页的招呼语音和酒吧音乐也是同样的情况，没配时落地页会安静一些，这不是坏了。

**本机体验**：不用存储桶，拉到本地，再用一个本地的静态服务器提供给浏览器。直接跑和 Docker 跑都一样，要装好 uv（见 2.1）。

- **要告诉用户的**：要拉 29 位角色的全部衣装，有几 GB。ShinyColorsDB 要求逐个下载、间隔约一秒，所以要几个小时。不花钱。
- **拉取**：用 `deploy/stand-sync.sh`，设 `EIDOLON_STAND_FETCH_ONLY=1`，只拉取，不渲染缩略图、不上传。日志在 `logs/stand-sync.log`。退出码 6 表示有一部分没拉到，再启动一次。
- **拉完以后**，你接着做下面三件事：
  1. 在后台启动静态服务器，它要一直开着。Windows：`Start-Process -WindowStyle Minimized -FilePath npx.cmd -ArgumentList "--yes","http-server","corpus/stand/source/assets","-p","8765","--cors"`；macOS、Linux：`nohup npx --yes http-server corpus/stand/source/assets -p 8765 --cors >/dev/null 2>&1 &`。
  2. 在 `.env` 里写上 `EIDOLON_STAND_ASSETS_URL=http://localhost:8765`，然后重启后端。
  3. 直接跑时，**前端也要带上这个地址重新启动**：`BACKEND_URL=http://localhost:8000 EIDOLON_STAND_ASSETS_URL=http://localhost:8765 npm run start`（PowerShell 写成两条 `$env:…=` 再 `npm run start`）。前端只允许页面从这个地址加载立绘，不带上它，立绘会被浏览器挡掉。Docker 跑时用 `docker compose up -d`，它会自动把地址传给前端。
- **完成的标准**：日志最后一行是「结束：退出码 0」，8765 端口在监听，用户打一通电话能看到她的立绘。
- 告诉用户：以后每次用之前，静态服务器也要和前后端一起开着。换衣装面板要有衣装清单和缩略图，本机体验没有，这是正常的。

**公网部署**要一个公开可读的 S3 兼容存储桶（推荐 Cloudflare R2，不收流量费）。存储桶和 API 令牌要用户在 Cloudflare 控制台里自己建：你一步步告诉用户点哪里，用户把四项 `EIDOLON_STAND_S3_*` 和公开地址填进 `.env`。存储桶的设置（公开访问、CORS）、服务器上要装的东西，见 `docs/deploy.md`「立绘素材」。之后由你按「拉取剧情和立绘」的做法在服务器上运行 `deploy/stand-sync.sh`，什么变量都不用设，它会拉取、渲染缩略图、上传。日志最后一行是「结束：退出码 0」、通话里能看到立绘，就算完成。

## 排障

先跑 doctor（命令见「三种跑法」）。后端起不来时它也能用。它按 `.env` 逐项试一次每个服务：直连不通时经代理再试，反过来也一样。每一项会报成下面某一类，并附上服务商的原话：

| 类别 | 意思 | 怎么办 |
|---|---|---|
| `network` 连不上 | 网络不通 | 看「网络和代理」。如果标着「!」、提示「经代理能用」，照最后的建议改 `EIDOLON_PROXY_SERVICES` |
| `region` 地区不支持 | 服务商不对这个地区开放 | 让它走代理，或者换一家服务 |
| `key` key 不对 | key 错了、复制时多带了空格或引号、key 没有这项权限、填错了变量 | 让用户到控制台重新复制一遍；百炼判断模型的 key 必须属于填的那个业务空间 |
| `balance` 余额不足 | 余额或额度用完了 | 让用户充值，或者换免费的模型 |
| `model` 模型不对 | 模型名错了、没开通，或者不支持工具调用 | 对照服务商的模型列表核对，或者换一个模型 |
| `other` | 以上都不是 | 读原话判断 |

- 第一行是「✗ .env 有错」时，后端连启动都不会，照它说的改 `.env`。
- 有后台时（设了管理者，或者本机开着开发登录），后台配置页改过的项优先于 `.env`，doctor 只查 `.env`。
- 生图和 GPT Image doctor 都不试，因为每张都花钱。GPT Image 走不走代理，按「服务一览」那一列自己加 `gpt_image`。
- Windows 上中文显示成乱码时，先在那个终端里运行 `chcp 65001`，再运行一次。
- doctor 全部正常、问题却还在，就按现象查：
  - **打不开 localhost:3000**：直接跑时，看前端那个终端有没有报错、`npm run build` 是不是成功了；Docker 跑时，用 `docker compose ps` 看两个容器是不是都在运行。端口被占时，按 2.3 的办法结束占用端口的进程。
  - **前端构建报连不上 Google Fonts（`Failed to fetch font`）**：设上 `HTTPS_PROXY` 再构建（见「网络和代理」）。
  - **公网部署时网站打不开、语音一直「接通中」、`/admin` 是 404**：见 `docs/deploy.md`「排障」。
