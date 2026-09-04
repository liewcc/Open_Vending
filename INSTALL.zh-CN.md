# Open Vending 安装指南（一步一步）

写给第一次在新电脑上安装本程序的人。如果你已经装过一次，看
[README](README.zh-CN.md#安装) 里的三步版本就够了。

---

## 0. 开始之前

| 需要准备 | 说明 |
|---|---|
| **Windows 10 或 11，64 位** | 仅支持 Windows。启动器、安装脚本和加密凭据都依赖 Windows 特有功能，没有 macOS / Linux 版本。 |
| **网络连接** | 安装过程约需下载 500 MB。 |
| **约 2 GB 可用磁盘空间** | 安装完成后约占用 600 MB。 |
| **DVends 账号和密码** | 程序以你的身份登录门户，下载补货报告。 |

你**不需要**先安装 Python、Node.js 或浏览器。安装程序会把它们各自的私有副本
下载到项目文件夹里。不写入系统目录、不需要管理员权限，删除文件夹即等于卸载。

---

## 1. 选择存放位置 —— 这一步很关键

放在一个你自己拥有的普通目录，例如：

```
C:\Apps\Open_Vending
```

**不要放在 OneDrive、Google Drive 或 Dropbox 里。** 如果开启了 OneDrive 备份，
桌面和「文档」文件夹同样属于同步目录 —— 解压前先确认路径里没有 `OneDrive`。
程序的数据存在一个实时读写的 SQLite 数据库中，同步工具在程序运行时复制该文件
会直接损坏数据库。完整说明见 [DATABASE.md](DATABASE.md)。

也不要放在网络驱动器或 U 盘上 —— 程序会从这个文件夹运行自带的 Chromium 和
Electron，需要本地磁盘的速度。

---

## 2. 获取文件

### 方式 A —— Git（推荐）

如果已安装 [Git](https://git-scm.com/download/win)，打开 PowerShell 运行：

```bash
git clone https://github.com/liewcc/Open_Vending.git C:\Apps\Open_Vending
```

以后更新只需一条命令（见[第 6 节](#6-以后如何更新)）。

### 方式 B —— 下载 ZIP

1. 打开 <https://github.com/liewcc/Open_Vending>。
2. 点击绿色 **Code** 按钮，选择 **Download ZIP**。
3. 右键点击下载的 zip，选择**属性**，勾选**解除锁定**，确定。
   Windows 会把来自网络的文件标记为锁定，导致里面的脚本静默失败。
4. 右键点击 zip，选择**全部解压缩**，解压到 `C:\Apps\Open_Vending`。

**检查解压结果。** 文件夹里应该**直接**看到 `setup.bat`、`run.vbs`、
`package.json` 和 `src\` 目录。如果里面只有一个名为 `Open_Vending-main` 的
文件夹，就把那个内层文件夹当作项目目录使用。

---

## 3. 运行安装

双击 **`setup.bat`**，会弹出一个黑色控制台窗口并保持打开。

如果 Windows 提示 *"Windows 已保护你的电脑"*，点击**更多信息**，再点
**仍要运行**。杀毒软件也可能弹窗；脚本只会从 python.org、nodejs.org、
pypi.org 和 Google 字体服务器下载文件。

安装分七步，每一步都会打印进度：

| 步骤 | 下载内容 |
|---|---|
| 1–3 | Python 3.12（嵌入版）、pip，以及 `playwright` + `openpyxl` |
| 4 | Chromium 浏览器 —— 约 150 MB，最慢的一步 |
| 5–6 | Node.js 20 和 Electron + xlsx —— 约 100 MB |
| 7 | Material Symbols 图标字体 |

正常网速约需 **5–10 分钟**。看到下面这段就表示完成：

```
 ============================================
  Setup complete! Run run.bat to start.
 ============================================
```

按任意键关闭窗口。桌面上会出现 **Open Vending** 快捷方式。

**如果中途出现 `[ERROR]`：** 直接重新运行 `setup.bat` 即可。每一步都会跳过
已经下载成功的部分，重跑只会重试失败的那一步。详细错误记录在项目目录下的
`setup.log`。

---

## 4. 首次启动

双击桌面上的 **Open Vending** 快捷方式（或项目目录里的 `run.vbs`，两者等效）。

1. 弹出 **Welcome to Open Vending** 窗口，输入 DVends 账号和密码，点击
   **Save & Connect**。
   凭据使用 Windows DPAPI 加密，保存在
   `%APPDATA%\open-vending\credentials.enc`。该文件与本机的这个 Windows 用户
   绑定，复制到别的电脑无法解密，所以每台电脑都要各自输入一次。
2. 程序随即登录门户，下载当天的补货报告。首次扫描需要几分钟，可以看底部的
   状态栏。
3. 扫描完成后主表格填充数据，项目目录下会生成 `db\vending.db`。

---

## 5. 设置你自己的路线计划

新克隆的仓库自带一份**示例** `db\route_plan.json`，里面是别人的机器，所以在
修改之前拣货清单不会匹配你的账号。首次扫描完成后处理一次即可：

1. 点击左侧边栏的 **route** 图标，打开**路线计划（Route Plan）**。
2. 删除不属于你的机器行。
3. 点击 **Add from report**（*playlist_add* 图标）—— 它会把你自己报告中出现、
   但计划里没有的机器全部加进来。
4. 为每台机器设置团队、日期和模式，然后点击 **Save**。

然后打开**拣货清单**，应该已经列出你自己的机器了。

### 安装完成 —— 快速自检

- [ ] 项目目录下存在 `db\vending.db`
- [ ] 主表格有数据
- [ ] 拣货清单列出的是你自己的机器

---

## 6. 以后如何更新

选一种方式，不要混用：

- **用 Git 克隆的** —— 在项目目录运行 `git pull`，然后再运行一次
  `setup.bat`（没有新依赖时只需几秒）。`db\`、`python\`、`node\`、`browsers\`
  和 `node_modules\` 都不在版本控制内，本地数据不会被动。
- **下载 ZIP 的** —— 使用侧边栏的应用内**更新**按钮。有新版本时图标会亮起，
  点击后自动下载并重启，同时保留 `node_modules\`、`python\` 和 `db\`。

Git 克隆同样可以用应用内更新按钮，但它会覆盖被版本控制跟踪的文件，之后
`git status` 会显示一堆已修改文件。

---

## 7. 出问题时

| 现象 | 处理办法 |
|---|---|
| 双击 `setup.bat` 没反应 | 文件被锁定。右键 → 属性 → **解除锁定**。或在该目录打开 PowerShell 运行 `.\setup.bat`。 |
| `[ERROR] ... download failed` | 网络或代理问题。看 `setup.log` 最后几行，然后重新运行 `setup.bat`。 |
| 弹窗 *"Setup not complete. Please run setup.bat first."* | `setup.bat` 没跑完（通常卡在第 6 步）。重新运行并查看 `setup.log`。 |
| 桌面没有快捷方式 | 不影响使用 —— 直接运行项目目录里的 `run.vbs`。 |
| 程序打开但表格空白，日志显示 *no credentials* | 打开**设定** → **Accounts** 卡片，编辑账号重新输入密码。 |
| 扫描卡在 *"Exporting Excel…"* | 门户导出失败。查看 `log\scan.log` 以及保存下来的页面 `log\export_fail.html` / `.png`，然后点**重新下载**。 |
| 扫描失败但看不出原因 | 在设定里打开**有头浏览器**再跑一次 —— 可以看到程序看到的门户页面，按 **F9** 保存当前页面。 |
| 彻底坏了，想重装 | 删除 `python\`、`node\`、`browsers\` 和 `node_modules\`，重新运行 `setup.bat`。`db\` 里的数据不受影响。 |

值得记住的日志：项目目录下的 `setup.log`（安装过程）和 `log\scan.log`
（每次门户扫描）。

---

## 8. 接下来

- [README](README.zh-CN.md) —— 每个按钮的功能说明
- [DATABASE.md](DATABASE.md) —— 直接操作数据、或让 AI 助手处理这个目录之前
  务必先读
- 多台电脑同时使用？见 [DATABASE.md](DATABASE.md) 第 6 节的共享数据库模式。
