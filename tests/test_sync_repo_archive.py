#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_repo_archive.py 的测试脚本
使用 Python 标准库 unittest 实现
"""

import os
import sys
import json
import tempfile
import shutil
import unittest
import logging
import zipfile
from io import StringIO, BytesIO
from unittest.mock import patch, MagicMock

# 添加父目录到路径，以便导入被测试的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入被测试的模块
import importlib.util
spec = importlib.util.spec_from_file_location(
    "sync_repo_archive",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sync_repo_archive.py")
)
sync_repo_archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_repo_archive)
RepoArchiveSync = sync_repo_archive.RepoArchiveSync
RepoInfo = sync_repo_archive.RepoInfo

# 禁用日志输出，避免测试时显示过多信息
logging.disable(logging.CRITICAL)


class TestRepoInfo(unittest.TestCase):
    """RepoInfo 类的测试用例"""

    def test_get_archive_url_github(self):
        """测试 GitHub archive URL 生成"""
        repo = RepoInfo('github', 'microsoft', 'vscode', 'main')
        url = repo.get_archive_url('zip')
        self.assertEqual(url, 'https://github.com/microsoft/vscode/archive/main.zip')

    def test_get_archive_url_github_head(self):
        """测试 GitHub HEAD archive URL"""
        repo = RepoInfo('github', 'microsoft', 'vscode', 'HEAD')
        url = repo.get_archive_url('zip')
        self.assertEqual(url, 'https://github.com/microsoft/vscode/archive/HEAD.zip')

    def test_get_archive_url_gitee(self):
        """测试 Gitee archive URL 生成"""
        repo = RepoInfo('gitee', 'oschina', 'git-osc', 'master')
        url = repo.get_archive_url('zip')
        self.assertEqual(url, 'https://gitee.com/oschina/git-osc/repository/archive/master')

    def test_get_archive_url_gitlab(self):
        """测试 GitLab archive URL 生成"""
        repo = RepoInfo('gitlab', 'gitlab-org', 'gitlab', 'main')
        url = repo.get_archive_url('zip')
        self.assertEqual(url, 'https://gitlab.com/gitlab-org/gitlab/-/archive/main/gitlab-main.zip')

    def test_get_archive_url_gitea(self):
        """测试 Gitea archive URL 生成"""
        repo = RepoInfo('gitea', 'owner', 'repo', 'master', 'https://gitea.example.com')
        url = repo.get_archive_url('zip')
        self.assertEqual(url, 'https://gitea.example.com/owner/repo/archive/master.zip')

    def test_get_commit_api_url_github(self):
        """测试 GitHub commit API URL 生成"""
        repo = RepoInfo('github', 'microsoft', 'vscode', 'main')
        url = repo.get_commit_api_url()
        self.assertEqual(url, 'https://api.github.com/repos/microsoft/vscode/commits/main')

    def test_get_commit_api_url_gitee(self):
        """测试 Gitee commit API URL 生成"""
        repo = RepoInfo('gitee', 'oschina', 'git-osc', 'master')
        url = repo.get_commit_api_url()
        self.assertEqual(url, 'https://gitee.com/api/v5/repos/oschina/git-osc/commits/master')

    def test_get_commit_api_url_gitlab(self):
        """测试 GitLab commit API URL 生成"""
        repo = RepoInfo('gitlab', 'gitlab-org', 'gitlab', 'main')
        url = repo.get_commit_api_url()
        self.assertEqual(url, 'https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab/repository/commits?ref_name=main&per_page=1')

    def test_get_commit_api_url_gitea(self):
        """测试 Gitea commit API URL 生成"""
        repo = RepoInfo('gitea', 'owner', 'repo', 'master', 'https://gitea.example.com')
        url = repo.get_commit_api_url()
        self.assertEqual(url, 'https://gitea.example.com/api/v1/repos/owner/repo/commits?sha=master&limit=1')

    def test_get_unique_key(self):
        """测试唯一 key 生成"""
        repo = RepoInfo('github', 'microsoft', 'vscode', 'main')
        key = repo.get_unique_key()
        self.assertEqual(key, 'github:microsoft/vscode:main')


class TestRepoArchiveSync(unittest.TestCase):
    """RepoArchiveSync 类的测试用例"""

    def setUp(self):
        """每个测试用例前的初始化"""
        self.test_dir = tempfile.mkdtemp(prefix="repo_sync_test_")
        self.sync = RepoArchiveSync()
        # 覆盖目录为临时目录
        self.sync.state_dir = os.path.join(self.test_dir, "states")
        self.sync.download_dir = os.path.join(self.test_dir, "downloads")
        self.sync.cache_dir = os.path.join(self.test_dir, "cache")
        os.makedirs(self.sync.state_dir, exist_ok=True)
        os.makedirs(self.sync.download_dir, exist_ok=True)
        os.makedirs(self.sync.cache_dir, exist_ok=True)

    def tearDown(self):
        """每个测试用例后的清理"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_filename(self):
        """测试文件名安全处理"""
        # 测试特殊字符替换
        self.assertEqual(
            self.sync._sanitize_filename('file<name>:"test"'),
            "file_name___test_"
        )
        # 测试路径分隔符替换
        self.assertEqual(
            self.sync._sanitize_filename("path/to\\file"),
            "path_to_file"
        )
        # 测试长度限制
        long_name = "a" * 150
        result = self.sync._sanitize_filename(long_name)
        self.assertEqual(len(result), 100)
        # 测试正常文件名
        self.assertEqual(
            self.sync._sanitize_filename("normal_file.txt"),
            "normal_file.txt"
        )

    def test_get_state_file_path(self):
        """测试状态文件路径生成"""
        path = self.sync._get_state_file_path("github_owner_repo_main")
        expected_path = os.path.join(self.sync.state_dir, "github_owner_repo_main.json")
        self.assertEqual(path, expected_path)

    def test_save_and_load_state(self):
        """测试状态保存和加载"""
        test_key = "github:microsoft/vscode:main"
        test_state = {
            "name": "VSCode",
            "url": "https://github.com/microsoft/vscode",
            "commit_sha": "abc123def456",
            "commit_date": "2026-04-09T12:00:00Z"
        }

        # 保存状态
        self.sync._save_state(test_key, test_state)

        # 加载状态
        loaded_state = self.sync._load_state(test_key)

        self.assertEqual(loaded_state, test_state)

    def test_load_nonexistent_state(self):
        """测试加载不存在的状态文件"""
        state = self.sync._load_state("nonexistent")
        self.assertEqual(state, {})

    def test_load_corrupted_state(self):
        """测试加载损坏的 JSON 状态文件"""
        test_key = "corrupted"
        state_file = self.sync._get_state_file_path(test_key)

        # 写入无效的 JSON
        with open(state_file, 'w') as f:
            f.write("invalid json content")

        # 应该返回空字典而不是抛出异常
        state = self.sync._load_state(test_key)
        self.assertEqual(state, {})

    def test_parse_repo_url_github(self):
        """测试解析 GitHub URL"""
        repo_info = self.sync.parse_repo_url("https://github.com/microsoft/vscode")
        self.assertEqual(repo_info.platform, 'github')
        self.assertEqual(repo_info.owner, 'microsoft')
        self.assertEqual(repo_info.repo, 'vscode')
        self.assertEqual(repo_info.ref, 'HEAD')

    def test_parse_repo_url_github_with_git_suffix(self):
        """测试解析带 .git 后缀的 GitHub URL"""
        repo_info = self.sync.parse_repo_url("https://github.com/microsoft/vscode.git")
        self.assertEqual(repo_info.repo, 'vscode')

    def test_parse_repo_url_gitee(self):
        """测试解析 Gitee URL"""
        repo_info = self.sync.parse_repo_url("https://gitee.com/oschina/git-osc")
        self.assertEqual(repo_info.platform, 'gitee')
        self.assertEqual(repo_info.owner, 'oschina')
        self.assertEqual(repo_info.repo, 'git-osc')

    def test_parse_repo_url_gitlab(self):
        """测试解析 GitLab URL"""
        repo_info = self.sync.parse_repo_url("https://gitlab.com/gitlab-org/gitlab")
        self.assertEqual(repo_info.platform, 'gitlab')
        self.assertEqual(repo_info.owner, 'gitlab-org')
        self.assertEqual(repo_info.repo, 'gitlab')

    def test_parse_repo_url_gitea(self):
        """测试解析 Gitea URL"""
        repo_info = self.sync.parse_repo_url(
            "https://gitea.example.com/owner/repo",
            api_base="https://gitea.example.com"
        )
        self.assertEqual(repo_info.platform, 'gitea')
        self.assertEqual(repo_info.api_base, 'https://gitea.example.com')

    def test_parse_repo_url_invalid(self):
        """测试解析无效 URL"""
        with self.assertRaises(ValueError):
            self.sync.parse_repo_url("https://github.com")

    @patch.object(sync_repo_archive, 'urlopen')
    def test_http_get(self, mock_urlopen):
        """测试 HTTP GET 请求"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"sha": "abc123"}'
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_urlopen.return_value.__enter__.return_value = mock_response

        data, headers = self.sync._http_get("https://api.github.com/test")

        self.assertEqual(data, b'{"sha": "abc123"}')
        self.assertEqual(headers['Content-Type'], 'application/json')

    @patch.object(sync_repo_archive, 'urlopen')
    def test_http_get_json(self, mock_urlopen):
        """测试 HTTP GET JSON 请求"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"sha": "abc123", "commit": {"message": "test"}}'
        mock_response.headers = {}
        mock_urlopen.return_value.__enter__.return_value = mock_response

        data, headers = self.sync._http_get_json("https://api.github.com/test")

        self.assertEqual(data['sha'], 'abc123')
        self.assertEqual(data['commit']['message'], 'test')

    @patch.object(RepoArchiveSync, '_http_get_json')
    def test_get_latest_commit_github(self, mock_get_json):
        """测试获取 GitHub 最新 commit"""
        mock_get_json.return_value = ({
            'sha': 'abc123def456789',
            'commit': {
                'committer': {'date': '2026-04-09T12:00:00Z'},
                'author': {'name': 'testuser'}
            }
        }, {})

        repo_info = RepoInfo('github', 'microsoft', 'vscode', 'main')
        sha, date, author = self.sync._get_latest_commit(repo_info)

        self.assertEqual(sha, 'abc123def456789')
        self.assertEqual(date, '2026-04-09T12:00:00Z')
        self.assertEqual(author, 'testuser')

    @patch.object(RepoArchiveSync, '_http_get_json')
    def test_get_latest_commit_gitee(self, mock_get_json):
        """测试获取 Gitee 最新 commit"""
        mock_get_json.return_value = ({
            'sha': 'abc123def456789',
            'commit': {
                'committer': {'date': '2026-04-09T12:00:00Z'},
                'author': {'name': 'testuser'}
            }
        }, {})

        repo_info = RepoInfo('gitee', 'oschina', 'git-osc', 'master')
        sha, date, author = self.sync._get_latest_commit(repo_info)

        self.assertEqual(sha, 'abc123def456789')

    @patch.object(RepoArchiveSync, '_http_get_json')
    def test_get_latest_commit_gitlab(self, mock_get_json):
        """测试获取 GitLab 最新 commit"""
        mock_get_json.return_value = ([{
            'id': 'abc123def456789',
            'committed_date': '2026-04-09T12:00:00Z',
            'author_name': 'testuser'
        }], {})

        repo_info = RepoInfo('gitlab', 'gitlab-org', 'gitlab', 'main')
        sha, date, author = self.sync._get_latest_commit(repo_info)

        self.assertEqual(sha, 'abc123def456789')
        self.assertEqual(date, '2026-04-09T12:00:00Z')
        self.assertEqual(author, 'testuser')

    @patch.object(RepoArchiveSync, '_http_get_json')
    def test_get_latest_commit_gitea(self, mock_get_json):
        """测试获取 Gitea 最新 commit"""
        mock_get_json.return_value = ([{
            'sha': 'abc123def456789',
            'commit': {
                'committer': {'date': '2026-04-09T12:00:00Z'},
                'author': {'name': 'testuser'}
            }
        }], {})

        repo_info = RepoInfo('gitea', 'owner', 'repo', 'master', 'https://gitea.example.com')
        sha, date, author = self.sync._get_latest_commit(repo_info)

        self.assertEqual(sha, 'abc123def456789')

    @patch.object(sync_repo_archive, 'urlopen')
    def test_download_archive(self, mock_urlopen):
        """测试下载 archive"""
        mock_response = MagicMock()
        test_content = b'PK\x03\x04' + b'x' * 100  # 模拟 zip 文件内容
        mock_response.read.side_effect = [test_content[i:i+8192] for i in range(0, len(test_content), 8192)] + [b'']
        mock_urlopen.return_value.__enter__.return_value = mock_response

        output_path = os.path.join(self.test_dir, "test.zip")
        result = self.sync._download_archive("https://example.com/archive.zip", output_path)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(output_path))

    def test_extract_archive_zip(self):
        """测试解压 zip 文件"""
        # 创建测试 zip 文件（模拟 GitHub archive 结构：single-dir/file）
        zip_path = os.path.join(self.test_dir, "test.zip")
        extract_path = os.path.join(self.test_dir, "extracted")

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("repo-main/test_file.txt", "Hello, World!")
            zf.writestr("repo-main/dir/nested_file.txt", "Nested content")

        self.sync._extract_archive(zip_path, extract_path)

        # 验证内容被提升到 extract_to 目录，而不是在子目录中
        self.assertTrue(os.path.exists(os.path.join(extract_path, "test_file.txt")))
        self.assertTrue(os.path.exists(os.path.join(extract_path, "dir", "nested_file.txt")))

        with open(os.path.join(extract_path, "test_file.txt"), 'r') as f:
            self.assertEqual(f.read(), "Hello, World!")

    def test_extract_archive_zip_flat(self):
        """测试解压没有子目录的 zip 文件"""
        zip_path = os.path.join(self.test_dir, "test_flat.zip")
        extract_path = os.path.join(self.test_dir, "extracted_flat")

        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("file1.txt", "Content 1")
            zf.writestr("file2.txt", "Content 2")

        self.sync._extract_archive(zip_path, extract_path)

        self.assertTrue(os.path.exists(os.path.join(extract_path, "file1.txt")))
        self.assertTrue(os.path.exists(os.path.join(extract_path, "file2.txt")))

    def test_get_archive_format(self):
        """测试获取 archive 格式"""
        github_repo = RepoInfo('github', 'owner', 'repo')
        self.assertEqual(self.sync._get_archive_format(github_repo), 'zip')

        gitee_repo = RepoInfo('gitee', 'owner', 'repo')
        self.assertEqual(self.sync._get_archive_format(gitee_repo), 'zip')

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    @patch.object(RepoArchiveSync, '_download_archive')
    @patch.object(RepoArchiveSync, '_extract_archive')
    def test_sync_repo_no_update(self, mock_extract, mock_download, mock_get_commit):
        """测试仓库无更新"""
        # 设置上次状态
        self.sync._save_state('github:microsoft/vscode:main', {
            'commit_sha': 'abc123def456'
        })

        # 模拟返回相同的 commit
        mock_get_commit.return_value = ('abc123def456', '2026-04-09T12:00:00Z', 'testuser')

        result = self.sync.sync_repo('VSCode', 'https://github.com/microsoft/vscode', 'main')

        self.assertFalse(result['updated'])
        self.assertFalse(result['downloaded'])
        self.assertFalse(result['extracted'])
        mock_download.assert_not_called()
        mock_extract.assert_not_called()

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    @patch.object(RepoArchiveSync, '_download_archive')
    @patch.object(RepoArchiveSync, '_extract_archive')
    def test_sync_repo_with_update(self, mock_extract, mock_download, mock_get_commit):
        """测试仓库有更新"""
        # 设置旧状态
        self.sync._save_state('github:microsoft/vscode:main', {
            'commit_sha': 'old_commit_sha'
        })

        # 模拟返回新的 commit
        mock_get_commit.return_value = ('new_commit_sha', '2026-04-09T12:00:00Z', 'testuser')
        mock_download.return_value = True
        mock_extract.return_value = True

        result = self.sync.sync_repo('VSCode', 'https://github.com/microsoft/vscode', 'main')

        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        self.assertTrue(result['extracted'])
        mock_download.assert_called_once()
        mock_extract.assert_called_once()

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    def test_sync_repo_no_extract(self, mock_get_commit):
        """测试仓库不解压（复制到缓存目录）"""
        mock_get_commit.return_value = ('new_commit_sha', '2026-04-09T12:00:00Z', 'testuser')

        # 创建真实的 archive 文件用于复制
        def mock_download_side_effect(url, output_path):
            # 创建模拟的 zip 文件
            with zipfile.ZipFile(output_path, 'w') as zf:
                zf.writestr("test.txt", "test content")
            return True

        with patch.object(self.sync, '_download_archive', side_effect=mock_download_side_effect):
            result = self.sync.sync_repo(
                'VSCode',
                'https://github.com/microsoft/vscode',
                'main',
                extract=False
            )

        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        self.assertFalse(result['extracted'])
        self.assertIsNotNone(result['cache_path'])
        # 验证缓存文件存在
        self.assertTrue(os.path.exists(result['cache_path']))

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    def test_sync_repo_no_extract_with_custom_filename(self, mock_get_commit):
        """测试仓库不解压并使用自定义文件名"""
        mock_get_commit.return_value = ('new_commit_sha', '2026-04-09T12:00:00Z', 'testuser')

        # 创建真实的 archive 文件用于复制
        def mock_download_side_effect(url, output_path):
            # 创建模拟的 zip 文件
            with zipfile.ZipFile(output_path, 'w') as zf:
                zf.writestr("test.txt", "test content")
            return True

        with patch.object(self.sync, '_download_archive', side_effect=mock_download_side_effect):
            result = self.sync.sync_repo(
                'VSCode',
                'https://github.com/microsoft/vscode',
                'main',
                extract=False,
                filename='my-vscode-archive.zip'
            )

        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        self.assertFalse(result['extracted'])
        self.assertIsNotNone(result['cache_path'])
        # 验证使用自定义文件名
        self.assertIn('my-vscode-archive.zip', result['cache_path'])
        self.assertTrue(os.path.exists(result['cache_path']))

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    @patch.object(RepoArchiveSync, '_download_archive')
    @patch.object(RepoArchiveSync, '_extract_archive')
    def test_sync_repo_custom_extract_dir(self, mock_extract, mock_download, mock_get_commit):
        """测试自定义解压目录"""
        mock_get_commit.return_value = ('new_commit_sha', '2026-04-09T12:00:00Z', 'testuser')
        mock_download.return_value = True
        mock_extract.return_value = True

        result = self.sync.sync_repo(
            'VSCode',
            'https://github.com/microsoft/vscode',
            'main',
            extract=True,
            extract_dir='my_custom_dir'
        )

        self.assertTrue(result['extracted'])
        # 验证解压路径包含自定义目录名
        self.assertIn('my_custom_dir', result['extract_path'])

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    def test_sync_repo_api_error(self, mock_get_commit):
        """测试 API 错误处理"""
        mock_get_commit.side_effect = Exception("API 请求失败")

        result = self.sync.sync_repo('VSCode', 'https://github.com/microsoft/vscode', 'main')

        self.assertFalse(result['updated'])
        self.assertIn('同步失败', result['message'])

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    @patch.object(RepoArchiveSync, '_download_archive')
    def test_sync_repo_extract_failure_cleanup(self, mock_download, mock_get_commit):
        """测试解压失败时清理目录"""
        mock_get_commit.return_value = ('new_commit_sha', '2026-04-09T12:00:00Z', 'testuser')
        mock_download.return_value = True

        # 模拟解压失败
        with patch.object(self.sync, '_extract_archive') as mock_extract:
            mock_extract.side_effect = Exception("解压失败: 文件损坏")

            # 预先创建目录模拟部分解压的内容
            extract_path = os.path.join(self.sync.cache_dir, 'vscode')
            os.makedirs(extract_path, exist_ok=True)
            with open(os.path.join(extract_path, 'partial_file.txt'), 'w') as f:
                f.write('partial content')

            result = self.sync.sync_repo(
                'VSCode',
                'https://github.com/microsoft/vscode',
                'main'
            )

        # 验证解压失败
        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        self.assertFalse(result['extracted'])
        self.assertIn('同步失败', result['message'])

        # 验证目录已被清理
        self.assertFalse(os.path.exists(extract_path))

    def test_sync_multiple_repos(self):
        """测试批量同步多个仓库"""
        config_list = [
            {"name": "repo1", "url": "https://github.com/owner1/repo1"},
            {"name": "repo2", "url": "https://gitee.com/owner2/repo2"},
            {"name": "invalid", "url": ""}  # 无效配置
        ]

        with patch.object(self.sync, '_get_latest_commit') as mock_commit:
            with patch.object(self.sync, '_download_archive') as mock_download:
                with patch.object(self.sync, '_extract_archive') as mock_extract:
                    mock_commit.return_value = ('abc123', '2026-04-09T12:00:00Z', 'user')
                    mock_download.return_value = True
                    mock_extract.return_value = True

                    results = self.sync.sync_multiple_repos(config_list)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]['name'], 'repo1')
        self.assertEqual(results[1]['name'], 'repo2')
        self.assertIn('error', results[2])

    def test_sync_multiple_repos_with_extract_config(self):
        """测试批量同步带解压配置"""
        config_list = [
            {"name": "repo1", "url": "https://github.com/owner1/repo1", "extract": True, "extract_dir": "custom1"},
            {"name": "repo2", "url": "https://github.com/owner2/repo2", "extract": False}
        ]

        with patch.object(self.sync, '_get_latest_commit') as mock_commit:
            with patch.object(self.sync, '_download_archive') as mock_download:
                with patch.object(self.sync, '_extract_archive') as mock_extract:
                    mock_commit.return_value = ('abc123', '2026-04-09T12:00:00Z', 'user')
                    mock_download.return_value = True
                    mock_extract.return_value = True

                    results = self.sync.sync_multiple_repos(config_list)

        self.assertTrue(results[0]['downloaded'])
        self.assertTrue(results[0]['extracted'])
        self.assertTrue(results[1]['downloaded'])
        self.assertFalse(results[1]['extracted'])


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="integration_test_")
        self.sync = RepoArchiveSync()
        self.sync.state_dir = os.path.join(self.test_dir, "states")
        self.sync.download_dir = os.path.join(self.test_dir, "downloads")
        self.sync.cache_dir = os.path.join(self.test_dir, "cache")
        os.makedirs(self.sync.state_dir, exist_ok=True)
        os.makedirs(self.sync.download_dir, exist_ok=True)
        os.makedirs(self.sync.cache_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch.object(RepoArchiveSync, '_get_latest_commit')
    @patch.object(RepoArchiveSync, '_download_archive')
    @patch.object(RepoArchiveSync, '_extract_archive')
    def test_full_workflow(self, mock_extract, mock_download, mock_get_commit):
        """测试完整工作流程"""
        # 第一轮：首次同步
        mock_get_commit.return_value = ('commit_v1', '2026-04-09T12:00:00Z', 'user1')
        mock_download.return_value = True
        mock_extract.return_value = True

        result1 = self.sync.sync_repo('TestRepo', 'https://github.com/owner/repo', 'main')

        self.assertTrue(result1['updated'])
        self.assertTrue(result1['downloaded'])
        self.assertTrue(result1['extracted'])

        # 第二轮：commit 相同，不需要更新
        result2 = self.sync.sync_repo('TestRepo', 'https://github.com/owner/repo', 'main')

        self.assertFalse(result2['updated'])
        self.assertFalse(result2['downloaded'])

        # 第三轮：commit 变化，需要更新
        mock_get_commit.return_value = ('commit_v2', '2026-04-09T13:00:00Z', 'user2')

        result3 = self.sync.sync_repo('TestRepo', 'https://github.com/owner/repo', 'main')

        self.assertTrue(result3['updated'])
        self.assertTrue(result3['downloaded'])
        self.assertTrue(result3['extracted'])


class TestMainFunction(unittest.TestCase):
    """测试主函数"""

    @patch('sys.stdout', new_callable=StringIO)
    def test_main_help(self, mock_stdout):
        """测试主函数帮助信息"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', ['sync_repo_archive.py', '-h']):
                sync_repo_archive.main()
        self.assertEqual(cm.exception.code, 0)
        output = mock_stdout.getvalue()
        self.assertIn('同步 Git 仓库', output)

    def test_main_no_args(self):
        """测试主函数无参数"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', ['sync_repo_archive.py']):
                sync_repo_archive.main()
        self.assertEqual(cm.exception.code, 1)

    @patch.object(RepoArchiveSync, 'sync_repo')
    def test_main_single_repo(self, mock_sync):
        """测试主函数单仓库模式"""
        mock_sync.return_value = {
            'updated': True,
            'downloaded': True,
            'extracted': True,
            'message': '同步成功'
        }

        with patch.object(sys, 'argv', [
            'sync_repo_archive.py',
            '-n', 'vscode',
            '-u', 'https://github.com/microsoft/vscode',
            '-r', 'main'
        ]):
            sync_repo_archive.main()

        mock_sync.assert_called_once()
        call_args = mock_sync.call_args
        self.assertEqual(call_args[1]['name'], 'vscode')
        self.assertEqual(call_args[1]['url'], 'https://github.com/microsoft/vscode')
        self.assertEqual(call_args[1]['ref'], 'main')

    def test_main_config_file_not_exist(self):
        """测试配置文件不存在"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_repo_archive.py',
                '-c', '/nonexistent/config.json'
            ]):
                sync_repo_archive.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_invalid_config_format(self):
        """测试无效的 JSON 配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json")
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_repo_archive.py',
                '-c', config_path
            ]):
                sync_repo_archive.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_config_not_list(self):
        """测试配置文件不是列表格式"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value"}, f)
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_repo_archive.py',
                '-c', config_path
            ]):
                sync_repo_archive.main()
        self.assertEqual(cm.exception.code, 1)

    @patch.object(RepoArchiveSync, 'sync_multiple_repos')
    def test_main_valid_config(self, mock_sync):
        """测试有效的配置文件"""
        config = [
            {"name": "repo1", "url": "https://github.com/owner1/repo1"},
            {"name": "repo2", "url": "https://github.com/owner2/repo2"}
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        mock_sync.return_value = [
            {'name': 'repo1', 'updated': True, 'downloaded': True, 'extracted': True},
            {'name': 'repo2', 'updated': False, 'downloaded': False, 'extracted': False}
        ]

        with patch.object(sys, 'argv', [
            'sync_repo_archive.py',
            '-c', config_path
        ]):
            sync_repo_archive.main()

        mock_sync.assert_called_once()


if __name__ == '__main__':
    unittest.main()
