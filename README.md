# Campo Reader — 网页版与 Windows 版

独立的 FAU Campo 工具，统一维护网页版和 Windows 桌面版。只包含课表、成绩、课程管理、学分进度和证明文件等 Campo Reader 功能，不包含博客、导航台、AI 对话、SSH 或设备控制台。

## 共享架构

- `campo_backend/`：两端共用的获取、解析、缓存和课程/证明业务逻辑。
- `public/`：两端共用的 HTML、CSS、JavaScript 界面。
- `server.py`：共享 HTTP API 与 Windows 本机访问控制。
- `web.py`：独立网页入口，使用共享 API，隐藏桌面操作。
- `desktop.py`、`desktop_updates.py`：Windows 窗口、原生下载和更新。
- `packaging/`、`.github/workflows/`：安装包、发布及两端检查。

网页版和桌面版独立运行、独立保存数据；合并代码不代表自动同步个人数据。两份仓库原有的提交历史已通过合并保留，旧 PyQt 客户端可从早期提交查看，当前使用同一套网页界面与核心逻辑。

## 独立网页版

Python 3.10+，推荐 Python 3.12：

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-web.txt
.venv/bin/python -m playwright install --only-shell chromium
.venv/bin/python web.py
```

打开 `http://127.0.0.1:8090/`。Linux 也可使用已有的 `/usr/bin/chromium-browser`。无需安装 Qt，也无需部署 BLOG。默认数据位于 `~/.local/share/campo-reader-web`，可通过 `--data-dir` 指定；不要使用正在被另一个 Campo 进程写入的目录。

这是单人私有网页服务，沿用个人设备内直接进入的使用方式，**没有多用户登录或公开访问控制**。默认仅监听本机。远程使用时放在 Tailscale/可信私有网络和 HTTPS 反向代理后面，并用 `--allowed-host your-private-host:port` 允许精确的代理 Host。不要直接暴露到公网。写入接口仍验证 Host、Origin、CSRF；不提供设备控制接口。

现有 Orange Pi 集成网页继续运行；本次仓库整理不会替换其服务或搬动账号、会话和文档。

## Windows 桌面版

从 Orange Pi 网页版提取，保留同一套界面和业务逻辑。只包含 Campo Reader，不依赖博客、导航台、SSH 或设备控制台。

## 使用

推荐运行 `CampoReader-Setup-Windows-x64.exe`，安装完成后双击桌面图标。
也可解压 `CampoReader-Portable-Windows-x64.zip`，双击其中的 `CampoReader.exe`；请保留整个文件夹。

- Windows 10/11 x64，不需要安装 Python，不需要命令行。内置桌面渲染引擎与 FAU 同步浏览器，首次启动不用下载运行组件。
- 首次添加账号并登录 FAU。Windows 与 Orange Pi 各自保存数据；安装包不包含任何服务器账号、密码、会话、分类或 PDF。
- 支持课表/成绩、变化中心、全学期课程报名、分类/批量分类、无需AI的模块关联、学分进度、个人计划和 Documents 获取/归档/导入/回收/下载。
- 自动更新在桌面程序运行期间有效；关闭程序后停止。重开程序继续使用本机缓存与有效会话。
- 设置和文件保存在 `%LOCALAPPDATA%\CampoReader`，可以从应用菜单或侧栏打开。升级和卸载默认保留该目录。
- 本地服务只监听 `127.0.0.1` 随机端口，并使用每次启动随机会话与 CSRF 校验；不开放局域网端口，不需要安装 HTTPS 证书。
- 外部官方网站链接用系统默认浏览器打开，PDF 下载使用原生保存窗口。

## 构建与验证

共享代码每次推送运行 Linux 回归测试。修改 `version.py` 的版本号并推送 main，或手动运行 `.github/workflows/windows.yml`，即可构建 Windows 发布包。使用 `.github/workflows/windows.yml` 在 Windows 2022 / Python 3.12 构建。
依赖固定于 requirements*.txt。PyInstaller 输出目录包，Inno Setup 生成当前用户安装包。
构建执行业务与本地接口测试，并直接运行打包后的 EXE 验证本地 API、内置 Chromium 和 Qt 页面加载。

安装包未进行商业代码签名；Windows 可能显示“未知发布者”。没有关停或绕过系统安全防护。

## 来源

当前网页版模块与原项目 https://github.com/vMarkEvanv/campo-reader-legacy 的核心解析代码。构建用私有仓库与源码工作区独立于 Orange Pi 运行目录；不会替换正在运行的服务。

## 软件更新（1.1 起）

侧栏“软件更新”或菜单“应用 → 检查更新”打开更新窗口。默认每天在启动时检查一次，可关闭；不会自动下载安装。发现新版本后可查看说明、下载、取消，确认后退出旧程序并安装，完成后重新启动。升级保留 `%LOCALAPPDATA%\CampoReader` 中的账号、分类、会话和 PDF。

更新源为自己的 Orange Pi：优先使用 Tailscale HTTPS，也可在原局域网中获取。发布清单使用 Ed25519 签名，客户端只携带公钥；下载完成和安装前均验证 SHA-256/大小，不运行未完成或被修改的文件。GitHub 访问令牌与签名私钥只在服务器侧使用，均不进入客户端或仓库。

1.0 没有更新入口，需要先手动安装一次 1.1；以后可在软件内升级。免安装版使用同一安装程序覆盖当前程序目录，会登记为当前用户安装版；个人数据位置保持不变。关闭软件时，未完成下载不会执行；安装前可选择稍后。
