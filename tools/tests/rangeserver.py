import http.server, os, re, sys, threading
COUNT = {'n': 0}
class H(http.server.SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def do_HEAD(self):
        p = self.translate_path(self.path)
        if not os.path.isfile(p): self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length', str(os.path.getsize(p))); self.send_header('Accept-Ranges', 'bytes'); self.end_headers()
    def do_GET(self):
        COUNT['n'] += 1
        if self.path == '/__count':
            body = str(COUNT['n']).encode(); self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        p = self.translate_path(self.path)
        if not os.path.isfile(p): self.send_error(404); return
        size = os.path.getsize(p); rng = self.headers.get('Range')
        if rng:
            m = re.match(r'bytes=(\d+)-(\d*)', rng); a = int(m.group(1)); b = int(m.group(2)) if m.group(2) else size - 1; b = min(b, size - 1)
            self.send_response(206); self.send_header('Content-Range', 'bytes %d-%d/%d' % (a, b, size)); self.send_header('Content-Length', str(b - a + 1)); self.send_header('Accept-Ranges', 'bytes'); self.end_headers()
            with open(p, 'rb') as f:
                f.seek(a); left = b - a + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left)); self.wfile.write(chunk); left -= len(chunk)
        else:
            self.send_response(200); self.send_header('Content-Length', str(size)); self.send_header('Accept-Ranges', 'bytes'); self.end_headers()
            with open(p, 'rb') as f: self.wfile.write(f.read())
    def log_message(self, *a): pass
os.chdir(sys.argv[1]); http.server.ThreadingHTTPServer(('127.0.0.1', 8768), H).serve_forever()
