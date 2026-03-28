var gaugeDisplay = null;
var currentTemp = 13.3;
var isEditingSetpoint = false;
var setpointTimer = null;
var pendingSetpointValue = null;
var lastManualEditTime = 0;
var lastManualHeatSwitchTime = 0;
var lastManualWaterSwitchTime = 0;
var lastManualHeatAdvanceTime = 0;
var lastManualWaterAdvanceTime = 0;

function setStatus(text) {
    setText("settings-save-status", text);
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

function saveIndexSwitch(settingKey, value, label, resetShieldFn) {
    setStatus("Saving " + label + " switch...");

    saveSetting(settingKey, value)
        .then(function (res) {
            if (res.ok) {
                setStatus(label + " switch saved");
                return loadIndexStatus();
            } else {
                setStatus(label + " switch save failed: " + (res.error || "unknown"));
                resetShieldFn();
            }
        })
        .catch(function (err) {
            setStatus(label + " switch save failed");
            console.log(label + " switch save failed", err);
            resetShieldFn();
        });
}

async function loadIndexStatus() {
    try {
        const r = await fetch("/api/status");
        const data = await r.json();
        if (!data.ok) return;

        const s = data.state || {};
        const cfg = data.settings || {};
        const now = Date.now();
        const gracePeriod = 5000;

        const heatAdvanceBtn = document.getElementById("bt-index-heat-advance");
        if (heatAdvanceBtn && (now - lastManualHeatAdvanceTime) > gracePeriod) {
            if (s.ch_advance || cfg.CH_ADVANCE === "True") {
                heatAdvanceBtn.classList.add("active");
            } else {
                heatAdvanceBtn.classList.remove("active");
            }
        }

        const waterAdvanceBtn = document.getElementById("bt-index-water-advance");
        if (waterAdvanceBtn && (now - lastManualWaterAdvanceTime) > gracePeriod) {
            if (s.hw_advance || cfg.HW_ADVANCE === "True") {
                waterAdvanceBtn.classList.add("active");
            } else {
                waterAdvanceBtn.classList.remove("active");
            }
        }

        if (pendingSetpointValue !== null) {
            var backendTarget = parseFloat(s.target);
            var pendingTarget = parseFloat(pendingSetpointValue);
            if (!isNaN(backendTarget) && !isNaN(pendingTarget) && Math.abs(backendTarget - pendingTarget) < 0.001) {
                pendingSetpointValue = null;
                isEditingSetpoint = false;
                setEditableValue("ip-index-setpoint", s.target);
            } else {
                setEditableValue("ip-index-setpoint", pendingSetpointValue);
            }
        } else if (!isEditingSetpoint && (now - lastManualEditTime) > gracePeriod) {
            setEditableValue("ip-index-setpoint", s.target);
        }

        if ((now - lastManualHeatSwitchTime) > gracePeriod) {
            setSelectValue(
                "sel-index-heat-switch",
                (s.ch_switch || cfg.CH_SYSTEM_SWITCH || "timed").toLowerCase()
            );
        }

        if ((now - lastManualWaterSwitchTime) > gracePeriod) {
            setSelectValue(
                "sel-index-water-switch",
                (s.hw_switch || cfg.HW_SYSTEM_SWITCH || "timed").toLowerCase()
            );
        }

        setText("heat-demand-status", s.ch_desired || "--");
        setText("water-demand-status", s.hw_desired || "--");

        setValue("ip-index-heat-boost", cfg.CH_BOOST_FINISH_TIME || "00:00");
        setValue("ip-index-water-boost", cfg.HW_BOOST_FINISH_TIME || "00:00");

        refreshBoostButtons(
            cfg.CH_BOOST_FINISH_EPOCH,
            "bt-index-heat-boost-plus",
            "bt-index-heat-boost-clear"
        );

        refreshBoostButtons(
            cfg.HW_BOOST_FINISH_EPOCH,
            "bt-index-water-boost-plus",
            "bt-index-water-boost-clear"
        );

        setText("heat-programs-status", s.reason || "--");
        setText("water-programs-status", s.hw_reason || "--");

        setText("relay-a-status", s.relay_a === true ? "ON" : (s.relay_a === false ? "OFF" : "--"));
        setText("relay-b-status", s.relay_b === true ? "ON" : (s.relay_b === false ? "OFF" : "--"));

        setText("last-message", "Demand: CH=" + (s.ch_desired || "--") + " HW=" + (s.hw_desired || "--"));
        setText(
            "dwellpi-system-status",
            s.updated ? ("Updated: " + new Date(s.updated * 1000).toLocaleString()) : "Updated: --"
        );

        if (s.temp !== null && s.temp !== undefined) {
            currentTemp = parseFloat(s.temp);
            if (gaugeDisplay) {
                gaugeDisplay.setValue(currentTemp);
            }
        }
    } catch (e) {
        console.log("loadIndexStatus failed", e);
    }
}

function DwellpiThermometer() {
    var canvas = document.getElementById("TemperatureGauge");
    var container = document.getElementById("gauge-container");
    if (!canvas || !container || typeof ThermometerGuage === "undefined") return;

    canvas.width = 160;
    canvas.height = 320;

    var options_gauge = {
        w: canvas.width,
        h: canvas.height,
        color: {
            label: "#fff",
            tickLabel: "rgba(255,0,0,0.4)"
        },
        centerTicks: true,
        majorTicks: 2,
        minorTicks: 3,
        max: 25,
        min: 5,
        bulbRadiusProportion: 0.25,
        bulbRadiusByHeight: false,
        scaleTickLabelText: 1.1,
        scaleLabelText: 1.1,
        scaleTickWidth: 2,
        unitsLabel: "\xB0C"
    };

    gaugeDisplay = new ThermometerGuage(canvas, options_gauge);
    gaugeDisplay.setValue(currentTemp);
}

window.addEventListener("resize", function () {
    DwellpiThermometer();
});

window.addEventListener("DOMContentLoaded", function () {
    DwellpiThermometer();

    bindClick("bt-index-heat-advance", function () {
        lastManualHeatAdvanceTime = Date.now();
        this.classList.toggle("active");
        postAction("/api/ch/advance", loadIndexStatus);
    });

    bindClick("bt-index-water-advance", function () {
        lastManualWaterAdvanceTime = Date.now();
        this.classList.toggle("active");
        postAction("/api/hw/advance", loadIndexStatus);
    });

    bindClick("bt-index-heat-boost-plus", function () {
        postAction("/api/ch/boost?mins=60", loadIndexStatus);
    });

    bindClick("bt-index-water-boost-plus", function () {
        postAction("/api/hw/boost?mins=60", loadIndexStatus);
    });

    bindClick("bt-index-heat-boost-clear", function () {
        postAction("/api/ch/boost?mins=0", loadIndexStatus);
    });

    bindClick("bt-index-water-boost-clear", function () {
        postAction("/api/hw/boost?mins=0", loadIndexStatus);
    });

    bindChange("sel-index-heat-switch", function (e) {
        lastManualHeatSwitchTime = Date.now();
        saveIndexSwitch("CH_SYSTEM_SWITCH", e.target.value, "Heat", function () {
            lastManualHeatSwitchTime = 0;
        });
    });

    bindChange("sel-index-water-switch", function (e) {
        lastManualWaterSwitchTime = Date.now();
        saveIndexSwitch("HW_SYSTEM_SWITCH", e.target.value, "Water", function () {
            lastManualWaterSwitchTime = 0;
        });
    });

    var stepperButtons = document.querySelectorAll(".stepper-btn");
    for (var i = 0; i < stepperButtons.length; i++) {
        stepperButtons[i].addEventListener("click", function () {
            var target = this.getAttribute("data-target");
            var step = this.getAttribute("data-step");

            if (target === "ip-index-setpoint") {
                isEditingSetpoint = true;
                lastManualEditTime = Date.now();
            }

            changeNumberInput(target, step);
        });
    }

    bindChange("ip-index-setpoint", function (e) {
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
                        return loadIndexStatus();
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
                    console.log("index setpoint save failed", err);
                    pendingSetpointValue = null;
                    isEditingSetpoint = false;
                    lastManualEditTime = 0;
                });
        }, 300);
    });

    loadIndexStatus();
    setInterval(loadIndexStatus, 3000);
});