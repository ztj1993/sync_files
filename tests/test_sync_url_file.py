#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_url_file.py 的测试脚本
使用 Python 标准库 unittest 实现
"""

import os
import sys
import json
import hashlib
import tempfile
import shutil
import unittest
import logging
from io import StringIO
from unittest.mock import patch, MagicMock

# 添加父目录到路径，以便导入被测试的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入被测试的模块
import importlib.util
spec = importlib.util.spec_from_file_location(
    "sync_url_file",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sync_url_file.py")
)
sync_url_file = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_url_file)
FileSync = sync_url_file.FileSync

# 禁用日志输出，避免测试时显示过多信息
logging.disable(logging.CRITICAL)


class TestFileSync(unittest.TestCase):
    """FileSync 类的测试用例"""

    def setUp(self):
        """每个测试用例前的初始化"""
        # 创建临时目录
        self.test_dir = tempfile.mkdtemp(prefix="file_sync_test_")
        self.sync = FileSync()
        # 覆盖状态目录和下载目录为临时目录
        self.sync.state_dir = os.path.join(self.test_dir, "states")
        self.sync.download_dir = os.path.join(self.test_dir, "downloads")
        os.makedirs(self.sync.state_dir, exist_ok=True)
        os.makedirs(self.sync.download_dir, exist_ok=True)

    def tearDown(self):
        """每个测试用例后的清理"""
        # 删除临时目录
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
        path = self.sync._get_state_file_path("test_file")
        expected_path = os.path.join(self.sync.state_dir, "test_file.json")
        self.assertEqual(path, expected_path)

    def test_save_and_load_state(self):
        """测试状态保存和加载"""
        test_name = "test_config"
        test_state = {
            "name": test_name,
            "url": "https://example.com/test.txt",
            "etag": "abc123",
            "file_hash": "def456"
        }

        # 保存状态
        self.sync._save_state(test_name, test_state)

        # 加载状态
        loaded_state = self.sync._load_state(test_name)

        self.assertEqual(loaded_state, test_state)

    def test_load_nonexistent_state(self):
        """测试加载不存在的状态文件"""
        state = self.sync._load_state("nonexistent")
        self.assertEqual(state, {})

    def test_load_corrupted_state(self):
        """测试加载损坏的状态文件"""
        test_name = "corrupted"
        state_file = self.sync._get_state_file_path(test_name)

        # 写入无效的 JSON
        with open(state_file, 'w') as f:
            f.write("invalid json content")

        # 应该返回空字典而不是抛出异常
        state = self.sync._load_state(test_name)
        self.assertEqual(state, {})

    def test_compute_file_hash(self):
        """测试文件哈希计算"""
        # 创建测试文件
        test_file = os.path.join(self.test_dir, "test.txt")
        test_content = b"Hello, World!"
        with open(test_file, 'wb') as f:
            f.write(test_content)

        # 计算哈希
        file_hash = self.sync._compute_file_hash(test_file)

        # 验证哈希值
        expected_hash = hashlib.sha256(test_content).hexdigest()
        self.assertEqual(file_hash, expected_hash)

    def test_compute_file_hash_large_file(self):
        """测试大文件哈希计算（分块读取）"""
        test_file = os.path.join(self.test_dir, "large.bin")
        # 创建大于 8192 字节的文件
        test_content = b"x" * 10000
        with open(test_file, 'wb') as f:
            f.write(test_content)

        file_hash = self.sync._compute_file_hash(test_file)
        expected_hash = hashlib.sha256(test_content).hexdigest()
        self.assertEqual(file_hash, expected_hash)

    def test_extract_filename_from_url(self):
        """测试从 URL 提取文件名"""
        # 正常 URL
        self.assertEqual(
            self.sync._extract_filename_from_url("https://example.com/file.txt"),
            "file.txt"
        )
        # 带路径的 URL
        self.assertEqual(
            self.sync._extract_filename_from_url("https://example.com/path/to/file.json"),
            "file.json"
        )
        # 带查询参数的 URL
        self.assertEqual(
            self.sync._extract_filename_from_url("https://example.com/file.txt?param=value"),
            "file.txt"
        )

    def test_extract_filename_from_url_invalid(self):
        """测试从无效 URL 提取文件名"""
        # 无路径的 URL
        with self.assertRaises(ValueError):
            self.sync._extract_filename_from_url("https://example.com")
        # 空路径
        with self.assertRaises(ValueError):
            self.sync._extract_filename_from_url("https://example.com/")

    def test_get_download_path_absolute(self):
        """测试获取下载路径 - 绝对路径"""
        abs_path = "/absolute/path/file.txt"
        result = self.sync._get_download_path(abs_path)
        self.assertEqual(result, abs_path)

    def test_get_download_path_relative(self):
        """测试获取下载路径 - 相对路径"""
        # 以 ./ 开头的相对路径
        rel_path = "./relative/file.txt"
        result = self.sync._get_download_path(rel_path)
        self.assertEqual(result, rel_path)

        # 以 ../ 开头的相对路径
        rel_path2 = "../parent/file.txt"
        result2 = self.sync._get_download_path(rel_path2)
        self.assertEqual(result2, rel_path2)

    def test_get_download_path_simple(self):
        """测试获取下载路径 - 简单文件名"""
        filename = "file.txt"
        result = self.sync._get_download_path(filename)
        expected = os.path.join(self.sync.download_dir, filename)
        self.assertEqual(result, expected)

    @patch.object(sync_url_file, 'urlopen')
    def test_check_remote_headers_with_etag(self, mock_urlopen):
        """测试检查远程文件头（带 ETag）"""
        # 模拟响应
        mock_response = MagicMock()
        mock_response.headers = {
            'ETag': '"abc123"',
            'Last-Modified': 'Wed, 21 Oct 2023 07:28:00 GMT',
            'Content-Length': '1024'
        }
        mock_urlopen.return_value.__enter__.return_value = mock_response

        etag, last_modified, content_length = self.sync._check_remote_headers(
            "https://example.com/file.txt"
        )

        self.assertEqual(etag, "abc123")
        self.assertEqual(last_modified, "Wed, 21 Oct 2023 07:28:00 GMT")
        self.assertEqual(content_length, "1024")

    @patch.object(sync_url_file, 'urlopen')
    def test_check_remote_headers_without_etag(self, mock_urlopen):
        """测试检查远程文件头（无 ETag）"""
        mock_response = MagicMock()
        mock_response.headers = {
            'Last-Modified': 'Wed, 21 Oct 2023 07:28:00 GMT'
        }
        mock_urlopen.return_value.__enter__.return_value = mock_response

        etag, last_modified, content_length = self.sync._check_remote_headers(
            "https://example.com/file.txt"
        )

        self.assertEqual(etag, "")
        self.assertEqual(last_modified, "Wed, 21 Oct 2023 07:28:00 GMT")
        self.assertIsNone(content_length)

    @patch.object(sync_url_file, 'urlopen')
    def test_download_file(self, mock_urlopen):
        """测试文件下载"""
        # 模拟响应
        mock_response = MagicMock()
        test_content = b"Test file content"
        mock_response.read.side_effect = [test_content[i:i+8192] for i in range(0, len(test_content), 8192)] + [b'']
        mock_urlopen.return_value.__enter__.return_value = mock_response

        output_path = os.path.join(self.test_dir, "downloaded.txt")
        file_hash = self.sync._download_file(
            "https://example.com/file.txt",
            output_path
        )

        # 验证文件已下载
        self.assertTrue(os.path.exists(output_path))
        with open(output_path, 'rb') as f:
            self.assertEqual(f.read(), test_content)

        # 验证哈希值
        expected_hash = hashlib.sha256(test_content).hexdigest()
        self.assertEqual(file_hash, expected_hash)

    @patch.object(sync_url_file, 'urlopen')
    def test_download_file_creates_directory(self, mock_urlopen):
        """测试下载时自动创建目录"""
        mock_response = MagicMock()
        mock_response.read.side_effect = [b'content', b'']
        mock_urlopen.return_value.__enter__.return_value = mock_response

        nested_path = os.path.join(self.test_dir, "nested", "dir", "file.txt")
        self.sync._download_file("https://example.com/file.txt", nested_path)

        self.assertTrue(os.path.exists(nested_path))

    @patch.object(FileSync, '_check_remote_headers')
    @patch.object(FileSync, '_download_file')
    def test_sync_file_no_update(self, mock_download, mock_check_headers):
        """测试同步文件无更新（ETag 相同）"""
        # 设置初始状态
        self.sync._save_state("test_file", {
            "etag": "same_etag",
            "last_modified": "",
            "file_hash": ""
        })

        # 模拟远程返回相同的 ETag
        mock_check_headers.return_value = ("same_etag", "", None)

        result = self.sync.sync_file(
            name="test_file",
            url="https://example.com/file.txt",
            filename=os.path.join(self.test_dir, "file.txt")
        )

        self.assertFalse(result['updated'])
        self.assertFalse(result['downloaded'])
        self.assertEqual(result['check_method'], 'ETag')
        mock_download.assert_not_called()

    @patch.object(FileSync, '_check_remote_headers')
    @patch.object(FileSync, '_download_file')
    def test_sync_file_with_update(self, mock_download, mock_check_headers):
        """测试同步文件有更新"""
        # 设置旧状态
        self.sync._save_state("test_file", {
            "etag": "old_etag",
            "last_modified": "",
            "file_hash": ""
        })

        # 模拟远程返回新的 ETag
        mock_check_headers.return_value = ("new_etag", "", None)
        mock_download.return_value = "new_file_hash"

        output_path = os.path.join(self.test_dir, "file.txt")
        result = self.sync.sync_file(
            name="test_file",
            url="https://example.com/file.txt",
            filename=output_path
        )

        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        mock_download.assert_called_once()

    @patch.object(FileSync, '_check_remote_headers')
    @patch.object(FileSync, '_download_file')
    def test_sync_file_new_file(self, mock_download, mock_check_headers):
        """测试同步新文件（本地不存在）"""
        mock_check_headers.return_value = ("", "", None)
        mock_download.return_value = "file_hash"

        output_path = os.path.join(self.test_dir, "new_file.txt")
        result = self.sync.sync_file(
            name="new_file",
            url="https://example.com/new.txt",
            filename=output_path
        )

        self.assertTrue(result['updated'])
        self.assertTrue(result['downloaded'])
        self.assertEqual(result['check_method'], '文件哈希')

    @patch.object(FileSync, '_check_remote_headers')
    def test_sync_file_http_error(self, mock_check_headers):
        """测试同步文件时 HTTP 错误"""
        mock_check_headers.side_effect = Exception("HTTP 错误 404: Not Found")

        result = self.sync.sync_file(
            name="error_file",
            url="https://example.com/notfound.txt",
            filename=os.path.join(self.test_dir, "file.txt")
        )

        self.assertFalse(result['updated'])
        self.assertIn("检查失败", result['message'])

    def test_sync_multiple_files(self):
        """测试批量同步多个文件"""
        config_list = [
            {"name": "file1", "url": "https://example.com/1.txt", "filename": os.path.join(self.test_dir, "1.txt")},
            {"name": "file2", "url": "https://example.com/2.txt", "filename": os.path.join(self.test_dir, "2.txt")},
            {"name": "file3", "url": "", "filename": ""}  # 无效配置
        ]

        with patch.object(self.sync, '_check_remote_headers') as mock_check:
            with patch.object(self.sync, '_download_file') as mock_download:
                mock_check.return_value = ("etag", "", None)
                mock_download.return_value = "hash"

                results = self.sync.sync_multiple_files(config_list)

        self.assertEqual(len(results), 3)
        # 前两个应该成功
        self.assertEqual(results[0]['name'], 'file1')
        self.assertEqual(results[1]['name'], 'file2')
        # 第三个应该失败（缺少 URL）
        self.assertIn('error', results[2])

    def test_sync_multiple_files_without_filename(self):
        """测试批量同步 - 自动提取文件名"""
        config_list = [
            {"name": "file1", "url": "https://example.com/auto_file.txt"}
        ]

        with patch.object(self.sync, '_check_remote_headers') as mock_check:
            with patch.object(self.sync, '_download_file') as mock_download:
                mock_check.return_value = ("etag", "", None)
                mock_download.return_value = "hash"

                results = self.sync.sync_multiple_files(config_list)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'file1')
        # 验证文件名被自动提取并保存到默认下载目录
        expected_path = os.path.join(self.sync.download_dir, "auto_file.txt")
        self.assertEqual(results[0]['filename'], expected_path)

    def test_sync_multiple_files_empty_list(self):
        """测试批量同步空列表"""
        results = self.sync.sync_multiple_files([])
        self.assertEqual(results, [])


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="integration_test_")
        self.sync = FileSync()
        self.sync.state_dir = os.path.join(self.test_dir, "states")
        self.sync.download_dir = os.path.join(self.test_dir, "downloads")
        os.makedirs(self.sync.state_dir, exist_ok=True)
        os.makedirs(self.sync.download_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch.object(FileSync, '_check_remote_headers')
    @patch.object(FileSync, '_download_file')
    def test_full_workflow(self, mock_download, mock_check_headers):
        """测试完整工作流程"""
        # 第一轮：文件不存在，需要下载
        mock_check_headers.return_value = ("etag_v1", "", None)
        mock_download.return_value = "hash_v1"

        output_path = os.path.join(self.test_dir, "workflow.txt")
        result1 = self.sync.sync_file(
            name="workflow_test",
            url="https://example.com/workflow.txt",
            filename=output_path
        )

        self.assertTrue(result1['updated'])
        self.assertTrue(result1['downloaded'])

        # 第二轮：ETag 相同，不需要下载
        result2 = self.sync.sync_file(
            name="workflow_test",
            url="https://example.com/workflow.txt",
            filename=output_path
        )

        self.assertFalse(result2['updated'])
        self.assertFalse(result2['downloaded'])

        # 第三轮：ETag 变化，需要重新下载
        mock_check_headers.return_value = ("etag_v2", "", None)
        mock_download.return_value = "hash_v2"

        result3 = self.sync.sync_file(
            name="workflow_test",
            url="https://example.com/workflow.txt",
            filename=output_path
        )

        self.assertTrue(result3['updated'])
        self.assertTrue(result3['downloaded'])


class TestMainFunction(unittest.TestCase):
    """测试主函数"""

    @patch('sys.stdout', new_callable=StringIO)
    def test_main_help(self, mock_stdout):
        """测试主函数帮助信息"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', ['sync_url_file.py', '-h']):
                sync_url_file.main()
        self.assertEqual(cm.exception.code, 0)
        output = mock_stdout.getvalue()
        self.assertIn('同步远程 URL 文件', output)

    def test_main_no_args(self):
        """测试主函数无参数"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', ['sync_url_file.py']):
                sync_url_file.main()
        self.assertEqual(cm.exception.code, 1)

    @patch.object(FileSync, 'sync_file')
    def test_main_single_file_with_output(self, mock_sync):
        """测试主函数单文件模式（带输出路径）"""
        mock_sync.return_value = {
            'updated': True,
            'downloaded': True,
            'message': '文件已下载'
        }

        with patch.object(sys, 'argv', [
            'sync_url_file.py',
            '-n', 'test',
            '-u', 'https://example.com/test.txt',
            '-o', '/tmp/test.txt'
        ]):
            sync_url_file.main()

        mock_sync.assert_called_once()

    @patch.object(FileSync, 'sync_file')
    def test_main_single_file_without_output(self, mock_sync):
        """测试主函数单文件模式（无输出路径，自动提取）"""
        mock_sync.return_value = {
            'updated': True,
            'downloaded': True,
            'message': '文件已下载'
        }

        with patch.object(sys, 'argv', [
            'sync_url_file.py',
            '-n', 'test',
            '-u', 'https://example.com/test.txt'
        ]):
            sync_url_file.main()

        mock_sync.assert_called_once()

    def test_main_config_file_not_exist(self):
        """测试配置文件不存在"""
        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_url_file.py',
                '-c', '/nonexistent/config.json'
            ]):
                sync_url_file.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_invalid_config_format(self):
        """测试无效的 JSON 配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json")
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_url_file.py',
                '-c', config_path
            ]):
                sync_url_file.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_config_not_list(self):
        """测试配置文件不是列表格式"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"key": "value"}, f)
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        with self.assertRaises(SystemExit) as cm:
            with patch.object(sys, 'argv', [
                'sync_url_file.py',
                '-c', config_path
            ]):
                sync_url_file.main()
        self.assertEqual(cm.exception.code, 1)

    @patch.object(FileSync, 'sync_multiple_files')
    def test_main_valid_config(self, mock_sync):
        """测试有效的配置文件"""
        config = [
            {"name": "file1", "url": "https://example.com/1.txt", "filename": "/tmp/1.txt"}
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        self.addCleanup(os.unlink, config_path)

        mock_sync.return_value = [
            {'updated': False, 'downloaded': False}
        ]

        with patch.object(sys, 'argv', [
            'sync_url_file.py',
            '-c', config_path
        ]):
            sync_url_file.main()

        mock_sync.assert_called_once()


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestFileSync))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestMainFunction))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 返回退出码
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
