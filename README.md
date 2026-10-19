# 时光修复师 (TimeKeeper)

<p align="center">
  <img src="ICON_256.PNG" width="128" height="128" alt="TimeKeeper Logo" />
</p>

<p align="center">
  <b>专为飞牛私有云 (fnOS) 打造的高性能照片与视频时间批量智能校准工具</b>
</p>

<p align="center">
  <a href="https://github.com/xuechao188/TimeKeeper/releases"><img src="https://img.shields.io/badge/version-v1.4.2-blue.svg" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
  <a href="https://www.fnnas.com/"><img src="https://img.shields.io/badge/platform-fnOS-orange.svg" alt="Platform"></a>
  <a href="https://github.com/xuechao188"><img src="https://img.shields.io/badge/maintainer-xuechao-purple.svg" alt="Maintainer"></a>
</p>

---

## 📖 项目简介 (Overview)

在日常使用手机、相机或通过微信、QQ 等通讯软件传输照片视频时，多媒体文件的拍摄时间（EXIF DateTimeOriginal）及文件系统属性（创建时间/修改时间）经常会遭到篡改或丢失（例如全部变成了导入 NAS 当天的时间），导致在 **飞牛相册 (fnOS Photos)** 或其它相册工具中**时间线严重错乱**、回忆无法按正确的岁月顺序呈现。

**时光修复师 (TimeKeeper)** 是专为飞牛私有云 NAS 开发的原生系统应用。依托高性能纯内存规则引擎、并发事务队列与 ExifTool 深度挖掘技术，能够从**文件名、目录层级、原生元数据、照片水印**等多种维度，智能还原照片与视频的真实历史时间，彻底治愈 NAS 相册时间线混乱！

---

## ✨ 核心特性 (Features)

- ⚡ **极速增量扫描引擎**：
  - 纯内存级正则与目录层级识别，6 万+ 多媒体文件可在秒级完成索引检索；
  - 智能增量跳过历史已成功修复文件（$O(1)$ 毫秒级直接过滤），零重复 IO 开销。
- 🎯 **业界最全的文件名时间解析规则库**：
  - **标准分隔符格式**：`IMG_20230815_143025.jpg`、`2023-08-15 14.30.25.jpg`、`Screenshot_2023-08-15-14-30-25.png`；
  - **14位/12位连续纯数字**：`20210515123045.jpg`、`202105151230.jpg`；
  - **8位日期 + 序号/后缀**：`20080321334.jpg`、`20080321_01.jpg`、`20080321(1).jpg`；
  - **主流品牌相机毫秒命名**：Google Pixel 等 `PXL_20230815_143025123.jpg`；
  - **社交应用导出时间戳**：微信 `mmexport1692085825000.jpg`（13位毫秒戳 / 10位秒戳）；
  - **中文年月日格式**：`2008年03月21日_聚会.jpg`。
- 📁 **父文件夹年月继承 (按目录归档)**：
  - 针对文件名无时间、无 Exif 的文件，自动向上扫描上级文件夹（如 `/照片/2015年12月/IMG_4270.JPG`），智能继承目录年月（如 `2015-12-01 12:00:00`）。
- 🖼️ **图片缩略图悬停与大图灯箱预览**：
  - 鼠标悬停文件名即时显示 220px 缩略图浮窗，并具备智能防屏幕边缘遮挡翻转；
  - 点击文件名弹出居中高清大图查看窗口（支持在新标签页打开、查看路径与拍摄时间、ESC快捷关闭）。
- ✏️ **手动单文件修改与多选批量递增指定时间**：
  - 支持对特殊无法解析的文件进行手动指定拍摄时间，或勾选多个文件批量递增间隔时间（如每张顺延 1 秒），保存后一键转入待修复队列。
- 🔤 **照片水印日期文字识别 (OCR)**：
  - 内置极智轻量级水印时间识别引擎，自动局部定点裁剪高发区识别日期水印，速度快、资源省。
- 🔍 **深度原生 Exif 挖掘**：
  - 对于文件名不含时间、无规则命名的相机原图，深度回退到文件内部提取原生 Exif/QuickTime 拍摄时间；
- 🛠️ **全维度时间同步**：
  - 同时修正文件系统属性（`CreationTime` 创建时间、`LastWriteTime` 修改时间）；
  - 同步写入照片与视频内部元数据（`DateTimeOriginal`、`CreateDate`、`ModifyDate`）；
- 🚀 **多线程并发加速**：
  - 支持动态配置 1~16 线程并发处理，充分利用 NAS 多核性能；
- 📊 **现代化响应式 WebUI**：
  - 飞牛原生设计语言，单行卡片实时展现待处理、成功、跳过、失败、**预计剩余时间与预计完成时间**；
  - 内置分页、文件名即时检索与状态筛选，支持目录列快速一键过滤；
  - 完美适配 PC 大屏与手机端窄屏触控操作（表格支持左右平滑滑动）；
  - 提供规则沙盒即时测试与实时控制台日志。
- 🛡️ **安全模拟 (Dry-Run)**：
  - 正式修改前支持一键“空跑模拟”，直观预览拟同步的时间点，确保数据安全无忧。

---

## 📸 界面预览 (Screenshots)

<p align="center">
  <img src="ICON.PNG" width="96" height="96" alt="Icon" />
</p>

*控制台操作面板（包含目录选择、指标统计卡片、实时进度与文件状态清单列表）*

---

## 🚀 安装与使用指南 (Installation)

### 1. 手动安装 (推荐)
1. 从本项目 [Releases](https://github.com/xuechao188/TimeKeeper/releases) 页面下载最新的安装包 `TimeKeeper.fpk`。
2. 登录您的飞牛私有云桌面 (fnOS)。
3. 打开 **应用中心 (App Center)** -> 点击右下角 **手动安装**。
4. 选择并上传已下载的 `TimeKeeper.fpk`，点击安装即可。

### 2. 使用步骤
1. 打开 **时光修复师** 应用。
2. 点击 **选择目录**，在弹窗中选择需要修复的照片或视频文件夹（支持各存储池路径）。
3. 点击 **全量扫描文件**，系统将在数秒内完成全部文件的时间检索与识别。
4. （可选）点击 **空跑模拟 (Dry-Run)**，在文件状态清单中预览匹配出的时间结果。
5. 点击 **执行修复**，系统将启动多线程并发修复，实时展示处理速度与预计剩余时间。
6. 修复完成后，回到飞牛相册中，照片即可按照正确的年月历史顺序排列呈现！

---

## 🏗️ 架构与技术栈 (Architecture)

```text
TimeKeeper/
├── app/
│   ├── backend/             # 后端服务 (Python 3.10+)
│   │   ├── server.py        # 极速轻量 HTTP 服务、并发线程池与任务状态机
│   │   ├── parser.py        # 纯内存级正则时间提取引擎与目录层级解析
│   │   ├── exif_writer.py   # ExifTool 适配器与文件系统时间戳修正器
│   │   └── db.py            # SQLite WAL 模式断点续传数据库
│   └── ui/                  # 前端 WebUI
│       └── index.html       # 原生飞牛风格响应式单页应用
├── cmd/                     # 应用生命周期钩子 (install/uninstall/upgrade/control)
├── wizard/                  # 安装引导配置
├── manifest                 # 飞牛应用安装包元数据描述
└── ICON_256.PNG             # 应用高清图标
```

- **后端**：Python 3、SQLite3 (WAL 并发模式)、ExifTool (Phil Harvey)
- **前端**：原生 HTML5 + CSS3 + JavaScript，零第三方重量级前端框架依赖，极低内存占用与秒级加载。
- **打包工具**：`fnpack`（飞牛官方应用打包工具）。

---

## 🛠️ 本地构建 (Building from Source)

若您希望自行编译打包 `.fpk`：

1. 克隆代码库：
   ```bash
   git clone https://github.com/xuechao188/TimeKeeper.git
   cd TimeKeeper
   ```
2. 使用飞牛官方打包工具 `fnpack` 进行打包：
   ```bash
   fnpack build --directory .
   ```
   打包完成后将在根目录下生成 `TimeKeeper.fpk`。

---

## 🙏 致谢与参考项目 (Acknowledgements & References)

本项目在研发过程中参考或直接使用了以下优秀开源项目与技术体系，特此鸣谢：

1. **[PhotoTimeFix](https://github.com/Cryolitia/PhotoTimeFix)** (by [@Cryolitia](https://github.com/Cryolitia))
   - 感谢 Cryolitia 开源的 PhotoTimeFix。本项目在设计之初深刻借鉴了其“通过文件名正则提取时间并同步回相片 EXIF/文件属性”的核心理念，并在此基础上为 Linux NAS 环境重写了多线程并发架构、增量引擎与 Web 交互界面。
2. **[ExifTool](https://exiftool.org/)** (by Phil Harvey)
   - 强大的开源多媒体元数据处理工具，本项目底层依赖 ExifTool 进行照片 EXIF 及视频 QuickTime 元数据的精准读取与写入。
3. **[fnOS (飞牛私有云)](https://www.fnnas.com/)** & **[fnpack](https://github.com/fnpack)**
   - 感谢飞牛团队提供的开放、优秀的 NAS 操作系统与应用分发打包体系。

---

## 📄 开源许可证 (License)

本项目采用 [MIT 许可证](LICENSE) 开源。欢迎 Star、Fork 和提交 Issue / PR 交流贡献！
