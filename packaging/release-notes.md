独立 Windows x64 桌面版，保留当前 Campo Reader 的界面和业务逻辑。

推荐下载 `CampoReader-Setup-Windows-x64.exe` 安装，之后双击桌面图标启动。
免安装版请解压整个 ZIP，再运行其中的 `CampoReader.exe`。

包含课表、成绩、变化中心、全部学期课程管理、批量分类、自动关联、学分统计与 Documents 归档。
内置桌面引擎、Python 和同步浏览器，不需要命令行或另外安装 Python。
首次使用需要添加 FAU 账号并登录。数据保存在本机 `%LOCALAPPDATA%\CampoReader`，不与 Orange Pi 版本自动同步；Orange Pi 版本继续保留。
关闭桌面程序时本机自动同步停止，重新打开可继续使用缓存。

已通过 Windows 回归测试及打包后 EXE 的本地 API、内置 Chromium 和 Qt 页面加载检查。
`smoke-windows.json` 是真实打包程序的启动检查结果，`SHA256SUMS.txt` 提供下载校验值。

该版本未进行商业代码签名，安装时可能显示未知发布者。
