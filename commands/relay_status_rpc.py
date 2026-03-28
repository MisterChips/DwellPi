#!/usr/bin/python
# -*- coding: utf-8 -*-
# commands/relay_status_rpc.py
#
# Query the running supervisor (which owns the queues) for relay status.
# Uses a Unix domain socket RPC (local only).

from __future__ import print_function

import os
import sys
import json
import socket


DEFAULT_SOCK = "/tmp/dwellpi.sock"


def die(msg, code=2):
    print(msg)
    raise SystemExit(code)


def _parse_args(argv):
    sock = DEFAULT_SOCK
    if "--sock" in argv:
        try:
            sock = argv[argv.index("--sock") + 1]
        except Exception:
            die("ERROR: --sock requires a path")
    return sock


def main(argv):
    sock_path = _parse_args(argv)

    if not os.path.exists(sock_path):
        die("ERROR: supervisor socket not found: %s (is the system running?)" % sock_path, 2)

    req = {"op": "relay_status"}

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(2.0)
        s.connect(sock_path)
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))

        # Simple line protocol: one JSON line back
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk

        if not buf:
            die("ERROR: no response from supervisor", 2)

        line = buf.split(b"\n", 1)[0].decode("utf-8")
        resp = json.loads(line)

        if not resp.get("ok"):
            die("ERROR: %s" % (resp.get("error") or "unknown error"), 2)

        a = resp.get("A")
        b = resp.get("B")

        print("RelayA:", "ON" if a else "OFF")
        print("RelayB:", "ON" if b else "OFF")
        return 0

    except Exception as e:
        die("ERROR: RPC failed: %s" % e, 2)
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))