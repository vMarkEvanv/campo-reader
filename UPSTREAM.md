# 代码结构与数据流

## 数据获取

`campo_backend/campo_source/` 负责登录状态识别和 Campo 页面解析。课表按日历数据解析，成绩、报名课程、Study Planner 及 Documents 通过各自的只读采集流程获取。

`campo_backend/campo.py` 负责账号、同步任务、持久化和接口所需的数据快照。业务模块处理课程关联、分类、学分统计和证明文件管理。课程关联与学分匹配使用确定性规则，不依赖 AI。

同步结果按项目合并到最新快照，保留其他项目及个人设置。每次成功提交更新数据版本，前端只在结果变化或任务结束时获取完整快照；运行中的任务使用轻量状态查询。

## 界面与平台入口

- `public/` 提供共用的 HTML、CSS 和 JavaScript 界面。
- `server.py` 提供账号、同步、课程、学分和文件等 HTTP API。
- `web.py` 启动单人网页版服务。
- `desktop.py` 与 `desktop_updates.py` 提供 Windows 窗口和更新操作。
- Android 使用 WebView 显示共用界面，Chaquopy 运行 Python，通过适配层执行 Campo 页面操作。

Windows 使用 Playwright/Chromium 读取学校页面。Android 使用独立 WebView，应用原生接口不暴露给学校页面。

## 数据与发布

账号、会话、分类及 PDF 由各平台分别管理。凭证加密后保存，安装包不携带用户数据。平台间复用代码不代表自动同步数据。

GitHub Actions 运行后端、界面和平台测试，生成发布附件。Windows 和 Android 使用独立版本及更新包，更新来源均为 GitHub Releases。
