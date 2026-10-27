"""Local test page: save only images pasted through Chromium's real paste event."""

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PAGE = b"""<!doctype html><meta charset="utf-8"><title>Clipboard screenshot test</title>
<style>body{margin:12px;font:20px sans-serif;background:white;color:black;outline:none}
h1{margin:0;height:44px;background:rgb(48,140,230);font:20px/44px sans-serif;text-align:center}
img{display:block;max-width:90%;max-height:65vh;margin:12px auto}</style>
<body contenteditable="true"><h1>Paste a screenshot here with Ctrl+V</h1><p id="status">Waiting for an image</p>
<img id="preview"><script>
document.body.focus();
document.addEventListener('paste',async event=>{
  event.preventDefault();
  const item=[...event.clipboardData.items].find(item=>item.kind==='file'&&item.type.startsWith('image/'));
  if(!item){document.querySelector('#status').textContent='No image in paste event';return;}
  const file=item.getAsFile();
  const image=document.querySelector('#preview');
  image.src=URL.createObjectURL(file);
  await image.decode();
  const response=await fetch('/image',{method:'POST',body:file});
  document.querySelector('#status').textContent=response.ok?
    `Pasted ${file.type}: ${image.naturalWidth} x ${image.naturalHeight}`:'Image save failed';
});
</script></body>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/image" or not 0 < size <= 64 * 1024 * 1024:
            self.send_error(400)
            return
        image = self.rfile.read(size)
        if len(image) != size:
            self.send_error(400)
            return
        Path(sys.argv[1]).write_bytes(image)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_arguments):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8790), Handler).serve_forever()
