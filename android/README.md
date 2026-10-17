# Campo Reader · Android 本地测试版

Android 8.0+，支持 arm64-v8a（包括小米 15T）及 x86_64。界面、Python 数据引擎与缓存随 APK 本地运行；直接连接 FAU 官方 HTTPS，不依赖个人服务器或 Tailscale。并非 FAU 官方应用。

## 安装与使用

1. 从本仓库 Android Release 下载签名 APK，按系统提示允许下载来源安装应用。
2. 打开后点“＋”添加本地账号，再“登录并同步”。账号密码默认不保存，可自行勾选记住。
3. 课表按天浏览，可切换周；底部进入课程、成绩、学业进度、证明文件夹。
4. PDF 支持系统文件选择器导入；本机归档可选择预览或保存到文件。
5. 缓存数据可离线查看。新同步需要手机联网并能连接 Campo。自动同步仅在应用前台运行时进行；系统杀进程、退出或后台不承诺定时执行。

凭证通过 AndroidKeyStore 的不可导出 AES-GCM 密钥加密；数据库在应用私有目录；禁用系统云备份。不导入服务器或其他设备的账号。首次安装为空数据，需要自己登录。卸载或清除应用数据会删除账号、缓存和密钥，请提前导出重要证明。学校账号不会被删除。后续同签名更新 APK 保留本机数据。

## 构建

Java 17、Python 3.11、Gradle 8.11.1、Android SDK 35：

```sh
gradle -p android assembleDebug
gradle -p android connectedDebugAndroidTest
```

发布签名由 `ANDROID_KEYSTORE_PATH` 与 `ANDROID_KEYSTORE_PASSWORD` 环境变量提供。签名密钥不在仓库内。GitHub Actions 在 Android 模拟器通过检查后发布独立 Android 预发行，不改 Windows 稳定更新源。当前版本 0.1.4 / versionCode 5。

## 架构与限制

- `campo_backend/`、`server.py` 和 `public/` 是网页/Windows/Android 共用代码；Android 构建时只复制源文件和明确列出的静态文件，不包含任何生产数据、凭证或 BLOG 功能。
- Chaquopy 运行本地 Python；只监听手机 `127.0.0.1` 随机端口，随机 HttpOnly cookie 和 CSRF 保护接口。不对局域网开放端口。
- `android_browser.py` 为现有只读 Campo 解析器提供窄浏览器适配；官方站点运行在独立 WebView，无 JavaScript 原生接口。逐请求限制 FAU HTTPS，证书错误停止。
- App UI 独立 WebView 仅能加载本机打包页面，官方链接交给外部浏览器；本机 PDF 通过系统保存对话框 / 私有 FileProvider 导出，无全盘存储权限。
- 当前仅实现已有登录流程。验证码或学校额外验证会明确停止，不绕过验证。Campo 改版或个别设备 WebView 差异可能需要适配，请报告错误提示；不要发送密码。
- 模拟器覆盖启动、真实 Python 运行、离线本地账号/分类、密钥加密和浏览器适配；不能替代真实 FAU 账号端到端核验，小米真机由用户测试。

## 应用更新

启动时后台检查 GitHub 的 Android Releases，发现新版本时提示，选择“暂不更新”即可继续使用。“检查更新”按钮和“关于”窗口均可手动检查。下载后校验 SHA-256、包名、版本及安装签名，再调用系统安装器；不会强制安装或上传学校账号。首次需要在系统设置中允许此应用安装更新。GitHub 不可达时自动检查静默失败，可稍后手动重试。Windows Releases 不会被识别为 Android 更新。
