# 文件同步工具集

纯 Python 标准库实现的文件同步工具，无需第三方依赖。

## 功能概述

本项目包含两个独立的同步工具：

| 工具 | 功能 | 适用场景 |
|------|------|----------|
| [sync_url_file.py](#sync_url_filepy) | 同步远程 URL 文件到本地 | 同步配置文件、静态资源等 |
| [sync_repo_archive.py](#sync_repo_archivepy) | 同步 Git 仓库 Archive 并自动解压 | 同步开源项目、依赖库源码等 |

---

## sync_url_file.py

检测远程文件是否有更新，有更新时自动下载到本地。支持通过 ETag、Last-Modified 或文件哈希来判断文件是否更新。

### 使用方法

#### 命令行方式

```bash
# 同步单个文件
python sync_url_file.py -n "配置文件" -u https://example.com/config.json -o ./config.json

# 同步 GitHub raw 文件
python sync_url_file.py -n "README" -u https://raw.githubusercontent.com/user/repo/main/README.md -o ./README.md

# 使用配置文件批量同步
python sync_url_file.py -c config.json
```

#### 配置文件方式

创建 `config.json`：

```json
[
  {
    "name": "VSCode README",
    "url": "https://raw.githubusercontent.com/microsoft/vscode/main/README.md",
    "filename": "./downloads/vscode-readme.md"
  },
  {
    "name": "Git-osc README",
    "url": "https://gitee.com/oschina/git-osc/raw/master/README.md",
    "filename": "./downloads/gitee-readme.md"
  }
]
```

执行同步：

```bash
python sync_url_file.py -c config.json
```

### 参数说明

| 参数 | 简写 | 说明 |
|------|------|------|
| `--name` | `-n` | 文件别名（用于显示） |
| `--url` | `-u` | 文件 URL |
| `--output` | `-o` | 本地保存路径 |
| `--config` | `-c` | 配置文件路径（JSON 格式） |

### 更新检测机制

工具按以下优先级检测文件更新：

1. **ETag** - 如果服务器提供 ETag 头，比较 ETag 值
2. **Last-Modified** - 如果服务器提供 Last-Modified 头，比较修改时间
3. **文件哈希** - 计算文件的 SHA256 哈希值进行比较

---

## sync_repo_archive.py

检测 GitHub/Gitee/GitLab/Gitea 等仓库是否有更新，有更新时自动下载 archive 并解压。

### 支持的平台

- **GitHub** - `https://github.com/owner/repo`
- **Gitee** - `https://gitee.com/owner/repo`
- **GitLab** - `https://gitlab.com/owner/repo`
- **Gitea** - 自托管 Gitea 实例

### 使用方法

#### 命令行方式

```bash
# 同步单个仓库（默认分支）
python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode

# 同步指定分支
python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode -r main

# 同步到指定解压路径
python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode -e ./repos/vscode

# 同步 Gitee 仓库
python sync_repo_archive.py -n "git-osc" -u https://gitee.com/oschina/git-osc

# 指定压缩格式
python sync_repo_archive.py -n "repo" -u https://github.com/owner/repo -f zip
```

#### 配置文件方式

创建 `config.json`：

```json
[
  {
    "name": "dnspod-powershell",
    "url": "https://github.com/ztj1993/dnspod-powershell",
    "ref": "main",
    "extract": true,
    "extract_dir": "dnspod-powershell",
    "archive_format": "zip"
  },
  {
    "name": "scoop-lock",
    "url": "https://gitee.com/zhangtianjie/scoop-lock",
    "ref": "master",
    "extract": false,
    "filename": "scoop-lock.zip"
  },
  {
    "name": "Scoop",
    "url": "https://gitlab.com/ScoopInstaller/Scoop",
    "ref": "master",
    "extract": false
  }
]
```

执行同步：

```bash
python sync_repo_archive.py -c config.json
```

### 参数说明

| 参数 | 简写 | 说明 |
|------|------|------|
| `--name` | `-n` | 仓库别名（用于显示） |
| `--url` | `-u` | 仓库 URL |
| `--ref` | `-r` | 分支/标签/Commit（可选，默认 HEAD） |
| `--extract` | `-e` | 解压目录名称（可选，默认使用仓库名） |
| `--format` | `-f` | 压缩格式（可选，zip 或 tar.gz） |
| `--config` | `-c` | 配置文件路径（JSON 格式） |

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `name` | string | 必填 | 仓库别名 |
| `url` | string | 必填 | 仓库 URL |
| `ref` | string | HEAD | 分支、标签或 Commit |
| `extract` | boolean | true | 是否解压 archive |
| `extract_dir` | string | 仓库名 | 解压目录名称 |
| `filename` | string | 自动生成 | 下载的 archive 文件名 |
| `archive_format` | string | 自动选择 | 压缩格式（zip/tar.gz） |
| `api_base` | string | 自动推断 | Gitea 实例的 API 基础 URL |

---

## 状态存储

两个工具都会将同步状态存储在系统临时目录中：

- **sync_url_file**: `%TEMP%/sync_url_file/state/`
- **sync_repo_archive**: `%TEMP%/sync_repo_archive/state/`

状态文件用于记录上次同步的 ETag、Last-Modified、文件哈希等信息，以便下次同步时判断文件是否有更新。

---

## 测试

项目包含完整的单元测试：

```bash
# 运行所有测试
python -m pytest tests/

# 运行指定测试文件
python -m pytest tests/test_sync_url_file.py
python -m pytest tests/test_sync_repo_archive.py
```

---

## 环境要求

- Python 3.6+
- 纯标准库实现，无需安装第三方依赖

---

## 许可证

MIT License
