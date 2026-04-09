#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git 仓库 Archive 同步工具
检测 GitHub/Gitee/GitLab/Gitea 等仓库是否有更新，有更新时自动下载 archive 并解压

纯 Python 标准库实现，无需第三方依赖
"""

import os
import sys
import json
import re
import argparse
import tempfile
import ssl
import logging
import zipfile
import tarfile
import shutil
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class RepoInfo:
    """仓库信息解析结果"""
    def __init__(self, platform, owner, repo, ref=None, api_base=None, raw_base=None):
        self.platform = platform      # github/gitee/gitlab/gitea
        self.owner = owner            # 仓库所有者
        self.repo = repo              # 仓库名
        self.ref = ref or 'HEAD'      # 分支/标签/Commit
        self.api_base = api_base      # API 基础 URL
        self.raw_base = raw_base      # Raw 文件基础 URL

    def get_archive_url(self, format='zip'):
        """获取 archive 下载 URL"""
        if self.platform == 'github':
            # https://github.com/{owner}/{repo}/archive/{ref}.{format}
            ref = self.ref if self.ref != 'HEAD' else 'HEAD'
            return f"https://github.com/{self.owner}/{self.repo}/archive/{ref}.{format}"
        elif self.platform == 'gitee':
            # https://gitee.com/{owner}/{repo}/repository/archive/{ref}
            ref = self.ref if self.ref != 'HEAD' else 'master'
            return f"https://gitee.com/{self.owner}/{self.repo}/repository/archive/{ref}"
        elif self.platform == 'gitlab':
            # https://gitlab.com/{owner}/{repo}/-/archive/{ref}/{repo}-{ref}.{format}
            ref = self.ref if self.ref != 'HEAD' else 'master'
            return f"https://gitlab.com/{self.owner}/{self.repo}/-/archive/{ref}/{self.repo}-{ref}.{format}"
        elif self.platform == 'gitea':
            # {api_base}/{owner}/{repo}/archive/{ref}.{format}
            ref = self.ref if self.ref != 'HEAD' else 'master'
            base = self.api_base or f"https://gitea.com"
            return f"{base}/{self.owner}/{self.repo}/archive/{ref}.{format}"
        return None

    def get_commit_api_url(self):
        """获取获取最新 commit 的 API URL"""
        if self.platform == 'github':
            # https://api.github.com/repos/{owner}/{repo}/commits/{ref}
            ref = self.ref if self.ref != 'HEAD' else 'HEAD'
            return f"https://api.github.com/repos/{self.owner}/{self.repo}/commits/{ref}"
        elif self.platform == 'gitee':
            # https://gitee.com/api/v5/repos/{owner}/{repo}/commits/{sha}
            ref = self.ref if self.ref != 'HEAD' else 'master'
            return f"https://gitee.com/api/v5/repos/{self.owner}/{self.repo}/commits/{ref}"
        elif self.platform == 'gitlab':
            # https://gitlab.com/api/v4/projects/{encoded_path}/repository/commits?ref_name={ref}
            encoded_path = f"{self.owner}/{self.repo}".replace('/', '%2F')
            ref = self.ref if self.ref != 'HEAD' else 'master'
            return f"https://gitlab.com/api/v4/projects/{encoded_path}/repository/commits?ref_name={ref}&per_page=1"
        elif self.platform == 'gitea':
            # {api_base}/api/v1/repos/{owner}/{repo}/commits?sha={ref}&limit=1
            ref = self.ref if self.ref != 'HEAD' else 'master'
            base = self.api_base or "https://gitea.com"
            return f"{base}/api/v1/repos/{self.owner}/{self.repo}/commits?sha={ref}&limit=1"
        return None

    def get_unique_key(self):
        """获取唯一标识 key"""
        return f"{self.platform}:{self.owner}/{self.repo}:{self.ref}"


class RepoArchiveSync:
    """仓库 Archive 同步器"""

    def __init__(self):
        # 使用系统临时目录下的 sync_repo_archive/state 作为状态文件存储位置
        self.state_dir = os.path.join(tempfile.gettempdir(), 'sync_repo_archive', 'state')
        os.makedirs(self.state_dir, exist_ok=True)
        # 默认下载目录：临时目录下的 sync_repo_archive/tmp
        self.download_dir = os.path.join(tempfile.gettempdir(), 'sync_repo_archive', 'tmp')
        os.makedirs(self.download_dir, exist_ok=True)
        # 默认解压目录：临时目录下的 sync_repo_archive/cache
        self.cache_dir = os.path.join(tempfile.gettempdir(), 'sync_repo_archive', 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        # 创建 SSL 上下文（允许访问 HTTPS）
        self.ssl_context = ssl.create_default_context()

    def _sanitize_filename(self, filename):
        """将字符串转换为安全的文件名"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        if len(filename) > 100:
            filename = filename[:100]
        return filename

    def _get_state_file_path(self, key):
        """根据 key 生成状态文件路径"""
        safe_key = self._sanitize_filename(key.replace('/', '_').replace(':', '_'))
        return os.path.join(self.state_dir, f"{safe_key}.json")

    def _load_state(self, key):
        """加载指定 key 的状态文件"""
        state_file = self._get_state_file_path(key)
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_state(self, key, state):
        """保存状态到指定 key 的状态文件"""
        state_file = self._get_state_file_path(key)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def parse_repo_url(self, url, ref=None, api_base=None):
        """
        解析仓库 URL，识别平台和仓库信息

        支持的 URL 格式：
        - GitHub: https://github.com/owner/repo
        - Gitee: https://gitee.com/owner/repo
        - GitLab: https://gitlab.com/owner/repo
        - Gitea: https://gitea.example.com/owner/repo (需要指定 api_base)
        """
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]

        if len(path_parts) < 2:
            raise ValueError(f"无效的仓库 URL: {url}")

        host = parsed.netloc.lower()

        # 识别平台
        if 'github.com' in host:
            platform = 'github'
        elif 'gitee.com' in host:
            platform = 'gitee'
        elif 'gitlab.com' in host:
            platform = 'gitlab'
        else:
            # 假设是 Gitea 或其他自托管平台
            platform = 'gitea'
            if not api_base:
                # 从 URL 推断 api_base
                api_base = f"{parsed.scheme}://{parsed.netloc}"

        owner = path_parts[0]
        repo = path_parts[1]
        # 移除 .git 后缀
        if repo.endswith('.git'):
            repo = repo[:-4]

        return RepoInfo(platform, owner, repo, ref, api_base)

    def _http_get(self, url, headers=None, timeout=30):
        """发送 HTTP GET 请求"""
        req = Request(url)
        req.add_header('User-Agent', 'SyncRepoArchive/1.0')
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        with urlopen(req, context=self.ssl_context, timeout=timeout) as response:
            return response.read(), dict(response.headers)

    def _http_get_json(self, url, headers=None, timeout=30):
        """发送 HTTP GET 请求并返回 JSON"""
        data, headers = self._http_get(url, headers, timeout)
        return json.loads(data.decode('utf-8')), headers

    def _get_latest_commit(self, repo_info):
        """
        获取仓库的最新 commit SHA
        返回: (commit_sha, commit_date, author)
        """
        api_url = repo_info.get_commit_api_url()
        if not api_url:
            raise ValueError(f"不支持的平台: {repo_info.platform}")

        try:
            if repo_info.platform == 'github':
                data, _ = self._http_get_json(api_url)
                return data.get('sha'), data.get('commit', {}).get('committer', {}).get('date'), \
                       data.get('commit', {}).get('author', {}).get('name')

            elif repo_info.platform == 'gitee':
                data, _ = self._http_get_json(api_url)
                return data.get('sha'), data.get('commit', {}).get('committer', {}).get('date'), \
                       data.get('commit', {}).get('author', {}).get('name')

            elif repo_info.platform == 'gitlab':
                data, _ = self._http_get_json(api_url)
                if isinstance(data, list) and len(data) > 0:
                    commit = data[0]
                    return commit.get('id'), commit.get('committed_date'), \
                           commit.get('author_name')
                return None, None, None

            elif repo_info.platform == 'gitea':
                data, _ = self._http_get_json(api_url)
                if isinstance(data, list) and len(data) > 0:
                    commit = data[0]
                    return commit.get('sha'), commit.get('commit', {}).get('committer', {}).get('date'), \
                           commit.get('commit', {}).get('author', {}).get('name')
                return None, None, None

        except HTTPError as e:
            raise Exception(f"API 请求失败 HTTP {e.code}: {e.reason}")
        except Exception as e:
            raise Exception(f"获取最新 commit 失败: {e}")

    def _download_archive(self, url, local_path):
        """下载 archive 文件到本地"""
        try:
            req = Request(url)
            req.add_header('User-Agent', 'SyncRepoArchive/1.0')

            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)

            with urlopen(req, context=self.ssl_context, timeout=120) as response:
                with open(local_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

            return True

        except HTTPError as e:
            raise Exception(f"HTTP 错误 {e.code}: {e.reason}")
        except URLError as e:
            raise Exception(f"URL 错误: {e.reason}")
        except Exception as e:
            raise Exception(f"下载失败: {e}")

    def _extract_archive(self, archive_path, extract_to):
        """解压 archive 文件，并将内容从子目录提升到 extract_to"""
        try:
            # 创建临时解压目录
            temp_extract_dir = tempfile.mkdtemp(prefix="extract_")

            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_extract_dir)

            elif archive_path.endswith(('.tar.gz', '.tgz')):
                with tarfile.open(archive_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(temp_extract_dir)

            elif archive_path.endswith('.tar'):
                with tarfile.open(archive_path, 'r') as tar_ref:
                    tar_ref.extractall(temp_extract_dir)

            else:
            	raise ValueError(f"不支持的压缩格式: {archive_path}")

            # 检查是否只有一级子目录（如 vscode-main/），将内容提升到上级
            extracted_items = os.listdir(temp_extract_dir)
            if len(extracted_items) == 1:
                single_item = os.path.join(temp_extract_dir, extracted_items[0])
                if os.path.isdir(single_item):
                    # 将子目录内容移动到目标目录
                    os.makedirs(extract_to, exist_ok=True)
                    for item in os.listdir(single_item):
                        src = os.path.join(single_item, item)
                        dst = os.path.join(extract_to, item)
                        shutil.move(src, dst)
                    # 清理临时目录
                    shutil.rmtree(temp_extract_dir)
                    return True

            # 如果不是单个子目录，直接将内容移动到目标目录
            os.makedirs(extract_to, exist_ok=True)
            for item in extracted_items:
                src = os.path.join(temp_extract_dir, item)
                dst = os.path.join(extract_to, item)
                shutil.move(src, dst)
            shutil.rmtree(temp_extract_dir)
            return True

        except Exception as e:
            # 清理临时目录
            if 'temp_extract_dir' in locals() and os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            raise Exception(f"解压失败: {e}")

    def _get_archive_format(self, repo_info):
        """根据平台获取推荐的 archive 格式"""
        if repo_info.platform == 'github':
            return 'zip'
        elif repo_info.platform == 'gitee':
            return 'zip'  # Gitee 默认返回 zip
        elif repo_info.platform == 'gitlab':
            return 'zip'
        elif repo_info.platform == 'gitea':
            return 'zip'
        return 'zip'

    def sync_repo(self, name, url, ref=None, extract=None, extract_dir=None, filename=None, api_base=None, archive_format=None):
        """
        同步单个仓库

        Args:
            name: 仓库别名（用于显示）
            url: 仓库 URL
            ref: 分支/标签/Commit（可选，默认 HEAD）
            extract: 是否解压（可选，默认 True）
            extract_dir: 解压目录名称（可选，默认使用仓库名）
            filename: 不解压时的缓存文件名（可选，默认使用 name + 原有后缀）
            api_base: API 基础 URL（用于 Gitea 自托管）
            archive_format: 压缩格式（zip/tar.gz，可选）

        Returns:
            dict: 包含同步结果和状态信息
        """
        logger.info(f"同步仓库 [{name}]...")
        logger.info(f"  URL: {url}")
        if ref:
            logger.info(f"  分支/标签: {ref}")

        result = {
            'name': name,
            'url': url,
            'ref': ref or 'HEAD',
            'updated': False,
            'downloaded': False,
            'extracted': False,
            'cache_path': None,
            'message': ''
        }

        try:
            # 解析仓库信息
            repo_info = self.parse_repo_url(url, ref, api_base)
            logger.info(f"  平台: {repo_info.platform}")
            logger.info(f"  仓库: {repo_info.owner}/{repo_info.repo}")

            # 获取唯一 key
            unique_key = repo_info.get_unique_key()

            # 获取最新 commit 信息
            logger.info(f"  检查更新...")
            commit_sha, commit_date, author = self._get_latest_commit(repo_info)

            if not commit_sha:
                result['message'] = "无法获取最新 commit 信息"
                logger.warning(f"  状态: {result['message']}")
                return result

            logger.info(f"  最新 commit: {commit_sha[:8]}...")
            if commit_date:
                logger.info(f"  提交时间: {commit_date}")
            if author:
                logger.info(f"  作者: {author}")

            # 加载上次状态
            last_state = self._load_state(unique_key)
            last_commit = last_state.get('commit_sha')

            # 检查是否有更新
            if last_commit == commit_sha:
                result['message'] = "仓库没有更新 (commit 相同)"
                logger.info(f"  状态: {result['message']}")
                return result

            result['updated'] = True
            logger.info(f"  发现更新: {last_commit[:8] if last_commit else 'N/A'}... -> {commit_sha[:8]}...")

            # 确定 archive 格式
            if not archive_format:
                archive_format = self._get_archive_format(repo_info)

            # 生成 archive 文件名
            archive_filename = f"{repo_info.owner}_{repo_info.repo}_{commit_sha[:8]}.{archive_format}"
            archive_path = os.path.join(self.download_dir, archive_filename)

            # 下载 archive
            archive_url = repo_info.get_archive_url(archive_format)
            logger.info(f"  下载 archive...")
            logger.info(f"  URL: {archive_url}")

            self._download_archive(archive_url, archive_path)
            result['downloaded'] = True
            result['archive_path'] = archive_path
            logger.info(f"  下载成功: {archive_path}")

            # 判断是否解压（extract 为 None 或 True 时解压，为 False 时不解压）
            should_extract = extract if extract is not None else True

            if should_extract:
                # 确定解压目录名称
                if extract_dir:
                    # 使用配置的目录名称
                    dir_name = extract_dir
                else:
                    # 默认使用仓库名
                    dir_name = repo_info.repo

                final_extract_path = os.path.join(self.cache_dir, dir_name)

                logger.info(f"  解压到: {final_extract_path}")

                # 如果目录已存在，先删除
                if os.path.exists(final_extract_path):
                    shutil.rmtree(final_extract_path)

                try:
                    self._extract_archive(archive_path, final_extract_path)
                    result['extracted'] = True
                    result['extract_path'] = final_extract_path
                    logger.info(f"  解压成功")
                except Exception as e:
                    # 解压失败，清理已创建的目录
                    if os.path.exists(final_extract_path):
                        logger.info(f"  解压失败，清理目录: {final_extract_path}")
                        shutil.rmtree(final_extract_path, ignore_errors=True)
                    raise
            else:
                # 不解压，复制压缩包到缓存目录
                # 确定缓存文件名
                if filename:
                    cache_filename = filename
                else:
                    # 默认使用 name + 原有后缀
                    cache_filename = f"{name}.{archive_format}"

                # 确保文件名安全
                cache_filename = self._sanitize_filename(cache_filename)
                cache_path = os.path.join(self.cache_dir, cache_filename)

                # 复制文件到缓存目录
                shutil.copy2(archive_path, cache_path)
                result['cache_path'] = cache_path
                logger.info(f"  复制到缓存: {cache_path}")

            # 保存状态
            new_state = {
                'name': name,
                'url': url,
                'ref': ref or 'HEAD',
                'platform': repo_info.platform,
                'owner': repo_info.owner,
                'repo': repo_info.repo,
                'commit_sha': commit_sha,
                'commit_date': commit_date,
                'author': author,
                'archive_path': archive_path,
                'extract_path': result.get('extract_path'),
                'cache_path': result.get('cache_path'),
                'last_sync': datetime.now().isoformat()
            }
            self._save_state(unique_key, new_state)

            if result['extracted']:
                result['message'] = f"同步成功: {final_extract_path}"
            elif result.get('cache_path'):
                result['message'] = f"下载成功（已缓存）: {result['cache_path']}"
            else:
                result['message'] = f"下载成功: {archive_path}"

        except Exception as e:
            result['message'] = f"同步失败: {e}"
            logger.error(f"  错误: {e}")

        return result

    def sync_multiple_repos(self, config_list):
        """
        批量同步多个仓库

        Args:
            config_list: 配置列表，每个元素是 dict

        Returns:
            list: 每个仓库的同步结果
        """
        results = []
        for config in config_list:
            try:
                name = config.get('name', '未命名')
                url = config.get('url')
                ref = config.get('ref')
                extract = config.get('extract', True)
                extract_dir = config.get('extract_dir')
                filename = config.get('filename')
                api_base = config.get('api_base')
                archive_format = config.get('archive_format')

                if not url:
                    raise ValueError("配置项必须包含 'url' 字段")

                result = self.sync_repo(
                    name=name,
                    url=url,
                    ref=ref,
                    extract=extract,
                    extract_dir=extract_dir,
                    filename=filename,
                    api_base=api_base,
                    archive_format=archive_format
                )
                results.append(result)
            except Exception as e:
                error_result = {
                    'name': config.get('name', '未命名'),
                    'url': config.get('url', ''),
                    'ref': config.get('ref', 'HEAD'),
                    'updated': False,
                    'downloaded': False,
                    'extracted': False,
                    'cache_path': None,
                    'error': str(e),
                    'message': f"同步失败: {e}"
                }
                results.append(error_result)
                logger.error(f"[{config.get('name', '未命名')}] 错误: {e}")
            logger.info("")
        return results


def main():
    parser = argparse.ArgumentParser(
        description='同步 Git 仓库 archive 到本地（纯标准库实现）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 同步单个仓库（默认分支）
  python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode

  # 同步指定分支
  python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode -r main

  # 同步到指定解压路径
  python sync_repo_archive.py -n "vscode" -u https://github.com/microsoft/vscode -e ./repos/vscode

  # 同步 Gitee 仓库
  python sync_repo_archive.py -n "git-osc" -u https://gitee.com/oschina/git-osc

  # 使用配置文件批量同步
  python sync_repo_archive.py -c config.json

配置文件格式:
  [
    {
      "name": "VSCode",
      "url": "https://github.com/microsoft/vscode",
      "ref": "main",
      "extract": true,
      "extract_dir": "vscode"
    },
    {
      "name": "Git-osc",
      "url": "https://gitee.com/oschina/git-osc",
      "ref": "master",
      "extract": false
    },
    {
      "name": "GitLab CE",
      "url": "https://gitlab.com/gitlab-org/gitlab",
      "ref": "master"
    }
  ]

配置项说明:
  - extract: 是否解压（可选，默认 true）
  - extract_dir: 解压目录名称（可选，默认使用仓库名）
        """
    )

    parser.add_argument('-n', '--name', help='仓库别名（用于显示）')
    parser.add_argument('-u', '--url', help='仓库 URL')
    parser.add_argument('-r', '--ref', help='分支/标签/Commit（可选，默认 HEAD）')
    parser.add_argument('-e', '--extract', help='解压目录名称（可选，默认使用仓库名）')
    parser.add_argument('-f', '--format', choices=['zip', 'tar.gz'], help='压缩格式（可选，默认自动选择）')
    parser.add_argument('-c', '--config', help='配置文件路径 (JSON 格式)')

    args = parser.parse_args()

    # 创建同步器实例
    sync = RepoArchiveSync()

    # 使用配置文件
    if args.config:
        if not os.path.exists(args.config):
            logger.error(f"错误: 配置文件不存在: {args.config}")
            sys.exit(1)

        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config_list = json.load(f)

            if not isinstance(config_list, list):
                logger.error("错误: 配置文件必须是 JSON 数组格式")
                sys.exit(1)

            logger.info(f"从配置文件加载了 {len(config_list)} 个同步项\n")
            results = sync.sync_multiple_repos(config_list)

            # 统计结果
            updated_count = sum(1 for r in results if r.get('updated'))
            downloaded_count = sum(1 for r in results if r.get('downloaded'))
            extracted_count = sum(1 for r in results if r.get('extracted'))
            failed_count = sum(1 for r in results if 'error' in r)

            stats_msg = f"同步完成: {updated_count} 个有更新, {downloaded_count} 个已下载, {extracted_count} 个已解压"
            if failed_count > 0:
                stats_msg += f", {failed_count} 个失败"
            logger.info(stats_msg)

        except json.JSONDecodeError as e:
            logger.error(f"错误: 配置文件 JSON 格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"错误: {e}")
            sys.exit(1)

    # 使用命令行参数
    elif args.url:
        try:
            result = sync.sync_repo(
                name=args.name or args.url,
                url=args.url,
                ref=args.ref,
                extract_dir=args.extract,
                archive_format=args.format
            )

            if result['updated'] and result['extracted']:
                logger.info(f"[OK] {result['message']}")
            elif result['updated']:
                logger.error(f"[PARTIAL] {result['message']}")
            else:
                logger.info(f"[NO CHANGE] {result['message']}")

        except Exception as e:
            logger.error(f"错误: {e}")
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
