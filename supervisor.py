#!/usr/bin/python
# -*- coding: utf-8 -*-
# supervisor.py

from __future__ import print_function

import sys
import multiprocessing
import time
import signal
import os

from db_init import initialise_database
from db_worker import DBWorker
from engine_process import EngineProcess
from sensor_process import SensorProcess
from relay_process import RelayProcess
from ui_process import UIProcess
from web_process import WebProcess
from message_schema import Message
from rpc_server import RpcServer


# ===== Runtime Mode =====
MODE = "TEST"  # safe default while migrating
if "--prod" in sys.argv:
    MODE = "PRODUCTION"
# ========================

DB_PATH = "/home/pi/heating.db" if MODE == "PRODUCTION" else "/home/pi/heating_test.db"

MIN_RESTART_GAP = 10
SUPERVISOR_TICK = 5

HEARTBEAT_TIMEOUT_ENGINE = 15
HEARTBEAT_TIMEOUT_SENSOR = 20
HEARTBEAT_TIMEOUT_RELAY = 20
HEARTBEAT_TIMEOUT_UI = 20
HEARTBEAT_TIMEOUT_WEB = 20

PROCESS_START_GRACE = 20


def handle_sigterm(signum, frame):
    print("[Supervisor] Received SIGTERM. Triggering graceful shutdown...")
    shutdown_event.set()


def log_supervisor_state(db_queue, system, state):
    try:
        db_queue.put(Message("supervisor", "state_change", {
            "system": system,
            "state": state
        }))
    except Exception:
        pass


def start_db(db_path, mode, db_queue, engine_ctrl_queue, sensor_ctrl_queue,
             relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue,
             supervisor_queue, shutdown_event):
    db_worker = DBWorker(db_path, mode)
    p = multiprocessing.Process(
        target=db_worker.run,
        args=(
            db_queue,
            engine_ctrl_queue,
            sensor_ctrl_queue,
            relay_ctrl_queue,
            ui_ctrl_queue,
            web_ctrl_queue,
            supervisor_queue,
            shutdown_event,
        )
    )
    p.start()
    return p


def start_engine(engine_queue, engine_rpc_queue, ui_queue, web_queue,
                 db_queue, engine_ctrl_queue, relay_queue, mode,
                 db_path, shutdown_event):
    engine_obj = EngineProcess(
        engine_queue,
        engine_rpc_queue,
        ui_queue,
        web_queue,
        db_queue,
        engine_ctrl_queue,
        relay_queue,
        mode,
        db_path,
        shutdown_event
    )
    p = multiprocessing.Process(target=engine_obj.run)
    p.start()
    return p


def start_sensor(engine_queue, db_queue, sensor_ctrl_queue, ui_queue,
                 web_queue, mode, shutdown_event):
    sensor_obj = SensorProcess(
        engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, mode, shutdown_event
    )
    p = multiprocessing.Process(target=sensor_obj.run)
    p.start()
    return p


def start_relay(relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue,
                rpc_reply_queue, engine_rpc_queue, web_rpc_queue,
                mode, shutdown_event):
    relay_obj = RelayProcess(
        relay_queue,
        db_queue,
        relay_ctrl_queue,
        ui_queue,
        web_queue,
        mode,
        shutdown_event,
        rpc_reply_queue=rpc_reply_queue,
        engine_rpc_queue=engine_rpc_queue,
        web_rpc_queue=web_rpc_queue
    )
    p = multiprocessing.Process(target=relay_obj.run)
    p.start()
    return p


def start_ui(ui_queue, ui_ctrl_queue, db_queue, supervisor_request_queue, mode, shutdown_event):
    ui_obj = UIProcess(ui_queue, ui_ctrl_queue, db_queue, supervisor_request_queue, mode, shutdown_event)
    p = multiprocessing.Process(target=ui_obj.run)
    p.start()
    return p


def start_web(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue,
              supervisor_queue, mode, db_path, shutdown_event):
    web_obj = WebProcess(
        web_queue,
        web_ctrl_queue,
        db_queue,
        relay_queue,
        web_rpc_queue,
        supervisor_queue,
        mode,
        db_path,
        shutdown_event
    )
    p = multiprocessing.Process(target=web_obj.run)
    p.start()
    return p


def perform_system_action(action, shutdown_event):
    action = str(action or "").strip().lower()

    if action == "restart_dwellpi":
        print("[Supervisor] restart_dwellpi requested")
        shutdown_event.set()
        return "restart_dwellpi"

    if action == "reboot_pi":
        print("[Supervisor] reboot_pi requested")
        shutdown_event.set()
        return "reboot_pi"

    return None


def wait_for_db_ready(supervisor_queue, shutdown_event, timeout=5.0):
    deadline = time.time() + float(timeout)
    while time.time() < deadline and not shutdown_event.is_set():
        try:
            m = supervisor_queue.get(timeout=0.5)
            if m.type == "db_ready":
                return True
        except Exception:
            pass
    return False


def _safe_is_alive(proc):
    return proc is not None and proc.is_alive()


def _mark_started(name, last_started, restart_counts):
    now = time.time()
    last_started[name] = now
    restart_counts[name] += 1
    return now


def _heartbeat_age(name, last_hb, now):
    ts = last_hb.get(name, 0) or 0
    if ts <= 0:
        return None
    return max(0.0, now - ts)


def _started_age(name, last_started, now):
    ts = last_started.get(name, 0) or 0
    if ts <= 0:
        return None
    return max(0.0, now - ts)


def _in_start_grace(name, last_started, now):
    started_at = last_started.get(name, 0) or 0
    if started_at <= 0:
        return False
    return (now - started_at) < PROCESS_START_GRACE


def _build_process_status(name, proc, last_hb, last_started, restart_counts, timeout, now):
    alive = _safe_is_alive(proc)
    hb_age = _heartbeat_age(name, last_hb, now)
    started_age = _started_age(name, last_started, now)
    in_grace = _in_start_grace(name, last_started, now)

    timed_out = False
    if alive and (hb_age is not None) and (not in_grace) and hb_age > timeout:
        timed_out = True

    return {
        "alive": alive,
        "heartbeat_age": hb_age,
        "started_age": started_age,
        "restart_count": int(restart_counts.get(name, 0) or 0),
        "start_grace_active": in_grace,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
    }


def _build_supervisor_status(mode, db_path, db_ready, procs, last_hb, last_started, restart_counts):
    now = time.time()

    return {
        "ok": True,
        "mode": mode,
        "db_path": db_path,
        "db_ready": bool(db_ready),
        "timestamp": now,
        "processes": {
            "db": {
                "alive": _safe_is_alive(procs.get("db")),
                "started_age": _started_age("db", last_started, now),
                "restart_count": int(restart_counts.get("db", 0) or 0),
                "start_grace_active": _in_start_grace("db", last_started, now),
            },
            "engine": _build_process_status("engine", procs.get("engine"), last_hb, last_started, restart_counts, HEARTBEAT_TIMEOUT_ENGINE, now),
            "sensor": _build_process_status("sensor", procs.get("sensor"), last_hb, last_started, restart_counts, HEARTBEAT_TIMEOUT_SENSOR, now),
            "relay": _build_process_status("relay", procs.get("relay"), last_hb, last_started, restart_counts, HEARTBEAT_TIMEOUT_RELAY, now),
            "ui": _build_process_status("ui", procs.get("ui"), last_hb, last_started, restart_counts, HEARTBEAT_TIMEOUT_UI, now),
            "web": _build_process_status("web", procs.get("web"), last_hb, last_started, restart_counts, HEARTBEAT_TIMEOUT_WEB, now),
        }
    }


def _reply_queue_for_source(source, ui_ctrl_queue, web_ctrl_queue):
    if source == "ui":
        return ui_ctrl_queue
    if source == "web":
        return web_ctrl_queue
    return None


if __name__ == "__main__":
    print("================================")
    print("  Heating System Starting")
    print("  MODE:", MODE)
    print("  DB:", DB_PATH)
    print("================================")

    shutdown_event = multiprocessing.Event()
    signal.signal(signal.SIGTERM, handle_sigterm)

    db_queue = multiprocessing.Queue()
    engine_queue = multiprocessing.Queue()
    relay_queue = multiprocessing.Queue()

    engine_ctrl_queue = multiprocessing.Queue()
    sensor_ctrl_queue = multiprocessing.Queue()
    supervisor_queue = multiprocessing.Queue()
    supervisor_request_queue = multiprocessing.Queue()
    relay_ctrl_queue = multiprocessing.Queue()
    rpc_reply_queue = multiprocessing.Queue()
    engine_rpc_queue = multiprocessing.Queue()
    web_rpc_queue = multiprocessing.Queue()
    ui_ctrl_queue = multiprocessing.Queue()
    ui_queue = multiprocessing.Queue()
    web_queue = multiprocessing.Queue()
    web_ctrl_queue = multiprocessing.Queue()

    engine_process = None
    sensor_process = None
    relay_process = None
    ui_process = None
    web_process = None
    db_process = None
    rpc = None

    initialise_database(DB_PATH)

    last_restart = {
        "engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0, "db": 0
    }
    last_hb = {
        "engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0
    }
    last_started = {
        "engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0, "db": 0
    }
    restart_counts = {
        "engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0, "db": 0
    }

    db_process = start_db(
        DB_PATH, MODE, db_queue, engine_ctrl_queue, sensor_ctrl_queue,
        relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue,
        supervisor_queue, shutdown_event
    )
    _mark_started("db", last_started, restart_counts)

    db_ready = wait_for_db_ready(supervisor_queue, shutdown_event, timeout=5.0)

    if not db_ready:
        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
    else:
        relay_process = start_relay(
            relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue,
            rpc_reply_queue, engine_rpc_queue, web_rpc_queue, MODE, shutdown_event
        )
        _mark_started("relay", last_started, restart_counts)

        engine_process = start_engine(
            engine_queue, engine_rpc_queue, ui_queue, web_queue,
            db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event
        )
        _mark_started("engine", last_started, restart_counts)

        sensor_process = start_sensor(
            engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event
        )
        _mark_started("sensor", last_started, restart_counts)

        ui_process = start_ui(
            ui_queue, ui_ctrl_queue, db_queue, supervisor_request_queue, MODE, shutdown_event
        )
        _mark_started("ui", last_started, restart_counts)

        web_process = start_web(
            web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue,
            supervisor_request_queue, MODE, DB_PATH, shutdown_event
        )
        _mark_started("web", last_started, restart_counts)

    rpc = RpcServer("/tmp/dwellpi.sock", relay_queue, rpc_reply_queue, ui_queue, shutdown_event)
    rpc.start()

    requested_system_action = None

    try:
        while not shutdown_event.is_set():
            now = time.time()

            engine_restarted_this_tick = False
            sensor_restarted_this_tick = False
            relay_restarted_this_tick = False
            ui_restarted_this_tick = False
            web_restarted_this_tick = False

            while True:
                try:
                    msg = supervisor_queue.get_nowait()
                except Exception:
                    break

                if msg.type == "heartbeat_notice":
                    src = (msg.payload or {}).get("source")
                    if src in last_hb:
                        last_hb[src] = now

                elif msg.type == "system_action_request":
                    action = (msg.payload or {}).get("action")
                    requested_system_action = perform_system_action(action, shutdown_event) or requested_system_action

                elif msg.type == "db_ready":
                    if not db_ready:
                        print("[Supervisor] DB reported ready")
                    db_ready = True

            while True:
                try:
                    msg = supervisor_request_queue.get_nowait()
                except Exception:
                    break

                if msg.type == "get_supervisor_status":
                    reply_q = _reply_queue_for_source(msg.source, ui_ctrl_queue, web_ctrl_queue)
                    if reply_q is None:
                        continue

                    status_payload = _build_supervisor_status(
                        MODE,
                        DB_PATH,
                        db_ready,
                        {
                            "db": db_process,
                            "engine": engine_process,
                            "sensor": sensor_process,
                            "relay": relay_process,
                            "ui": ui_process,
                            "web": web_process,
                        },
                        last_hb,
                        last_started,
                        restart_counts
                    )

                    try:
                        reply_q.put(Message(
                            "supervisor",
                            "supervisor_status_result",
                            status_payload,
                            target=msg.source,
                            request_id=getattr(msg, "request_id", None)
                        ))
                    except Exception:
                        pass
                    continue

                if msg.type == "restart_process":
                    p = msg.payload or {}
                    proc_name = str(p.get("name") or "").strip().lower()


                    reply_q = _reply_queue_for_source(msg.source, ui_ctrl_queue, web_ctrl_queue)
                    if reply_q is None:
                        continue

                    allowed = ("engine", "sensor", "relay", "ui", "web")
                    if proc_name not in allowed:
                        try:
                            reply_q.put(Message(
                                "supervisor",
                                "restart_process_result",
                                {"ok": False, "error": "Invalid process name", "name": proc_name},
                                target=msg.source,
                                request_id=getattr(msg, "request_id", None)
                            ))
                        except Exception:
                            pass
                        continue

                    was_running = False

                    try:
                        if proc_name == "engine" and _safe_is_alive(engine_process):
                            was_running = True
                            engine_process.terminate()
                            engine_process.join(2)
                            engine_process = None
                            last_restart["engine"] = 0
                            last_hb["engine"] = 0

                        elif proc_name == "sensor" and _safe_is_alive(sensor_process):
                            was_running = True
                            sensor_process.terminate()
                            sensor_process.join(2)
                            sensor_process = None
                            last_restart["sensor"] = 0
                            last_hb["sensor"] = 0

                        elif proc_name == "relay" and _safe_is_alive(relay_process):
                            was_running = True
                            relay_process.terminate()
                            relay_process.join(2)
                            relay_process = None
                            last_restart["relay"] = 0
                            last_hb["relay"] = 0

                        elif proc_name == "ui" and _safe_is_alive(ui_process):
                            was_running = True
                            ui_process.terminate()
                            ui_process.join(2)
                            ui_process = None
                            last_restart["ui"] = 0
                            last_hb["ui"] = 0

                        elif proc_name == "web" and _safe_is_alive(web_process):
                            was_running = True
                            web_process.terminate()
                            web_process.join(2)
                            web_process = None
                            last_restart["web"] = 0
                            last_hb["web"] = 0

                        log_supervisor_state(db_queue, proc_name.upper(), "RESTART_REQUESTED")

                        try:
                            reply_q.put(Message(
                                "supervisor",
                                "restart_process_result",
                                {"ok": True, "name": proc_name, "was_running": was_running},
                                target=msg.source,
                                request_id=getattr(msg, "request_id", None)
                            ))
                        except Exception:
                            pass

                    except Exception as e:
                        try:
                            reply_q.put(Message(
                                "supervisor",
                                "restart_process_result",
                                {"ok": False, "error": str(e), "name": proc_name},
                                target=msg.source,
                                request_id=getattr(msg, "request_id", None)
                            ))
                        except Exception:
                            pass
                    continue

                print("[Supervisor] WARNING: unknown supervisor request %r from %r" % (
                    getattr(msg, "type", None), getattr(msg, "source", None)
                ))
                continue

            if shutdown_event.is_set():
                break

            # ---- DB FIRST ----
            if not _safe_is_alive(db_process):
                db_ready = False

                if now - last_restart["db"] >= MIN_RESTART_GAP:
                    print("[Supervisor] DB died - restarting (and stopping engine/sensor/relay/ui/web)")
                    last_restart["db"] = now
                    log_supervisor_state(db_queue, "DB", "RESTARTED_DB_DIED")

                    for p in (engine_process, sensor_process, relay_process, ui_process, web_process):
                        if _safe_is_alive(p):
                            try:
                                p.terminate()
                                p.join(2)
                            except Exception:
                                pass

                    engine_process = None
                    sensor_process = None
                    relay_process = None
                    ui_process = None
                    web_process = None

                    db_process = start_db(
                        DB_PATH, MODE, db_queue, engine_ctrl_queue, sensor_ctrl_queue,
                        relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue,
                        supervisor_queue, shutdown_event
                    )
                    _mark_started("db", last_started, restart_counts)

                    db_ready = wait_for_db_ready(supervisor_queue, shutdown_event, timeout=5.0)

                    if not db_ready:
                        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
                    else:
                        last_hb["engine"] = 0
                        last_hb["sensor"] = 0
                        last_hb["relay"] = 0
                        last_hb["ui"] = 0
                        last_hb["web"] = 0

            # ---- Watchdog timeouts with start grace ----
            if _safe_is_alive(engine_process):
                hb_age = _heartbeat_age("engine", last_hb, now)
                if hb_age is not None and (not _in_start_grace("engine", last_started, now)) and hb_age > HEARTBEAT_TIMEOUT_ENGINE:
                    print("[Supervisor] Engine heartbeat timeout - restarting engine")
                    log_supervisor_state(db_queue, "ENGINE", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        engine_process.terminate()
                        engine_process.join(2)
                    except Exception:
                        pass
                    engine_process = None
                    engine_restarted_this_tick = True

            if _safe_is_alive(sensor_process):
                hb_age = _heartbeat_age("sensor", last_hb, now)
                if hb_age is not None and (not _in_start_grace("sensor", last_started, now)) and hb_age > HEARTBEAT_TIMEOUT_SENSOR:
                    print("[Supervisor] Sensor heartbeat timeout - restarting sensor")
                    log_supervisor_state(db_queue, "SENSOR", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        sensor_process.terminate()
                        sensor_process.join(2)
                    except Exception:
                        pass
                    sensor_process = None
                    sensor_restarted_this_tick = True

            if _safe_is_alive(relay_process):
                hb_age = _heartbeat_age("relay", last_hb, now)
                if hb_age is not None and (not _in_start_grace("relay", last_started, now)) and hb_age > HEARTBEAT_TIMEOUT_RELAY:
                    print("[Supervisor] Relay heartbeat timeout - restarting relay")
                    log_supervisor_state(db_queue, "RELAY", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        relay_process.terminate()
                        relay_process.join(2)
                    except Exception:
                        pass
                    relay_process = None
                    relay_restarted_this_tick = True

            if _safe_is_alive(ui_process):
                hb_age = _heartbeat_age("ui", last_hb, now)
                if hb_age is not None and (not _in_start_grace("ui", last_started, now)) and hb_age > HEARTBEAT_TIMEOUT_UI:
                    print("[Supervisor] UI heartbeat timeout - restarting ui")
                    log_supervisor_state(db_queue, "UI", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        ui_process.terminate()
                        ui_process.join(2)
                    except Exception:
                        pass
                    ui_process = None
                    ui_restarted_this_tick = True

            if _safe_is_alive(web_process):
                hb_age = _heartbeat_age("web", last_hb, now)
                if hb_age is not None and (not _in_start_grace("web", last_started, now)) and hb_age > HEARTBEAT_TIMEOUT_WEB:
                    print("[Supervisor] Web heartbeat timeout - restarting web")
                    log_supervisor_state(db_queue, "WEB", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        web_process.terminate()
                        web_process.join(2)
                    except Exception:
                        pass
                    web_process = None
                    web_restarted_this_tick = True

            # ---- Restart Engine/Sensor/Relay/UI/Web only if DB alive and ready ----
            if _safe_is_alive(db_process) and db_ready:
                if (engine_process is None or (not engine_process.is_alive())) and (not engine_restarted_this_tick):
                    if now - last_restart["engine"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Engine not running - starting")
                        log_supervisor_state(db_queue, "ENGINE", "RESTARTED_NOT_RUNNING")
                        last_restart["engine"] = now
                        engine_process = start_engine(
                            engine_queue, engine_rpc_queue, ui_queue, web_queue,
                            db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event
                        )
                        _mark_started("engine", last_started, restart_counts)
                        last_hb["engine"] = 0

                if (sensor_process is None or (not sensor_process.is_alive())) and (not sensor_restarted_this_tick):
                    if now - last_restart["sensor"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Sensor not running - starting")
                        log_supervisor_state(db_queue, "SENSOR", "RESTARTED_NOT_RUNNING")
                        last_restart["sensor"] = now
                        sensor_process = start_sensor(
                            engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event
                        )
                        _mark_started("sensor", last_started, restart_counts)
                        last_hb["sensor"] = 0

                if (relay_process is None or (not relay_process.is_alive())) and (not relay_restarted_this_tick):
                    if now - last_restart["relay"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Relay not running - starting")
                        log_supervisor_state(db_queue, "RELAY", "RESTARTED_NOT_RUNNING")
                        last_restart["relay"] = now
                        relay_process = start_relay(
                            relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue,
                            rpc_reply_queue, engine_rpc_queue, web_rpc_queue, MODE, shutdown_event
                        )
                        _mark_started("relay", last_started, restart_counts)
                        last_hb["relay"] = 0

                if (ui_process is None or (not ui_process.is_alive())) and (not ui_restarted_this_tick):
                    if now - last_restart["ui"] >= MIN_RESTART_GAP:
                        print("[Supervisor] UI not running - starting")
                        log_supervisor_state(db_queue, "UI", "RESTARTED_NOT_RUNNING")
                        last_restart["ui"] = now
                        ui_process = start_ui(
                            ui_queue, ui_ctrl_queue, db_queue, supervisor_request_queue, MODE, shutdown_event
                        )
                        _mark_started("ui", last_started, restart_counts)
                        last_hb["ui"] = 0

                if (web_process is None or (not web_process.is_alive())) and (not web_restarted_this_tick):
                    if now - last_restart["web"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Web not running - starting")
                        log_supervisor_state(db_queue, "WEB", "RESTARTED_NOT_RUNNING")
                        last_restart["web"] = now
                        web_process = start_web(
                            web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue,
                            supervisor_request_queue, MODE, DB_PATH, shutdown_event
                        )
                        _mark_started("web", last_started, restart_counts)
                        last_hb["web"] = 0

            if shutdown_event.is_set():
                break

            time.sleep(SUPERVISOR_TICK)

    except (KeyboardInterrupt, SystemExit):
        shutdown_event.set()

    print("[Supervisor] Cleaning up processes...")

    try:
        db_queue.put(Message("supervisor", "flush", {}))
    except Exception:
        pass

    shutdown_event.set()

    if rpc is not None:
        print("[Supervisor] Joining RPC...")
        try:
            rpc.join(timeout=2)
        except Exception:
            pass

    all_procs = {
        "Web": web_process,
        "UI": ui_process,
        "Sensor": sensor_process,
        "Engine": engine_process,
        "Relay": relay_process,
        "DB": db_process
    }

    for name, p in all_procs.items():
        if p and p.is_alive():
            print("[Supervisor] Joining %s..." % name)
            p.join(timeout=3)

    for name, p in all_procs.items():
        if p and p.is_alive():
            print("[Supervisor] %s refused to exit, terminating..." % name)
            p.terminate()

    print("[Supervisor] Shutdown complete.")

    if requested_system_action == "restart_dwellpi":
        print("[Supervisor] Executing restart_dwellpi")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    elif requested_system_action == "reboot_pi":
        print("[Supervisor] Executing reboot_pi")
        os.system("sudo /sbin/reboot")