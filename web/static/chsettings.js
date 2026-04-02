var isEditingSetpoint = false;
var setpointTimer = null;
var pendingSetpointValue = null;

// Grace Period Tracking
var lastManualEditTime = 0;       // Main Setpoint
var lastManualSwitchTime = 0;     // Timed/On/Off switch
var lastManualSettingsTime = 0;   // All numeric live-save fields
var lastManualAdvanceTime = 0;    // Advance button
var lastManualComfortTime = 0;    // Comfort Radios

var SETTING_KEY_MAP = {
    "ip-chsettings-boost-setpoint": "BOOST_SETPOINT",
    "ip-chsettings-default-on-setpoint": "DEFAULT_ON_SETPOINT",
    "ip-chsettings-default-setpoint": "DEFAULT_SETPOINT",
    "ip-temp-sensor-adjustment-degrees": "TEMP_SENSOR_ADJUSTMENT_DEGREES",
    "ip-chsettings-hysteresis-band": "HYSTERESIS_BAND",
    "ip-chsettings-min-on-seconds": "CH_MIN_ON_SECONDS",
    "ip-chsettings-min-off-seconds": "CH_MIN_OFF_SECONDS"
};

function setRadio(name, wantedValue) {
    var radios = document.getElementsByName(name);
    for (var i = 0; i < radios.length; i++) {
        radios[i].checked = (String(radios[i].value).toLowerCase() === String(wantedValue).toLowerCase());
    }
}

function setStatus(text) {
    var el = document.getElementById("chsettings-save-status");
    if (el) el.textContent = text;
}

function flashSaved(el, durationMs) {
    if (!el) return;
    el.classList.add("saved");
    setTimeout(function () {
        el.classList.remove("saved");
    }, durationMs || 1000);
}

function getBoostRemainingSeconds(finishEpoch) {
    var nowSec = Math.floor(Date.now() / 1000);
    var finish = parseInt(finishEpoch || 0, 10);
    if (isNaN(finish)) finish = 0;
    return Math.max(0, finish - nowSec);
}

function refreshBoostButtons(finishEpoch, plusBtnId, clearBtnId) {
    var plusBtn = document.getElementById(plusBtnId);
    var clearBtn = document.getElementById(clearBtnId);

    if (!plusBtn || !clearBtn) return;

    var remaining = getBoostRemainingSeconds(finishEpoch);
    var active = remaining > 0;
    var atMax = remaining >= (3 * 3600);

    if (!active) {
        plusBtn.textContent = "1 Hour";
        plusBtn.style.display = "";
        clearBtn.disabled = true;
        return;
    }

    clearBtn.disabled = false;

    if (atMax) {
        plusBtn.style.display = "none";
    } else {
        plusBtn.style.display = "";
        plusBtn.textContent = "+ Hour";
    }
}

async function loadCHSettingsStatus() {
    try {
        var r = await fetch("/api/status");
        var data = await r.json();
        if (!data.ok) return;

        var s = data.state || {};
        var cfg = data.settings || {};
        var now = Date.now();
        var gracePeriod = 5000;

        setText("heat-demand-status", s.ch_desired || "--");

        // Main Setpoint Shield
        if (pendingSetpointValue !== null) {
            var backendTarget = parseFloat(s.target);
            var pendingTarget = parseFloat(pendingSetpointValue);
            if (!isNaN(backendTarget) && !isNaN(pendingTarget) && Math.abs(backendTarget - pendingTarget) < 0.001) {
                pendingSetpointValue = null;
                isEditingSetpoint = false;
                setEditableValue("ip-chsettings-setpoint", s.target);
            } else {
                setEditableValue("ip-chsettings-setpoint", pendingSetpointValue);
            }
        } else if (!isEditingSetpoint && (now - lastManualEditTime) > gracePeriod) {
            setEditableValue("ip-chsettings-setpoint", s.target);
        }

        // System Switch Shield
        if ((now - lastManualSwitchTime) > gracePeriod) {
            setSelectValue("sel-chsettings-heat-switch", (s.ch_switch || cfg.CH_SYSTEM_SWITCH || "timed").toLowerCase());
        }

        // Advance Button Shield
        var advBtn = document.getElementById("bt-chsettings-heat-advance");
        if (advBtn && (now - lastManualAdvanceTime) > gracePeriod) {
            if (s.ch_advance || cfg.CH_ADVANCE === "True") {
                advBtn.classList.add("active");
            } else {
                advBtn.classList.remove("active");
            }
        }

        // Numeric Settings Shield
        if ((now - lastManualSettingsTime) > gracePeriod) {
            setEditableValue("ip-chsettings-boost-setpoint", cfg.BOOST_SETPOINT);
            setEditableValue("ip-chsettings-default-on-setpoint", cfg.DEFAULT_ON_SETPOINT);
            setEditableValue("ip-chsettings-default-setpoint", cfg.DEFAULT_SETPOINT);
            setEditableValue("ip-temp-sensor-adjustment-degrees", cfg.TEMP_SENSOR_ADJUSTMENT_DEGREES);
            setEditableValue("ip-chsettings-hysteresis-band", cfg.HYSTERESIS_BAND);
            setEditableValue("ip-chsettings-min-on-seconds", cfg.CH_MIN_ON_SECONDS);
            setEditableValue("ip-chsettings-min-off-seconds", cfg.CH_MIN_OFF_SECONDS);
        }

        // Comfort Radios Shield
        if ((now - lastManualComfortTime) > gracePeriod) {
            if (cfg.COMFORT !== undefined && cfg.COMFORT !== null) {
                var comfortValue = (String(cfg.COMFORT).toLowerCase() === "true") ? "On" : "Off";
                setRadio("COMFORT", comfortValue);
            }
        }

        setValue("ip-chsettings-heat-boost", cfg.CH_BOOST_FINISH_TIME || "00:00");
        refreshBoostButtons(
            cfg.CH_BOOST_FINISH_EPOCH,
            "bt-chsettings-heat-boost-plus",
            "bt-chsettings-heat-boost-clear"
        );
        setText("heat-programs-status", s.reason || "--");

    } catch (e) {
        console.log("loadCHSettingsStatus failed", e);
    }
}

window.addEventListener("DOMContentLoaded", function () {
    var liveSaveIds = Object.keys(SETTING_KEY_MAP);

    liveSaveIds.forEach(function(id) {
        bindChange(id, function(e) {
            lastManualSettingsTime = Date.now();

            var el = e.target;
            var key = SETTING_KEY_MAP[id];

            if (!key) {
                setStatus("Unknown setting");
                lastManualSettingsTime = 0;
                return;
            }

            setStatus("Saving " + key + "...");

            saveSetting(key, el.value)
                .then(function(res) {
                    if (res.ok) {
                        setStatus("Saved " + key);
                        flashSaved(el);
                    } else {
                        setStatus("Save failed: " + (res.error || "unknown"));
                        lastManualSettingsTime = 0;
                    }
                })
                .catch(function(err) {
                    setStatus("Error saving " + key);
                    console.log("save failed for " + key, err);
                    lastManualSettingsTime = 0;
                });
        });
    });

    bindClick("bt-chsettings-heat-advance", function () {
        lastManualAdvanceTime = Date.now();
        this.classList.toggle("active");
        postAction("/api/ch/advance", loadCHSettingsStatus);
    });

    bindClick("bt-chsettings-heat-boost-plus", function () {
        postAction("/api/ch/boost?mins=60", loadCHSettingsStatus);
    });

    bindClick("bt-chsettings-heat-boost-clear", function () {
        postAction("/api/ch/boost?mins=0", loadCHSettingsStatus);
    });

    var stepperButtons = document.querySelectorAll(".stepper-btn");
    for (var i = 0; i < stepperButtons.length; i++) {
        stepperButtons[i].addEventListener("click", function () {
            var target = this.getAttribute("data-target");
            var step = this.getAttribute("data-step");

            var now = Date.now();
            if (target === "ip-chsettings-setpoint") {
                isEditingSetpoint = true;
                lastManualEditTime = now;
            } else {
                lastManualSettingsTime = now;
            }

            changeNumberInput(target, step);
        });
    }

    bindChange("sel-chsettings-heat-switch", function (e) {
        lastManualSwitchTime = Date.now();
        setStatus("Saving heat switch...");

        saveSetting("CH_SYSTEM_SWITCH", e.target.value)
            .then(function (res) {
                if (res.ok) {
                    setStatus("Heat switch saved");
                    return loadCHSettingsStatus();
                } else {
                    setStatus("Heat switch save failed: " + (res.error || "unknown"));
                    lastManualSwitchTime = 0;
                }
            })
            .catch(function (err) {
                setStatus("Heat switch save failed");
                console.log("CH switch save failed", err);
                lastManualSwitchTime = 0;
            });
    });

    [document.getElementById("COMFORT_ON"), document.getElementById("COMFORT_OFF")].forEach(function(rb) {
        if (rb) {
            rb.addEventListener("change", function() {
                lastManualComfortTime = Date.now();
                var val = document.getElementById("COMFORT_ON").checked ? "True" : "False";

                saveSetting("COMFORT", val)
                    .then(function(res) {
                        if (res && res.ok) {
                            setStatus("Comfort mode updated");
                        } else {
                            setStatus("Comfort mode update failed");
                            lastManualComfortTime = 0;
                        }
                    })
                    .catch(function(err) {
                        setStatus("Comfort mode update failed");
                        console.log("comfort save failed", err);
                        lastManualComfortTime = 0;
                    });
            });
        }
    });

    bindChange("ip-chsettings-setpoint", function (e) {
        clearTimeout(setpointTimer);
        isEditingSetpoint = true;
        lastManualEditTime = Date.now();

        setpointTimer = setTimeout(function () {
            var val = parseFloat(e.target.value);

            e.target.classList.remove("saved");

            if (isNaN(val)) {
                setStatus("Invalid setpoint");
                e.target.classList.remove("saving");
                isEditingSetpoint = false;
                pendingSetpointValue = null;
                lastManualEditTime = 0;
                return;
            }

            pendingSetpointValue = val.toFixed(1);

            setStatus("Saving setpoint...");
            e.target.classList.add("saving");

            saveLiveCHSetpoint(String(val))
                .then(function (res) {
                    e.target.classList.remove("saving");

                    if (res.ok) {
                        flashSaved(e.target);
                        setStatus("Setpoint saved (" + describeSetpointTarget(res.target) + ")");
                        return loadCHSettingsStatus();
                    } else {
                        setStatus("Setpoint save failed: " + (res.error || "unknown"));
                        pendingSetpointValue = null;
                        isEditingSetpoint = false;
                        lastManualEditTime = 0;
                    }
                })
                .catch(function (err) {
                    e.target.classList.remove("saving");
                    setStatus("Setpoint save failed");
                    console.log("chsettings setpoint save failed", err);
                    pendingSetpointValue = null;
                    isEditingSetpoint = false;
                    lastManualEditTime = 0;
                });
        }, 300);
    });

    loadCHSettingsStatus();
    setInterval(loadCHSettingsStatus, 3000);
});