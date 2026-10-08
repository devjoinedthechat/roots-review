"""Streamable HTTP transport: run the server on a loopback port for the test, then stop it."""

import json
import os
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

from roots_review import OUT, ROOT

R4 = "v29.4-roots.4"


def start(*extra):
    p = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "mcp_server.py"), "--http", "127.0.0.1:0", *extra],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    m = re.search(r"http://127\.0\.0\.1:(\d+)/mcp", p.stderr.readline())
    return p, f"http://127.0.0.1:{m.group(1)}/mcp"


def req(url, body=None, headers=None, method="POST"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                        **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), json.loads(raw) if raw else None


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}


@unittest.skipUnless(os.path.exists(os.path.join(OUT, R4, "manifest.json")), "run `roots-review build` first")
class HTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.url = start("--allow-origin", "https://ok.example")

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate()
        cls.p.wait(timeout=10)
        cls.p.stderr.close()

    def session(self):
        code, headers, body = req(self.url, INIT)
        self.assertEqual(code, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "roots-review")
        return headers["Mcp-Session-Id"]

    def test_session_flow(self):
        sid = self.session()
        h = {"Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"}
        self.assertEqual(req(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, h)[0], 202)
        code, _, body = req(self.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, h)
        self.assertEqual((code, len(body["result"]["tools"])), (200, 14))
        code, _, body = req(self.url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                       "params": {"name": "list_releases", "arguments": {}}}, h)
        self.assertFalse(body["result"]["isError"])
        self.assertEqual(req(self.url, None, h, method="DELETE")[0], 204)
        self.assertEqual(req(self.url, {"jsonrpc": "2.0", "id": 4, "method": "ping"}, h)[0], 404)

    def test_rejections(self):
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(req(self.url, ping)[0], 400)                                       # no session
        self.assertEqual(req(self.url, ping, {"Mcp-Session-Id": "nope"})[0], 404)          # unknown session
        self.assertEqual(req(self.url, INIT, {"Origin": "https://evil.example"})[0], 403)  # browser origin
        self.assertEqual(req(self.url, INIT, {"Origin": "https://ok.example"})[0], 200)    # allowlisted origin
        self.assertEqual(req(self.url, INIT, {"Host": "attacker.example"})[0], 403)        # DNS rebinding
        # A newer client may announce its newest version on initialize; negotiation happens in the body.
        code, _, body = req(self.url, dict(INIT, params=dict(INIT["params"], protocolVersion="2026-07-28")),
                            {"MCP-Protocol-Version": "2026-07-28"})
        self.assertEqual((code, body["result"]["protocolVersion"]), (200, "2025-11-25"))
        sid = self.session()
        self.assertEqual(req(self.url, ping, {"Mcp-Session-Id": sid, "MCP-Protocol-Version": "1999-01-01"})[0], 400)
        self.assertEqual(req(self.url, b"x" * (1 << 20 + 1))[0], 413)
        self.assertEqual(req(self.url.replace("/mcp", "/other"), INIT)[0], 404)
        self.assertEqual(req(self.url, None, method="GET")[0], 405)


if __name__ == "__main__":
    unittest.main()
