    $( document ).on( "pagecontainershow", function ( event, ui ) {
        var id_url = $.mobile.pageContainer.pagecontainer( "getActivePage" )[0].id;
        FooterButtonJustifyRight();
        DisableNumberSpinners()

        if (id_url.indexOf("sys-page") >= 0) {
            DwellpiThermometer();
            IndexPage();
        }

        if (id_url.indexOf("progs-page") >= 0) {
            equalHeight(jQuery(".programs"));
            equalHeightGridHeader(jQuery(".grid-header"));
        }

        if (id_url.indexOf("chsettings-page") >= 0) {
            CHSettingsPage();
        }

        if (id_url.indexOf("hwsettings-page") >= 0) {
            HWSettingsPage();
        }

        if (id_url.indexOf("syssettings-page") >= 0) {
            SysSettingsPage();
        }

        if (id_url.indexOf("chprogs-page") >= 0) {
            CHProgsPage();
        }

        if (id_url.indexOf("hwprogs-page") >= 0) {
            HWProgsPage();
        }


    });



function DwellpiThermometer() {
    //misc_curves(document.getElementById( 'TemperatureGauge'));
    //draw gauge
    var w = document.getElementById('TemperatureGauge').width;
    var h = document.getElementById('TemperatureGauge').height;
    //console.log("DwellpiThermometer w, h: ", w, " | ", h)
    var options_gauge = {
        w: w,
        h: h,
        color: {
            label: 'rgba(255, 255, 255, 1)',
            tickLabel: 'rgba(255, 0, 0, 0.4)'
        },
        centerTicks: true,
        majorTicks: 2,
        minorTicks: 3,
        max: 25,
        min: 5,
        bulbRadiusProportion: 0.2,
        bulbRadiusByHeight: false,
        scaleTickLabelText: 1.3,
        scaleLabelText: 1.2,
        scaleTickWidth: 2,
        unitsLabel: "\xB0C"
        };

    gaugeDisplay = new ThermometerGuage( document.getElementById( 'TemperatureGauge'), options_gauge );
    gaugeDisplay.setValue(parseFloat(13.3));
    };

function DisableNumberSpinners() {
 // Disable scroll when focused on a number input.
    $('form').on('focus', 'input[type=number]', function(e) {
        $(this).on('wheel', function(e) {
            e.preventDefault();
        });
    });

    // Restore scroll on number inputs.
    $('form').on('blur', 'input[type=number]', function(e) {
        $(this).off('wheel');
    });

    // Disable up and down keys.
    $('form').on('keydown', 'input[type=number]', function(e) {
        if ( e.which == 38 || e.which == 40 )
            e.preventDefault();
    });
};


function FooterButtonJustifyRight() {
    $(".footer-button-justify-right")
        .removeClass( "ui-btn-icon-left" )
        .addClass( "ui-btn-icon-right" );
};

function equalHeightGridHeader(group) {
    var tallest = 0;
    group.each(function() {
        var thisHeight = jQuery(this).height();
        if(thisHeight > tallest) {
            tallest = thisHeight;
        }
    });
    group.height(tallest);
};

function equalHeight(group) {
    var tallest = 0;
    group.children().each(function() {
        var thisHeight = jQuery(this).height();
        if(thisHeight > tallest) {
            tallest = thisHeight - 12;
        }
    });
    //console.log("Hello: " + (tallest-30)/2);
    jQuery('button.edit-button').css({'margin-top':(tallest-30)/2 + 'px'});
    jQuery('.ui-bar.program').height(tallest);
    jQuery('.ui-bar.edit-button').height(tallest);
};

function minutesToHoursAndMinutes(totalMinutes) {
    var hours = Math.floor(totalMinutes / 60)
    var minutes = totalMinutes % 60

    return [hours, minutes]
};

function createDataSource(oArrData)
{
    var oArrDataNum = [ 6, 59],
    iTempIndex1, iTempIndex2;

    for(iTempIndex1 = 0; iTempIndex1 < oArrDataNum.length; iTempIndex1++)
    {
        var iNum = oArrDataNum[iTempIndex1],
        iStart = (iTempIndex1 === 0) ? 1 : 0;
        iStart = 0
        iEnd = iNum + 1,
        oArrDataComp = [];

        for(iTempIndex2 = iStart; iTempIndex2 < iEnd; iTempIndex2++)
        {
            oArrDataComp.push({
                val: iTempIndex2.toString(),
                label: iTempIndex2.toString()
            });
        }

        oArrData.push(oArrDataComp);
    }
}

function IndexPage() {

    //---------------
    // Setpoint START

    var oAPIndex1
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel
    var oArrData = [];

    dSetDecimal = 10.7;
    dMinDecimal = 0.6;
    dMaxDecimal = 25.3;
    sUnitLabel = " °C";
    bShowSeparator = true;
    sFormatDecimal = "nn.d"


    jQuery("#ip-index-setpoint").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            showSeparator: bShowSeparator,

            inputDecimalFormat: sFormatDecimal,
            DecimalFormat: sFormatDecimal,

            onInit: function()
            {
                oAPIndex1 = this;

                sMaxDecimal = oAPIndex1.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPIndex1.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                oAPIndex1.setMaximumDecimal(sMaxDecimal);
                oAPIndex1.setMinimumDecimal(sMinDecimal);

                sSetDecimal = oAPIndex1.formatOutputDecimals(dSetDecimal, sFormatDecimal);

                oAPIndex1.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })
    // Setpoint END
    //---------------

    //---------------
    // Boost START

    var oAPIndex2, oAPIndex3
    var sHeatBoost, sWaterBoost, bShowShortLabel

    bShowShortLabel = true
    sHeatBoost = "92"
    sWaterBoost = "0"

    var oArrData = [];

    createDataSource(oArrData);

    var oArrComponents = [
        {
            component: 0,
            name: "hours",
            label: "Hours",
            shortLabel: "hr",
            width: "20%",
            textAlign: "center"
        },
        {
            component: 1,
            name: "minutes",
            label: "Minutes",
            shortLabel: "m",
            width: "30%",
            textAlign: "center"
        }
    ],
    oArrDataSource1 = [
        {
            component: 0,
            data: oArrData[0]
        },
        {
            component: 1,
            data: oArrData[1]
        }
    ]



    jQuery("#ip-index-heat-boost").AnyPicker(
    {
        mode: "select",
        actionMode: "both",
        showComponentLabel: true,
        components: oArrComponents,
        dataSource: oArrDataSource1,

        showShortLabel: bShowShortLabel,

        onInit: function()
        {
            oAPIndex2 = this;
            oAPIndex2.setSelectedSelect(minutesToHoursAndMinutes(sHeatBoost));
        },

        onSetOutput: function(sOutput, oSelectedValues)
        {
            bclusterHeatBoost.SwitchSetClearBtn()
            //bclusterHeatBoost.setPlusOneBoost()
            //send to server
        }
    });

    jQuery("#ip-index-water-boost").AnyPicker(
    {
        mode: "select",
        actionMode: "both",
        showComponentLabel: true,
        components: oArrComponents,
        dataSource: oArrDataSource1,

        showShortLabel: bShowShortLabel,

        onInit: function()
        {
            oAPIndex3 = this;
            oAPIndex3.setSelectedSelect(minutesToHoursAndMinutes(sWaterBoost));
        },

        onSetOutput: function(sOutput, oSelectedValues)
        {
            bclusterWaterBoost.SwitchSetClearBtn()
            //bclusterWaterBoost.setPlusOneBoost()
            //send to server
        }
    });


    var bclusterHeatBoost = new Plusone_combinedSetClear_BtnCluster("ip-index-heat-boost", oArrComponents)
    var bclusterWaterBoost = new Plusone_combinedSetClear_BtnCluster("ip-index-water-boost", oArrComponents)


    function Plusone_combinedSetClear_BtnCluster(ip, oArrComponents) {
        var btPlus = document.getElementById('bt'+ ip.substring(2) + '-plus')
        var btSet = document.getElementById('bt'+ ip.substring(2) + '-set')
        var input = document.getElementById(ip)

        jQuery(btPlus).on('click', function() {
            plusOneBoost()
        });

        jQuery(btSet).on('click', function() {
            SwitchSetClearBtn(false, btSet)
        });



        function SwitchSetClearBtn(firstRun, btClicked){
            if (firstRun){
                if (input.value === "None"){
                    btSet.disabled = true
                    btSet.textContent = "Set"
                }
                else{
                    btSet.disabled = false
                    btSet.textContent = "Clear"
                }
            }
            else{
                if (btClicked === btPlus){
                    btSet.textContent = "Set"
                    btSet.disabled = false
                }
                else if(btClicked === btSet){
                    if(btSet.textContent === "Set"){
                        setPlusOneBoost(ip)
                        if (input.value !== "None"){
                            btSet.textContent = "Clear"
                            btSet.disabled = false
                        }
                        else if (input.value === "None"){
                            btSet.disabled = true
                        }
                    }
                    else if(btSet.textContent === "Clear"){
                        input.value = "None"
                        btSet.textContent = "Set"
                    }

                }
                else if (!btClicked){
                    setPlusOneBoost(ip)
                    if(input.value === "None"){
                        btSet.textContent = "Set"
                        btSet.disabled = true
                    }
                    else{
                        btSet.textContent = "Clear"
                        btSet.disabled = false
                    }
                }
            }
        }

        function plusOneBoost()
        {
            var arrBoostTime, iTime = [], iTempTimeComp
            //if (btSet.disabled)
            //    btSet.disabled = false

            arrBoostTime = (input.value.trim()).split(" ")
            for (iTempIndex = 0; iTempIndex < arrBoostTime.length; iTempIndex++)
            {
                iTempTimeComp = arrBoostTime[iTempIndex].replace(oArrComponents[iTempIndex].shortLabel, "")
                iTempTimeComp = (iTempTimeComp === "None") ? "0" : iTempTimeComp

                if ((oArrComponents[iTempIndex].shortLabel === "hr") && !(iTempTimeComp.includes(oArrComponents[oArrComponents.length - 1].shortLabel)))
                {
                    iTempTimeComp = ((iTempTimeComp === "") ? ("1" + oArrComponents[iTempIndex].shortLabel) : ((parseInt(iTempTimeComp) < 6) ? (parseInt(iTempTimeComp) +1) + oArrComponents[iTempIndex].shortLabel : ""))
                }
                else if ((oArrComponents[iTempIndex].shortLabel === "m") && iTempTimeComp)
                {
                    iTempTimeComp = iTempTimeComp + oArrComponents[iTempIndex].shortLabel
                }
                else
                {
                iTime.push("1" + oArrComponents[iTempIndex].shortLabel)
                }
                if (iTempTimeComp)
                    iTime.push(iTempTimeComp)
            }

            input.value = (Array.isArray(iTime) && iTime.length) ? iTime.join(" ") : "None"
            SwitchSetClearBtn(false, btPlus)
        }


    function setPlusOneBoost()    {
        console.log("SEND TO SERVER elInput.value", input.value)//mc
        //send to server
    }

    //public Functions
    this.setPlusOneBoost =function () {
        setPlusOneBoost()
    }
    this.SwitchSetClearBtn = function () {
        SwitchSetClearBtn()
    }

    SwitchSetClearBtn(firstRun = true)
    }

    // Boost END
    //---------------

    //---------------
    // Program Switch START

    jQuery('#sel-index-heat-switch').on('change', function() {
        console.log( "SEND TO SERVER value", this.value );
    });

    jQuery('#sel-index-water-switch').on('change', function() {
        console.log("SEND TO SERVER value", this.value );
    });

    // Program Switch END
    //---------------

    //---------------
    // Advance START

    jQuery('#bt-index-heat-advance').on('click', function() {
        console.log( "SEND TO SERVER heat Advance");
    });

    jQuery('#bt-index-water-advance').on('click', function() {
        console.log( "SEND TO SERVER water Advance");
    });

    // Advance END
    //---------------
};

function CHSettingsPage() {
    //---------------
    // Setpoint START

    var oAPCHset1
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel
    var oArrData = [];

    dSetDecimal = 10.7;
    dMinDecimal = 0.6;
    dMaxDecimal = 25.3;
    sUnitLabel = " °C";
    bShowSeparator = true;
    sFormatDecimal = "nn.d"


    jQuery("#ip-chsettings-setpoint").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            showSeparator: bShowSeparator,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            onInit: function()
            {
                oAPCHset1 = this;

                sMaxDecimal = oAPCHset1.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPCHset1.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                oAPCHset1.setMaximumDecimal(sMaxDecimal);
                oAPCHset1.setMinimumDecimal(sMinDecimal);

                sSetDecimal = oAPCHset1.formatOutputDecimals(dSetDecimal, sFormatDecimal);

                oAPCHset1.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })
    // Setpoint END
    //---------------

//---------------
    // Boost START

    var oAPCHset2
    var sHeatBoost, bShowShortLabel

    bShowShortLabel = true
    sHeatBoost = "0"

    var oArrData = [];

    createDataSource(oArrData);

    var oArrComponents = [
        {
            component: 0,
            name: "hours",
            label: "Hours",
            shortLabel: "hr",
            width: "20%",
            textAlign: "center"
        },
        {
            component: 1,
            name: "minutes",
            label: "Minutes",
            shortLabel: "m",
            width: "30%",
            textAlign: "center"
        }
    ],
    oArrDataSource1 = [
        {
            component: 0,
            data: oArrData[0]
        },
        {
            component: 1,
            data: oArrData[1]
        }
    ]



    jQuery("#ip-chsettings-heat-boost").AnyPicker(
    {
        mode: "select",
        actionMode: "both",
        showComponentLabel: true,
        components: oArrComponents,
        dataSource: oArrDataSource1,

        showShortLabel: bShowShortLabel,

        onInit: function()
        {
            oAPCHset2 = this;
            oAPCHset2.setSelectedSelect(minutesToHoursAndMinutes(sHeatBoost));
        },

        onSetOutput: function(sOutput, oSelectedValues)
        {
            bclusterHeatBoost.setPlusOneBoost()
            bclusterHeatBoost.EnableDisableClearBtn()
            //send to server
        }
    });


    var bclusterHeatBoost = new PlusoneClearSet_BtnCluster("ip-chsettings-heat-boost", oArrComponents)

    function PlusoneClearSet_BtnCluster(ip, oArrComponents) {
        var btPlus = document.getElementById('bt'+ ip.substring(2) + '-plus')
        var btSet = document.getElementById('bt'+ ip.substring(2) + '-set')
        var btClear = document.getElementById('bt'+ ip.substring(2) + '-clear')
        var input = document.getElementById(ip)


        jQuery(btPlus).on('click', function() {
            plusOneBoost()
            btSet.disabled = false
            EnableDisableClearBtn()
        });

        jQuery(btSet).on('click', function() {
            setPlusOneBoost()
            this.disabled = true
            EnableDisableClearBtn()
        });

        jQuery(btClear).on('click', function() {
            input.value = "None"
            this.disabled = true
            btSet.disabled = false
        });

        function EnableDisableClearBtn(firstRun) {
            if (firstRun)
            {
                btSet.disabled = true
                if (input.value ==="None")
                    btClear.disabled = true
                else
                    btClear.disabled = false
            }
            else if (!firstRun)
            {
                if (btSet.disabled === true && input.value === "None")
                {
                    btClear.disabled = true
                }
                else
                    btClear.disabled = false
            }
        }

        function plusOneBoost(){
            var arrBoostTime, iTime = [], iTempTimeComp
            if (btSet.disabled)
                btSet.disabled = false

            arrBoostTime = (input.value.trim()).split(" ")
            for (iTempIndex = 0; iTempIndex < arrBoostTime.length; iTempIndex++)
            {
                iTempTimeComp = arrBoostTime[iTempIndex].replace(oArrComponents[iTempIndex].shortLabel, "")
                iTempTimeComp = (iTempTimeComp === "None") ? "0" : iTempTimeComp

                if ((oArrComponents[iTempIndex].shortLabel === "hr") && !(iTempTimeComp.includes(oArrComponents[oArrComponents.length - 1].shortLabel)))
                {
                    iTempTimeComp = ((iTempTimeComp === "") ? ("1" + oArrComponents[iTempIndex].shortLabel) : ((parseInt(iTempTimeComp) < 6) ? (parseInt(iTempTimeComp) +1) + oArrComponents[iTempIndex].shortLabel : ""))
                }
                else if ((oArrComponents[iTempIndex].shortLabel === "m") && iTempTimeComp)
                {
                    iTempTimeComp = iTempTimeComp + oArrComponents[iTempIndex].shortLabel
                }
                else
                {
                iTime.push("1" + oArrComponents[iTempIndex].shortLabel)
                }
                if (iTempTimeComp)
                    iTime.push(iTempTimeComp)
            }

            input.value = (Array.isArray(iTime) && iTime.length) ? iTime.join(" ") : "None"
        }


    function setPlusOneBoost(){
        console.log("SEND TO SERVER elInput.value", input.value)//mc
        //send to server
    }

    //public Functions

    this.setPlusOneBoost =function () {
        setPlusOneBoost()
    }
    this.EnableDisableClearBtn = function () {
        EnableDisableClearBtn()
    }

    EnableDisableClearBtn(firstRun = true)
    }

    // Boost END
    //---------------

    //---------------
    // Program Switch START

    jQuery('#sel-chsettings-heat-switch').on('change', function() {
        console.log( "SEND TO SERVER value", this.value );
    });

    // Program Switch END
    //---------------

    //---------------
    // Advance START

    jQuery('#bt-chsettings-heat-advance').on('click', function() {
        console.log( "SEND TO SERVER heat Advance");
    });

    // Advance END
    //---------------

    //---------------
    // Boost/On Setpoint START

    var oAPCHset3
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel
    var oArrData = [];

    dSetDecimal = 10.7;
    dMinDecimal = 0.6;
    dMaxDecimal = 25.3;
    sUnitLabel = " °C";
    bShowSeparator = true;
    sFormatDecimal = "nn.d"


    jQuery("#ip-chsettings-boost-and-on-setpoint").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            showSeparator: bShowSeparator,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            onInit: function()
            {
                oAPCHset3 = this;

                sMaxDecimal = oAPCHset3.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPCHset3.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                oAPCHset3.setMaximumDecimal(sMaxDecimal);
                oAPCHset3.setMinimumDecimal(sMinDecimal);

                sSetDecimal = oAPCHset3.formatOutputDecimals(dSetDecimal, sFormatDecimal);

                oAPCHset3.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })
    // Boost/On Setpoint END
    //---------------

    //---------------
    // Default Setpoint START
    var oAPCHset4
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel
    var oArrData = [];

    dSetDecimal = 10.7;
    dMinDecimal = 0.6;
    dMaxDecimal = 25.3;
    sUnitLabel = " °C";
    bShowSeparator = true;
    sFormatDecimal = "nn.d"


    jQuery("#ip-chsettings-default-setpoint").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            showSeparator: bShowSeparator,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            onInit: function()
            {
                oAPCHset4 = this;

                sMaxDecimal = oAPCHset4.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPCHset4.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                oAPCHset4.setMaximumDecimal(sMaxDecimal);
                oAPCHset4.setMinimumDecimal(sMinDecimal);

                sSetDecimal = oAPCHset4.formatOutputDecimals(dSetDecimal, sFormatDecimal);

                oAPCHset4.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })
    // Default Setpoint END
    //---------------

    //---------------
    // Heatup Rate START

    var oAPCHset5
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel,
        iInterval
    var oArrData = [];

    dSetDecimal = .35;
    dMinDecimal = 0.1;
    dMaxDecimal = 1;
    sUnitLabel = null;
    bShowSeparator = true;
    bAllInOneComponent = true;
    sFormatDecimal = "n.dd"
    iInterval = 5


    jQuery("#ip-chsettings-heatup-rate").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            showSeparator: bShowSeparator,
            allInOneComponent: bAllInOneComponent,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            intervals:
                    {
                        n: 1,
                        d: iInterval
                    },

            onInit: function()
            {
                oAPCHset5 = this;

                sMaxDecimal = oAPCHset5.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPCHset5.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                //console.log("ip-chsettings-heatup-rates sMaxDecimal: ", sMaxDecimal)//mc
                //console.log("ip-chsettings-heatup-rates sMinDecimal: ", sMinDecimal)//mc
                oAPCHset5.setMaximumDecimal(sMaxDecimal);
                oAPCHset5.setMinimumDecimal(sMinDecimal);

                sSetDecimal = String(oAPCHset5.formatOutputDecimals(dSetDecimal, sFormatDecimal))
                //console.log("ip-chsettings-heatup-rates SetDecimal: ", sSetDecimal)//mc

                oAPCHset5.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })


    // Heatup Rate END
    //---------------

    //---------------
    // Min Startup Time START

var oAPCHset6
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel,
        iInterval
    var oArrData = [];

    dSetDecimal = 30;
    dMinDecimal = 1;
    dMaxDecimal = 60;
    sUnitLabel = null;
    //bShowSeparator = true;
    //bAllInOneComponent = true;
    //sFormatDecimal = "n.dd"
    sFormatDecimal = "nn"
    //iInterval = 5


    jQuery("#ip-chsettings-min-startup-time").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            //showSeparator: bShowSeparator,
            //allInOneComponent: bAllInOneComponent,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            intervals:
                    {
                        n: 5,
                    },

            onInit: function()
            {
                oAPCHset6 = this;

                sMaxDecimal = oAPCHset6.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                sMinDecimal = oAPCHset6.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                //console.log("ip-chsettings-heatup-rates sMaxDecimal: ", sMaxDecimal)//mc
                //console.log("ip-chsettings-heatup-rates sMinDecimal: ", sMinDecimal)//mc
                oAPCHset6.setMaximumDecimal(sMaxDecimal);
                oAPCHset6.setMinimumDecimal(sMinDecimal);

                sSetDecimal = String(oAPCHset5.formatOutputDecimals(dSetDecimal, sFormatDecimal))
                //console.log("ip-chsettings-heatup-rates SetDecimal: ", sSetDecimal)//mc

                oAPCHset6.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })


    // Min Startup Time END
    //---------------

    //---------------
    // Max Startup Time START

var oAPCHset7
    var dSetDecimal, dMinDecimal, dMaxDecimal,
        sSetDecimal, sMinDecimal, sMaxDecimal,
        bShowSeparator,sFormatDecimal, sUnitLabel,
        iInterval
    var oArrData = [];

    dSetDecimal = 240;
    dMinDecimal = 1;
    dMaxDecimal = 480;
    sUnitLabel = null;
    //bShowSeparator = true;
    //bAllInOneComponent = true;
    //sFormatDecimal = "n.dd"
    sFormatDecimal = "nnn"
    //iInterval = 5


    jQuery("#ip-chsettings-max-startup-time").AnyPicker(
        {
            mode: "decimal",

            unitLabel: sUnitLabel,
            //showSeparator: bShowSeparator,
            //allInOneComponent: bAllInOneComponent,

            inputDecimalFormat: sFormatDecimal,
            decimalFormat: sFormatDecimal,

            intervals:
                    {
                        n: 5,
                    },

            onInit: function()
            {
                oAPCHset7 = this;

                //console.log("ip-chsettings-max-startup-time dMaxDecimal: ", dMaxDecimal)//mc
                //console.log("ip-chsettings-max-startup-time sFormatDecimal: ", sFormatDecimal)//mc
                //console.log("ip-chsettings-max-startup-time oAPCHset7.formatOutputDecimals(dMaxDecimal, sFormatDecimal): ", oAPCHset7.formatOutputDecimals(dMaxDecimal, sFormatDecimal))//mc
                sMaxDecimal = oAPCHset7.formatOutputDecimals(dMaxDecimal, sFormatDecimal);
                //console.log("ip-chsettings-max-startup-time sMaxDecimal: ", sMaxDecimal)//mc
                sMinDecimal = oAPCHset7.formatOutputDecimals(dMinDecimal, sFormatDecimal);

                //console.log("ip-chsettings-heatup-rates sMaxDecimal: ", sMaxDecimal)//mc
                //console.log("ip-chsettings-heatup-rates sMinDecimal: ", sMinDecimal)//mc
                oAPCHset7.setMaximumDecimal(sMaxDecimal);
                oAPCHset7.setMinimumDecimal(sMinDecimal);

                sSetDecimal = String(oAPCHset5.formatOutputDecimals(dSetDecimal, sFormatDecimal))
                //console.log("ip-chsettings-heatup-rates SetDecimal: ", sSetDecimal)//mc

                oAPCHset7.setSelectedDecimal(sSetDecimal);

                sMaxDecimal = dMaxDecimal
                sMinDecimal = dMinDecimal
            },

            onSetOutput: function(sOutput, oSelectedValues)
            {
                console.log("SEND TO SERVER onSetOutput sOutput: ", sOutput) //mc
                //sMinDecimal = sOutput;
            }
        })



    // Max Startup Time END
    //---------------

    //---------------
    // Setpoint Offset START


    // Setpoint Offset END
    //---------------

    //---------------
    // Comfort START


    // Comfort END
    //---------------

};

function HWSettingsPage() {

};

function SysSettingsPage() {

};

function CHProgsPage() {

};

function HWProgsPage() {

};

function HolidayProgsPage() {

};

function SpecialProgsPage() {

};

function CHProgDetailsPage() {

};

function HWProgDetailsPage() {

};

function HolidayProgDetailsPage() {

};

function SpecialProgDetailsPage() {

};
