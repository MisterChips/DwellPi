#!/usr/bin/python
# -*- coding: utf-8 -*-
# rpc_server.py

from __future__ import print_function

import os
import json
import time
import uuid
import socket
import threading

from message_schema import Message


class RpcServer(threading.Thread):
    def __init__(self, sock_path, relay_queue, rpc_reply_queue, ui_queue, shutdown_event):
        threading.Thread.__init__(self)
        self.daemon = True
        self.sock_path = sock_path
        self.relay_queue = relay_queue
        self.rpc_reply_queue = rpc_reply_queue
        self.ui_queue = ui_queue
        self.shutdown_event = shutdown_event

    def _handle_ui_button(self, req):
        button = (req.get("button") or "").strip().lower()
        if button not in ("up", "down", "left", "right", "enter"):
            return {"ok": False, "error": "Invalid button"}

        try:
            self.ui_queue.put(Message("rpc", "button_press", {"button": button}))
            return {"ok": True, "button": button}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _handle_relay_status(self):
        # Clear any stale RPC replies
        while True:
            try:
                self.rpc_reply_queue.get_nowait()
            except Exception:
                break
        req_id = uuid.uuid4().hex
        self.relay_queue.put(Message("rpc", "relay_status", {"request_id": req_id}))

        deadline = time.time() + 2.0
        while time.time() < deadline and (not self.shutdown_event.is_set()):
            try:
                msg = self.rpc_reply_queue.get(timeout=0.2)
            except Exception:
                continue

            if getattr(msg, "type", None) != "relay_status_result":
                continue
            if getattr(msg, "request_id", None) != req_id:
                continue
            if getattr(msg, "target", None) not in (None, "rpc"):
                continue

            p = msg.payload or {}
            return {"ok": True, "A": bool(p.get("A")), "B": bool(p.get("B"))}

        return {"ok": False, "error": "Timed out waiting for relay_status_result"}

    def run(self):
        # Remove stale socket
        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except Exception:
            pass

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(5)

        # Optional: restrict permissions
        try:
            os.chmod(self.sock_path, 0o666)
        except Exception:
            pass

        while not self.shutdown_event.is_set():
            try:
                srv.settimeout(0.5)
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except Exception:
                continue

            try:
                conn.settimeout(2.0)
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                line = data.split(b"\n", 1)[0].decode("utf-8") if data else ""
                req = json.loads(line) if line else {}

                op = req.get("op")
                if op == "relay_status":
                    resp = self._handle_relay_status()
                elif op == "ui_button":
                    resp = self._handle_ui_button(req)
                else:
                    resp = {"ok": False, "error": "Unknown op"}

                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))

            except Exception as e:
                try:
                    conn.sendall((json.dumps({"ok": False, "error": str(e)}) + "\n").encode("utf-8"))
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        try:
            srv.close()
        except Exception:
            pass

        try:
            if os.path.exists(self.sock_path):
                os.unlink(self.sock_path)
        except Exception:
            pass