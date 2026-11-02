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
    port_file.write_text(str(server.server_address[1]))
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
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    BIND_EPHEMERAL,
                    str(SOURCE),
                    str(Path(directory) / "pasted.png"),
                    str(port_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.observation = {"source": str(SOURCE), "pid": process.pid}
            idle = request = None
            try:
                deadline = time.monotonic() + 5
                while not port_file.exists():
                    self.assertIsNone(
                        process.poll(), "Browser fixture exited before listening"
                    )
                    self.assertLess(
                        time.monotonic(), deadline, "Browser fixture did not listen"
                    )
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
                    self.assertLess(
                        time.monotonic(), deadline, "Idle connection was not accepted"
                    )
                    time.sleep(0.01)
                self.observation.update(
                    port=address[1], accepted_descriptors=descriptors
                )
                self.observation["thread_wait_channels"] = {
                    path.name: (path / "wchan").read_text()
                    for path in Path(f"/proc/{process.pid}/task").iterdir()
                }
                request = socket.create_connection(address, timeout=2)
                request.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                started = time.monotonic()
                try:
                    response = request.recv(16384)
                except TimeoutError:
                    self.observation["blocked_seconds"] = time.monotonic() - started
                    idle.close()
                    idle = None
                    released = request.recv(16384)
                    self.observation["response_after_idle_closed"] = released.decode(
                        errors="replace"
                    )
                    self.fail(
                        "Document GET blocked behind the idle connection; closing idle immediately released it"
                    )
                self.observation["response_seconds_with_idle_open"] = (
                    time.monotonic() - started
                )
                self.assertIn(b"200 OK", response)
                while b"Paste a screenshot here" not in response:
                    chunk = request.recv(16384)
                    self.assertTrue(
                        chunk, "Fixture document ended without its paste page"
                    )
                    response += chunk
                self.observation["document_received_with_idle_open"] = True
            finally:
                if idle is not None:
                    idle.close()
                if request is not None:
                    request.close()
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate(timeout=3)
                self.observation.update(
                    cleanup_returncode=process.returncode,
                    server_stdout=stdout.decode(errors="replace"),
                    server_stderr=stderr.decode(errors="replace"),
                )


if __name__ == "__main__":
    unittest.main()
