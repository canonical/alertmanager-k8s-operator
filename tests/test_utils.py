# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import utils
import unittest


class TestUtils(unittest.TestCase):
    def test_append_unless(self):
        # unless = None
        self.assertEqual('address:port', utils.append_unless(None, 'address', ':port'))
        self.assertEqual(None, utils.append_unless(None, None, ':port'))

        # unless = string
        self.assertEqual('basesuffix', utils.append_unless('bad', 'base', 'suffix'))
        self.assertEqual('bad', utils.append_unless('bad', 'bad', 'suffix'))

        # unless = None, args = lists
        self.assertEqual([1, 2, 3], utils.append_unless(None, [1, 2], [3]))
        self.assertEqual(None, utils.append_unless(None, None, [3]))

    def test_md5(self):
        self.assertEqual('50e1eeff19b2501c791612cd907fff7a',
                         utils.md5('test string\nwith newline'))

    def test_fetch_url(self):
        self.assertEqual(None, utils.fetch_url('no such thing'))
        self.assertEqual(None, utils.fetch_url('http://no-such-thing.abc/asdasd123'))

        def start_server():
            from http.server import HTTPServer, BaseHTTPRequestHandler

            class MyServer(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(bytes("works", "utf-8"))

            server_address = ('', 8000)
            httpd = HTTPServer(server_address, MyServer)
            httpd.serve_forever()

        def start_server_in_a_thread():
            import threading
            daemon = threading.Thread(name='daemon_server', target=start_server)
            daemon.setDaemon(True)  # so it will be killed once the main thread is dead
            daemon.start()
            import time
            time.sleep(1)  # wait for server to start

        start_server_in_a_thread()
        self.assertEqual(b"works", utils.fetch_url('http://localhost:8000'))
