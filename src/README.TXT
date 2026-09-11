# TiLauScope is a fork from Artisan roaster

## Current version: 3.4.6 Build 202512

## what computer can run think Fork

- Windows 11, maybe 10 (not tested)
- MacOS up to 26 (latest version) Intel and Silicon

## What is inside?

- holds all latest official Artisan changes and roaster support from continuous build of 2025-10
- prevent screen saver to start when roasting on battery and prevent screen to dim if not in front as well (from ON to OFF phases)
- add floating annotation on PID, display in real time at BT offset Manual or Ramp/Soak phases, remaining phases and time
- add explicit display of ON and OFF PID so that there is no confusion if it works or not
- add floating annotation during roast if DeltaBT projection is ON. annotation displays information from CHARGE to DROP with appropriate information such as % and length, temperatures, ...
- displays floating vertical line with expected DE and FC time based on phases menu (cross of t° with projection)
- add import of Hibean roast logs exported from Hibean app, convert to Artisan all the parameters including events and timing. displayed profile can be saved as alog afterwards
- add support for Lebrew C1 RoastSee in roast properties and device tabs. scan in device/network tab to discover, then use afterwards in roast properties. a button helps to store value measured to whole/ground fields
- add modbus to mqtt container to allow to gather MQTT ambient information and push them to ambient fields of Artisan (Pressure, Temperature, Humidity)
- add a bean storage management (bean cave) that stores information locally (no cloud required). bean cave allows to define many kind of green beans and parse your alog information to display their content.
  - bean management (add, update, delete) with support for many parameters, stock in g included
  - alog profiles exploration (displays the curves in real time), load in artisan main window or background directly
  - if a Niimbot B21 printer is detected, labels can be printed in 80x50 and 50x30 for bean storage (bag and tubes). For the moment only these two sizes are supported
  - all roasting information including color prediction are displayed in an additional tab
  - beancave directory can be chosen, alog directory as well
  - a buttons allows to parse the alog files and compute stats, and number of roasts displayed oin the first tab
  - a LLM button allows to compute IA stuff to detect quality of your roasts, compute coefficients that will be used for predictive calculation adapted to your machine/roast habits. this is also generating a CSV file that can be used in some other IA engine. this is the choice I made to keep Artisan lightweight with data usage
- Difluid Airwave support
  - detection of device is done in device tab, choose if you want to use it manually or if you wan the automatic PID feature working withe the device/airwave pid tab to take over. this  intelligent pid, monitors your roast and keep variations of temperature within the drumm as small as possible to prevent crash/flick using succion power of Airwave. values are based on my experiments on cyberroaster/skywalker v2 roaster
  - omniflux emulation mode also supported (automatically disables the pid), but not officially available at the moment, working only with the V500 firmware
  - in device tab, airwave inlet and catalyst temps can be mapped to extra devices
  - in event/config, you can add commands with "Difluid Airwave Command" device listed or IO Commands
    - with IOCommands, syntax is: airwave(GET|SET,COMMAND), airwave is interpreted in lower case only at the moment
    - with Difluid Airwave command: COMMAND[,COMMAND] (multiple commands separated by comma, all commands in uppercases, spaces are trimmed)
    - SET commands :
      - POWER ON|OFF ON=activates, OFF=in ready mode, does extract air. this command has no effect in Omniflux emulation mode
      - FAN [30-10] Set fan speed, should be done AFTER setting mode
      - MODE [FAN|STD|EXT] Set succion mode, FAN only triggers air out, STD activates catalyst for low smoke roasts, EXT activates exteme mode for heavy loads that generate a lot of smoke. Mode can be chose in the airwave pid as well
      - EVENT [PREHEAT|CHARGE|DRY|FCS|FCE|DROP] send the actual roasting phase (works only in Omniflux mode)
      - CONTROL [MANUAL|AUTO] allows in Omniflux mode to go in full automated mode or to get back to manual mode. at the moment there is no mean to get out of Omniflux mode else than switching the device off and on with the current firmware
      - OMNIFLUX [ARM|DISARM]: set omniflux mode on or off (off mode does not really work at the moment, airwave returns in manual mode and stops to query for roasting phase)
    - GET commands that can be used with airwave() syntax:
      - FAN : returns the FAN actual % 30-100
      - STATE : returns the actual power on/off state (can be useful for scripting)
      - SN : returns serial number of device
      - FW : returns firmware version (actually V400 string)
      - INLET : returns temperature of inlet probe in °C
      - CATALYST: returns temperature of catalyst probe in °C
      - TEMP : returns a dictionary of two values with 'inlet' and 'catalyst' temperatures rounded at 1 digit (this is used by sampling loop or artisan and not intended to be used directly)
  - PID on DeltaET move of Airware to control flicks and crashes with equalized succion
- TiLauScope ambient probe support to get temperature, humidity, pressure, and also add beta of crack detection at FC with 3 commands (CALIBRATE, START and STOP on Tilauscopeambient 56, 5th slot)
