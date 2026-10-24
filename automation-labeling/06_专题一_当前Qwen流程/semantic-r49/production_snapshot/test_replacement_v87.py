import unittest,time,threading
from http.server import HTTPServer,BaseHTTPRequestHandler
from delivery_v87 import explicit_incompatibilities
from delivery_v4 import post_json

class DeadlineAndTypes(unittest.TestCase):
    def test_explicit_area_type(self):
        self.assertIn('D0186',explicit_incompatibilities('實用面積4,732呎'))
        self.assertNotIn('D0186',explicit_incompatibilities('以上面积均为建筑面积，120㎡'))

    def test_suites_not_master_bedrooms(self):
        self.assertIn('D0210',explicit_incompatibilities('五房五套设计'))
        self.assertNotIn('D0210',explicit_incompatibilities('5房5套，主卧数量2间'))

    def test_chinese_dimensions_not_vetoed(self):
        self.assertEqual(explicit_incompatibilities('客厅面宽十二米，17米面宽'),{})

    def test_http_absolute_deadline_with_keepalive_body(self):
        class Trickle(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                self.send_response(200);self.send_header('Content-Length','65536');self.end_headers()
                try:
                    for _ in range(300):self.wfile.write(b' ');self.wfile.flush();time.sleep(.01)
                except (BrokenPipeError,ConnectionResetError,OSError):pass
        server=HTTPServer(('127.0.0.1',0),Trickle)
        thread=threading.Thread(target=server.handle_request,daemon=True);thread.start();start=time.monotonic()
        try:
            with self.assertRaises((TimeoutError,OSError,ValueError)):
                response=post_json('http://127.0.0.1:'+str(server.server_port)+'/',{},'local-test-not-a-secret',.2)
                response.json()
            self.assertLess(time.monotonic()-start,1.5)
        finally:server.server_close()

if __name__=='__main__':unittest.main()
