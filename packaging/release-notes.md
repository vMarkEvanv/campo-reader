Campo Reader 1.2.0 · WebView2 测试版

- Windows 客户端从 Qt/PySide6 迁移到 pywebview + Microsoft WebView2，重点验证下拉菜单黑屏与闪烁问题。
- 本机 Python 后端、账号、学分分类、证明文件及原有更新签名继续保留；不依赖 Orange Pi。
- 更新窗口改为网页弹窗，继续从 GitHub Releases 下载和校验安装包。
- 安装时自动检查 WebView2 Runtime，缺少时通过微软安装程序联网安装。
- 开始菜单提供 compatible rendering 入口，可用软件渲染进一步排查显卡问题。
- 包含网页审阅分支的课程分类、两位小数学分、Study Planner 自动学分、可选加密记住密码和性能优化；移除变化中心。
- 此版本为预发布测试包，不替换 1.1.1 稳定更新源。请重点测试下拉菜单、PDF 保存、文件选择、缩放和休眠恢复。
