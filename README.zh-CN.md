# Open Vending

[English](README.md) | **简体中文**

<p align="center"><img src="asset/image/1.png" width="50%"></p>

## 安装

> 第一次安装？请改看 **[INSTALL.zh-CN.md](INSTALL.zh-CN.md)** —— 同样是三步，
> 但写得更细：文件夹放哪里、首次启动要做什么、出错时怎么查。

### 第一步 — 下载

克隆本项目，或从 <https://github.com/liewcc/Open_Vending> 下载 ZIP 后解压。

```bash
git clone https://github.com/liewcc/Open_Vending.git C:\Apps\Open_Vending
```

不要把文件夹放在 OneDrive、Google Drive 或 Dropbox 里 —— 原因见
[DATABASE.md](DATABASE.md)。

### 第二步 — 运行安装程序

双击 **`setup.bat`**。

程序将自动下载并安装所有依赖（Python、Chromium、Node.js、Electron）。需要网络连接，首次运行约需 5–10 分钟。

看到 **"Setup complete! Run run.bat to start."** 即表示安装完成。

### 第三步 — 启动

双击桌面上的 **Open Vending** 快捷方式（由安装程序自动创建）启动应用。

首次启动时，程序会提示输入你的 DVends 账号和密码。凭据会加密存储在本机，不会上传。

> 也可以双击项目目录下的 **`run.vbs`** 启动。`run.bat` 同样可用，但会短暂闪现一个黑色窗口，这是 Windows `.bat` 文件的限制。

---

## 使用说明

启动后，程序会自动从 DVends 下载最新补货报告，并显示在主表格中。

### 侧边栏按钮

| 图标 | 按钮 | 功能说明 |
|------|------|----------|
| <img src="asset/button img/table_view.png" width="24"> | **主页** | 返回主补货表格 |
| <img src="asset/button img/cloud_sync.png" width="24"> | **重新下载** | 从 DVends 获取最新报告 |
| <img src="asset/button img/track_changes.png" width="24"> | **变动清单** | 显示上次扫描后补货值有变化的商品 |
| <img src="asset/button img/shopping_basket.png" width="24"> | **拣货清单** | 每日补货计划，按贩卖机分组 — 详见下方[拣货清单](#拣货清单) |
| <img src="asset/button img/settings.png" width="24"> | **设定** | 配置应用选项 |
| <img src="asset/button img/update.png" width="24"> | **更新** | 版本最新时为灰色，检测到新版本时亮起。点击即可更新（详见下方[自动更新](#自动更新)） |

### 设定选项

| 选项 | 说明 |
|------|------|
| 显示菜单栏 | 显示 Electron 应用菜单栏 |
| 显示控制台窗口 | 下载数据时显示 DOS 控制台 |
| 关闭到系统托盘 | 点击 × 最小化到托盘，而不是退出 |
| 补货变动通知 | 扫描后若补货值有变化，发出系统托盘通知 |
| 有头浏览器 | 扫描时使用可见浏览器（按 **F9** 可截取当前页面） |

---

## 拣货清单

从侧边栏点击 <img src="asset/button img/shopping_basket.png" width="16"> **拣货清单** 进入。

### 机器列表（左侧面板）

左侧列出今日需要补货的所有贩卖机。每台机器旁边显示一个填充百分比徽章，表示需要补充的商品数量占机器总货道容量的比例。点击某台机器，主面板会显示该机器的详细品相信息。

### 品相明细（主面板）

主面板列出所选机器的所有货道，包含商品名称、当前库存、货道容量和补货数量。红色高亮行表示该货道已断货。点击任意行可查看该商品的**补货历史**图表。

明细面板上方工具栏有两个按钮：

| 图标 | 功能 |
|------|------|
| <img src="asset/button img/pending_actions.png" width="20"> | 打开**在途队列**弹窗 |
| <img src="asset/button img/picture_as_pdf.png" width="20"> | 将所有排队的拣货清单导出为 PDF |

### 加入队列

点击明细面板右上角的 <img src="asset/button img/check_box.png" width="16"> 将该机器加入队列。图标变为**绿色**即表示已加入。点击左侧的 <img src="asset/button img/home.png" width="16"> 可返回机器列表。

### 在途队列弹窗

点击工具栏中的 <img src="asset/button img/pending_actions.png" width="16"> 打开队列弹窗。每台机器显示总单位数和货道数。可执行以下操作：

| 图标 | 功能 |
|------|------|
| <img src="asset/button img/edit.png" width="16"> | 以**编辑模式**打开该机器 |
| <img src="asset/button img/delete.png" width="16"> | 将该机器从队列中移除 |
| <img src="asset/button img/refresh.png" width="16"> | 将所有排队条目刷新至最新报告数据 |
| <img src="asset/button img/delete_forever.png" width="16"> | 清空整个队列 |

### 编辑模式

点击排队机器旁的 <img src="asset/button img/edit.png" width="16"> 以编辑模式打开。明细面板顶部出现 **"Edit mode"** 横幅，所有表格单元格变为可编辑状态。输入后自动保存，数据存储在 `db/` 文件夹中，不影响原始报告。点击右上角的 <img src="asset/button img/save.png" width="16"> 退出编辑模式。

---

## 数据库

所有数据以 SQLite 格式存放在 `db/` 目录下。如果你要直接查看或修改数据，
或者让 AI 助手（例如 Claude Code）来处理数据，请先阅读
**[DATABASE.md](DATABASE.md)**。文档说明了每个表的用途、在 app 运行时如何
安全查询，以及几条从 schema 看不出来的规则：拣货端与销售端的机器名称不同、
product ID 是按账号区分的、以及 `vending.db` 绝对不能用 Drive 或 Dropbox 同步。

---

## 自动更新

每次启动时，程序会自动检查远端 `package.json` 是否有新版本。侧边栏的 <img src="asset/button img/update.png" width="16"> 图标在版本最新时为灰色，检测到新版本时会亮起。

点击图标即可开始更新：

1. 程序下载最新版本的 zip 文件。
2. 在后台启动一个 PowerShell 脚本，随后程序退出。
3. 脚本等待程序完全关闭后，解压 zip 并覆盖更新的文件（保留 `node_modules/`、`python/`、`db/` 等本地数据）。
4. 程序通过 `run.vbs` 自动重新启动。
