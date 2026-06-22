# Open Vending

[English](README.md) | **简体中文**

<p align="center"><img src="asset/image/1.png" width="50%"></p>

## 安装

### 第一步 — 下载

将本项目下载或克隆到你的电脑。

### 第二步 — 运行安装程序

双击 **`setup.bat`**。

程序将自动下载并安装所有依赖（Python、Chromium、Node.js、Electron）。需要网络连接，首次运行约需 5–10 分钟。

看到 **"Setup complete! Run run.bat to start."** 即表示安装完成。

### 第三步 — 启动

双击 **`run.vbs`** 启动应用，不会出现控制台窗口。

首次启动时，程序会提示输入你的 DVends 账号和密码。凭据会加密存储在本机，不会上传。

> 也可以双击 `run.bat` 启动，但会短暂闪现一个黑色窗口，这是 Windows `.bat` 文件的限制。

---

## 使用说明

启动后，程序会自动从 DVends 下载最新补货报告，并显示在主表格中。

### 侧边栏按钮

| 图标 | 按钮 | 功能说明 |
|------|------|----------|
| <img src="asset/button img/table_view.png" width="24"> | **主页** | 返回主补货表格 |
| <img src="asset/button img/cloud_sync.png" width="24"> | **重新下载** | 从 DVends 获取最新报告 |
| <img src="asset/button img/track_changes.png" width="24"> | **变动清单** | 显示上次扫描后补货值有变化的商品 |
| <img src="asset/button img/shopping_basket.png" width="24"> | **拣货清单** | 显示需要补货的商品，点击任意行可查看该商品的补货历史图表 |
| <img src="asset/button img/settings.png" width="24"> | **设定** | 配置应用选项 |
| <img src="asset/button img/update.png" width="24"> | **检查更新** | 下载并应用最新版本 |

### 设定选项

| 选项 | 说明 |
|------|------|
| 显示菜单栏 | 显示 Electron 应用菜单栏 |
| 显示控制台窗口 | 下载数据时显示 DOS 控制台 |
| 关闭到系统托盘 | 点击 × 最小化到托盘，而不是退出 |
| 补货变动通知 | 扫描后若补货值有变化，发出系统托盘通知 |
| 有头浏览器 | 扫描时使用可见浏览器（按 **F9** 可截取当前页面） |
