"""The actual browser fixture must serve a document despite a preopened socket."""

import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("clipboard-browser.py")
BIND_EPHEMERAL = """
import runpy, socketserver, sys
from pathlib import Path
port_file = Path(sys.argv[3])
original_bind = socketserver.TCPServer.server_bind
original_activate = socketserver.TCPServer.server_activate
def bind(server):
    assert server.server_address == ('127.0.0.1', 8790)
    server.server_address = ('127.0.0.1', 0)
    original_bind(server)
def activate(server):
    original_activate(server)
    temporary = port_file.with_suffix(".tmp")
    temporary.write_text(str(server.server_address[1]))
    temporary.replace(port_file)
socketserver.TCPServer.server_bind = bind
socketserver.TCPServer.server_activate = activate
source, destination = sys.argv[1:3]
sys.argv = [source, destination]
runpy.run_path(source, run_name='__main__')
"""


class ClipboardBrowserTests(unittest.TestCase):
    def test_document_serves_while_a_browser_preopened_connection_is_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            port_file = Path(directory) / "port"
            destination = Path(directory) / "pasted.png"
            arguments = [str(SOURCE), str(destination), str(port_file)]
            process = subprocess.Popen(
                [sys.executable, "-c", BIND_EPHEMERAL, *arguments],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            idle = request = None
            try:
                deadline = time.monotonic() + 5
                while not port_file.exists():
                    self.assertIsNone(process.poll(), "Fixture exited before listening")
                    self.assertLess(time.monotonic(), deadline, "Not listening")
                    time.sleep(0.01)
                address = ("127.0.0.1", int(port_file.read_text()))
                idle = socket.create_connection(address, timeout=2)
                # Wait for acceptance, making the idle-first ordering deterministic.
                while True:
                    descriptors = [
                        str(path.readlink())
                        for path in Path(f"/proc/{process.pid}/fd").iterdir()
                    ]
                    if sum(value.startswith("socket:") for value in descriptors) >= 2:
                        break
                    self.assertLess(time.monotonic(), deadline, "Not accepted")
                    time.sleep(0.01)
                request = socket.create_connection(address, timeout=2)
                request.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                try:
                    response = request.recv(16384)
                except TimeoutError:
                    self.fail("Document GET blocked behind the idle connection")
                self.assertIn(b"200 OK", response)
                while b"Paste a screenshot here" not in response:
                    chunk = request.recv(16384)
                    self.assertTrue(chunk, "Document ended without its paste page")
                    response += chunk
            finally:
                if idle is not None:
                    idle.close()
                if request is not None:
                    request.close()
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
