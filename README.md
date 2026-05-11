<h1>米游签</h1>

<div align="center">
  <h1 align="center">
    <img src="./miyouqian/webui/assets/myq_logo.png" width="200" alt="米游签" style="border-radius:10px">
  </h1>
  <p>一个小而美的带 Web 控制台的米游社签到工具，支持扫码登录、游戏签到、米游币任务、每日自动执行和结果推送。</p>
  <p>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&style=flat-square">
    <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-1E9BFA?style=flat-square">
    <img alt="Encoding" src="https://img.shields.io/badge/encoding-UTF--8-2EA44F?style=flat-square">
  </p>
</div>

## 仓库统计

![Repobeats analytics image](https://repobeats.axiom.co/api/embed/fe6d87dac87579ae661915dfc1ba84cceb511728.svg "https://repobeats.axiom.co/api/embed/fe6d87dac87579ae661915dfc1ba84cceb511728.svg")

## 简介

米游签是一款小而美，精致便捷的米游社每日签到工具。你只需要用米游社 APP 扫码登录一次，之后就可以在本地 Web 控制台里管理账号、选择任务、设置每天自动执行签到任务。

<img src="./assets/home.png" alt="demo" style="max-width:100%;border-radius:10px">

### 请勿在其他平台宣传本项目，请不要大范围传播本项目！！！

### 大怨种是谁呢

太久没有玩米游了，回坑就做这个项目，要做完突然发现天塌了，米游社要更新米游币获取规则了，部分用户现在已经不能回帖点赞获取米游币了，不知道官方后续的新规是什么，赶上了好时候，卑微QWQ，不知道以后新的规则还能不能搞自动任务

### 交流群
如果你有兴趣参与开发，或者在使用过程中遇到问题，可以加入交流群：

<p align="center">
  <img src="./assets/QQ_qrcode.jpg" alt="QQ群" width="300">
</p>

## 功能

### 重大更新：支持自动过验证码！！！

- 米游社 APP 扫码登录
- 多账号管理
- 游戏每日签到
- 米游币社区任务
- 本地 Web 控制台
- 每日自动执行
- 执行结果推送
- 日志查看

## 支持的游戏

| 游戏 | 配置名 |
| --- | --- |
| 原神 | `genshin` |
| 崩坏：星穹铁道 | `starrail` |
| 绝区零 | `zzz` |
| 崩坏3 | `honkai3rd` |
| 未定事件簿 | `tears` |
| 崩坏学园2 | `honkai2` |

默认启用原神、崩坏：星穹铁道、绝区零。其他游戏可以在 Web 控制台或配置文件中开启。

## 米游币任务

米游币任务默认关闭，需要时手动开启。可执行的任务包括：

- 社区签到
- 看帖
- 点赞
- 分享
- 点赞后自动取消点赞

米游币任务比游戏签到更容易遇到验证码或风控。第一次使用建议先只开启游戏签到，确认稳定后再开启米游币任务。

## 部署流程

### Docker 部署（推荐）

适合部署在服务器或 NAS 上，无需手动安装 Python 和 uv。

#### 1. 获取项目文件

```bash
git clone <你的仓库地址>
cd 米游社签到
```

#### 2. 构建并启动

```bash
# 进入 docker 目录
cd docker

# 构建并启动（后台运行）
docker compose up -d --build
```

启动成功后，通过端口映射从宿主机访问 `http://localhost:5890` 即可打开 Web 控制台。

> 容器首次启动时会自动从 `config.example.yaml` 生成 `config.yaml`，无需手动操作。
> 容器内服务已默认监听 `0.0.0.0`（Docker 必需），宿主机通过 `localhost:5890` 访问即可。

#### 4. 常用命令

```bash
cd docker

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 重新构建（更新代码后）
docker compose up -d --build
```

#### 5. 数据持久化

`docker-compose.yml` 已配置以下目录的持久化映射：

| 宿主机路径 | 容器路径 | 说明 |
| --- | --- | --- |
| `config.yaml` | `/app/config.yaml` | 配置文件 |
| `data/` | `/app/data/` | 登录凭证（敏感） |
| `logs/` | `/app/logs/` | 运行日志 |

容器重建后数据不会丢失。

#### 注意事项

- 容器内时区默认为 `Asia/Shanghai`，如需修改可在 `docker-compose.yml` 中调整 `TZ` 环境变量
- 如需修改端口，同时修改 `docker-compose.yml` 的 `ports` 和 `config.yaml` 的 `web.port`
- 公网访问需要在宿主机层面配置（开放防火墙端口、反向代理等），首次访问时页面会引导设置密码

---

### GitHub Actions 定时签到（无需服务器）

适合不想长期运行电脑、服务器或 NAS 的用户。Actions 会按 `.github/workflows/checkin.yml` 里的时间自动执行一次 `python main.py run`。

> ⚠️ **必须使用 "Use this template" 创建项目，不要使用 Fork！**
>
> Fork 仓库的 Actions 运行时长会统计到上游（原）仓库，会导致上游仓库因超出时长限制而被封禁。
> 请点击仓库右上角的 **`Use this template`** -> **`Create a new repository`**，将项目创建到你自己的 GitHub 账号下。
>
> GitHub Actions 只负责定时触发一次性签到，不会启动 Web 控制台。首次扫码登录和配置调整建议先在本地或 Docker 环境完成。

#### 1. 本地生成配置和凭证

先按“本地部署”或“Docker 部署”完成一次扫码登录，并确认手动执行签到正常。完成后项目目录里会有：

| 文件 | 说明 |
| --- | --- |
| `config.yaml` | 公开配置，不建议直接提交仓库 |
| `data/credentials.yaml` | 登录凭证，敏感信息，绝对不要提交仓库 |

#### 2. 创建项目并启用 Actions

点击本仓库右上角的 `Use this template` -> `Create a new repository`，将项目创建到你自己的 GitHub 账号下。

进入你创建的新仓库后，打开 `Actions` 页面。如果页面提示 workflow 被禁用，点击启用。

开启 Actions 后无论配置 secrets 与否都会每天执行一次。不要在原项目仓库里配置你的账号凭证，也不要把凭证发给项目作者。

#### 3. 添加 GitHub Secrets

进入你创建的仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

添加两个 Secret：

| Secret 名称 | 内容 |
| --- | --- |
| `MIYOUQIAN_CONFIG` | 复制 `config.yaml` 的完整内容 |
| `MIYOUQIAN_CREDENTIALS` | 复制 `data/credentials.yaml` 的完整内容 |

粘贴时保留 YAML 原本的换行和缩进。凭证过期、账号变化或推送配置变化后，重新复制最新文件内容覆盖对应 Secret 即可。

#### 4. 修改定时执行时间

默认每天北京时间 `09:20` 执行：

```yaml
schedule:
  - cron: "20 9 * * *"
    timezone: "Asia/Shanghai"
```

如果想改成每天北京时间 `18:30`，改为：

```yaml
schedule:
  - cron: "30 18 * * *"
    timezone: "Asia/Shanghai"
```

`cron` 的 5 个字段分别是：

```text
分钟 小时 日期 月份 星期
```

不建议设置在整点，例如 `0 9 * * *`，整点附近 GitHub Actions 排队更容易延迟。定时任务只会在默认分支上的 workflow 生效。

#### 5. 手动执行一次

进入你创建的仓库的 `Actions` 页面，选择 `米游签定时签到`，点击 `Run workflow`：

`执行模式` 用来决定这一次手动运行要跑哪些任务：

| 选项 | 说明 |
| --- | --- |
| `全部任务` | 默认选项，按 `config.yaml` 中的开关执行游戏签到和米游币社区任务 |
| `只执行游戏签到` | 只跑各游戏每日签到，跳过米游币社区任务 |
| `只执行米游币社区任务` | 只跑社区签到、看帖、点赞、分享等米游币任务，跳过游戏签到 |

`account` 是可选项，用来只执行某一个账号名；留空则执行 `config.yaml` 中的全部账号。

执行完成后可以在 Actions 日志底部查看任务摘要。如果配置了推送渠道，执行结果也会按 `config.yaml` 中的推送配置发送。

#### 注意事项

- 不要把 `config.yaml`、`data/credentials.yaml`、Actions 日志截图公开给别人
- 不要在原项目仓库提交 Issue、PR 或评论时粘贴任何账号凭证
- GitHub Actions 的定时任务可能会因平台负载延迟几分钟
- 公开仓库如果长期没有活动，GitHub 可能会自动停用定时 workflow
- `config.yaml` 里的 `schedule` 配置不会影响 Actions 定时，Actions 的执行时间以 `.github/workflows/checkin.yml` 为准

---

### 本地部署

下面以本地部署为例。项目推荐使用 `uv` 管理 Python 环境和依赖。Windows 用户可以直接使用 PowerShell；Linux 或 macOS 用户把对应命令换成下方给出的 shell 命令即可。

### 1. 安装 uv

Windows PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux 或 macOS：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装完成后，重新打开一个终端，检查 uv 是否可用：

```powershell
uv --version
```

看到版本号后再继续下一步。uv 会为项目创建虚拟环境，也可以在需要时自动准备 Python 版本。

### 2. 获取项目文件

如果你下载的是压缩包，请先解压，然后进入解压后的项目目录。

如果你使用 Git，可以执行：

```powershell
git clone <你的仓库地址>
cd 米游社签到
```

后续所有命令都需要在项目目录中执行，也就是能看到 `main.py`、`pyproject.toml` 和 `uv.lock` 的目录。

### 3. 创建虚拟环境并安装依赖

在项目目录执行：

```powershell
uv venv --python 3.11
uv sync
```

这会在项目目录下创建 `.venv`，并安装项目运行所需依赖。日常使用时不需要手动激活虚拟环境，后续命令直接通过 `uv run` 执行即可。

如果下载依赖很慢，可以临时使用镜像源：

```powershell
uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 启动 Web 控制台

```powershell
uv run python main.py
```

启动成功后，终端会显示访问地址，通常是：

```text
http://127.0.0.1:5890
```

如果端口被占用，程序会自动切换到后续端口。请以终端显示的实际地址为准。

### 5. 完成首次配置

打开 Web 控制台后，按顺序完成：

1. 添加账号
2. 使用米游社 APP 扫码登录
3. 选择要执行的游戏签到任务
4. 点击“立即执行”测试一次
5. 测试正常后再开启每日调度和推送

### 6. 保持程序运行

每日自动执行依赖当前程序保持运行。关闭终端、电脑关机或休眠后，自动任务不会继续执行。

## 快速开始

推荐使用 Web 控制台完成所有日常操作。

### 1. 启动

在项目目录运行：

```powershell
uv run python main.py
```

启动成功后，终端会显示 Web 控制台地址，通常是：

```text
http://127.0.0.1:5890
```

如果 `5890` 端口被占用，程序会自动尝试后续端口。请以终端里显示的实际地址为准。

### 2. 添加账号

打开 Web 控制台后：

1. 在“账号”区域点击“添加”
2. 可以先把账号名改成 `main`、`小号1` 等方便识别的名字
3. 点击账号卡片里的“登录”
4. 使用米游社 APP 扫码

扫码路径：

```text
米游社 APP -> 我的 -> 左上角扫一扫
```

登录成功后，账号卡片会显示 UID。

### 3. 选择任务

在“任务配置”里选择你想执行的内容：

- 游戏每日签到
- 具体游戏
- 米游币任务
- 社区签到、看帖、点赞、分享

第一次使用建议只开启“游戏每日签到”，先跑通一次。

### 4. 手动测试

点击右上角“立即执行”。执行过程中可以在右侧日志区域查看结果。

如果提示“今日已签到”，说明账号和任务配置已经正常。

### 5. 开启每日自动执行

确认手动执行正常后，再展开“每日调度”：

1. 勾选“启用每日自动执行”
2. 设置执行时间
3. 设置随机波动分钟
4. 按需选择“启动后执行一次”

示例：执行时间为 `09:00`，随机波动为 `45`，表示每天 09:00 到 09:45 之间随机执行一次。

自动执行要求程序保持运行。关闭终端、电脑关机或休眠后，任务不会继续执行，所以推荐服务器上运行。

## Web 控制台说明

Web 控制台主要分为几块：

| 区域 | 用途 |
| --- | --- |
| 顶部状态 | 查看账号数量、自动调度状态、下次执行时间、最近结果 |
| 账号 | 添加账号、扫码登录、刷新凭证、删除账号 |
| 任务配置 | 开关游戏签到和米游币任务 |
| 每日调度 | 设置每天什么时候自动运行 |
| 推送通道 | 设置任务完成后的通知方式 |
| 日志 | 查看本次启动后的运行记录 |

日志区域只显示本次 Web 服务启动后的记录。历史日志会保存在 `logs/miyouqian.log`。

## 命令行用法

如果你不想使用 Web 控制台，也可以用命令行。

生成配置：

```powershell
uv run python main.py init
```

扫码登录：

```powershell
uv run python main.py login --account main
```

执行全部任务：

```powershell
uv run python main.py run
```

只执行指定账号：

```powershell
uv run python main.py run --account main
```

只执行游戏签到：

```powershell
uv run python main.py run --games-only
```

只执行米游币任务：

```powershell
uv run python main.py run --bbs-only
```

只执行指定游戏：

```powershell
uv run python main.py run --game genshin --game starrail
```

启动 Web 控制台并指定端口：

```powershell
uv run python main.py serve --port 5891
```

`--host` 和 `--port` 参数会覆盖配置文件中的设置。不指定时读取 `config.yaml` 中的 `web.host` 和 `web.port`。

查看当前配置摘要：

```powershell
uv run python main.py show
```

## 常用设置

大多数设置都可以在 Web 控制台里完成。只有在需要批量修改、迁移配置或高级调整时，才建议手动编辑 `config.yaml`。

请使用 UTF-8 编码保存配置文件，否则中文可能乱码。

### 文件位置

默认会生成或使用这些文件：

```text
config.yaml              # 账号名称、任务开关、调度、推送等普通配置
data/credentials.yaml    # 登录凭证
logs/miyouqian.log       # 历史日志
qrcode.png               # 命令行扫码登录时生成的二维码图片
```

开发时不要把这些文件上传到公开仓库，尤其是 `data/credentials.yaml`。

### 账号

Web 控制台添加账号后，会在配置中保存账号名。扫码登录成功后，登录凭证会单独保存到 `data/credentials.yaml`。

通常不需要手动填写 cookie 或 stoken。

### 游戏签到

如果你想手动指定游戏，可以编辑：

```yaml
games:
  enabled:
    - genshin
    - starrail
    - zzz
```

如果某个游戏里有多个角色，但你想跳过其中一个角色，可以把角色 UID 加到黑名单：

```yaml
games:
  black_list:
    genshin:
      - "100000001"
```

### 米游币任务

开启米游币任务：

```yaml
features:
  bbs_tasks: true
```

常用选项：

```yaml
bbs:
  forums:
    - 5
    - 2
  checkin: true
  read: true
  like: true
  share: true
  cancel_like: true
  delay_seconds:
    - 1
    - 3
```

社区 ID：

| ID | 社区 |
| --- | --- |
| `1` | 崩坏3 |
| `2` | 原神 |
| `3` | 崩坏2 |
| `4` | 未定事件簿 |
| `5` | 大别野 |
| `6` | 崩坏：星穹铁道 |
| `8` | 绝区零 |

### 验证码识别

项目默认不会自动处理验证码。验证码识别按渠道配置，当前只适配打码狗；后续新增平台时会在同一组渠道中扩展。

```yaml
captcha:
  max_retries: 3
  channels:
    - provider: damagou
      enable: false
      userkey: ""
      timeout: 60
```

说明：

| 设置 | 说明 |
| --- | --- |
| `max_retries` | 每次触发验证码后最多重新获取并识别的次数 |
| `channels[].provider` | 打码渠道，目前支持 `damagou` |
| `channels[].enable` | 是否启用该渠道 |
| `channels[].userkey` | 打码狗用户 `userkey` |
| `channels[].timeout` | 调用打码接口的超时时间，单位秒 |

打码狗的 `type` 默认不需要设置；识别困难时可以在配置文件中给该渠道补 `type: "1006"`，会增加积分消耗。

识别、校验或提交失败时，会重新获取验证码并重试，最多执行 `max_retries` 次。

### 每日调度

```yaml
schedule:
  enable: true
  time: "09:00"
  jitter_minutes: 45
  run_on_start: false
```

含义：

| 设置 | 说明 |
| --- | --- |
| `enable` | 是否开启每日自动执行 |
| `time` | 每天的基准执行时间 |
| `jitter_minutes` | 随机延后分钟数 |
| `run_on_start` | 启动 Web 服务后是否立即执行一次 |

### 网络访问与密码

Web 控制台默认只监听本机地址 `127.0.0.1`，只能在本机浏览器中访问。

如果需要从局域网或外网访问（例如部署在服务器上），可以在配置文件中修改监听地址：

```yaml
web:
  host: "0.0.0.0"   # 监听地址，设为 0.0.0.0 允许外部访问
  port: 5890        # 监听端口
  password: ""      # 访问密码（见下方说明）
```

**密码说明：**

- `host` 为 `127.0.0.1` 或 `localhost` 时，不需要密码，直接访问
- `host` 为 `0.0.0.0` 或其他非本机地址时，必须设置密码才能使用
- 首次访问会显示密码设置页面，输入后自动保存（存储为哈希值）
- 也可以在配置文件中直接填写明文密码，启动时会自动转换为哈希
- 服务重启后需要重新输入密码

| 设置 | 说明 |
| --- | --- |
| `host` | 监听地址，`127.0.0.1` 仅本机，`0.0.0.0` 允许外部 |
| `port` | 监听端口，默认 `5890` |
| `password` | 访问密码，留空首次通过页面设置，也可直接填写明文 |

## 推送设置

推送可以在 Web 控制台中配置。开启后，任务结束时会发送结果通知。

如果只想失败时通知，勾选“仅失败时推送”，或设置：

```yaml
push:
  error_only: true
```

### pushplus

需要填写：

- Token
- 群组编码，可留空

示例：

```yaml
push:
  channels:
    - provider: pushplus
      enable: true
      token: "你的 token"
      topic: ""
```

### Telegram

需要填写：

- Bot Token
- Chat ID

示例：

```yaml
push:
  channels:
    - provider: telegram
      enable: true
      token: "bot token"
      chat_id: "chat id"
```

### 钉钉机器人

需要填写：

- Webhook
- 加签 Secret，可留空

示例：

```yaml
push:
  channels:
    - provider: dingrobot
      enable: true
      webhook: "https://oapi.dingtalk.com/robot/send?access_token=..."
      secret: "SEC..."
```

### 飞书机器人

需要填写：

- Webhook

示例：

```yaml
push:
  channels:
    - provider: feishubot
      enable: true
      webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/..."
```

### 邮箱

需要填写：

- SMTP 服务器
- SMTP 端口
- 邮箱账号
- 邮箱授权码
- 发件人
- 收件人

示例：

```yaml
push:
  channels:
    - provider: email
      enable: true
      smtp_host: "smtp.example.com"
      smtp_port: 465
      smtp_user: "name@example.com"
      smtp_password: "邮箱授权码"
      mail_from: "name@example.com"
      mail_to: "target@example.com"
      smtp_ssl: true
```

多个收件人通常可以用英文逗号分隔。

## 推荐使用流程

第一次使用建议这样做：

1. 安装 uv
2. 创建虚拟环境并安装依赖
3. 运行 `uv run python main.py`
4. 打开 Web 控制台
5. 添加账号并扫码登录
6. 只开启游戏签到
7. 点击“立即执行”
8. 确认日志正常
9. 开启每日调度
10. 按需开启推送
11. 最后再考虑开启米游币任务

## FAQ

### 扫码登录后凭证保存在哪里？

默认保存在 `data/credentials.yaml`。普通设置保存在 `config.yaml`。

### 为什么 `config.yaml` 里看不到 cookie？

登录凭证会单独保存，避免普通配置文件里直接暴露敏感信息。

### Web 控制台打不开怎么办？

先看终端里显示的实际地址。默认端口是 `5890`，可以在配置文件 `web.port` 中修改，如果被占用，程序会自动切换到后续端口。

也可以手动指定端口：

```powershell
uv run python main.py serve --port 5891
```

### 自动调度没有执行？

请检查：

- 程序是否一直运行
- “每日调度”是否已开启
- 电脑是否休眠或关机
- 当前时间是否已经过了今天的执行窗口
- 日志里是否显示了下次执行时间

### 签到提示首次绑定怎么办？

部分游戏第一次绑定签到活动时，需要先在米游社或活动页面手动签到一次。手动完成后，后续再交给米游签执行。

### 遇到验证码怎么办？

默认不会自动处理验证码。遇到验证码时会跳过该项并写入日志。可以稍后手动签到，或降低米游币任务使用频率。

如果你有打码狗 `userkey`，可以在 Web 控制台开启验证码识别。项目只负责调用打码狗并按游戏签到、社区签到两种不同方式提交结果。

### 米游币任务失败，但游戏签到正常？

这是可能的。米游币任务更容易受到验证码、风控和任务状态影响。建议先确保游戏签到稳定，再开启米游币任务。

### 可以添加多个账号吗？

可以。每个账号都需要分别扫码登录。不要重复添加同一个 UID。

### 可以放到服务器运行吗？

本项目推荐放到服务器运行，但要注意：

- 扫码登录时需要能看到二维码
- 如果需要外部访问，将 `web.host` 设为 `0.0.0.0`，并设置访问密码
- 也可以用 `--host 0.0.0.0` 启动，但密码仍需在配置文件或首次访问时设置
- 服务器时间会影响每日调度时间

## 下一步计划

| 完成 | 计划 | 完成时间 |
| --- | --- | --- |
| [ ] | 补充更多游戏渠道签到 | -- |
| [ ] | 新增米游社其他功能，例如米游币兑换功能 | -- |
| [ ] | 补充更多推送渠道 | -- |
| [ ] | 优化签到流程，降低风控风险 | -- |
| [ ] | 增加配置导入、导出功能 | -- |
| [ ] | 完善产品文档 | -- |
| [ ] | 持续适配米游社规则变化，尽量保持工具可用 | -- |
| [ ] | ... | -- |

## 注意事项

- 请妥善保管 `data/credentials.yaml`
- 不要公开上传配置文件、日志文件或二维码图片
- 遇到验证码时需要手动处理
- 如果米游社规则变化，可能会出现签到失败，需要等待项目更新
- 使用自动化工具存在账号风控风险，请低频、保守使用

## 致谢

本项目的部分功能思路参考：

- [Womsxd/MihoyoBBSTools](https://github.com/Womsxd/MihoyoBBSTools)
- [jiarui666/mihoyo_qr_login](https://github.com/jiarui666/mihoyo_qr_login)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Marchen-zcl/MiyoQian&type=Date)](https://star-history.com/#Marchen-zcl/MiyoQian&Date)

## 免责声明

本项目仅供学习和个人使用，请勿用于商业用途或违反米哈游、米游社相关用户协议的场景。

使用本项目产生的账号风险、数据丢失、任务失败、风控限制或其他后果均由使用者自行承担。请妥善保管账号凭证，不要将配置文件、日志文件或二维码图片公开分享。

如果你不同意以上内容，请不要使用本项目。

## 友链

- [linux.do](https://linux.do/) 学AI来L站~
