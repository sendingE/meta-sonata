# meta-sonata

[![Tests](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml/badge.svg)](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml)
[![macOS App](https://img.shields.io/github/v/release/sendingE/meta-sonata?label=macOS%20app)](https://github.com/sendingE/meta-sonata/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/meta-sonata)](https://pypi.org/project/meta-sonata/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-2f6f73)](https://github.com/sendingE/meta-sonata/blob/main/LICENSE)

[English](https://github.com/sendingE/meta-sonata) | **简体中文**

Meta Sonata 是一个本地优先的音乐元数据工作台。它既有可直接使用的独立 macOS
App，也有适合批处理和自动化的 CLI；补全标签、封面和同步歌词的同时，原始音乐和
长期身份数据始终由你掌控。

## 两个核心优势

### 真正独立的 macOS App

拖入一首歌，检查补全结果，再把处理后的副本拖回 Finder。原文件始终不变。同一个
App 还可以打开本地音乐文件夹，以只读方式浏览标签、封面、音频参数、来源 ID 和
完整歌词。

应用自带完整后端，不要求用户安装 Python、打开终端或另外启动 Web 服务。当前支持
英语、简体中文、繁体中文、日语、韩语、法语、德语、西班牙语和巴西葡萄牙语。

### 不是一堆旁路文件，而是分层的本地数据结构

Meta Sonata 不会把所有信息都硬塞进音乐文件，也不会让一个数据库成为唯一真相。
不同生命周期的数据分开保存：

| 层级 | 保存什么 | 生命周期 |
| --- | --- | --- |
| 音乐文件 | 可携带标签、MusicBrainz ID、封面和歌词 | 跟随音乐移动 |
| 本地目录库 | 音乐库根目录、相对路径、实体、外部 ID、别名和确认记录 | 用户级长期数据；可从文件重建 |
| 第三方缓存 | MusicBrainz 等服务的响应 | 可随时删除 |

这套结构既能支撑更大的音乐库和后续人工确认，又不会把用户锁死在数据库中。目录库
损坏、缓存被删除或第三方接口失败时，本地浏览和文件处理仍能继续。

## 获取 macOS App

[下载最新版 Apple 芯片 DMG](https://github.com/sendingE/meta-sonata/releases/latest)。

当前 DMG 使用 ad-hoc 签名，尚未经过 Apple 公证；首次启动时可能需要按住 Control
点击应用并选择“打开”。应用严格遵循副本补全：输出是新文件，原文件保持不变。

也可以在本地构建 `.app` 和 `.dmg`：

```bash
./scripts/build_macos_release.sh
```

需要公证分发时，通过 `MACOS_SIGN_IDENTITY` 指定 Developer ID，并继续完成 Apple
公证流程。

## CLI 快速开始

```bash
pipx install meta-sonata
```

也可以使用 `uv` 安装：

```bash
uv tool install meta-sonata
```

查询并预览 Meta Sonata 找到的元数据，不会写入文件：

```bash
meta-sonata enrich "/音乐/待处理专辑"
```

一键抓取并写入元数据、封面和歌词：

```bash
meta-sonata enrich "/音乐/待处理专辑" --write
```

两个命令都可以处理单张专辑或更大的音乐目录。Meta Sonata 优先相信已有标签、
文件名和目录结构，再使用在线数据源补全缺失信息。

![meta-sonata CLI 预演与写入流程](https://raw.githubusercontent.com/sendingE/meta-sonata/main/docs/assets/cli-demo.gif)

## 为什么用 Meta Sonata？

- **本地优先：** 已有标签、目录名和曲目结构是匹配锚点。
- **保护原文件：** macOS App 只补全副本；CLI 必须显式允许才会写入。
- **保守写入：** 检查曲目数、时长、现场/录音室冲突和候选歧义。
- **一次补全：** 元数据、封面和同步歌词使用一个命令处理。
- **失败可降级：** 单个数据源失败只产生警告，本地处理和其他来源继续工作。
- **适合自动化：** 支持预演、外部增量状态、递归发现和 JSON 审计计划。

典型输出：

```text
scan: root=/音乐/待处理专辑 files=12 album_groups=1 loose_tracks=0 max_depth=3
resolve: 1/1 /音乐/待处理专辑
lyrics: 1/1 /音乐/待处理专辑
dry run: 1 plan(s)
- album: 歌手 / 专辑: artist=歌手  album=专辑  year=2006  tracks=12  confidence=0.96  lyrics=11/12
nothing written; pass --write to apply
```

`enrich` 默认启用元数据、封面和歌词抓取，并向下发现三层目录。可以使用
`--max-depth N` 指定深度，或使用 `--recursive` 无限递归。

## 能补全什么？

| 类别 | 字段 |
| --- | --- |
| 歌曲身份 | 标题、歌手、专辑歌手、专辑、曲目号、碟号 |
| 发行信息 | 日期、厂牌、目录编号、条码、发行类型 |
| 来源信息 | MusicBrainz 艺术家、录音、发行版、发行组和发行曲目 ID；数据来源标签 |
| 媒体内容 | 内嵌封面、同步 LRC、普通歌词 |

专辑元数据来源：**MusicBrainz**、**iTunes**、**网易云音乐**。

歌词来源：**QQ 音乐**、**网易云音乐**、**酷狗**、**酷我**、**咪咕**。

```bash
meta-sonata sources
```

## 接入自动化流程

建议放在下载、解压、CUE 分轨之后，最终同步到音乐库之前：

```bash
meta-sonata enrich "/staging/new-music" \
  --changed-only \
  --state-dir "/var/lib/meta-sonata" \
  --write
```

增量状态保存在音乐目录之外，不会在专辑中留下标记文件。

## 可选的 metadata 浏览器

```bash
meta-sonata web "/音乐" --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/`，可以浏览音频文件、核心标签、来源 ID、
音频参数、封面和内嵌歌词。Web 界面只读，没有写入接口。

![meta-sonata 只读 metadata 浏览器](https://raw.githubusercontent.com/sendingE/meta-sonata/main/docs/assets/web-ui.png)

_截图使用 Nine Inch Nails《The Slip》的 CC 授权音频与封面，详见[素材署名](https://github.com/sendingE/meta-sonata/blob/main/docs/assets/ATTRIBUTION.md)。_

## 存储位置与故障降级

音乐文件中的标签仍是可携带的主数据。图形版会在后台建立一个可重建的本机目录，
用于跨文件夹检索、记录匹配结果和以后扩展人工确认；第三方接口响应则放在独立的
可丢弃缓存中：

- 长期目录：`~/Library/Application Support/com.sendinge.meta-sonata/catalog.sqlite3`
- API 缓存：`~/Library/Caches/com.sendinge.meta-sonata/provider-cache.sqlite3`

删除 API 缓存不会影响音乐或目录数据；目录损坏或不可写也不会阻塞文件浏览和补全。
MusicBrainz 的真实网络请求在命令行、图形版和测试路径中统一限制为每秒最多一次。
所有第三方接口失败都会降级为警告并继续处理本地文件或其他数据源。

## 安全设计

- 没有 `--write` 时，所有写入命令都只做预演。
- 低可信歌词和存在歧义的发行版身份会被跳过。
- 混杂散歌不会被强行归入一个虚假专辑。
- 可通过 `META_SONATA_PROTECTED_PATHS` 保护真实音乐库。
- 测试只生成静音 FLAC，仓库不包含受版权保护的媒体文件。

## 更多文档

- [完整使用手册（英文）](https://github.com/sendingE/meta-sonata/blob/main/docs/guide.md)
- [版本记录](https://github.com/sendingE/meta-sonata/blob/main/CHANGELOG.md)
- [公开测试素材规范](https://github.com/sendingE/meta-sonata/blob/main/tests/README.md)
- [MIT License](https://github.com/sendingE/meta-sonata/blob/main/LICENSE)

支持 Python 3.9+。当前属于早期 `0.2.x` 版本，非官方数据接口可能发生变化
或受到限流。
