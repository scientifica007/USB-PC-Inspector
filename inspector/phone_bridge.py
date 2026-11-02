"""Opt-in phone browser bridge. Ephemeral TLS and one-session bearer secret.

No cloud, write access, shell, file-system traversal or inbound server by default.
The phone can read a frozen report and bounded L2/L3 session results.
Users must verify the TLS fingerprint before accepting the local certificate.
"""
from __future__ import annotations

import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit


def local_ipv4() -> list[str]:
    """Only bind an active private LAN/hotspot/tether address."""
    try:
        result = subprocess.run(["ip", "-j", "-4", "addr", "show", "up"],
                                capture_output=True, text=True, timeout=3,
                                check=False)
        interfaces = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        interfaces = []
    addresses = []
    for interface in interfaces:
        for addr in interface.get("addr_info", []):
            value = addr.get("local")
            try:
                ip = ipaddress.ip_address(value)
                if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    addresses.append(str(ip))
            except ValueError:
                continue
    return list(dict.fromkeys(addresses))


def _handler_factory(bridge: "PhoneBridge"):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, _format, *_args):
            # NEVER log token-bearing URLs.
            return

        def _reply(self, status: int, payload: bytes, kind: str,
                   filename: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "form-action 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition",
                                 'attachment; filename="' + filename + '"')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            credential = query.get("token", [""])[0]
            if not secrets.compare_digest(credential, bridge.token):
                self._reply(403, b"Forbidden", "text/plain; charset=utf-8")
                return
            if parsed.path in ("/api/report", "/api/report-html", "/api/complete"):
                with bridge._lock:
                    report = bridge.report
                if report is None:
                    self._reply(404, b"Report not ready", "text/plain; charset=utf-8")
                    return
                from .report import make_html
                raw_json = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                raw_html = make_html(report).encode("utf-8")
                if parsed.path == "/api/report":
                    self._reply(200, raw_json, "application/json; charset=utf-8",
                                "report.json")
                elif parsed.path == "/api/report-html":
                    self._reply(200, raw_html, "text/html; charset=utf-8",
                                "report.html")
                else:
                    manifest = {"complete": True, "files": {
                        "report.json": {"bytes": len(raw_json),
                                        "sha256": hashlib.sha256(raw_json).hexdigest()},
                        "report.html": {"bytes": len(raw_html),
                                        "sha256": hashlib.sha256(raw_html).hexdigest()},
                    }}
                    self._reply(200, json.dumps(manifest).encode("utf-8"),
                                "application/json; charset=utf-8", "complete.json")
            elif parsed.path == "/api/session":
                with bridge._lock:
                    data = {"has_report": bridge.report is not None,
                            "diagnostics": bridge.diagnostics}
                self._reply(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")
            elif parsed.path == "/":
                with bridge._lock:
                    report = bridge.report
                    diagnostics = bridge.diagnostics
                model = (report or {}).get("bios", {}).get("model", "قيد الفحص")
                verdict = (report or {}).get("purchase_assessment", {}).get(
                    "reason", "لم يكتمل L1 بعد")
                status = ("، ".join(x.get("level", "?") + ": " + x.get("status", "")
                          for x in diagnostics) or "لم ينفذ فحص إضافي")
                link = "/api/report?token=" + bridge.token
                html_link = "/api/report-html?token=" + bridge.token
                verify_link = "/api/complete?token=" + bridge.token
                page = (
                    '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>USB PC Inspector — الهاتف</title>'
                    '<style>body{font:17px/1.9 sans-serif;background:#f4f6fa;color:#172b4a;'
                    'max-width:720px;padding:20px;margin:auto}section{background:white;'
                    'padding:16px;border-radius:12px;margin:12px 0}a{color:#184c9a}'
                    '</style><h1>USB PC Inspector</h1><section><h2>الحاسوب</h2><p>' +
                    html.escape(str(model)) + '</p></section><section><h2>القرار الأولي</h2><p>' +
                    html.escape(str(verdict)) + '</p></section><section><h2>الفحوص الإضافية</h2><p>' +
                    html.escape(status) + '</p></section><section>'
                    '<a href="' + html.escape(link, quote=True) + '">تنزيل التقرير JSON</a>'
                    ' | <a href="' + html.escape(html_link, quote=True) + '">تقرير HTML</a>'
                    ' | <a href="' + html.escape(verify_link, quote=True) + '">بصمات SHA-256</a>'
                    '<p>نزّل الملفات من الجلسة نفسها، ثم قارِن بصماتها بملف complete.json.'
                    ' يمكن تحديث الصفحة لمشاهدة أحدث النتائج. الاتصال محلي ومؤقت.</p>'
                    '</section></html>')
                self._reply(200, page.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._reply(404, b"Not found", "text/plain; charset=utf-8")

    return Handler


class PhoneBridge:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self._lock = threading.RLock()
        self.report: dict | None = None
        self.diagnostics: list[dict] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._temp: tempfile.TemporaryDirectory | None = None

    def set_report(self, report: dict | None) -> None:
        # Freeze data as JSON to avoid sharing mutable GTK state with web threads.
        with self._lock:
            self.report = (json.loads(json.dumps(report, ensure_ascii=False))
                           if report is not None else None)

    def set_diagnostics(self, data: list[dict]) -> None:
        with self._lock:
            self.diagnostics = json.loads(json.dumps(data, ensure_ascii=False))

    def start(self) -> dict:
        if self._server is not None:
            raise RuntimeError("خدمة الهاتف تعمل بالفعل.")
        addresses = local_ipv4()
        if not addresses:
            raise RuntimeError("لم يُكتشف عنوان شبكة خاصة؛ فعّل نقطة اتصال الهاتف أو USB tethering.")
        if not shutil_which_openssl():
            raise RuntimeError("أداة openssl غير موجودة؛ يرفض التطبيق الاتصال دون TLS.")
        directory = tempfile.TemporaryDirectory(prefix="pcinsp-phone-")
        cert, key = Path(directory.name) / "cert.pem", Path(directory.name) / "key.pem"
        try:
            created = subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-sha256", "-days", "1", "-subj", "/CN=PC-Inspector-Local",
                 "-keyout", str(key), "-out", str(cert)],
                capture_output=True, timeout=20, check=False)
            if created.returncode:
                raise RuntimeError("تعذر إنشاء شهادة TLS مؤقتة.")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(cert), str(key))
            # Bind one explicit private interface, not every interface.
            server = ThreadingHTTPServer((addresses[0], 0), _handler_factory(self))
            server.daemon_threads = True
            server.socket = context.wrap_socket(server.socket, server_side=True)
            der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))
            fingerprint = hashlib.sha256(der).hexdigest().upper()
            self._server = server
            self._temp = directory
            self._thread = threading.Thread(target=server.serve_forever,
                                            name="pcinsp-phone-https", daemon=True)
            self._thread.start()
            return {"url": "https://" + addresses[0] + ":" + str(server.server_port)
                    + "/?token=" + self.token,
                    "certificate_sha256": fingerprint,
                    "transport": "TLS with temporary self-signed certificate",
                    "warning": "تحقق من بصمة الشهادة على الهاتف؛ لا تتجاوز تحذير الشهادة دون مطابقتها."}
        except Exception:
            directory.cleanup()
            raise

    def stop(self) -> None:
        server, self._server = self._server, None
        self.token = secrets.token_urlsafe(32)
        if server:
            server.shutdown()
            server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._temp:
            self._temp.cleanup()
            self._temp = None


def shutil_which_openssl() -> bool:
    from shutil import which
    return which("openssl") is not None
