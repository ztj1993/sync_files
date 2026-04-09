#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URL 文件同步工具
检测指定 URL 的文件是否有更新，有更新时自动下载到本地
支持 ETag、Last-Modified 或文件哈希来判断更新

纯 Python 标准库实现，无需第三方依赖
"""

import os
import sys
import json
import hashlib
import argparse
import tempfile
import ssl
import logging
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class FileSync:
    """URL 文件同步器"""

    def __init__(self):
        # 使用系统临时目录下的 sync_url_file/state 作为状态文件存储位置
        self.state_dir = os.path.join(tempfile.gettempdir(), 'sync_url_file', 'state')
        os.makedirs(self.state_dir, exist_ok=True)
        # 默认下载目录：临时目录下的 sync_url_file/cache
        self.download_dir = os.path.join(tempfile.gettempdir(), 'sync_url_file', 'cache')
        os.makedirs(self.download_dir, exist_ok=True)
        # 创建 SSL 上下文（允许访问 HTTPS）
        self.ssl_context = ssl.create_default_context()

    def _get_state_file_path(self, name):
        """根据别名生成状态文件路径"""
        # 使用别名作为文件名（进行安全处理）
        safe_name = self._sanitize_filename(name)
        return os.path.join(self.state_dir, f"{safe_name}.json")

    def _sanitize_filename(self, filename):
        """将别名转换为安全的文件名"""
        # 替换不安全的字符
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        # 限制长度
        if len(filename) > 100:
            filename = filename[:100]
        return filename

    def _extract_filename_from_url(self, url):
        """从 URL 中提取文件名，如果不合法则抛出错误"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        # 获取路径最后一部分作为文件名
        filename = os.path.basename(path)
        # 检查文件名是否合法
        if not filename or filename == '/' or filename == '':
            raise ValueError(f"无法从 URL 提取有效的文件名: {url}")
        return filename

    def _load_state(self, name):
        """加载指定别名的状态文件"""
        state_file = self._get_state_file_path(name)
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_state(self, name, state):
        """保存状态到指定别名的状态文件"""
        state_file = self._get_state_file_path(name)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _compute_file_hash(self, filepath):
        """计算本地文件的 SHA256 哈希值"""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _check_remote_headers(self, url):
        """
        检查远程文件的 HTTP 头信息
        返回: (etag, last_modified, content_length)
        """
        try:
            req = Request(url, method='HEAD')
            req.add_header('User-Agent', 'SyncUrlFile/1.0')

            with urlopen(req, context=self.ssl_context, timeout=30) as response:
                headers = dict(response.headers)

                etag = headers.get('ETag', '').strip('"')
                last_modified = headers.get('Last-Modified', '')
                content_length = headers.get('Content-Length')

                return etag, last_modified, content_length

        except HTTPError as e:
            raise Exception(f"HTTP 错误 {e.code}: {e.reason}")
        except URLError as e:
            raise Exception(f"URL 错误: {e.reason}")
        except Exception as e:
            raise Exception(f"获取远程文件头信息失败: {e}")

    def _download_file(self, url, local_path):
        """下载文件到本地，返回文件内容的哈希值"""
        try:
            req = Request(url)
            req.add_header('User-Agent', 'SyncUrlFile/1.0')

            # 确保目标目录存在
            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)

            sha256 = hashlib.sha256()
            with urlopen(req, context=self.ssl_context, timeout=60) as response:
                with open(local_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        sha256.update(chunk)

            return sha256.hexdigest()

        except HTTPError as e:
            raise Exception(f"HTTP 错误 {e.code}: {e.reason}")
        except URLError as e:
            raise Exception(f"URL 错误: {e.reason}")
        except Exception as e:
            raise Exception(f"下载文件失败: {e}")

    def sync_file(self, name, url, filename):
        """
        同步单个文件，检查更新并下载

        Args:
            name: 文件别名（用于显示）
            url: 文件 URL
            filename: 本地保存路径

        Returns:
            dict: 包含同步结果和状态信息
        """
        logger.info(f"同步 [{name}]...")
        logger.info(f"  URL: {url}")
        logger.info(f"  本地文件: {filename}")

        result = {
            'name': name,
            'url': url,
            'filename': filename,
            'updated': False,
            'downloaded': False,
            'check_method': '',
            'message': ''
        }

        # 获取远程文件头信息
        try:
            etag, last_modified, content_length = self._check_remote_headers(url)
        except Exception as e:
            result['message'] = f"检查失败: {e}"
            logger.info(f"  状态: {result['message']}")
            return result

        # 获取上次保存的状态（使用别名作为 key）
        last_state = self._load_state(name)

        # 判断更新策略（优先级: ETag > Last-Modified > 文件哈希）
        if etag:
            # 使用 ETag 判断
            result['check_method'] = 'ETag'
            last_etag = last_state.get('etag', '')

            if last_etag == etag:
                result['message'] = "文件没有更新 (ETag 相同)"
                logger.info(f"  检查方式: ETag")
                logger.info(f"  状态: {result['message']}")
                return result

            logger.info(f"  检查方式: ETag")
            logger.info(f"  旧 ETag: {last_etag[:16] if last_etag else 'N/A'}...")
            logger.info(f"  新 ETag: {etag[:16]}...")
            result['updated'] = True

        elif last_modified:
            # 使用 Last-Modified 判断
            result['check_method'] = 'Last-Modified'
            last_modified_saved = last_state.get('last_modified', '')

            if last_modified_saved == last_modified:
                result['message'] = "文件没有更新 (Last-Modified 相同)"
                logger.info(f"  检查方式: Last-Modified")
                logger.info(f"  状态: {result['message']}")
                return result

            logger.info(f"  检查方式: Last-Modified")
            logger.info(f"  旧时间: {last_modified_saved}")
            logger.info(f"  新时间: {last_modified}")
            result['updated'] = True

        else:
            # 使用文件哈希判断
            result['check_method'] = '文件哈希'
            logger.info(f"  检查方式: 文件哈希 (服务器未提供 ETag 或 Last-Modified)")

            # 如果本地文件不存在，直接下载
            if not os.path.exists(filename):
                logger.info(f"  本地文件不存在，需要下载")
                result['updated'] = True
            else:
                # 计算本地文件哈希
                local_hash = self._compute_file_hash(filename)
                last_hash = last_state.get('file_hash', '')

                # 先比较上次保存的哈希
                if last_hash:
                    logger.info(f"  旧哈希: {last_hash[:16]}...")

                # 无论如何都需要下载后比较
                result['updated'] = True

        # 下载文件
        try:
            file_hash = self._download_file(url, filename)
            result['downloaded'] = True
            result['message'] = f"文件已下载到: {filename}"
            logger.info(f"  下载: 成功 -> {filename}")

            # 如果是哈希检查方式，比较下载后的文件
            if result['check_method'] == '文件哈希':
                if os.path.exists(filename):
                    old_hash = last_state.get('file_hash', '')
                    if old_hash == file_hash:
                        result['updated'] = False
                        result['message'] = "文件没有更新 (哈希相同)"
                        logger.info(f"  新哈希: {file_hash[:16]}...")
                        logger.info(f"  状态: {result['message']}")
                        return result
                    else:
                        logger.info(f"  新哈希: {file_hash[:16]}...")

            # 更新状态
            new_state = {
                'name': name,
                'url': url,
                'etag': etag,
                'last_modified': last_modified,
                'file_hash': file_hash,
                'content_length': content_length,
                'last_check': datetime.now().isoformat(),
                'filename': filename
            }
            self._save_state(name, new_state)

        except Exception as e:
            result['message'] = f"下载失败: {e}"
            logger.error(f"  下载: 失败 - {e}")

        return result

    def _get_download_path(self, filename):
        """获取完整的下载路径"""
        if not filename:
            return None
        # 如果是绝对路径，直接使用
        if os.path.isabs(filename):
            return filename
        # 如果是相对路径（以 ./ 或 ../ 开头），保持原样（相对于当前工作目录）
        if filename.startswith('./') or filename.startswith('../'):
            return filename
        # 否则拼接默认下载目录
        return os.path.join(self.download_dir, filename)

    def sync_multiple_files(self, config_list):
        """
        批量同步多个文件

        Args:
            config_list: 配置列表，每个元素是 dict，包含 name, url, filename（可选）

        Returns:
            list: 每个文件的同步结果
        """
        results = []
        for config in config_list:
            try:
                # 获取配置项
                name = config.get('name', '未命名')
                url = config.get('url')
                filename = config.get('filename')

                if not url:
                    raise ValueError("配置项必须包含 'url' 字段")

                # 如果没有指定 filename，从 URL 提取并保存到临时目录
                if not filename:
                    filename = self._extract_filename_from_url(url)
                    logger.info(f"[{name}] 未指定 filename，使用 URL 中的文件名: {filename}")

                # 获取完整的下载路径
                download_path = self._get_download_path(filename)

                # 同步文件
                result = self.sync_file(
                    name=name,
                    url=url,
                    filename=download_path
                )
                results.append(result)
            except Exception as e:
                error_result = {
                    'name': config.get('name', '未命名'),
                    'url': config.get('url', ''),
                    'filename': config.get('filename', ''),
                    'updated': False,
                    'downloaded': False,
                    'error': str(e),
                    'message': f"同步失败: {e}"
                }
                results.append(error_result)
                logger.error(f"[{config.get('name', '未命名')}] 错误: {e}")
            logger.info("")
        return results


def main():
    parser = argparse.ArgumentParser(
        description='同步远程 URL 文件到本地（纯标准库实现）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 同步单个文件
  python sync_url_file.py -n "配置文件" -u https://example.com/config.json -o ./config.json

  # 同步 GitHub raw 文件
  python sync_url_file.py -n "README" -u https://raw.githubusercontent.com/user/repo/main/README.md -o ./README.md

  # 使用配置文件批量同步
  python sync_url_file.py -c config.json

配置文件格式:
  [
    {
      "name": "文件别名",
      "url": "https://example.com/file.txt",
      "filename": "./downloads/file.txt"
    }
  ]
        """
    )

    parser.add_argument('-n', '--name', help='文件别名（用于显示）')
    parser.add_argument('-u', '--url', help='文件 URL')
    parser.add_argument('-o', '--output', help='本地保存路径')
    parser.add_argument('-c', '--config', help='配置文件路径 (JSON 格式)')

    args = parser.parse_args()

    # 创建同步器实例
    sync = FileSync()

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
            results = sync.sync_multiple_files(config_list)

            # 统计结果
            updated_count = sum(1 for r in results if r.get('updated'))
            downloaded_count = sum(1 for r in results if r.get('downloaded'))
            logger.info(f"检查完成: {updated_count} 个文件有更新, {downloaded_count} 个文件已下载")

        except json.JSONDecodeError as e:
            logger.error(f"错误: 配置文件 JSON 格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"错误: {e}")
            sys.exit(1)

    # 使用命令行参数
    elif args.url:
        try:
            # 如果没有指定输出路径，从 URL 提取文件名并保存到临时目录
            if args.output:
                output_path = args.output
            else:
                output_path = sync._get_download_path(
                    sync._extract_filename_from_url(args.url)
                )
                logger.info(f"未指定输出路径，使用默认路径: {output_path}")

            result = sync.sync_file(
                name=args.name or args.url,
                url=args.url,
                filename=output_path
            )

            if result['updated'] and result['downloaded']:
                logger.info(f"[OK] {result['message']}")
            elif result['updated']:
                logger.error(f"[FAIL] {result['message']}")
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
