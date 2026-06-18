# Open Vending

[English](README.md) | **简体中文**

![Open Vending](asset/image/1.png)

DVends 补货报告自动化工具。

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

程序启动后会自动下载最新的补货报告，并在主面板中显示。

点击侧边栏中的 **Re-download** 可重新下载刷新数据。

## 目录结构

```
Open_Vending/
├── src/              UI 源文件（Electron）
├── open_vending.py   下载自动化脚本
├── setup.bat         首次安装程序
├── run.bat           启动程序
└── requirements.txt  Python 依赖
```
