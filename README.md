# Campo Reader · Windows 独立桌面版

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

使用 `.github/workflows/windows.yml` 在 Windows 2022 / Python 3.12 构建。
依赖固定于 requirements*.txt。PyInstaller 输出目录包，Inno Setup 生成当前用户安装包。
构建执行业务与本地接口测试，并直接运行打包后的 EXE 验证本地 API、内置 Chromium 和 Qt 页面加载。

安装包未进行商业代码签名；Windows 可能显示“未知发布者”。没有关停或绕过系统安全防护。

## 来源

当前网页版模块与 https://github.com/vMarkEvanv/campo-reader 的核心解析代码。构建用私有仓库与源码工作区独立于 Orange Pi 运行目录；不会替换正在运行的服务。
