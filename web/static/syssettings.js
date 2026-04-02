// A simple lock to prevent overlapping saves
var isSaving = false;
var isSavingEmail = false;

function setStatus(text) {
    setText("syssettings-status-line", text);
}

// Helper to build payload from a list of keys/IDs
function buildPayload(settingsList) {
    return settingsList.map(item => {
        return { key: item.key, value: getValue(item.id, item.default || "") };
    });
}

// Define the "Master List" of settings once
const ALL_SYSTEM_SETTINGS = [
    { key: "ENGINE_INTERVAL", id: "sys-engine-interval" },
    { key: "SENSOR_INTERVAL", id: "sys-sensor-interval" },
    { key: "LOGGING_INTERVAL", id: "sys-logging-interval" },
    { key: "RELAY_ENABLE", id: "sys-relay-enable", default: "False" },
    { key: "RELAY_BOARD_DEVICE_ID", id: "sys-relay-board-device-id" },
    { key: "CH_RELAY_LETTER", id: "sys-ch-relay-letter", default: "A" },
    { key: "HW_RELAY_LETTER", id: "sys-hw-relay-letter", default: "B" },
    { key: "SENSOR_DEVICE_ID", id: "sys-sensor-device-id" },
    { key: "LCD_BRIGHTNESS", id: "sys-lcd-brightness" },
    { key: "LCD_DIM_LEVEL", id: "sys-lcd-dim-level" },
    { key: "LCD_DIM_START_TIME", id: "sys-lcd-dim-start", default: "00:00" },
    { key: "LCD_DIM_END_TIME", id: "sys-lcd-dim-end", default: "00:00" },

    { key: "PREDICTIVE_HEATING_ENABLED", id: "sys-predictive-heating-enabled", default: "True" },
    { key: "PREDICTIVE_BASE_RATE", id: "sys-predictive-base-rate", default: "0.7" },
    { key: "PREDICTIVE_MIN_LEARNING_SECONDS", id: "sys-predictive-min-learning-seconds", default: "600" },
    { key: "PREDICTIVE_MIN_RATE", id: "sys-predictive-min-rate", default: "0.15" },
    { key: "PREDICTIVE_MAX_RATE", id: "sys-predictive-max-rate", default: "1.5" },

    { key: "EMAIL_ENABLE", id: "sys-email-enable", default: "False" },
    { key: "ALERT_COOLDOWN_SECONDS", id: "sys-alert-cooldown-seconds", default: "1800" },
    { key: "ALERT_SEND_RECOVERY_EMAILS", id: "sys-alert-send-recovery-emails", default: "True" },

    { key: "WARMUP_MINIMUM_LEAD_TIME", id: "sys-warmup-minimum-lead-time", default: "30" },
    { key: "WARMUP_MAXIMUM_LEAD_TIME", id: "sys-warmup-maximum-lead-time", default: "120" },
    { key: "FALLBACK_HEATUP_RATE", id: "sys-fallback-heatup-rate", default: "0.4" },
    { key: "WARMUP_TARGET_OFFSET", id: "sys-warmup-target-offset", default: "-0.5" }
];

async function saveSettings(onlyLcd = false) {
    if (isSaving) return;
    isSaving = true;

    const list = onlyLcd
        ? ALL_SYSTEM_SETTINGS.filter(s => s.key.startsWith("LCD_"))
        : ALL_SYSTEM_SETTINGS;

    setStatus(onlyLcd ? "Saving LCD settings..." : "Saving settings...");

    try {
        const result = await postBulkSettings(buildPayload(list));
        if (result.ok) {
            setStatus("Settings saved successfully.");
        } else {
            setStatus("Save failed: " + (result.error || "unknown error"));
        }
    } catch (e) {
        setStatus("Network error during save.");
    } finally {
        isSaving = false;
    }
}

function isValidEmailList(value) {
    if (!value) return true;

    var parts = value.split(",");
    for (var i = 0; i < parts.length; i++) {
        var addr = parts[i].trim();
        if (!addr) continue;

        if (addr.indexOf("@") < 1 || addr.indexOf("@") !== addr.lastIndexOf("@")) {
            return false;
        }
    }
    return true;
}

function getEmailConfigPayload() {
    var emailTo = getValue("email-to", "").trim();
    var emailFrom = getValue("email-from", "").trim();
    var smtpHost = getValue("smtp-host", "").trim();
    var smtpPort = getValue("smtp-port", "465").trim();
    var smtpUsername = getValue("smtp-username", "").trim();
    var smtpPassword = getValue("smtp-password", "");
    var smtpUseSsl = getValue("smtp-use-ssl", "True");

    if (!isValidEmailList(emailTo)) {
        setStatus("Invalid To email address list");
        return null;
    }

    if (emailFrom && (emailFrom.indexOf("@") < 1 || emailFrom.indexOf("@") !== emailFrom.lastIndexOf("@"))) {
        setStatus("Invalid From email address");
        return null;
    }

    if (!smtpHost) {
        setStatus("SMTP host is required");
        return null;
    }

    if (!smtpPort || isNaN(Number(smtpPort))) {
        setStatus("SMTP port must be a number");
        return null;
    }

    var payload = {
        EMAIL_TO: emailTo,
        EMAIL_FROM: emailFrom,
        SMTP_HOST: smtpHost,
        SMTP_PORT: smtpPort,
        SMTP_USERNAME: smtpUsername,
        SMTP_USE_SSL: smtpUseSsl
    };

    if (smtpPassword) {
        payload.SMTP_PASSWORD = smtpPassword;
    }

    return payload;
}

async function loadEmailConfig() {
    try {
        const r = await fetch("/api/email/config");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load email config");
            return;
        }

        const item = data.item || {};

        setValue("email-to", item.EMAIL_TO || "");
        setValue("email-from", item.EMAIL_FROM || "");
        setValue("smtp-host", item.SMTP_HOST || "");
        setValue("smtp-port", item.SMTP_PORT || "465");
        setValue("smtp-username", item.SMTP_USERNAME || "");
        setValue("smtp-password", item.SMTP_PASSWORD || "");
        setValue("smtp-use-ssl", item.SMTP_USE_SSL || "True");
    } catch (e) {
        console.log("loadEmailConfig failed", e);
        setStatus("Error loading email config");
    }
}

async function reloadEmailConfig() {
    try {
        const r = await fetch("/api/email/reload", { method: "POST" });
        const data = await r.json();

        if (data.ok) {
            return true;
        }

        setStatus("Reload email config failed: " + (data.error || "unknown error"));
        return false;
    } catch (e) {
        console.log("reloadEmailConfig failed", e);
        setStatus("Network error reloading email config.");
        return false;
    }
}

async function saveEmailConfig() {
    if (isSavingEmail) return;
    isSavingEmail = true;

    setStatus("Saving email config...");

    try {
        const configPayload = getEmailConfigPayload();
        if (!configPayload) {
            return;
        }

        const saveResp = await fetch("/api/email/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ item: configPayload })
        });

        const saveData = await saveResp.json();
        if (!saveData.ok) {
            setStatus("Email config save failed: " + (saveData.error || "unknown error"));
            return;
        }

        const settingsResult = await postBulkSettings(buildPayload(
            ALL_SYSTEM_SETTINGS.filter(s =>
                s.key === "EMAIL_ENABLE" ||
                s.key === "ALERT_COOLDOWN_SECONDS" ||
                s.key === "ALERT_SEND_RECOVERY_EMAILS"
            )
        ));

        if (!settingsResult.ok) {
            setStatus("Email settings save failed: " + (settingsResult.error || "unknown error"));
            return;
        }

        const reloadOk = await reloadEmailConfig();
        if (!reloadOk) {
            return;
        }

        await loadEmailConfig();
        setStatus("Email config saved and reloaded.");
    } catch (e) {
        console.log("saveEmailConfig failed", e);
        setStatus("Network error saving email config.");
    } finally {
        isSavingEmail = false;
    }
}

async function postSystemAction(url, pendingText, doneText) {
    setStatus(pendingText);

    try {
        const r = await fetch(url, { method: "POST" });
        const data = await r.json();

        if (data.ok) {
            setStatus(doneText);
        } else {
            setStatus("Action failed: " + (data.error || "unknown error"));
        }
    } catch (e) {
        console.log("system action failed", e);
        setStatus("Network error requesting system action.");
    }
}

async function loadSysSettingsStatus() {
    try {
        const r = await fetch("/api/status");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load system settings");
            return;
        }

        const settings = data.settings || {};

        ALL_SYSTEM_SETTINGS.forEach(item => {
            const val = settings[item.key];
            const finalVal = (val !== undefined && val !== null)
                ? val
                : (item.default || "");

            setValue(item.id, finalVal);
        });

        updateSupervisorPanel(data.supervisor || {});
        setStatus("System settings loaded.");
    } catch (e) {
        console.log("loadSysSettingsStatus failed", e);
        setStatus("Error loading system settings");
    }
}

async function loadSystemLoadInfo() {
    try {
        const r = await fetch("/api/system/load");
        const data = await r.json();

        if (!data.ok) {
            setText("sys-info-uptime", "Uptime: --");
            setText("sys-info-loadavg", "Load Average: --");
            return;
        }

        setText("sys-info-uptime", data.uptime || "Uptime: --");
        setText("sys-info-loadavg", data.loadavg || "Load Average: --");
    } catch (e) {
        console.log("loadSystemLoadInfo failed", e);
        setText("sys-info-uptime", "Uptime: --");
        setText("sys-info-loadavg", "Load Average: --");
    }
}

function fmtRelayBool(v) {
    if (v === true) return "ON";
    if (v === false) return "OFF";
    return "--";
}

function clearRelayInfo(text) {
    setText("relay-info-device", "Device ID: " + (text || "--"));
    setText("relay-info-type", "Device Type: --");
    setText("relay-info-name", "Device Name: --");
    setText("relay-info-fw", "Firmware: --");
    setText("relay-info-llap", "LLAP Version: --");
    setText("relay-info-serial", "Serial: --");
    setText("relay-info-battery", "Battery: --");
    setText("relay-info-status", "Relay A/B: -- / --");
}

async function loadRelayInfo() {
    try {
        const r = await fetch("/api/relay/info");
        const data = await r.json();

        if (!data.ok) {
            clearRelayInfo("error");
            return;
        }

        const info = data.info || {};

        setText("relay-info-device", "Device ID: " + (info.device_id || "--"));
        setText("relay-info-type", "Device Type: " + (info.device_type || "--"));
        setText("relay-info-name", "Device Name: " + (info.device_name || "--"));
        setText("relay-info-fw", "Firmware: " + (info.firmware_version || "--"));
        setText("relay-info-llap", "LLAP Version: " + (info.llap_version || "--"));
        setText("relay-info-serial", "Serial: " + (info.serial_number || "--"));
        setText("relay-info-battery", "Battery: " + (info.battery_level || "--"));
        setText(
            "relay-info-status",
            "Relay A/B: " + fmtRelayBool(info.relay_a) + " / " + fmtRelayBool(info.relay_b)
        );
    } catch (e) {
        console.log("loadRelayInfo failed", e);
        clearRelayInfo("error");
    }
}

function fmtAgeSeconds(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    return Math.round(Number(value)) + "s";
}

function fmtRestartCount(value) {
    if (value === null || value === undefined || isNaN(value)) return "0";
    return String(parseInt(value, 10));
}

function aliveText(flag) {
    return flag ? "UP" : "DN";
}

function dbReadyText(flag) {
    return flag ? "OK" : "WAIT";
}

async function loadSupervisorStatus() {
    try {
        const r = await fetch("/api/status");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load supervisor status");
            return;
        }

        updateSupervisorPanel(data.supervisor || {});
    } catch (e) {
        console.log("loadSupervisorStatus failed", e);
        setStatus("Error loading supervisor status");
    }
}

function updateSupervisorPanel(wrapper) {
    var sup = (wrapper && wrapper.data) ? wrapper.data : {};
    var procs = sup.processes || {};

    var nowSec = Date.now() / 1000;
    var updatedAge = "--";
    var ts = parseFloat(sup.timestamp || wrapper.updated || 0);
    if (!isNaN(ts) && ts > 0) {
        updatedAge = fmtAgeSeconds(nowSec - ts);
    }

    setText("supervisor-mode", "Mode: " + (sup.mode || "--"));
    setText("supervisor-db-ready", "DB Ready: " + dbReadyText(!!sup.db_ready));
    setText("supervisor-updated-age", "Last Update: " + updatedAge);

    function processSummary(name, p) {
        p = p || {};
        return (
            name +
            ": " + aliveText(!!p.alive) +
            " | hb " + fmtAgeSeconds(p.heartbeat_age) +
            " | restarts " + fmtRestartCount(p.restart_count)
        );
    }

    setText("supervisor-engine", processSummary("Engine", procs.engine));
    setText("supervisor-sensor", processSummary("Sensor", procs.sensor));
    setText("supervisor-relay", processSummary("Relay", procs.relay));
    setText("supervisor-ui", processSummary("UI", procs.ui));
    setText("supervisor-web", processSummary("Web", procs.web));
    setText("supervisor-email", processSummary("Email", procs.email));

    var db = procs.db || {};
    setText(
        "supervisor-db",
        "DB: " + aliveText(!!db.alive) +
        " | restarts " + fmtRestartCount(db.restart_count)
    );
}

async function restartProcess(name) {
    setStatus("Requesting " + name + " restart...");

    try {
        const r = await fetch("/api/system/restart_process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name })
        });

        const data = await r.json();

        if (data.ok) {
            if (data.was_running === false) {
                setStatus(name + " was already stopped. Started fresh.");
            } else {
                setStatus(name + " restarted.");
            }
            setTimeout(loadSupervisorStatus, 1000);
        } else {
            setStatus("Restart failed: " + (data.error || "unknown error"));
        }
    } catch (e) {
        console.log("restartProcess failed", e);
        setStatus("Network error requesting process restart.");
    }
}

async function testEmail() {
    setStatus("Requesting test email...");

    try {
        const r = await fetch("/api/system/test_email", { method: "POST" });
        const data = await r.json();

        if (data.ok) {
            setStatus("Test email queued. Check inbox shortly.");
        } else {
            setStatus("Test email failed: " + (data.error || "unknown error"));
        }
    } catch (e) {
        console.log("testEmail failed", e);
        setStatus("Network error requesting test email.");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadSysSettingsStatus();
    loadSystemLoadInfo();
    loadRelayInfo();
    loadEmailConfig();
    setInterval(loadSupervisorStatus, 5000);

    bindClick("bt-syssettings-save", () => saveSettings(false));
    bindClick("bt-save-lcd-settings", () => saveSettings(true));
    bindClick("bt-save-email-settings", async () => {
        await saveEmailConfig();
    });

    // Stepper Button Setup
    document.querySelectorAll(".stepper-btn").forEach(btn => {
        btn.addEventListener("click", function () {
            changeNumberInput(this.getAttribute("data-target"), this.getAttribute("data-step"));
        });
    });

    // Refresh Buttons
    bindClick("bt-refresh-system-load", async () => {
        setStatus("Refreshing Pi load...");
        await loadSystemLoadInfo();
        setStatus("Pi load refreshed.");
    });

    bindClick("bt-refresh-relay-info", async () => {
        setStatus("Refreshing RelayBoard info...");
        await loadRelayInfo();
        setStatus("RelayBoard info refreshed.");
    });

    bindClick("bt-reload-email-config", async () => {
        setStatus("Reloading email config...");
        const ok = await reloadEmailConfig();
        if (ok) {
            await loadEmailConfig();
            setStatus("Email config reloaded.");
        }
    });

    bindClick("bt-toggle-smtp-password", function () {
        var el = document.getElementById("smtp-password");
        var btn = document.getElementById("bt-toggle-smtp-password");

        if (!el || !btn) return;

        if (el.type === "password") {
            el.type = "text";
            btn.textContent = "Hide";
        } else {
            el.type = "password";
            btn.textContent = "Show";
        }
    });

    bindClick("bt-test-email", async () => {
        if (!window.confirm("Send a test email now?")) return;
        await testEmail();
    });

    // RESTART Buttons
    bindClick("bt-restart-dwellpi", async () => {
        if (!window.confirm("Restart DwellPi now?")) return;
        await postSystemAction("/api/system/restart_dwellpi", "Requesting DwellPi restart...", "DwellPi restart requested.");
    });

    bindClick("bt-reboot-pi", async () => {
        if (!window.confirm("Reboot Raspberry Pi now?")) return;
        await postSystemAction("/api/system/reboot_pi", "Requesting Raspberry Pi reboot...", "Raspberry Pi reboot requested.");
    });

    bindClick("bt-refresh-supervisor", async () => {
        setStatus("Refreshing supervisor status...");
        await loadSupervisorStatus();
        setStatus("Supervisor status refreshed.");
    });

    bindClick("bt-restart-engine", async () => {
        if (!window.confirm("Restart Engine now?")) return;
        await restartProcess("engine");
    });

    bindClick("bt-restart-sensor", async () => {
        if (!window.confirm("Restart Sensor now?")) return;
        await restartProcess("sensor");
    });

    bindClick("bt-restart-relay", async () => {
        if (!window.confirm("Restart Relay now?")) return;
        await restartProcess("relay");
    });

    bindClick("bt-restart-ui", async () => {
        if (!window.confirm("Restart UI now?")) return;
        await restartProcess("ui");
    });

    bindClick("bt-restart-web", async () => {
        if (!window.confirm("Restart Web now?")) return;
        await restartProcess("web");
    });

    bindClick("bt-restart-email", async () => {
        if (!window.confirm("Restart Email now?")) return;
        await restartProcess("email");
    });
});