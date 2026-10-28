# Campo Reader

FAU Campo 的课表、成绩和课程管理工具，提供网页版、Windows 桌面版和 Android 应用。

## 功能

- 查看课表、搜索课程、切换日期和周次。
- 同步成绩与各学期已报名课程，关联已通过的模块。
- 按学期、分类和学习类型管理课程，设置考试计划及练习课类型。
- 从 Study Planner 获取学分，支持手动调整和两位小数。
- 统计已获得及计划修读的学分，管理个人分组与目标。
- 从 Documents 获取证明，支持 PDF 导入、预览、下载、归档及回收。
- 设置同步间隔，按需记住账号密码；同步时显示处理阶段。

各平台独立保存账号和数据，不会自动在设备之间同步。此项目并非 FAU 官方应用。

## 下载与使用

[查看发布版本](https://github.com/vMarkEvanv/campo-reader/releases)

### Windows

支持 Windows 10/11 x64。

1. 下载并运行 `CampoReader-Setup-Windows-x64.exe`，安装后打开 Campo Reader。
2. 也可下载 `CampoReader-Portable-Windows-x64.zip`，完整解压后运行 `CampoReader.exe`。
3. 添加账号，点击“登录并同步”，使用学校账号登录。
4. 在课程管理中分类课程、设置修读类型与学分，在学业进度中查看统计。

无需安装 Python。应用菜单提供软件更新、重新加载、数据文件夹和退出操作。若出现闪烁或黑屏，可尝试开始菜单中的 compatible rendering 入口。

### Android

支持 Android 8.0 及以上，提供 arm64-v8a 和 x86_64 架构。

1. 在 Android 发布版本中下载 `CampoReader-Android-<版本>.apk`，按系统提示安装。
2. 添加账号并登录同步，通过底部标签查看课表、课程、成绩、学业进度和证明文件。
3. 课表支持按天浏览；PDF 可通过系统文件选择器导入、预览或保存。

应用在手机上运行并连接 FAU。自动同步仅在应用前台运行时进行。Android 的构建与实现说明见 [Android 文档](https://github.com/vMarkEvanv/campo-reader/blob/android/first-preview/android/README.md)。

### 网页版

需要 Python 3.10 或以上，推荐 Python 3.12。在项目目录执行：

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-web.txt
.venv/bin/python -m playwright install --only-shell chromium
.venv/bin/python web.py
```

浏览器打开 `http://127.0.0.1:8090/`，添加账号后登录并同步。

默认数据目录为 `~/.local/share/campo-reader-web`，可通过 `--data-dir` 修改。服务默认只监听本机，适用于单人使用，没有多用户登录机制。需要远程访问时，应配置访问控制和 HTTPS 反向代理，并通过 `--allowed-host` 指定允许的代理 Host。

## 手动课表

在课表中选择「添加课程」，可添加单节或按周重复的课程，指定多个星期、间隔和截止日期。点击课次可只调整/取消这一节，也可编辑整组；「手动课程」管理全部个人安排。手动课程不影响学校报名与学分统计，同步不会覆盖。

## 同步、数据与更新

- 同步成功的项目会先显示，其他项目继续处理；后续项目失败时保留已更新的数据。
- Study Planner 的自动学分以可靠匹配为准，未知或冲突项保留待确认状态；手动设置的学分优先。
- 账号密码默认不保存；勾选记住后，仅在成功同步后加密保存。也可更换或清除已保存的凭证。
- 应用关闭后暂停自动同步；已获取的数据可离线查看。
- Windows 数据目录为 `%LOCALAPPDATA%\CampoReader`，升级及默认卸载操作保留数据。Android 卸载或清除应用数据会删除账号、缓存和密钥。
- Windows 和 Android 均从 GitHub Releases 检查更新，使用各自的安装包。发现新版后可选择稍后更新，下载与安装需要用户确认；覆盖安装保留现有数据。

## 实现方式

网页、Windows 和 Android 复用 HTML/CSS/JavaScript 界面及 Python 业务逻辑，通过 HTTP API 交换数据。

| 部分 | 实现 |
| --- | --- |
| 数据引擎 | `campo_backend/`：获取与解析课表、成绩、报名课程、Study Planner 和 Documents，管理缓存及个人设置 |
| 共享界面 | `public/`：课表、课程管理、学业进度、证明文件及设置界面 |
| HTTP API | `server.py`：共享接口、会话与 CSRF 校验 |
| 网页入口 | `web.py`：浏览器访问与服务启动参数 |
| Windows | `desktop.py`、`desktop_updates.py`：pywebview/WebView2 窗口、原生文件操作与软件更新；Playwright/Chromium 负责读取 Campo |
| Android | Java、Android WebView 与 Chaquopy：在应用内运行 Python，并适配浏览器操作、文件导入导出和安装更新 |
| 构建与发布 | `packaging/`、GitHub Actions：生成安装包、运行测试并发布附件 |

Windows 使用加密凭证存储，Android 使用 AndroidKeyStore。桌面及手机应用的内部 API 仅监听本机，使用启动会话和 CSRF 校验；学校登录页面与应用界面分开处理。

Windows 更新清单使用 Ed25519 签名，安装包下载后校验 SHA-256 和大小。Android 更新校验 SHA-256、包名、版本号及应用签名，再调用系统安装器。

更多说明见 [代码结构与数据流](UPSTREAM.md)、[Windows 使用说明](packaging/USER_GUIDE.md)和[第三方组件声明](THIRD_PARTY_NOTICES.md)。

## 开发与验证

Python 依赖见 `requirements*.txt`。运行共享后端测试：

```bash
python -m unittest discover -s tests -q
```

界面回归测试位于 `tests/ui_*.py`，需要 Playwright 和 Chromium。Windows 工作流构建 PyInstaller 应用与 Inno Setup 安装包，验证 WebView2 窗口及覆盖升级。Android 工作流使用 Java 17、Gradle、Android SDK 和 Chaquopy 构建 APK，并运行模拟器测试。

各平台的版本号、构建入口和发布附件分别管理；修改源码不会自动更新已安装的软件。
