#!/usr/bin/python
# -*- coding: utf-8 -*-
# email_process.py

from __future__ import print_function

import os
import time
import socket
import smtplib

try:
    from Queue import Empty as QueueEmpty
except ImportError:
    from queue import Empty as QueueEmpty

from email.mime.text import MIMEText

from message_schema import Message
from commands.common import parse_bool
from settings_client import SettingsClient


class EmailProcess(SettingsClient):
    def __init__(self, email_queue, db_queue, ctrl_queue, mode, shutdown_event):
        SettingsClient.__init__(self, ctrl_queue, shutdown_event, name="Email")

        self.email_queue = email_queue
        self.db_queue = db_queue
        self.mode = mode
        self.shutdown_event = shutdown_event

        # config file path
        self.email_config_path = "/home/pi/dwellpi_email.conf"

        # settings defaults
        self.email_enable = False
        self.email_to = ""
        self.email_from = ""
        self.smtp_host = ""
        self.smtp_port = 587
        self.smtp_username = ""
        self.smtp_password = ""
        self.smtp_use_ssl = True
        self.alert_cooldown_seconds = 1800
        self.alert_send_recovery_emails = True

        # runtime
        self.last_sent_by_key = {}

    def _load_email_config_file(self):
        path = self.email_config_path

        if not os.path.exists(path):
            print("[Email] Config file not found: %s" % path)
            return False

        loaded = {}

        try:
            with open(path, "r") as f:
                for raw_line in f:
                    line = raw_line.strip()

                    if not line:
                        continue
                    if line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    key = key.strip().upper()
                    value = value.strip()

                    loaded[key] = value

        except Exception as e:
            print("[Email] Failed reading config file %s: %s" % (path, e))
            return False

        try:
            self.email_to = str(loaded.get("EMAIL_TO", "") or "").strip()
            self.email_from = str(loaded.get("EMAIL_FROM", "") or "").strip()
            self.smtp_host = str(loaded.get("SMTP_HOST", "") or "").strip()

            port_value = loaded.get("SMTP_PORT", 587)
            self.smtp_port = int(float(port_value or 587))

            self.smtp_username = str(loaded.get("SMTP_USERNAME", "") or "").strip()
            self.smtp_password = str(loaded.get("SMTP_PASSWORD", "") or "")
            if "SMTP_USE_SSL" in loaded:
                self.smtp_use_ssl = parse_bool(loaded.get("SMTP_USE_SSL", "True"))
            else:
                # fallback for old configs
                self.smtp_use_ssl = parse_bool(loaded.get("SMTP_USE_TLS", "True"))

            print("[Email] Loaded email config from %s" % path)
            return True

        except Exception as e:
            print("[Email] Failed applying config values from %s: %s" % (path, e))
            return False

    def _apply_setting_changed(self, key, value):
        try:
            if key == "EMAIL_ENABLE":
                self.email_enable = parse_bool(value)

            elif key == "ALERT_COOLDOWN_SECONDS":
                self.alert_cooldown_seconds = max(0, int(float(value or 1800)))

            elif key == "ALERT_SEND_RECOVERY_EMAILS":
                self.alert_send_recovery_emails = parse_bool(value)

        except Exception as e:
            print("[Email] Failed applying setting %s=%r: %s" % (key, value, e))

    def _can_send_email(self):
        if not self.email_enable:
            return False, "EMAIL_ENABLE=False"

        if not self.email_to:
            return False, "EMAIL_TO missing"

        if not self.email_from:
            return False, "EMAIL_FROM missing"

        if not self.smtp_host:
            return False, "SMTP_HOST missing"

        if not self.smtp_port:
            return False, "SMTP_PORT missing"

        return True, "ok"

    def _cooldown_key(self, alert_key, is_recovery):
        return "%s|%s" % (alert_key, "recovery" if is_recovery else "alert")

    def _should_send_alert(self, alert_key, is_recovery):
        if is_recovery and (not self.alert_send_recovery_emails):
            return False, "recovery emails disabled"

        now = time.time()
        cooldown_key = self._cooldown_key(alert_key, is_recovery)
        last_sent = self.last_sent_by_key.get(cooldown_key)

        if last_sent is None:
            return True, "first send"

        if (now - last_sent) < float(self.alert_cooldown_seconds):
            return False, "cooldown active"

        return True, "cooldown expired"

    def _mark_sent(self, alert_key, is_recovery):
        cooldown_key = self._cooldown_key(alert_key, is_recovery)
        self.last_sent_by_key[cooldown_key] = time.time()

    def _build_subject(self, payload):
        subject = str((payload or {}).get("subject") or "").strip()
        if subject:
            return subject

        subsystem = str((payload or {}).get("subsystem") or "SYSTEM").upper()
        event = str((payload or {}).get("event") or "UNKNOWN").upper()
        is_recovery = bool((payload or {}).get("is_recovery"))

        prefix = "RECOVERY" if is_recovery else "ALERT"
        return "DwellPi %s: %s %s" % (prefix, subsystem, event)

    def _build_body(self, payload):
        payload = payload or {}

        lines = []
        lines.append("DwellPi notification")
        lines.append("")
        lines.append("Host: %s" % socket.gethostname())
        lines.append("Mode: %s" % self.mode)
        lines.append("Subsystem: %s" % str(payload.get("subsystem") or "--"))
        lines.append("Event: %s" % str(payload.get("event") or "--"))
        lines.append("Severity: %s" % str(payload.get("severity") or "--"))
        lines.append("Time: %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        lines.append("")

        message = str(payload.get("body") or "").strip()
        if message:
            lines.append(message)
            lines.append("")

        extra = payload.get("extra") or {}
        if isinstance(extra, dict) and extra:
            lines.append("Details:")
            for k in sorted(extra.keys()):
                try:
                    lines.append("- %s: %r" % (k, extra[k]))
                except Exception:
                    pass

        return "\n".join(lines).strip() + "\n"

    def _send_email(self, subject, body):
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        smtp = None
        try:
            recipients = [addr.strip() for addr in self.email_to.split(",") if addr.strip()]
            if not recipients:
                return False, "No valid recipients"

            print("[Email] Connecting to SMTP host=%s port=%s ssl=%s" % (
                self.smtp_host, self.smtp_port, self.smtp_use_ssl
            ))

            if self.smtp_use_ssl:
                smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20)
                print("[Email] SMTP_SSL connection created")
                smtp.ehlo()
                print("[Email] EHLO completed over SSL")
            else:
                smtp = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20)
                print("[Email] SMTP connection created")
                smtp.ehlo()
                print("[Email] EHLO completed")

            if self.smtp_username:
                print("[Email] Attempting SMTP login as %s" % self.smtp_username)
                smtp.login(self.smtp_username, self.smtp_password)
                print("[Email] SMTP login successful")

            print("[Email] Sending email to %s" % recipients)
            smtp.sendmail(self.email_from, recipients, msg.as_string())
            print("[Email] SMTP sendmail successful")

            return True, None

        except Exception as e:
            print("[Email] _send_email exception: %s" % e)
            return False, str(e)

        finally:
            try:
                if smtp is not None:
                    smtp.quit()
            except Exception:
                pass

    def _handle_test_email(self, msg):
        can_send, reason = self._can_send_email()

        # Override EMAIL_ENABLE for manual tests
        if not can_send and reason == "EMAIL_ENABLE=False":
            can_send = True
        if not can_send:
            print("[Email] Test email not sent: %s" % reason)
            try:
                self.db_queue.put(Message("email", "state_change", {
                    "system": "EMAIL",
                    "state": "TEST_EMAIL_NOT_SENT: %s" % reason
                }))
            except Exception:
                pass
            return

        subject = "DwellPi Test Email"
        body = "\n".join([
            "This is a manual DwellPi test email.",
            "",
            "Host: %s" % socket.gethostname(),
            "Mode: %s" % self.mode,
            "Time: %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "",
            "If you received this, SMTP configuration is working."
        ]) + "\n"

        ok, err = self._send_email(subject, body)

        if ok:
            print("[Email] Test email sent")
            try:
                self.db_queue.put(Message("email", "state_change", {
                    "system": "EMAIL",
                    "state": "TEST_EMAIL_SENT"
                }))
            except Exception:
                pass
        else:
            print("[Email] Test email failed: %s" % err)
            try:
                self.db_queue.put(Message("email", "state_change", {
                    "system": "EMAIL",
                    "state": "TEST_EMAIL_FAILED: %s" % err
                }))
            except Exception:
                pass

    def _handle_alert(self, msg):
        payload = msg.payload or {}

        alert_key = str(payload.get("alert_key") or "").strip()
        if not alert_key:
            print("[Email] Ignored alert with no alert_key")
            return

        is_recovery = bool(payload.get("is_recovery"))

        can_send, reason = self._can_send_email()
        if not can_send:
            print("[Email] Not sending %s: %s" % (alert_key, reason))
            return

        should_send, why = self._should_send_alert(alert_key, is_recovery)
        if not should_send:
            print("[Email] Suppressed %s: %s" % (alert_key, why))
            return

        subject = self._build_subject(payload)
        body = self._build_body(payload)

        ok, err = self._send_email(subject, body)
        if ok:
            self._mark_sent(alert_key, is_recovery)
            print("[Email] Sent: %s" % alert_key)
            try:
                self.db_queue.put(Message("email", "state_change", {
                    "system": "EMAIL",
                    "state": "SENT_%s" % alert_key.upper()
                }))
            except Exception:
                pass
        else:
            print("[Email] Send failed for %s: %s" % (alert_key, err))
            try:
                self.db_queue.put(Message("email", "state_change", {
                    "system": "EMAIL",
                    "state": "SEND_FAILED_%s: %s" % (alert_key.upper(), err)
                }))
            except Exception:
                pass

    def run(self):
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        print("[Email] Started in mode: %s" % self.mode)

        try:
            self.db_queue.put(Message("email", "request_settings_snapshot", {}))
        except Exception:
            pass

        ok = self.wait_for_initial_snapshot(timeout=3.0)
        if not ok:
            print("[Email] No settings snapshot received yet; using defaults")

        self._load_email_config_file()

        last_hb = 0.0

        while not self.shutdown_event.is_set():
            self.drain_ctrl_queue()

            now = time.time()
            if now - last_hb >= 5.0:
                try:
                    self.db_queue.put(Message("email", "heartbeat", {"status": "ok"}))
                except Exception:
                    pass
                last_hb = now

            try:
                msg = self.email_queue.get(timeout=1.0)
            except QueueEmpty:
                continue
            except Exception as e:
                print("[Email] email_queue get failed: %s" % e)
                continue

            try:
                if msg.type == "email_alert":
                    self._handle_alert(msg)

                elif msg.type == "test_email":
                    self._handle_test_email(msg)

                elif msg.type == "reload_email_config":
                    self._load_email_config_file()

                elif msg.type == "shutdown":
                    break

            except Exception as e:
                print("[Email] ERROR handling %s: %s" % (getattr(msg, "type", "?"), e))

        print("[Email] Shutting down cleanly")