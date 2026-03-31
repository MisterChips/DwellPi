#!/usr/bin/python
# -*- coding: utf-8 -*-
# supervisor.py

from __future__ import print_function

import sys, multiprocessing, time, signal, os

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
        args=(db_queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue,
              ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event,)
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


def start_ui(ui_queue, ui_ctrl_queue, db_queue, mode, shutdown_event):
    ui_obj = UIProcess(ui_queue, ui_ctrl_queue, db_queue, mode, shutdown_event)
    p = multiprocessing.Process(target=ui_obj.run)
    p.start()
    return p


def start_web(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue,
              mode, db_path, shutdown_event):
    web_obj = WebProcess(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue, mode, db_path, shutdown_event)
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
    rpc = None

    initialise_database(DB_PATH)

    last_restart = {"engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0, "db": 0}
    last_hb = {"engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0}

    db_process = start_db(
        DB_PATH, MODE, db_queue, engine_ctrl_queue, sensor_ctrl_queue,
        relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue,
        supervisor_queue, shutdown_event
    )

    db_ready = wait_for_db_ready(supervisor_queue, shutdown_event, timeout=5.0)

    if not db_ready:
        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
    else:
        relay_process = start_relay(
            relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue,
            rpc_reply_queue, engine_rpc_queue, web_rpc_queue, MODE, shutdown_event
        )
        engine_process = start_engine(
            engine_queue, engine_rpc_queue, ui_queue, web_queue,
            db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event
        )
        sensor_process = start_sensor(
            engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event
        )
        ui_process = start_ui(ui_queue, ui_ctrl_queue, db_queue, MODE, shutdown_event)
        web_process = start_web(
            web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue, MODE, DB_PATH, shutdown_event
        )

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
                    if src:
                        last_hb[src] = now

                elif msg.type == "system_action_request":
                    action = (msg.payload or {}).get("action")
                    requested_system_action = perform_system_action(action, shutdown_event) or requested_system_action

                elif msg.type == "db_ready":
                    if not db_ready:
                        print("[Supervisor] DB reported ready")
                    db_ready = True

            if shutdown_event.is_set():
                break

            # ---- DB FIRST ----
            if not db_process.is_alive():
                db_ready = False
                if now - last_restart["db"] >= MIN_RESTART_GAP:
                    print("[Supervisor] DB died - restarting (and stopping engine/sensor/relay/ui/web)")
                    last_restart["db"] = now

                    for p in (engine_process, sensor_process, relay_process, ui_process, web_process):
                        if p is not None and p.is_alive():
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

                    db_ready = wait_for_db_ready(supervisor_queue, shutdown_event, timeout=5.0)

                    if not db_ready:
                        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
                        engine_process = None
                        sensor_process = None
                        relay_process = None
                        ui_process = None
                        web_process = None
                    else:
                        last_hb["engine"] = 0
                        last_hb["sensor"] = 0
                        last_hb["relay"] = 0
                        last_hb["ui"] = 0
                        last_hb["web"] = 0

                        log_supervisor_state(db_queue, "DB", "RESTARTED_DB_DIED")

            # ---- Watchdog timeouts ----
            if engine_process is not None and engine_process.is_alive():
                if last_hb["engine"] and (now - last_hb["engine"] > HEARTBEAT_TIMEOUT_ENGINE):
                    print("[Supervisor] Engine heartbeat timeout - restarting engine")
                    log_supervisor_state(db_queue, "ENGINE", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        engine_process.terminate()
                        engine_process.join(2)
                    except Exception:
                        pass
                    engine_process = None
                    engine_restarted_this_tick = True

            if sensor_process is not None and sensor_process.is_alive():
                if last_hb["sensor"] and (now - last_hb["sensor"] > HEARTBEAT_TIMEOUT_SENSOR):
                    print("[Supervisor] Sensor heartbeat timeout - restarting sensor")
                    log_supervisor_state(db_queue, "SENSOR", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        sensor_process.terminate()
                        sensor_process.join(2)
                    except Exception:
                        pass
                    sensor_process = None
                    sensor_restarted_this_tick = True

            if relay_process is not None and relay_process.is_alive():
                if last_hb["relay"] and (now - last_hb["relay"] > HEARTBEAT_TIMEOUT_RELAY):
                    print("[Supervisor] Relay heartbeat timeout - restarting relay")
                    log_supervisor_state(db_queue, "RELAY", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        relay_process.terminate()
                        relay_process.join(2)
                    except Exception:
                        pass
                    relay_process = None
                    relay_restarted_this_tick = True

            if ui_process is not None and ui_process.is_alive():
                if last_hb["ui"] and (now - last_hb["ui"] > HEARTBEAT_TIMEOUT_UI):
                    print("[Supervisor] UI heartbeat timeout - restarting ui")
                    log_supervisor_state(db_queue, "UI", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        ui_process.terminate()
                        ui_process.join(2)
                    except Exception:
                        pass
                    ui_process = None
                    ui_restarted_this_tick = True

            if web_process is not None and web_process.is_alive():
                if last_hb["web"] and (now - last_hb["web"] > HEARTBEAT_TIMEOUT_WEB):
                    print("[Supervisor] Web heartbeat timeout - restarting web")
                    log_supervisor_state(db_queue, "WEB", "RESTARTED_HEARTBEAT_TIMEOUT")
                    try:
                        web_process.terminate()
                        web_process.join(2)
                    except Exception:
                        pass
                    web_process = None
                    web_restarted_this_tick = True

            # ---- Restart Engine/Sensor/Relay/UI/Web only if DB alive and ready” ----
            if db_process.is_alive() and db_ready:
                if (engine_process is None or (not engine_process.is_alive())) and (not engine_restarted_this_tick):
                    if now - last_restart["engine"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Engine not running - starting")
                        log_supervisor_state(db_queue, "ENGINE", "RESTARTED_NOT_RUNNING")
                        last_restart["engine"] = now
                        engine_process = start_engine(
                            engine_queue, engine_rpc_queue, ui_queue, web_queue,
                            db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event
                        )
                        last_hb["engine"] = 0

                if (sensor_process is None or (not sensor_process.is_alive())) and (not sensor_restarted_this_tick):
                    if now - last_restart["sensor"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Sensor not running - starting")
                        log_supervisor_state(db_queue, "SENSOR", "RESTARTED_NOT_RUNNING")
                        last_restart["sensor"] = now
                        sensor_process = start_sensor(
                            engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event
                        )
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
                        last_hb["relay"] = 0

                if (ui_process is None or (not ui_process.is_alive())) and (not ui_restarted_this_tick):
                    if now - last_restart["ui"] >= MIN_RESTART_GAP:
                        print("[Supervisor] UI not running - starting")
                        log_supervisor_state(db_queue, "UI", "RESTARTED_NOT_RUNNING")
                        last_restart["ui"] = now
                        ui_process = start_ui(ui_queue, ui_ctrl_queue, db_queue, MODE, shutdown_event)
                        last_hb["ui"] = 0

                if (web_process is None or (not web_process.is_alive())) and (not web_restarted_this_tick):
                    if now - last_restart["web"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Web not running - starting")
                        log_supervisor_state(db_queue, "WEB", "RESTARTED_NOT_RUNNING")
                        last_restart["web"] = now
                        web_process = start_web(
                            web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue,
                            MODE, DB_PATH, shutdown_event
                        )
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