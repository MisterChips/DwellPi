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

# Determine DB path
DB_PATH = "/home/pi/heating.db" if MODE == "PRODUCTION" else "/home/pi/heating_test.db"

# ADDRESS for DALLAS temperature sensor
# SENSOR_DEVICE_ID = "28-000007e4fecf"   # change if needed

# Relay board LLAP device id (legacy default)
#RELAY_BOARD_DEVICE_ID = "RB"  # >>> ADD (you can make this a DB setting later)

MIN_RESTART_GAP = 10            # seconds
SUPERVISOR_TICK = 5             # seconds
HEARTBEAT_TIMEOUT_ENGINE = 15   # seconds
HEARTBEAT_TIMEOUT_SENSOR = 20   # seconds
HEARTBEAT_TIMEOUT_RELAY  = 20   # seconds
HEARTBEAT_TIMEOUT_UI = 20       # seconds
HEARTBEAT_TIMEOUT_WEB = 20      # seconds


def handle_sigterm(signum, frame):
    print("[Supervisor] Received SIGTERM. Triggering graceful shutdown...")
    shutdown_event.set()

def start_db(db_path, mode, db_queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event):
    db_worker = DBWorker(db_path, mode)
    p = multiprocessing.Process(
        target=db_worker.run,
        args=(db_queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event,)
    )
    p.start()
    return p

def start_engine(engine_queue, engine_rpc_queue, ui_queue, web_queue, db_queue, engine_ctrl_queue, relay_queue, mode, db_path, shutdown_event):
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

def start_sensor(engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, mode, shutdown_event):
    sensor_obj = SensorProcess(engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, mode, shutdown_event)
    p = multiprocessing.Process(target=sensor_obj.run)
    p.start()
    return p

def start_relay(relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue, rpc_reply_queue, engine_rpc_queue, web_rpc_queue, mode, shutdown_event):
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

def start_web(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue, mode, db_path, shutdown_event):
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

if __name__ == "__main__":
    print("================================")
    print("  Heating System Starting")
    print("  MODE:", MODE)
    print("  DB:", DB_PATH)
    print("================================")

    signal.signal(signal.SIGTERM, handle_sigterm)

    # Shared queues (must be created here, then inherited by child processes)
    db_queue = multiprocessing.Queue()
    engine_queue = multiprocessing.Queue()
    relay_queue = multiprocessing.Queue()  # >>> ADD

    engine_ctrl_queue = multiprocessing.Queue()     # DB -> Engine push
    sensor_ctrl_queue = multiprocessing.Queue()     # DB -> Sensor push
    supervisor_queue = multiprocessing.Queue()      # DB -> Supervisor heartbeat notices
    relay_ctrl_queue = multiprocessing.Queue()      # DB -> Relay push
    rpc_reply_queue = multiprocessing.Queue()
    engine_rpc_queue = multiprocessing.Queue()
    web_rpc_queue = multiprocessing.Queue()
    ui_ctrl_queue = multiprocessing.Queue()         # User Interface Control
    ui_queue = multiprocessing.Queue()              # User Interface Queue
    web_queue = multiprocessing.Queue()
    web_ctrl_queue = multiprocessing.Queue()

    shutdown_event = multiprocessing.Event()
    engine_process = None
    sensor_process = None
    relay_process = None
    ui_process = None
    web_process = None

    # Ensure DB schema & defaults exist before starting anything else
    initialise_database(DB_PATH)

    last_restart = {"engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0, "db": 0}
    last_hb = {"engine": 0, "sensor": 0, "relay": 0, "ui": 0, "web": 0}

    # Start DB first
    db_process = start_db(DB_PATH, MODE, db_queue, engine_ctrl_queue, sensor_ctrl_queue, relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event)

    # Wait for DB ready signal (max 5s)
    db_ready = False
    deadline = time.time() + 5.0
    while time.time() < deadline and not shutdown_event.is_set():
        try:
            m = supervisor_queue.get(timeout=0.5)
            if m.type == "db_ready":
                db_ready = True
                break
        except Exception:
            pass

    rpc = None

    if not db_ready:
        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
    else:
        relay_process = start_relay(relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue, rpc_reply_queue, engine_rpc_queue, web_rpc_queue, MODE, shutdown_event)
        engine_process = start_engine(engine_queue, engine_rpc_queue, ui_queue, web_queue, db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event)
        sensor_process = start_sensor(engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event)
        ui_process = start_ui(ui_queue, ui_ctrl_queue, db_queue, MODE, shutdown_event)
        web_process = start_web(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue, MODE, DB_PATH, shutdown_event)

    rpc = RpcServer("/tmp/dwellpi.sock", relay_queue, rpc_reply_queue, ui_queue, shutdown_event)
    rpc.start()

    # ONE-SHOT interval test
    # >>> OPTIONAL: one-shot interval test (NOT inside the loop)
    #did_interval_test = False
    #interval_test_at = time.time() + 10.0  # run once ~10s after start

    # Supervisor loop
    requested_system_action = None

    try:
        while not shutdown_event.is_set():
            now = time.time()
            pending_system_action = None

            # Drain supervisor queue
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

            if shutdown_event.is_set():
                break

            # ---- DB FIRST ----
            if not db_process.is_alive():
                if now - last_restart["db"] >= MIN_RESTART_GAP:
                    print("[Supervisor] DB died - restarting (and stopping engine/sensor/relay/ui/web)")
                    last_restart["db"] = now

                    # Stop dependents
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

                    db_process = start_db(DB_PATH, MODE, db_queue, engine_ctrl_queue, sensor_ctrl_queue,
                                          relay_ctrl_queue, ui_ctrl_queue, web_ctrl_queue, supervisor_queue, shutdown_event)

                    db_ready = False
                    deadline = time.time() + 5.0
                    while time.time() < deadline and not shutdown_event.is_set():
                        try:
                            m = supervisor_queue.get(timeout=0.5)
                            if m.type == "db_ready":
                                db_ready = True
                                break
                        except Exception:
                            pass

                    if not db_ready:
                        print("[Supervisor] DB did not report ready; holding engine/sensor/relay/ui/web")
                        engine_process = None
                        sensor_process = None
                        relay_process = None
                        ui_process = None
                        web_process = None
                    else:
                        # clear heartbeat times so watchdog doesn't fire immediately on fresh starts
                        last_hb["engine"] = 0
                        last_hb["sensor"] = 0
                        last_hb["relay"]  = 0
                        last_hb["ui"] = 0
                        last_hb["web"] = 0

            # ONE-SHOT interval test
            # >>> OPTIONAL: one-shot interval test safely
            #if (not did_interval_test) and db_process.is_alive() and (now >= interval_test_at):
            #    try:
            #        db_queue.put(Message("supervisor", "set_setting", {"key": "ENGINE_INTERVAL", "value": "1"}))
            #        db_queue.put(Message("supervisor", "set_setting", {"key": "SENSOR_INTERVAL", "value": "3"}))
            #        print("[Supervisor] Sent set_setting ENGINE_INTERVAL=1, SENSOR_INTERVAL=3 (one-shot test)")
            #    except Exception:
            #        pass
            #    did_interval_test = True

            # ---- Watchdog timeouts ----
            if engine_process is not None and engine_process.is_alive():
                if last_hb["engine"] and (now - last_hb["engine"] > HEARTBEAT_TIMEOUT_ENGINE):
                    print("[Supervisor] Engine heartbeat timeout - restarting engine")
                    try:
                        engine_process.terminate()
                        engine_process.join(2)
                    except Exception:
                        pass
                    engine_process = None

            if sensor_process is not None and sensor_process.is_alive():
                if last_hb["sensor"] and (now - last_hb["sensor"] > HEARTBEAT_TIMEOUT_SENSOR):
                    print("[Supervisor] Sensor heartbeat timeout - restarting sensor")
                    try:
                        sensor_process.terminate()
                        sensor_process.join(2)
                    except Exception:
                        pass
                    sensor_process = None

            if relay_process is not None and relay_process.is_alive():
                if last_hb["relay"] and (now - last_hb["relay"] > HEARTBEAT_TIMEOUT_RELAY):
                    print("[Supervisor] Relay heartbeat timeout - restarting relay")
                    try:
                        relay_process.terminate()
                        relay_process.join(2)
                    except Exception:
                        pass
                    relay_process = None

            if ui_process is not None and ui_process.is_alive():
                if last_hb["ui"] and (now - last_hb["ui"] > HEARTBEAT_TIMEOUT_UI):
                    print("[Supervisor] UI heartbeat timeout - restarting ui")
                    try:
                        ui_process.terminate()
                        ui_process.join(2)
                    except Exception:
                        pass
                    ui_process = None

            if web_process is not None and web_process.is_alive():
                if last_hb["web"] and (now - last_hb["web"] > HEARTBEAT_TIMEOUT_WEB):
                    print("[Supervisor] Web heartbeat timeout - restarting web")
                    try:
                        web_process.terminate()
                        web_process.join(2)
                    except Exception:
                        pass
                    web_process = None

            # ---- Restart Engine/Sensor/Relay/UI/Web only if DB alive ----
            if db_process.is_alive():
                if engine_process is None or (not engine_process.is_alive()):
                    if now - last_restart["engine"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Engine not running - starting")
                        last_restart["engine"] = now
                        engine_process = start_engine(engine_queue, engine_rpc_queue, ui_queue, web_queue, db_queue, engine_ctrl_queue, relay_queue, MODE, DB_PATH, shutdown_event)

                if sensor_process is None or (not sensor_process.is_alive()):
                    if now - last_restart["sensor"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Sensor not running - starting")
                        last_restart["sensor"] = now
                        sensor_process = start_sensor(engine_queue, db_queue, sensor_ctrl_queue, ui_queue, web_queue, MODE, shutdown_event)

                if relay_process is None or (not relay_process.is_alive()):
                    if now - last_restart["relay"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Relay not running - starting")
                        last_restart["relay"] = now
                        relay_process = start_relay(relay_queue, db_queue, relay_ctrl_queue, ui_queue, web_queue, rpc_reply_queue, engine_rpc_queue, web_rpc_queue, MODE, shutdown_event)

                if ui_process is None or (not ui_process.is_alive()):
                    if now - last_restart["ui"] >= MIN_RESTART_GAP:
                        print("[Supervisor] UI not running - starting")
                        last_restart["ui"] = now
                        ui_process = start_ui(ui_queue, ui_ctrl_queue, db_queue, MODE, shutdown_event)

                if web_process is None or (not web_process.is_alive()):
                    if now - last_restart["web"] >= MIN_RESTART_GAP:
                        print("[Supervisor] Web not running - starting")
                        last_restart["web"] = now
                        web_process = start_web(web_queue, web_ctrl_queue, db_queue, relay_queue, web_rpc_queue, MODE, DB_PATH, shutdown_event)

            if shutdown_event.is_set():
                break

            time.sleep(SUPERVISOR_TICK)

    except (KeyboardInterrupt, SystemExit):
        shutdown_event.set()

    print("[Supervisor] Cleaning up processes...")
    shutdown_event.set()

    try:
        db_queue.put(Message("supervisor", "flush", {}))
    except:
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