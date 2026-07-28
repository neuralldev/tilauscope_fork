#
# ABOUT
# Hibean JSON Profile importer for Artisan

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2025


import json
from datetime import datetime
import math
import logging
from typing import Final

_log: Final[logging.Logger] = logging.getLogger(__name__)

#if TYPE_CHECKING:
#    from artisanlib.main import ApplicationWindow # pylint: disable=unused-import

try:
    from PyQt6.QtWidgets import QApplication # @UnusedImport @Reimport  @UnresolvedImport
except ImportError:
    from PyQt5.QtWidgets import QApplication # type: ignore # @UnusedImport @Reimport  @UnresolvedImport


from artisanlib.atypes import ProfileData
from artisanlib.util import events_external_to_internal_value

# this is the artisan alog structure to generate
class AlogStructure:
    def __init__(self):
        super().__init__()
        self.alog = {
            "recording_version": "3.2.1",
            "#recording_revision=": "",
            "#recording_build=": "0",
            "version": "3.2.1",
            "revision": "0",
            "build":"0",
            "artisan_os": "macOS",
            "artisan_os_version": "15.6",
            "artisan_os_arch": "arm64",
            "mode": "",
            "viewerMode": False,
            "timeindex": [0, 0, 0, 0, 0, 0, 0, 0],
            "flavors": [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            "flavors_total_correction": 0.0,
            "flavorlabels": ["acidity", "aftertaste", "aroma", "body", "cleanCup", "fragrance", "sweetness", "uniformity", "balance"],
            "flavorstartangle": 90,
            "flavoraspect": 1.0,
            "title": "", # import from roastcontext["name"]
            "locale": "en",
            "beans":"",
            "weight": [0.0,0.0,"g"],
            "defects_weight":0.0,
            "volume":[0,0,"l"],
            "density":[0,"g",1.0,"l"], #import from roastContext["bean"]["density"] into second parameter as integer
            "density_roasted":[0,"g",1.0,"l"],
            "roastertype":"", # import from deviceInfo["name"]
            "roastersize":0.0,
            "roasterheating": 3,
            "machinesetup":"Legacy",
            "operator":"",
            "organization":"",
            "drumspeed":"",
            
            "lowFC":False,
            "heavyFC":False,
            "lightCut":False,
            "darkCut":False,
            "drops":False,
            "oily":False,
            "uneven":False,
            "tipping":False,
            "scorching":False,
            "divots":False,
            
            "whole_color":0, # import from roastContext["roastLevel"]["roastLevelStandard"]
            "ground_color":0,
            "color_system":"Agtron",
            "volumeCalcWeightIn":"0",
            "volumeCalcWeightOut":"0",
            "roastdate":"", # import from dateTime to string, convert from formated string YYYY-MM-ddThh:mm:ss.000"
            "roastisodate":"", # import from dateTime to YYYY-MM-DD string, convert from formated string YYYY-MM-ddThh:mm:ss.000"
            "roasttime":"",  # import from dateTime to hh:mm:ss string, convert from formated string
            "roastepoch":0,
            "roasttzoffset":0, # ?
            "roastbatchnr":0,
            "roastbatchprefix":"",
            "roastbatchpos":1,
            "roastUUID":"", #import from cloudId as string
            "beansize_min":"0",
            "beansize_max":"0",
            "specialevents":[],
            "specialeventstype":[],
            "specialeventsvalue":[],
            "specialeventsStrings":[],
            "default_etypes":[True,True,True,True,True],
            "default_etypes_set":[0,0,0,0,0],
            "etypes":[ "Air","Drum","Damper","Burner","--"],
            "roastingnotes":"",
            "cuppingnotes":"",
            "timex":[], # import from datalist[duration] for each record
            "temp1":[], # import from datalist[et] for each record
            "temp2":[], # import from datalist[bt] for each record
            "phases":[0,150,185,230], # import from phaselist[duration] where phaselist[phase] = 2 to second value,  where phaselist[phase] = 3 in third value, where phaselist[phase] = 4 to 4th value
            "zmax":0, # import max value from datalist records from "ror" field, round value to next upper multiple of 5
            "zmin":0,
            "ymax":250, # import max value from datalist records from "et" and "bt" fields, round to next upper multiple of 50
            "ymin":0,
            "xmax":0, # import max value from datalist records from "duration" ield, round to next upper multiple of 5
            "xmin":0,
            "ambientTemp":0.0, # import from roastContext["envTemp"]["value"] as float
            "ambient_humidity":0.0, # import from roastContext["envHumidity]["value"] as float
            "ambient_pressure":0.0, # import from roastContext["pressure]["value"] as float
            "moisture_greens":0.0,
            "greens_temp":0.0,
            "moisture_roasted":0.0,
            "extradevices":[32, 44],  #assume  '+ArduinoTC4 56' and 78
            "extraname1":["{3}","{1}"], #burner
            "extraname2":["{0}","SV"], #fan
            "extratimex":[],
            "extratemp1":[],
            "extratemp2":[],
            "extramathexpression1":["",""], 
            "extramathexpression2":["",""], 
            "extradeicecolor1":[ "#ad0427", "#ad0427"], 
            "extradevicecolor2":["#48abffff","#000000"], 
     #       "extraLCDvisibility1":[False, False], 
     #       "extraLCDvisibility2":[True, False], 
     #       "extraCurveVisibility1":[False, False], 
     #       "extraCurveVisibility2":[False, False], 
     #       "extraDelta1":[False, False], 
     #       "extraDelta2":[False, False], 
     #       "extraFill1":[0,0], 
     #       "extraFill2":[0,0], 
     #       "extramarkersizes1":[6.0,6.0], 
     #       "extramarkersizes2":[6.0,6.0], 
     #       "extramarkers1":["None","None"], 
     #       "extramarkers2":["None","None"], 
     #       "extralinewidths1":[1.0,1.0], 
     #       "extralinewidths2":[1.0,1.0], 
     #       "extralinestyles1":["-","-"], 
     #       "extralinestyles2":["-","-"], 
     #       "extradrawstyles1":["default","default"], 
     #       "extradrawstyles2":["default","default"], 
            "externalprogram":"test.py", 
            "externaloutprogram":"out.py", 
            "extraNoneTempHint1":[False,False,True,False,True,True], 
            "extraNoneTempHint2":[False,False,True,False,False,True], 
#            "alarmsetlabel":"",
#            "alarmflag":[], 
#            "alarmguard":[], 
#            "alarmnegguard":[], 
#            "alarmtime":[], 
#            "alarmoffset":[], 
#            "alarmcond":[], 
#            "alarmsource":[], 
#            "alarmaction":[], 
#            "alarmbeep":[], 
#            "alarmtemperature":[], 
#            "alarmstrings":[], 
            "backgroundpath":"", 
            "samplinginterval":1.0, 
            "svLabel":"regular", 
            "svValues":[0,0,0,0,0,0,0,0], 
            "svRamps":[0,0,0,0,0,0,0,0], 
            "svSoaks":[0,0,0,0,0,0,0,0], 
            "svActions":[0,0,0,0,0,0,0,0], 
            "svBeeps":[False,False,False,False,False,False,False,False], 
            "svDescriptions":["","","","","","","",""], 
            "pidKp":0.0, 
            "pidKi":0.0, 
            "pidKd":0.0, 
            "svLookahead":0.0, 
            "devices":["-ARDUINOTC4","+ArduinoTC4 56","+ArduinoTC4 78"],
            "elevation":0, 
            "computed": { 
                "CHARGE_ET": 0.0, # if datalist records have an "event" value =1, the take record "et"
                "CHARGE_BT": 0.0, # if datalist records have an "event" value =1, the take record "bt"
                "TP_idx": 315,  # if datalist records have an "event" value =2, the take record index in the table
                "TP_time": 0.0,  # if datalist records have an "event" value =2, the take record "duration"
                "TP_ET": 124.4, # if datalist records have an "event" value =2, the take record "et"
                "TP_BT": 97.7, # if datalist records have an "event" value =2, the take record "bt"
                "MET": 0,
                "DRY_time": 368.0, # if datalist records have an "event" value =3, the take record "duration"
                "DRY_ET": 135.0, # if datalist records have an "event" value =3, the take record "et"
                "DRY_BT": 154.7, # if datalist records have an "event" value =3, the take record "bt"
                "FCs_time": 588.0, # if datalist records have an "event" value =4, the take record "duration"
                "FCs_ET": 150.7, # if datalist records have an "event" value =4, the take record "et"
                "FCs_BT": 187.0, # if datalist records have an "event" value =4, the take record "bt"
                "DROP_time": 668.0, # if datalist records have an "event" value =6, the take record "duration"
                "DROP_ET": 155.6, # if datalist records have an "event" value =6, the take record "et"
                "DROP_BT": 197.1, # if datalist records have an "event" value =6, the take record "bt"
                "totaltime": 668.0, # import from roastContext["duration"]
                "dryphasetime": 368.0, # import from phaselist[0]["duration"] 
                "midphasetime": 220.0, # import from phaselist[1]["duration"] 
                "finishphasetime": 80.0, # import from phaselist[2]["duration"] 
                "dry_phase_ror": 21.6, # compute mean of datalist records "ror" field from field "event" 2 to 3 
                "mid_phase_ror": 8.8, # compute mean of datalist records "ror" field from field "event" 3 to 4 
                "finish_phase_ror": 7.5, # compute mean of datalist records "ror" field from field "event" 4 to 6 
                "total_ror": 10.1, # mean of the three previous values
                "fcs_ror": 8.8, # dry_phase_ror calculation
                "dry_phase_delta_temp": 132.7, # compute delta between min and max value of datalist records "BT" field from field "event" 2 to 3 
                "mid_phase_delta_temp": 32.3, # compute delta between min and max value of datalist records "BT" field from field "event" 3 to 4 
                "finish_phase_delta_temp": 10.1, # compute delta between min and max value of datalist records "BT" field from field "event" 4 to 6 
                "total_ts": 0,
                "total_ts_ET": 0,
                "total_ts_BT": 0,
                "AUC": 0,
                "AUCbegin": "CHARGE",
                "AUCbase": 0,
                "AUCfromeventflag": 1,
                "dry_phase_AUC": 0,
                "mid_phase_AUC": 0,
                "finish_phase_AUC": 0,
                "weight_loss": 0,
                "roast_defects_loss": 0,
                "volumein": 0,
                "volumeout": 0,
                "weightin": 0.0, # import from roastContext["greenBeanWeight"]["value"]
                "weightout": 0.0,# import from roastContext["roastedBeanWeight"]["value"]
                "roast_defects_weight": 0.0,
                "total_yield": 0.0,
                "total_loss": 0.0, # computed from weightin - weightout
                "green_density":0.0 , # computed from density
                "roasted_density": 0.0, # computed from density_roasted[0]
                "set_density": 0.0, # computed from density
                "moisture_greens": 0.0,
                "ambient_temperature": 0.0, # computed from ambientTemp
                "BTU_preheat": 0.0,
                "CO2_preheat": 0.0,
                "BTU_bbp":0.0,
                "CO2_bbp": 0.0,
                "BTU_cooling": 0.0,
                "CO2_cooling": 0.0,
                "BTU_LPG": 0.0,
                "BTU_NG": 0.0,
                "BTU_ELEC": 0.0,
                "BTU_batch": 0.0,
                "BTU_batch_per_green_kg": 0.0,
                "BTU_roast": 0.0,
                "BTU_roast_per_green_kg": 0.0,
                "CO2_batch": 0.0,
                "CO2_batch_per_green_kg": 0.0,
                "CO2_roast": 0.0,
                "CO2_roast_per_green_kg": 0.0,
                "KWH_batch_per_green_kg": 0.0,
                "KWH_roast_per_green_kg": 0.0,
                "bbp_total_time": 0.0,
                "bbp_bottom_temp": 0.0,
                "bbp_begin_to_bottom_time": 0.0,
                "bbp_bottom_to_charge_time": 0.0,
                "bbp_begin_to_bottom_ror": 0.0,
                "bbp_bottom_to_charge_ror": 0.0
            },
            "anno_positions": [],
            "flag_positions": [],
            "loadlabels": [
                "",
                "",
                "",
                ""
            ],
            "loadratings": [
                0.0,
                0.0,
                0.0,
                0.0
            ],
            "ratingunits": [
                0,
                0,
                0,
                0
            ],
            "sourcetypes": [
                0,
                0,
                0,
                0
            ],
            "load_etypes": [
                0,
                0,
                0,
                0
            ],
            "presssure_percents": [
                False,
                False,
                False,
                False
            ],
            "loadevent_zeropcts": [
                0,
                0,
                0,
                0
            ],
            "loadevent_hundpcts": [
                100,
                100,
                100,
                100
            ],
            "meterlabels": [
                "",
                ""
            ],
            "meterunits": [
                3,
                3
            ],
            "meterfuels": [
                2,
                2
            ],
            "metersources": [
                0,
                0
            ],
            "meterreads": [
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0
                ],
                [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0
                ]
            ],
            "co2kg_per_btu": [
                6.288e-05,
                5.291e-05,
                0.0002964
            ],
            "biogas_co2_reduction": 0.7562,
            "preheatDuration": 0,
            "preheatenergies": [
                0.0,
                0.0,
                0.0,
                0.0
            ],
            "betweenbatchDuration": 0,
            "betweenbatchenergies": [
                0.0,
                0.0,
                0.0,
                0.0
            ],
            "coolingDuration": 0,
            "coolingenergies": [
                0.0,
                0.0,
                0.0,
                0.0
            ],
            "betweenbatch_after_preheat": True,
            "electricEnergyMix": 0,
            "gasMix": 0,
            "bbp_begin": "Start",
            "bbp_time_added_from_prev": 0.0,
            "bbp_endroast_epoch_msec": 0,
            "bbp_endevents": [],
            "bbp_dropevents": [],
            "bbp_dropbt": 0.0,
            "bbp_dropet": 0.0,
            "bbp_drop_to_end": 0.0
        }

# returns a dict containing all profile information contained in the given Hibean JSON file
def extractProfileHibeanJson(file:str, etypesdefault, altetypesdefault, artisanflavordefaultlabels, eventsExternal2InternalValue) -> ProfileData:

  
    def _get_time_for_event(event_list, event_id):
        event = next((e for e in event_list if e.get("event") == event_id), None)
        return event.get("time", 0.0) if event else 0.0
       
    def _update_crack_info(alog_data, event_list, event_id, temp_key, time_key):
        for event in event_list:
            if event.get("event") == event_id:
                alog_data[temp_key] = event.get("temperature", 0.0)
                alog_data[time_key] = event.get("time", 0.0)
                return
    
    res:ProfileData = ProfileData() # the interpreted data set
    artisan_structure = AlogStructure()
    alog_data = artisan_structure.alog
    events_fan:list[tuple[int, float, float]] = [] # list of triples (tx_idx, event_nr, value)
    events_heat:list[tuple[int, float, float]] = [] # list of triples (tx_idx, event_nr, value)
    events_drum:list[tuple[int, float, float]] = [] # list of triples (tx_idx, event_nr, value)
    events_ts:list[tuple[int, float, float]] = [] # list of triples (tx_idx, event_nr, value)   
    events:list[tuple[int, float, float]] = [] # list of triples (tx_idx, event_nr, value)

    try:
        with open(file) as f:
            hibean_data = json.load(f)
            
        # Mapping des données de base
        roast_context = hibean_data.get("roastContext", {})
        device_info = hibean_data.get("deviceInfo", {})
        data_list = hibean_data.get("dataList", [])
        event_list = hibean_data.get("eventList", [])
        phase_list = hibean_data.get("phaseList", [])

        if roast_context is None or device_info is None or data_list is None or event_list is None or phase_list is None:
            return res
        
        date_time_str = hibean_data.get("dateTime", "")
        if date_time_str:   
            dt_object = datetime.fromisoformat(date_time_str.replace('Z', ''))
            roast_date = dt_object.strftime("%Y-%m-%d")
            roast_time = dt_object.strftime("%H:%M:%S")
            roast_longdate = dt_object.strftime("%a %b %d %Y")
            roast_epoch = dt_object.timestamp()
        else:
            roast_date = ""
            roast_time = ""
            roast_longdate = ""
            roast_epoch = 0

        # Remplir la structure Artisan avec les données Hibean
        # Modification : Mise à jour des valeurs directement dans le dictionnaire
        alog_data["mode"] =hibean_data.get("temperatureUnit", "C")
        alog_data["title"] =roast_context.get("name", "")
        alog_data["roastertype"] = device_info.get("name","") 
        alog_data["roastisodate"] = roast_date
        alog_data["roastdate"] = roast_longdate
        alog_data["roasttime"] = roast_time
        alog_data["roastepoch"] = roast_epoch
        alog_data["roastUUID"] = hibean_data.get("id","")
        alog_data["beans"] = roast_context.get("greenBeanWeight", {}).get("value", 0.0) if roast_context.get("greenBeanWeight") is not None else 0.0
        alog_data["weight"][0] = roast_context.get("greenBeanWeight", {}).get("value", 0.0) if roast_context.get("greenBeanWeight") is not None else 0.0
        alog_data["weight"][1] = roast_context.get("roastedBeanWeight", {}).get("value", 0.0) if roast_context.get("roastedBeanWeight") is not None else 0.0
        alog_data["ambientTemp"] = roast_context.get("envTemp", {}).get("value", 0.0) if roast_context.get("envTemp") is not None else 0.0
        alog_data["ambient_humidity"] = roast_context.get("envHumidity", 0) if roast_context.get("envHumidity") is not None else 0
        alog_data["ambient_pressure"] = roast_context.get("pressure", 0) if roast_context.get("pressure") is not None else 0

        # Remplissage de timeindex avec les index correspondants
        hibean_time_indices = [0,0,0,0,0,0,0,0,0]
        time_indices = [0,0,0,0,0,0,0]
        for idx, record in enumerate(data_list):   
            ev = record.get("event")
            if ev is not None :
                hibean_time_indices[ev] = idx
        time_indices[0] = hibean_time_indices[1] #CHARGE
        time_indices[1] = hibean_time_indices[3] #DE
        time_indices[2] = hibean_time_indices[4] #FCs
        time_indices[3] = 0 #FCe
        time_indices[4] = hibean_time_indices[6] #SC
        time_indices[5] = hibean_time_indices[7] #SCe
        time_indices[6] = hibean_time_indices[8] #DROP

        alog_data["timeindex"] = time_indices

        # Remplir les données de séries temporelles
        data_list = hibean_data.get("dataList", [])
        time_series = []
        bt_series = []
        et_series = []
        heat_series = []
        fan_series = []
        drum_series = []
        ts_series = []
        ror_bt_series = []
        ror_et_series = []

        for data_point in data_list:
            time_series.append(data_point.get("duration", 0.0))
            bt_series.append(data_point.get("bt", 0.0))
            et_series.append(data_point.get("et", 0.0))
            ror_bt_series.append(data_point.get("ror", 0.0))
            ror_et_series.append(data_point.get("ror", 0.0))

            roaster_params = data_point.get("roasterParams", [])

            heat = 0
            fan = 0
            drum = 0
            heat = next((param.get("value", 0) for param in roaster_params if param.get("key") == "HP"), 0)
            fan = next((param.get("value", 0) for param in roaster_params if param.get("key") == "FC"), 0)
            drum = next((param.get("value", 0) for param in roaster_params if param.get("key") == "RC"), 0)
            ts = next((param.get("value", 0) for param in roaster_params if param.get("key") == "TS"), 0)
            timer = int(round(data_point.get("duration", 0),0))
            heat_series.append(events_external_to_internal_value(heat))
            fan_series.append(events_external_to_internal_value(fan))
            drum_series.append(events_external_to_internal_value(drum))
            ts_series.append(ts)

            # extract fan information
            if (len(events_fan)==0 and fan > 0.0) or (len(events_fan) > 0 and events_fan[-1][2] != fan):
                events_fan.append((0,timer, fan)) # 0= etype fan

            # extract heater information
            if (len(events_heat)==0 and heat > 0.0) or (len(events_heat) > 0 and events_heat[-1][2] != heat):
                events_heat.append((3,timer, heat)) # 3= etype heater

            # extract drum information
            if (len(events_drum)==0 and drum > 0.0) or (len(events_drum) > 0 and events_drum[-1][2] != drum):
                events_drum.append((1,timer, drum)) # 1= etype drum

            # extract ts information
            if (len(events_ts)==0 and ts > 0.0) or (len(events_ts) > 0 and events_ts[-1][2] != ts):
                events_ts.append((2,timer, ts)) # 2= etype ts

        events = events_fan + events_heat + events_drum + events_ts
        events.sort(key=lambda x: (x[1], x[0]))  # Sort by time index, event
        
        # populate heater and fan change, drum is not present at the moment
        alog_data["specialevents"]=[e[1] for e in events]
        alog_data["specialeventstype"]=[e[0] for e in events]
        alog_data["specialeventsvalue"]=[(events_external_to_internal_value(int(e[2]))) for e in events] # fix 2024/11/20

        alog_data["specialeventsStrings"] = [f"set {alog_data['etypes'][e[0]]} to {(int(e[2]))}" for e in events] # fix 2024/11/20

        alog_data["timex"] = time_series
        alog_data["temp2"] = bt_series
        alog_data["temp1"] = et_series

        alog_data["extratimex"].append(time_series) # one for device 1 -> 2 entries
        alog_data["extratimex"].append(time_series) # one for device 2 -> 2 entries
        alog_data["extratemp1"].append(heat_series)
        alog_data["extratemp1"].append(drum_series)
        alog_data["extratemp2"].append(fan_series)
        alog_data["extratemp2"].append(ts_series)

        #alog_data["ror_bt"] = ror_bt_series
        #alog_data["ror_et"] = ror_et_series

        # calcul des valeurs min et max des axes
#        min_bt = min(bt_series)
        max_bt = max(bt_series)
        zmax = round(math.ceil(max_bt / 5) * 5,0)
        alog_data["zmax"] = zmax
        alog_data["zmin"] = 0

        # Trouver les temps de charge et de drop
        charge_time = next((event['time'] for event in event_list if event['event'] == 1), 0.0)
        drop_time = next((event['time'] for event in event_list if event['event'] == 6), 
                max(event['duration'] for event in data_list) if data_list else 0.0)
        # Calculer xmin
        xmin = max(0, charge_time - 10)
        # Calculer xmax
        xmax = math.ceil(drop_time / 60) * 60
        alog_data["xmax"] = xmax
        alog_data["xmin"] = xmin

        # Déterminer les temps et températures pour les cracks et drop
        _update_crack_info(alog_data, event_list, 4, "first_crack_temp", "first_crack_time")
        _update_crack_info(alog_data, event_list, 5, "second_crack_temp", "second_crack_time")
        _update_crack_info(alog_data, event_list, 8, "drop_temp", "drop_time")
        _update_crack_info(alog_data, event_list, 8, "end_temp", "end_time")

        # Dictionnaire pour stocker les temps des événements pour les calculs ROR
        event_times = {
            'charge': _get_time_for_event(event_list, 1),
            'tp': _get_time_for_event(event_list, 2),
            'dry': _get_time_for_event(event_list, 3),
            'fcs': _get_time_for_event(event_list, 4),
            'drop': _get_time_for_event(event_list, 8)
        }

        # Remplissage des valeurs dans 'computed'
        computed = alog_data["computed"]

        # Extraction des données des événements spécifiques
        charge_event = next((e for e in event_list if e.get("event") == 1), None)
        if charge_event:
            computed["CHARGE_ET"] = round(charge_event.get("temperature", 0.0), 1)
            computed["CHARGE_BT"] = round(charge_event.get("temperature", 0.0), 1)

        tp_event = next((e for e in event_list if e.get("event") == 2), None)
        if tp_event:
            computed["TP_time"] = round(tp_event.get("time", 0.0), 1)
            computed["TP_ET"] = round(tp_event.get("temperature", 0.0), 1)
            computed["TP_BT"] = round(tp_event.get("temperature", 0.0), 1)

        dry_event = next((e for e in event_list if e.get("event") == 3), None)
        if dry_event:
            computed["DRY_time"] = round(dry_event.get("time", 0.0), 1)
            computed["DRY_ET"] = round(dry_event.get("temperature", 0.0), 1)
            computed["DRY_BT"] = round(dry_event.get("temperature", 0.0), 1)

        fcs_event = next((e for e in event_list if e.get("event") == 4), None)
        if fcs_event:
            computed["FCs_time"] = round(fcs_event.get("time", 0.0), 1)
            computed["FCs_ET"] = round(fcs_event.get("temperature", 0.0), 1)
            computed["FCs_BT"] = round(fcs_event.get("temperature", 0.0), 1)

        drop_event = next((e for e in event_list if e.get("event") == 8), None)
        if drop_event:
            computed["DROP_time"] = round(drop_event.get("time", 0.0), 1)
            computed["DROP_ET"] = round(drop_event.get("temperature", 0.0), 1)
            computed["DROP_BT"] = round(drop_event.get("temperature", 0.0), 1)

        computed["totaltime"] = round(hibean_data.get("roastContext", {}).get("duration", 0.0), 1) if roast_context.get("duration") is not None else 0.0
        computed["ambient_temperature"] = round(roast_context.get("envTemp", {}).get("value", 0.0), 1) if roast_context.get("envTemp") is not None else 0.0
        #            computed["ambient_humidity"] = round(roast_context.get("envHumidity", 0.0), 1) if roast_context.get("envHumidity") is not None else 0.0

        phases_map = {1: "dryphasetime", 2: "midphasetime", 3: "finishphasetime"}
        for phase_point in phase_list:
            phase_type = phase_point.get("phase")
            if phase_type in phases_map:
                computed[phases_map[phase_type]] = round(phase_point.get("duration", 0.0), 1)

        event_times = {
        'tp': _get_time_for_event(event_list, 2),
        'dry': _get_time_for_event(event_list, 3),
        'fcs': _get_time_for_event(event_list, 4),
        'drop': _get_time_for_event(event_list, 6)
        }

        durations = [d.get("duration", 0.0) for d in data_list]

        # Calcul des ROR moyens et des deltas de température par phase
        def get_sub_series(data, start_time, end_time, durations):
            start_index = next((i for i, d in enumerate(durations) if d >= start_time), 0)
            end_index = next((i for i, d in enumerate(durations) if d >= end_time), len(durations))
            return data[start_index:end_index]

        ror_series_full = [d.get("ror", 0.0) for d in data_list]
        bt_series_full = [d.get("bt", 0.0) for d in data_list]

        dry_ror_sub = get_sub_series(ror_series_full, event_times['tp'], event_times['dry'], durations)
        mid_ror_sub = get_sub_series(ror_series_full, event_times['dry'], event_times['fcs'], durations)
        finish_ror_sub = get_sub_series(ror_series_full, event_times['fcs'], event_times['drop'], durations)

        computed["dry_phase_ror"] = round(sum(dry_ror_sub) / len(dry_ror_sub), 1) if dry_ror_sub else 0.0
        computed["mid_phase_ror"] = round(sum(mid_ror_sub) / len(mid_ror_sub), 1) if mid_ror_sub else 0.0
        computed["finish_phase_ror"] = round(sum(finish_ror_sub) / len(finish_ror_sub), 1) if finish_ror_sub else 0.0
        computed["fcs_ror"] = computed["dry_phase_ror"]

        all_roasts = [ror for ror in [computed["dry_phase_ror"], computed["mid_phase_ror"], computed["finish_phase_ror"]] if ror > 0]
        computed["total_ror"] = round(sum(all_roasts) / len(all_roasts), 1) if all_roasts else 0.0

        dry_bt_sub = get_sub_series(bt_series_full, event_times['tp'], event_times['dry'], durations)
        mid_bt_sub = get_sub_series(bt_series_full, event_times['dry'], event_times['fcs'], durations)
        finish_bt_sub = get_sub_series(bt_series_full, event_times['fcs'], event_times['drop'], durations)

        computed["dry_phase_delta_temp"] = round(max(dry_bt_sub) - min(dry_bt_sub), 1) if dry_bt_sub else 0.0
        computed["mid_phase_delta_temp"] = round(max(mid_bt_sub) - min(mid_bt_sub), 1) if mid_bt_sub else 0.0
        computed["finish_phase_delta_temp"] = round(max(finish_bt_sub) - min(finish_bt_sub), 1) if finish_bt_sub else 0.0

        # Remplissage des valeurs de poids et de densité avec arrondi
        computed["weightin"] = round(roast_context.get("greenBeanWeight", {}).get("value", 0.0), 1)  if roast_context.get("greenBeanWeight") is not None else 0.0
        computed["weightout"] = round(roast_context.get("roastedBeanWeight", {}).get("value", 0.0), 1)  if roast_context.get("roastedBeanWeight") is not None else 0.0

        if computed["weightin"] > 0:
            computed["total_loss"] = round(computed["weightin"] - computed["weightout"], 1)
            computed["weight_loss"] = round((computed["total_loss"] / computed["weightin"]) * 100, 1)

        green_density_value = alog_data["density"][0]
        if green_density_value:
            computed["green_density"] = round(green_density_value, 1)
        # now collect special events
        
        res['etypes'] = [QApplication.translate('ComboBox', 'Drum') + 'H',
                            QApplication.translate('ComboBox', 'Drum')+'S',
                            'Halogen',
                            QApplication.translate('ComboBox', 'Heater'),
                            '--']
    
        
    except FileNotFoundError as e:
        _log.exception(e)

    except Exception as e:
        _log.exception(e)
    # Copier les valeurs des clés communes de alog_data dans res
    for key in alog_data:
        res[key] = alog_data[key]
    return res
