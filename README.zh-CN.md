# meta-sonata

[![Tests](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml/badge.svg)](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-2f6f73)](LICENSE)

[English](README.md) | **简体中文**

自动抓取并补全音乐文件的元数据、封面和同步歌词。先预览改动，再用一个命令
批量写入。

![meta-sonata 只读元数据浏览器](docs/assets/web-ui.png)

_截图使用生成的静音 FLAC 演示文件及公版作品元数据。_

## 为什么用 meta-sonata？

- **本地优先：** 已有标签、目录名和曲目结构是匹配锚点。
- **保守写入：** 检查曲目数、时长、现场/录音室冲突和候选歧义。
- **一次补全：** 元数据、封面和同步歌词使用一个命令处理。
- **适合自动化：** 支持预演、外部增量状态、递归发现和 JSON 审计计划。
- **方便核验：** 使用本地只读 Web 界面检查文件及内嵌标签。

## 快速开始

```bash
git clone https://github.com/sendingE/meta-sonata.git
cd meta-sonata
python3 -m pip install -e .
```

先预演，不写文件：

```bash
meta-sonata enrich "/音乐/待处理专辑"
```

典型输出：

```text
scan: root=/音乐/待处理专辑 files=12 album_groups=1 loose_tracks=0 max_depth=3
resolve: 1/1 /音乐/待处理专辑
lyrics: 1/1 /音乐/待处理专辑
dry run: 1 plan(s)
- album: 歌手 / 专辑: artist=歌手  album=专辑  year=2006  tracks=12  confidence=0.96  lyrics=11/12
nothing written; pass --write to apply
```

确认后写入：

```bash
meta-sonata enrich "/音乐/待处理专辑" --write
```

`enrich` 默认启用元数据、封面和歌词抓取，并向下发现三层目录。可以使用
`--max-depth N` 指定深度，或使用 `--recursive` 无限递归。

## 能补全什么？

| 类别 | 字段 |
| --- | --- |
| 歌曲身份 | 标题、歌手、专辑歌手、专辑、曲目号、碟号 |
| 发行信息 | 日期、厂牌、目录编号、条码、发行类型 |
| 来源信息 | MusicBrainz 发行版/曲目 ID、数据来源标签 |
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

## 检查处理结果

```bash
meta-sonata web "/音乐" --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/`，可以浏览音频文件、核心标签、来源 ID、
音频参数、封面和内嵌歌词。Web 界面只读，没有写入接口。

## 安全设计

- 没有 `--write` 时，所有写入命令都只做预演。
- 低可信歌词和存在歧义的发行版身份会被跳过。
- 混杂散歌不会被强行归入一个虚假专辑。
- 可通过 `META_SONATA_PROTECTED_PATHS` 保护真实音乐库。
- 测试只生成静音 FLAC，仓库不包含受版权保护的媒体文件。

## 更多文档

- [完整使用手册（英文）](docs/guide.md)
- [公开测试素材规范](tests/README.md)
- [MIT License](LICENSE)

支持 Python 3.9+。当前属于早期 `0.1.x` 版本，非官方数据接口可能发生变化
或受到限流。
