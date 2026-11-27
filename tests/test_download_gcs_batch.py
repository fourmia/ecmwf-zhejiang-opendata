#!/usr/bin/env python3
"""GCS 断点下载离线回归：范围校验、socket.timeout、MD5 和仅代理访问。"""
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from socket import timeout as SocketTimeout
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import download_gcs_batch as batch


class Response(BytesIO):
    status = 206

    def __init__(self, data=b'cd', content_range='bytes 2-3/4'):
        super().__init__(data)
        self.headers = {'Content-Range': content_range}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.name = 'sample.grib2'
        self.part = self.root / (self.name + '.part')
        self.part.write_bytes(b'ab')
        self.md5 = base64.b64encode(hashlib.md5(b'abcd').digest()).decode()
        self.meta = (4, '123', self.md5)
        self.patchers = [patch.object(batch, 'ROOT', self.root),
                         patch.object(batch, 'VOLUME', None),
                         patch.object(batch.time, 'sleep'), patch.object(batch, 'log')]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_resumed_transfer_and_checksum(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value = Response()
        batch.get_file(opener, 'pl', 'grib2', self.name, self.meta, 1, 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Range'), 'bytes=2-')
        self.assertIn('generation=123', request.full_url)
        self.assertEqual((self.root / self.name).read_bytes(), b'abcd')
        self.assertFalse(self.part.exists())

    def test_wrong_range_leaves_partial_untouched(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value = Response(content_range='bytes 0-1/4')
        with self.assertRaises(batch.TransferError):
            batch.transfer(opener, 'https://example.com/data', self.part, 2, 4)
        self.assertEqual(self.part.read_bytes(), b'ab')

    def test_socket_timeout_retries_same_offset(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = [SocketTimeout('read timed out'), Response()]
        batch.get_file(opener, 'pl', 'grib2', self.name, self.meta, 1, 1)
        self.assertEqual([call.args[0].get_header('Range') for call in opener.open.call_args_list],
                         ['bytes=2-', 'bytes=2-'])
        self.assertEqual((self.root / self.name).read_bytes(), b'abcd')

    def test_complete_partial_promoted_without_network(self):
        from unittest.mock import Mock
        self.part.write_bytes(b'abcd')
        opener = Mock()
        batch.get_file(opener, 'pl', 'grib2', self.name, self.meta, 1, 1)
        opener.open.assert_not_called()
        self.assertTrue(batch.is_valid(self.root / self.name, 4, self.md5))

    def test_checksum_failure_restarts_file(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = [Response(b'xx'), Response(b'abcd', 'bytes 0-3/4')]
        batch.get_file(opener, 'pl', 'grib2', self.name, self.meta, 1, 1)
        self.assertEqual([call.args[0].get_header('Range') for call in opener.open.call_args_list],
                         ['bytes=2-', 'bytes=0-'])
        self.assertEqual((self.root / self.name).read_bytes(), b'abcd')

    def test_retry_exhaustion_preserves_partial(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = SocketTimeout('read timed out')
        with self.assertRaises(RuntimeError):
            batch.get_file(opener, 'pl', 'grib2', self.name, self.meta, 1, 1)
        self.assertEqual(opener.open.call_count, 8)
        self.assertEqual(self.part.read_bytes(), b'ab')

    def test_proxy_required_and_no_storage_bypass(self):
        from urllib.request import proxy_bypass
        with patch.object(batch, 'getproxies', return_value={}):
            with self.assertRaises(SystemExit):
                batch.system_proxy_opener()
        with patch.dict(batch.os.environ, {}, clear=True):
            opener = batch.system_proxy_opener('http://127.0.0.1:1082')
            self.assertFalse(proxy_bypass('storage.googleapis.com'))
            handler = next(h for h in opener.handlers if isinstance(h, batch.ProxyHandler))
            self.assertEqual(handler.proxies, {'https': 'http://127.0.0.1:1082'})


if __name__ == '__main__':
    unittest.main()
