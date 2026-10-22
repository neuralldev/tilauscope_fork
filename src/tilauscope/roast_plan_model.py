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
# TiLau 2025, 2026

"""The roast plan on the desktop: the engine of the library shared with the tablet
(tilaucore.roast_plan), fed by Artisan's live settings and TilauScope's folders;
the plan's alarms and its PDF."""


import logging
from typing import Final, Any
from fpdf import FPDF, XPos, YPos
import json
import math
from pathlib import Path
import numpy as np

from tilauscope.tilauscope_types import GreenBean
from tilauscope.roasters import RoasterContext
from tilauscope.alogmanager import AlogIndex, AlogMetadata
from tilauscope import text_shaping
from PyQt6.QtCore import  QSettings
from PyQt6.QtWidgets import QApplication

from tilaucore.artisan_compat import RoRSettings
from tilaucore import roast_plan as _core
from tilaucore.roast_plan import *  # noqa: F403  pylint: disable=wildcard-import,unused-wildcard-import
from tilaucore.roast_plan import (  # noqa: F401  (re-exported for the desktop and its tests)
    _DEV_DESTINATION_BONUS_SEC, _DEV_DESTINATION_DEFAULT, _PlanSource, _SRC_LEARNED, _STRUCTURE_DEAD_BAND_LOW,
    _STRUCTURE_INDEX_MAX, _STRUCTURE_PROXY_WEIGHT, _TECH_GENERIC, _TECH_RADIANT, _choose_coherent_history,
    _fit_fc_charge_regression, _heater_authority_notes, _learning_log_is_eligible, _resolve_green_aw,
    _resolve_green_moisture, _resolve_green_structure, _select_cohort_medoid, _selected_roast_color,
    _tasting_under_reference)
from tilaucore.roast_plan import ROAST_DESTINATION_SETTING, RoastPlanEngine, reference_roast
from tilaucore.roast_plan_view import (_plan_num, _plan_secs, control_trajectories, entry_levels,  # noqa: F401
                                      phase_pct, plan_cooled_weight)

_logd: Final[logging.Logger] = logging.getLogger('tilau')

# The engine's texts come out in the operator's language.
_core.translate = lambda text: QApplication.translate(*text)


class TilauScopeRoastPlan(RoastPlanEngine):
    """The plan engine, reading Artisan and the settings live at each use."""

    def __init__(self, parent=None, roaster_ctx: RoasterContext | None = None):
        self.parent = parent
        # parent IS the ApplicationWindow (aw); its temperature unit lives on aw.qmc.mode.
        # The previous `self.parent.aw.qmc` dereference never resolved (ApplicationWindow
        # has no `.aw`), so self.mode silently stayed "C" and every °F install got a plan
        # computed in °C numbers. Read qmc.mode directly, like all other accesses below.
        mode = parent.qmc.mode if hasattr(parent, 'qmc') and parent.qmc else "C"
        super().__init__(roaster_ctx, alog_directory=QSettings().value('alogDirectory', "", str), mode=mode)

    def _current_mode(self) -> str:
        return (self.parent.qmc.mode
                if self.parent is not None and getattr(self.parent, "qmc", None) is not None
                else "C")

    def _recording(self) -> bool:
        return bool(self.parent.qmc.flagon)

    def _ror_settings(self) -> RoRSettings:
        q = self.parent.qmc
        return RoRSettings(curvefilter=q.curvefilter, interpolate_drops=q.interpolateDropsflag,
                           delta_samples=q.deltaBTsamples, delta_filter=q.deltaBTfilter,
                           median_filter_factor=q.median_filter_factor_RoR, filter_dropouts=q.filterDropOuts,
                           limit=q.RoRlimitFlag, limit_min=max(-q.maxRoRlimit, q.RoRlimitm),
                           limit_max=min(q.maxRoRlimit, q.RoRlimit))

    def _beancave_directory(self) -> str:
        return QSettings().value('beancaveDirectory', '', str)

    def _cave_beans(self) -> list:
        from tilauscope.cave.common import load_cave_beans  # noqa: PLC0415
        return load_cave_beans()

    def _load_index(self, directory: Path) -> "dict[str, AlogMetadata]":
        return AlogIndex.instance().records(directory)

    # Destination du café. Lue en réglage plutôt que passée en paramètre :
    # les trois appelants de generate_roast_plan (dont le replan en cours de
    # roast) restent inchangés. Relue à CHAQUE plan — le moteur est mis en
    # cache par ses appelants, donc une valeur figée ici resterait celle du
    # premier plan alors que l'utilisateur peut changer de destination.
    @staticmethod
    def _read_roast_destination() -> str:
        """Destination courante du café, normalisée sur la table des bonus."""
        _dest = str(QSettings().value(ROAST_DESTINATION_SETTING,
                                      _DEV_DESTINATION_DEFAULT, str) or "").strip().lower()
        return _dest if _dest in _DEV_DESTINATION_BONUS_SEC else _DEV_DESTINATION_DEFAULT

    @staticmethod
    def _reference_roast(bean: GreenBean) -> "tuple[str, str]":
        """(roastUUID, status) of the bean's reference roast; ('', '') when it has none."""
        return reference_roast(bean, QSettings().value('beancaveDirectory', '', str))


class TilauscopeAlarmFactory:
    def __init__(self, plan_data):
        self.plan = plan_data
        # code des actions Tilauscope/Artisan
        self.ACTION_LIST = {
        'Nothing': -1,
        'PopUp': 0,
        'Call Program': 1,
        'Event Button': 2,
        'Slider Air': 3,
        'Slider Drum': 4,
        'Slider Damper': 5,
        'Slider Burner': 6,
        'START': 7,
        'DRY END': 8,
        'FC START': 9,
        'FC END': 10,
        'SC START': 11,
        'SC END': 12,
        'DROP': 13,
        'COOL END': 14,
        'OFF': 15,
        'CHARGE': 16,
        'RampSoak ON': 17,
        'RampSoak OFF': 18,
        'PID ON': 19,
        'PID OFF': 20,
        'SV': 21,
        'Playback ON': 22,
        'Playback OFF': 23,
        'Set Canvas Color': 24,
        'Reset Canvas Color': 25,
        'Difluid Airwave command': 26,
        'TilauScope Ambient command': 27,
        'TilauScope command': 28
        }
        # Codes d'événements Tilauscope/Artisan
        self.EVENTS = {
        'ON': 9,
        'START': -1,
        'CHARGE': 0,
        'TP': 8,
        'DRY END': 1,
        'FC START': 2,
        'FC END': 3,
        'SC START': 4,
        'SC END': 5,
        'DROP': 6,
        'COOL END': 7,
        'If Alarm': 10
        }
        self._airwave_present:bool = self.plan.get("_airwave_present", "no") == "yes"
        self.alarms = self.generate()

    def _parse_val(self, key:str)->float:
        """Nettoie les chaînes comme '75%' ou '201.5' pour obtenir des nombres."""
        raw_val = self.plan.get(key, "0")
        if isinstance(raw_val, str):
            # On prend la première valeur si c'est une liste "75% | 60%"
            first_part = raw_val.split('|')[0].strip()
            return float(first_part.replace('%', ''))
        return float(raw_val)

    def _time_to_seconds(self, time_str:str)-> int:
        """Convertit 'MM:SS' en secondes totales."""
        try:
            m, s = map(int, time_str.split(':'))
            return m * 60 + s
        except Exception:
            return 0

    def generate(self):
        alarms  = {
            "alarmflags": [], "alarmguards": [], "alarmnegguards": [],
            "alarmtimes": [], "alarmoffsets": [], "alarmconds": [],
            "alarmsources": [], "alarmtemperatures": [], "alarmactions": [],
            "alarmbeep": [], "alarmstrings": []
        }

        # 0. PARAMÈTRES DE PHASE (Extraits du plan)
        def _pct_list(key: str) -> list[int | None]:
            """'70% | 55% | 40%' → [70, 55, 40] ; '--' (tambour fixe) → None."""
            out: list[int | None] = []
            for v in self.plan.get(key, "").split('|'):
                try:
                    out.append(int(v.strip().replace('%', '')))
                except ValueError:
                    out.append(None)
            return (out + [None, None, None])[:3]

        heaters = _pct_list("Heater (%) (Dry|Mai|Dev)")
        airflows = _pct_list("Airflow (%) (Dry|Mai|Dev)")
        drums = _pct_list("Drum Speed (%) (Dry|Mai|Dev)")
        extractions = (_pct_list("Extraction (%) (Dry|Mai|Dev)")
                       if self._airwave_present else [0, 0, 0])


        # 1. ON/START EVENT
        #             alarms, 1, 0, 0, EVENT                    , Time (s), Source  , =, 0.0, Action                   , Beep, Comment
        # Time rows wait 1 s: Artisan skips the time check of a 0 s offset, so the row never fires.
        # The preheat is not started here: it stays the operator's gesture.
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("ON")   , 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("PopUp"), 0,    "Starting PLAN"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("ON")   , 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"), 0,    "0"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"), 0,    "20"   )

        # 2. ÉVÉNEMENTS DE SÉCURITÉ & POPUPS
        # Alerte à CHARGE
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{heaters[0]}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[0]}"   )
        if drums[0] is not None:   # tambour fixe → pas de ligne Slider Drum
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 2.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Drum"),   0,    f"{drums[0]}"   )
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{extractions[0]}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("CHARGE"), 4., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE FAN")

        # At TP
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("TP"),     1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{self.plan["Heater at TP"]}"   )

        # Alerte fin de Séchage (DRY END)
        # Valeur d'ENTRÉE, pas la colonne Maillard : celle-ci est la MOYENNE
        # d'une descente, et l'escalier brûleur a déjà commencé à la jouer avant
        # le DE (le feu de séchage est tenu jusqu'à ~30 s du jalon, puis lâché
        # par paliers). Poser la moyenne ici faisait chuter le brûleur d'un cran
        # de trop au DE, puis l'escalier le faisait remonter — un geste que
        # personne ne peut exécuter. On pose ce que l'escalier TIENT au DE.
        _de_bt = self._parse_val("End of Dry Temp")
        _de_held = [int(s["heater"]) for s in (self.plan.get("Heater Ramp") or [])
                    if float(s["bt"]) <= _de_bt]
        _de_burner = ((_de_held[-1] if _de_held else heaters[0])
                      if self.plan.get("Heater Ramp") else heaters[1])
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{_de_burner}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{airflows[1]}"   )
        # Doctrine tambour : aucune ligne tambour in-roast — posé une fois à la
        # CHARGE (setup), ne bouge qu'au DROP (refroidissement).
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{extractions[1]}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 5., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE STD")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 4.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "CAL"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DRY END"), 45.     , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "START"   )

        # 2b. RAMPE HEATER ANTICIPÉE (Maillard → Dev)
        # Steps déclenchés sur seuil BT (source 1, cond 1 = "rises above"),
        # armés après DRY END. Le dernier step applique le heater de dev
        # AVANT le FC (anticipation ∝ inertie machine, calculée dans le plan).
        pre_fc_idx = -1
        heater_ramp = self.plan.get("Heater Ramp") or []
        for step in heater_ramp:
            pre_fc_idx = self._add_row(
                alarms, 1, -1, -1, self.EVENTS.get("DRY END"), 0., 1, 1,
                float(step["bt"]), self.ACTION_LIST.get("Slider Burner"), 0,
                f"{int(step['heater'])}")

        # 2c. RAMPE AIRFLOW DE MAILLARD (mi-Maillard → pre-FC)
        # Même mécanique que la rampe brûleur : seuil BT, armé après DRY END.
        # Elle n'était pas exportée — l'air restait sur sa valeur de Maillard
        # jusqu'au FC alors que le plan demande de l'ouvrir progressivement dès
        # l'arrivée du brunissement, et le PDF, lui, dessinait bien la montée.
        air_ramp = self.plan.get("Air Ramp") or []
        for step in air_ramp:
            self._add_row(
                alarms, 1, -1, -1, self.EVENTS.get("DRY END"), 0., 1, 1,
                float(step["bt"]), self.ACTION_LIST.get("Slider Air"), 0,
                f"{int(step['airflow'])}")

        # Alerte First Crack (FC START)
        # ── Valeurs d'ENTRÉE de phase, pas valeurs de fin ────────────────────
        # Quand la Dev Ramp est exportée (plus bas), le FC n'est plus l'endroit
        # où l'on pose le réglage de développement : c'est la rampe qui l'amène,
        # palier par palier. Poser ici la colonne DEV — qui vaut désormais la
        # DERNIÈRE valeur de la Dev Ramp — sauterait d'un coup à l'arrivée puis
        # ferait redescendre les paliers, exactement le saut brutal que la rampe
        # existe pour éviter. On pose donc ce que la trajectoire TIENT au FC :
        # le dernier palier de la rampe d'air pour l'airflow, la valeur de
        # Maillard pour l'AirWave, le dernier palier de la rampe brûleur pour le
        # filet de sécurité. Même lecture que la table d'entrée de phase du PDF
        # (_entry_settings). Sans Dev Ramp, rien ne suivrait : on garde alors la
        # colonne DEV, seule valeur qui sera jamais posée.
        dev_ramp = self.plan.get("Dev Ramp") or []
        _fc_burner = (int(heater_ramp[-1]["heater"]) if (dev_ramp and heater_ramp)
                      else heaters[2])
        _fc_air = (int(air_ramp[-1]["airflow"]) if (dev_ramp and air_ramp)
                   else (airflows[1] if dev_ramp else airflows[2]))
        _fc_ext = extractions[1] if dev_ramp else extractions[2]
        # Le step burner à FC n'est qu'un filet de sécurité : negguard sur le
        # dernier step de la rampe — il ne tire que si le seuil BT anticipé
        # n'a jamais été atteint (FC précoce, sonde en retard). Offset +1 s :
        # une ligne temporelle à offset 0 ne tire jamais (bloc offset sauté).
        self._add_row(alarms, 1, -1, pre_fc_idx, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"), 0,    f"{_fc_burner}"   )
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),    0,    f"{_fc_air}"   )
        # Pas de ligne tambour à FC START (doctrine setup).
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"),          0, f"{_fc_ext}")
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 5., -3, 2, 0.0, self.ACTION_LIST.get("Difluid Airwave command"), 0, "MODE EXT")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 4.      , -3       , 2, 0.0, self.ACTION_LIST.get("TilauScope Ambient command"),   0,    "STOP"   )

        # 2d. RAMPE DE DÉVELOPPEMENT (FC → drop)
        # Seuils BT armés après FC START. Un palier peut porter plusieurs
        # leviers : le feu descend pendant que l'air s'ouvre pour soutenir la
        # réaction (doctrine Tilau) — les deux gestes tombent au même seuil et
        # font donc deux lignes. Le damper ne sort que si l'AirWave est là, comme
        # partout ailleurs dans cette fabrique.
        _dev_actions = (("heater", "Slider Burner"), ("airflow", "Slider Air"),
                        ("extraction", "Slider Damper"))
        for step in dev_ramp:
            for _key, _action in _dev_actions:
                if _key not in step:
                    continue
                if _key == "extraction" and not self._airwave_present:
                    continue
                self._add_row(
                    alarms, 1, -1, -1, self.EVENTS.get("FC START"), 0., 1, 1,
                    float(step["bt"]), self.ACTION_LIST.get(_action), 0,
                    f"{int(step[_key])}")

        # 3. ALERTE DE DROP ESTIMÉE (ANTICIPATION)
        # Seuil BT ≈ 20 s avant la température de drop planifiée (au RoR de
        # drop du plan), armé après FC START. Remplace l'ancien popup statique
        # tiré à FC, qui n'anticipait rien.
        t_dev_sec = self._time_to_seconds(self.plan["Development Phase"])
        if t_dev_sec > 15:
            drop_temp = self._parse_val("Drop Temp")
            drop_ror  = self._parse_val("Target ROR at Drop")
            bt_margin = max(0.5, drop_ror * 20.0 / 60.0)   # °/20 s au RoR de drop
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("FC START"), 0.      , 1        , 1, round(drop_temp - bt_margin, 1), self.ACTION_LIST.get("PopUp"), 1,    "PREPARE TO DROP (~20 s)"   )

        # 4. DROP
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Burner"),       0, "0")
        self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 1.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Air"),      0, "50" )
        if drums[0] is not None:   # même gating tambour fixe qu'aux autres phases
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 2.      , -3       , 2, 0.0, self.ACTION_LIST.get("Slider Drum"),     0, "80" )
        if self._airwave_present:
            self._add_row(alarms, 1, -1,-1, self.EVENTS.get("DROP"), 3., -3, 2, 0.0, self.ACTION_LIST.get("Slider Damper"), 0, "80")

# should add cooling fan if any

        return alarms

    def _add_row(self, storage, status=1, ifalarm=-1, butnotalarm=-1, from_event=0, at_seconds=0, source=1, condition=1, condition_value=0.0, action=1, beep=0, msg="")->int:
        storage["alarmflags"].append(status)
        storage["alarmguards"].append(ifalarm)
        storage["alarmnegguards"].append(butnotalarm)
        storage["alarmtimes"].append(from_event)
        storage["alarmoffsets"].append(at_seconds)
        storage["alarmsources"].append(source) # -3=time, 1=BT, …
        storage["alarmconds"].append(condition) # 0 = falls below; 1 = rises above; 2 = equal
        storage["alarmtemperatures"].append(condition_value)
        storage["alarmactions"].append(action) # "Popup", "SV", etc.
        storage["alarmbeep"].append(beep)
        storage["alarmstrings"].append(msg)
        return len(storage["alarmflags"]) - 1   # row index, usable as (neg)guard

    def export(self, filename:str)->None:
        with open(filename, 'w') as f:
            json.dump(self.alarms, f, separators=(',', ':'))

def plan_comparison_rows(plan_a: dict, plan_b: dict, unit: str) -> "list[tuple[str, str, str, str]]":
    """(label, A, B, B − A) for the milestones two plans of one coffee are compared on.

    The delta is empty when the two values agree, so a reader sees at once what moved.
    Shared by the PLAN tab and the comparison page of the PDF, which must not disagree.
    """
    def _signed(value: float, fmt: str) -> str:
        return ("+" if value > 0 else "−") + fmt.format(abs(value))

    def _time_delta(key: str) -> str:
        ta, tb = _plan_secs(plan_a.get(key)), _plan_secs(plan_b.get(key))
        if ta is None or tb is None or ta == tb:
            return ""
        d = tb - ta
        return ("+" if d > 0 else "−") + f"{abs(d) // 60}:{abs(d) % 60:02d}"

    def _num_delta(key: str, fmt: str) -> str:
        va, vb = _plan_num(plan_a.get(key)), _plan_num(plan_b.get(key))
        return _signed(vb - va, fmt) if va is not None and vb is not None and abs(vb - va) >= 0.05 else ""

    def _joined(*parts: str) -> str:
        return " · ".join(p for p in parts if p)

    def _temp_time(plan: dict, temp_key: str, time_key: str) -> str:
        return f"{plan.get(temp_key, 'N/A')} · {plan.get(time_key, 'N/A')}"

    def _dev(plan: dict) -> str:
        return f"{plan.get('Development Phase', 'N/A')} · {plan.get('Development Phase %', 'N/A')} %"

    def _weight(plan: dict) -> str:
        w = _plan_num(plan.get("Weight"))
        return f"{w:.0f}" if w is not None else "N/A"

    time_lbl = QApplication.translate("Label", "time")
    ca, cb = plan_cooled_weight(plan_a), plan_cooled_weight(plan_b)
    return [
        (QApplication.translate("tilauscope_roast_plan", "Weight to roast") + " (g)",
         _weight(plan_a), _weight(plan_b), _num_delta("Weight", "{:.0f}")),
        (QApplication.translate("tilauscope_roast_plan", "Charge Temp") + f" ({unit})",
         str(plan_a.get("Charge Temp")), str(plan_b.get("Charge Temp")), _num_delta("Charge Temp", "{:.0f}")),
        (QApplication.translate("tilauscope_roast_plan", "End of Dry") + f" ({unit} · {time_lbl})",
         _temp_time(plan_a, "End of Dry Temp", "Dry Phase"), _temp_time(plan_b, "End of Dry Temp", "Dry Phase"),
         _joined(_num_delta("End of Dry Temp", "{:.0f}"), _time_delta("Dry Phase"))),
        (QApplication.translate("tilauscope_roast_plan", "First Crack") + f" ({unit} · {time_lbl})",
         _temp_time(plan_a, "First Crack Temp", "FC Time"), _temp_time(plan_b, "First Crack Temp", "FC Time"),
         _joined(_num_delta("First Crack Temp", "{:.0f}"), _time_delta("FC Time"))),
        (QApplication.translate("Tooltip", "Drop") + f" ({unit} · {time_lbl})",
         _temp_time(plan_a, "Drop Temp", "Total Time"), _temp_time(plan_b, "Drop Temp", "Total Time"),
         _joined(_num_delta("Drop Temp", "{:.0f}"), _time_delta("Total Time"))),
        (QApplication.translate("Label", "Development") + f" ({time_lbl} · DTR)",
         _dev(plan_a), _dev(plan_b), _time_delta("Development Phase")),
        (QApplication.translate("tilauscope_roast_plan", "Target weight loss (%)"),
         str(plan_a.get("Target Weight Loss")), str(plan_b.get("Target Weight Loss")),
         _num_delta("Target Weight Loss", "{:.1f}")),
        (QApplication.translate("tilauscope_roast_plan", "Weight after cooling") + " (g)",
         f"≈ {ca:.0f}" if ca is not None else "N/A", f"≈ {cb:.0f}" if cb is not None else "N/A",
         _signed(cb - ca, "{:.0f}") if ca is not None and cb is not None and round(cb) != round(ca) else ""),
    ]


class BuildPRoastPlanPDF(FPDF):
    """Custom FPDF class for the roast plan report."""

    #: Unicode family registered in place of FPDF's latin-1 core fonts. The core
    #: fonts RAISE on any character outside latin-1, which took down the whole
    #: plan for 18 of the 35 shipped languages — a single word like CHARGE
    #: translated to "ÚČTOVAT" (cs) or "投豆" (zh) was enough. A registered
    #: TrueType font renders an unknown glyph blank instead of raising, so the
    #: worst case becomes a gap in the page rather than no page at all.
    #: DejaVu Sans is proportional like the Helvetica it replaces, carries the
    #: three styles the report uses, and is freely redistributable
    #: (licenses/DejaVu-Fonts.txt).
    _FONT: Final[str] = "tilauplan"
    #: fpdf style code → (bold, italic), resolved through tilauscope.text_shaping
    #: so the report, the label sheets and the Niimbot bitmaps all use one face.
    _FONT_STYLES: Final[dict] = {'': (False, False), 'B': (True, False),
                                 'I': (False, True)}
    #: Class-level default so the set_font override is safe even if FPDF's own
    #: __init__ reaches it before ours has run.
    _family: str = "helvetica"

    def __init__(self, orientation="P", unit="mm", format="A4", temp_unit="C",
                 roaster_ctx: "RoasterContext | None" = None):
        super().__init__(orientation, unit, format)
        self.mode = temp_unit
        self._target = ""
        self._roaster = ""
        self._destination = ""
        self._roaster_ctx: "RoasterContext | None" = roaster_ctx
        self._family: str = self._register_unicode_font()

    def _register_unicode_font(self) -> str:
        """Register the Unicode family; fall back to the core font if absent.

        A source checkout without the bundled fonts must still produce a plan,
        so a missing file degrades to 'helvetica' rather than raising — the same
        report as before, with the same latin-1 limit.
        """
        try:
            for style, (bold, italic) in self._FONT_STYLES.items():
                path = text_shaping.sans_path(bold=bold, italic=italic)
                if path is None:
                    _logd.warning(
                        "RoastPlanPDF: body face missing, falling back to a latin-1 core font")
                    return "helvetica"
                self.add_font(self._FONT, style, str(path))
            cjk = text_shaping.cjk_path()
            if cjk is not None:
                self.add_font("tilauplancjk", "", str(cjk))
                self.set_fallback_fonts(["tilauplancjk"])
        except Exception as e:      # never let typography stop a roast plan
            _logd.warning("RoastPlanPDF: Unicode font unavailable (%s), using core font", e)
            return "helvetica"
        return self._FONT

    # ── Bidirectional scripts ────────────────────────────────────────────────
    # The pass itself lives in tilauscope.text_shaping: the Niimbot labels need
    # exactly the same treatment (Pillow shapes no better than fpdf), and two
    # copies would drift.
    _RTL_RANGES: Final[tuple] = text_shaping.RTL_RANGES
    _ARABIC_RANGES: Final[tuple] = text_shaping.ARABIC_RANGES

    @classmethod
    def _bidi(cls, text: Any) -> Any:
        """Join and reorder Arabic/Persian/Hebrew — see text_shaping.shape_bidi."""
        return text_shaping.shape_bidi(text)

    @staticmethod
    def _in_ranges(ch: str, ranges: tuple) -> bool:
        return text_shaping.in_ranges(ch, ranges)

    # Routed centrally, like set_font: one missed call site would leave a single
    # label unjoined, which is exactly the defect nobody notices in review.
    def _bidi_call(self, args: tuple, kwargs: dict) -> "tuple[tuple, dict]":
        """Apply the bidi pass whichever way the caller passed the string.

        cell/multi_cell/text all take it third; it can also arrive as ``text=``
        or as the deprecated ``txt=`` alias fpdf still accepts and rewrites. A
        signature that assumed one form broke the graph labels, which use
        ``txt=``, so the argument is located rather than assumed.
        """
        for key in ("text", "txt"):
            if key in kwargs:
                kwargs[key] = self._bidi(kwargs[key])
                return args, kwargs
        if len(args) > 2:
            mutable = list(args)
            mutable[2] = self._bidi(mutable[2])
            return tuple(mutable), kwargs
        return args, kwargs

    def cell(self, *args, **kwargs):            # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().cell(*args, **kwargs)

    def multi_cell(self, *args, **kwargs):      # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().multi_cell(*args, **kwargs)

    def text(self, *args, **kwargs):            # type: ignore[override]
        args, kwargs = self._bidi_call(args, kwargs)
        return super().text(*args, **kwargs)

    def output(self, *args, **kwargs):   # type: ignore[override]
        """Write the document, then release the font file handles.

        fpdf2 keeps every registered TrueType open — fontTools reads it lazily
        for subsetting — and never closes it. A session generating several plans
        would accumulate descriptors for nothing. Closing after `output` is safe
        because subsetting is done by then; the instance is single-use
        afterwards, which is how the report is built.
        """
        try:
            return super().output(*args, **kwargs)
        finally:
            for font in getattr(self, 'fonts', {}).values():
                tt = getattr(font, 'ttfont', None)
                if tt is not None:
                    try:
                        tt.close()
                    except Exception:   # noqa: S110 - releasing a handle must never fail a report
                        pass

    def set_font(self, family=None, style="", size=0):   # type: ignore[override]
        """Route every call to the registered Unicode family.

        Overridden rather than edited at ~38 call sites: a single missed site
        would reintroduce the crash for one string only, which is exactly the
        kind of defect that ships unnoticed.
        """
        super().set_font(self._family if family else family, style, size)

    def _fmt_ctrl(self, raw: str, label_fn) -> str:
        """Enrich '75%' → '75% (1800 W)' when physical range is available."""
        try:
            return label_fn(float(raw.strip().replace('%', '')))
        except (ValueError, AttributeError):
            return raw

    def header(self)->None:
        self.set_font('helvetica', 'B', 15)
        self.cell(0, 10, QApplication.translate("tilauscope_roast_plan",'Automated Roast Profile Plan'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(2)
        self.set_font('helvetica', 'B', 12)
        _sub = f"({self._target})" if not self._destination else f"({self._target} - {self._destination})"
        self.cell(0, 10, _sub, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(3)

    def footer(self)->None:
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def draw_enhanced_roast_graph(self, master_data, x_pos, y_pos, width, height, bt_plan_curve=None):
        """
        Dual-axis roast graph:
          Left  Y-axis : ROR in °C/min  → scale_ror()   range [ROR_MIN .. ROR_MAX]
          Right Y-axis : BT  in °C      → scale_bt()    range [BT_MIN  .. BT_MAX ]
          Both axes share the same pixel rectangle (x_pos,y_pos,width,height) but
          each curve is mapped through its OWN scale function — they never mix.

        Layer order (bottom → top):
          A  Phase background bands
          B  ROR variance envelope (fill) + historical ROR mean (blue solid)
          C  Historical BT mean (dark red, dashed)
          D  Planned BT curve (orange solid) + planned ROR (orange dashed)
          E  Waypoint circles & labels on planned BT
          F  Grid lines + axis tick labels  (drawn last so grid is on top of fills)
          G  Graph border
          H  Legend below graph
        """
        # ── 0. TIME AXIS ────────────────────────────────────────────────────────
        T_MAX = master_data["time_min"][-1]
        if bt_plan_curve:
            T_MAX = max(T_MAX, bt_plan_curve["time_min"][-1])

        def scale_x(t: float) -> float:
            return x_pos + (t / T_MAX) * width

        ROR_MIN = 0.0
        ROR_MAX = 25.0 if self.mode == "C" else 25.0 * 1.8   # 45 °F/min ≈ 25 °C/min

        def scale_ror(r: float) -> float:
            """Maps a RoR value in native °/min to a PDF Y coordinate."""
            r_clamped = max(ROR_MIN, min(ROR_MAX, r))
            return y_pos + height - (r_clamped / ROR_MAX) * height

        # ── 2. BT AXIS   (right, BT_MIN … BT_MAX °C) ───────────────────────────
        # Compute dynamic BT range from ALL BT data (historical + planned).
        all_bt_values: list[float] = [
            v for v in master_data.get("bt_mean", [])
            if v is not None and not (isinstance(v, float) and np.isnan(v)) and v > 0
        ]
        if bt_plan_curve:
            all_bt_values += [
                v for v in bt_plan_curve["bt_plan"]
                if v is not None and v > 0
            ]

        if all_bt_values:
            BT_MIN = int(min(all_bt_values) // 10) * 10       # floor to decade
            BT_MAX = int((max(all_bt_values) // 10) + 1) * 10 # ceil  to decade
        else:
            BT_MIN = 60 if self.mode == "C" else (60 * 9/5) + 32
            BT_MAX = 240 if self.mode == "C" else (240 * 9/5) + 32

        # Safety: prevent degenerate scale
        if BT_MAX <= BT_MIN:
            BT_MIN = 60 if self.mode == "C" else (60 * 9/5) + 32
            BT_MAX = 240 if self.mode == "C" else (240 * 9/5) + 32

        def scale_bt(temp: float) -> float:
            """Maps a BT temperature (°C) to a PDF Y coordinate using the BT axis."""
            t_clamped = max(BT_MIN, min(BT_MAX, temp))
            return y_pos + height - ((t_clamped - BT_MIN) / (BT_MAX - BT_MIN)) * height

        # ── A. PHASE BACKGROUND BANDS ───────────────────────────────────────────
        phases = master_data.get("phase_times", {})
        phase_colors = {
            "DRY":         (255, 252, 230),
            "MAILLARD":    (255, 240, 210),
            "DEVELOPMENT": (245, 230, 220),
        }
        curr_t = 0
        plan_phases = {wp["label"]: wp["time_min"] * 60 for wp in bt_plan_curve.get("waypoints", [])} if bt_plan_curve else {}
        for phase_name, t_end_sec in [
            ("DRY",         plan_phases.get(QApplication.translate("Button", "DRY END"), phases.get("dry_end_sec", 300))),
            ("MAILLARD",    plan_phases.get(QApplication.translate("Button", "FC START"),      phases.get("fc_start_sec", 600))),
            ("DEVELOPMENT", int(T_MAX * 60)),
        ]:
            t_start_min = curr_t / 60.0
            t_end_min   = t_end_sec / 60.0
            band_x      = scale_x(t_start_min)
            band_w      = scale_x(t_end_min) - band_x
            self.set_fill_color(*phase_colors[phase_name])
            self.rect(band_x, y_pos, band_w, height, style="F")
            curr_t = t_end_sec

        # ── B. ROR VARIANCE ENVELOPE + HISTORICAL ROR MEAN ─────────────────────
        ror_times = master_data["time_min"]
        ror_min = master_data["ror_min"]
        ror_max = master_data["ror_max"]
        ror_mean  = master_data["ror_mean"]

        # Variance fill (light blue)
        # Check if we have data and if there is actually a difference to draw
       # Create the envelope path
        points = []
        # Forward for the top edge
        for i, val in enumerate(ror_max):
            points.append((scale_x(ror_times[i]), scale_ror(val)))
        for i in reversed(range(len(ror_min))):
            points.append((scale_x(ror_times[i]), scale_ror(ror_min[i])))
        self.set_fill_color(173, 216, 230)   # light blue — RGB for "light blue"
        self.set_draw_color(173, 216, 230)   # same, so the outline doesn't show a darker border
        self.polygon(points, style="F")

        # Historical ROR mean (solid blue, 0.6 pt)
        self.set_draw_color(0, 50, 150)
        self.set_line_width(0.6)
        self.set_dash_pattern()           # SOLID — reset any previous dash
        for i in range(len(ror_times) - 1):
            rc, rn = ror_mean[i], ror_mean[i+1]
            if rc is not None and rc > 0 and rn is not None and rn > 0:
                self.line(
                    scale_x(ror_times[i]),   scale_ror(rc),
                    scale_x(ror_times[i+1]), scale_ror(rn),
                )

        # ── C.1  BT VARIANCE ENVELOPE (light blue, BT axis) ──────────────────
        bt_times = master_data["time_min"]
        bt_mean  = master_data["bt_mean"]

        bt_min_data = master_data.get("bt_min")
        bt_max_data = master_data.get("bt_max")
        if bt_min_data and bt_max_data:
            self.set_fill_color(173, 216, 230)   # light blue
            self.set_draw_color(173, 216, 230)
            bt_points = []
            for i, val in enumerate(bt_max_data):
                if val is not None and not np.isnan(val):
                    bt_points.append((scale_x(bt_times[i]), scale_bt(val)))
            for i in reversed(range(len(bt_min_data))):
                val = bt_min_data[i]
                if val is not None and not np.isnan(val):
                    bt_points.append((scale_x(bt_times[i]), scale_bt(val)))
            if len(bt_points) > 2:
                self.polygon(bt_points, style="F")

        # ── C. HISTORICAL BT MEAN  (dark red solid, mapped on BT axis) ─────────

        self.set_draw_color(160, 0, 0)    # dark red — distinct from orange plan
        self.set_line_width(0.5)
        self.set_dash_pattern()
        for i in range(len(bt_times) - 1):
            bc, bn = bt_mean[i], bt_mean[i+1]
            if (bc is not None and not (isinstance(bc, float) and np.isnan(bc)) and bc > 0 and
                bn is not None and not (isinstance(bn, float) and np.isnan(bn)) and bn > 0):
                self.line(
                    scale_x(bt_times[i]),   scale_bt(bc),
                    scale_x(bt_times[i+1]), scale_bt(bn),
                )
        self.set_dash_pattern()           # RESET to solid

        # ── D. PLANNED BT CURVE + PLANNED ROR  (both orange, mapped on CORRECT axes)
        if bt_plan_curve:
            plan_times = bt_plan_curve["time_min"]
            plan_bt    = bt_plan_curve["bt_plan"]
            plan_ror   = bt_plan_curve["ror_plan"]
            STEP = 1   # subsample every 5 points (= 5 s) for PDF size

            # D.1  Planned BT — green 0.4 pt — uses scale_bt (RIGHT axis)
            self.set_draw_color(0, 160, 0)    # green
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=1.5, gap=1.0)
            bt_plan_points = []
            for i in range(0, len(plan_times) - STEP, STEP):
                bc = plan_bt[i]
                if bc is not None:
                    # Append as a tuple (x, y)
                    bt_plan_points.append((
                        scale_x(plan_times[i]),
                        scale_bt(bc)
                    ))
            if len(bt_plan_points) > 1:
                self.polyline(bt_plan_points)

            # D.2  Planned ROR — dashed orange 0.4 pt — uses scale_ror (LEFT axis)
            self.set_draw_color(200, 120, 20)   # slightly lighter orange for ROR
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=2.5, gap=1.5)
            ror_plan_points = []
            for i in range(0, len(ror_times), STEP):
                val = plan_ror[i] if i< len (plan_times) else None
                if val is not None:
                    # Append as a tuple (x, y)
                    ror_plan_points.append((
                        scale_x(plan_times[i]),
                        scale_ror(val)
                    ))
            if len(ror_plan_points) > 1:
                self.polyline(ror_plan_points)

            self.set_dash_pattern()       # RESET

        # ── E. WAYPOINT ANNOTATIONS (Option 2: Leader Lines) ────────────────
        # Define a fixed 'lane' for labels 7mm above the graph grid top
        lane_high = y_pos - 10  # Higher lane
        lane_low = y_pos - 4   # Lower lane

        self.set_font("Helvetica", "B", 6)
        self.set_line_width(0.35)

        ANNOTATED = {QApplication.translate("Button","CHARGE"), QApplication.translate("Label","TP"), QApplication.translate("Button","DRY END"), QApplication.translate("Button","FC START"), QApplication.translate("Button","DROP")}

        # Sort waypoints by time to ensure the alternating pattern is consistent
        active_waypoints = [wp for wp in bt_plan_curve["waypoints"] if wp["label"] in ANNOTATED]
        active_waypoints.sort(key=lambda x: x["time_min"])

        for i, wp in enumerate(active_waypoints):
            x_wp = scale_x(wp["time_min"])
            y_wp = scale_bt(wp["bt"])

            # Alternating height: 0=High, 1=Low
            # This prevents "CHARGE" and "TP" from crashing into each other
            current_lane_y = lane_high if i % 2 == 0 else lane_low

            # 1. Waypoint Marker
            self.set_draw_color(70, 160, 0)
            self.set_fill_color(255, 255, 255)
            self.set_line_width(0.5)
            self.ellipse(x_wp - 0.8, y_wp - 0.8, 1.6, 1.6, style="FD")

            # 2. Leader Line (adjusts length based on the chosen lane)
            self.set_draw_color(20, 20, 20)
            self.set_line_width(0.1)
            self.set_dash_pattern(dash=0.4, gap=0.4)
            self.line(x_wp, y_wp, x_wp, current_lane_y)
            self.set_dash_pattern() # Reset

            # 3. Text Label
            label_txt = f"{wp['label']}\n{wp['bt']:.1f}°{self.mode}"
            # Since it's multi-line, we calculate width based on the longest line
            title_w = self.get_string_width(wp['label'])
            value_w = self.get_string_width(f"{wp['bt']:.1f}°{self.mode}")
            text_w = max(title_w, value_w) + 2  # Added 2mm padding for safety

            # Position text relative to the leader line tip
            # If high lane, text goes above. If low lane, text sits right there.
            lx = x_wp - (text_w / 2)
            # Boundary check
            lx = max(x_pos, min(lx, x_pos + width - text_w))

            self.set_text_color(30, 30, 30)

            line_height = 3.0  # Height of a single line of text
            # multi_cell allows \n and handles the line wrapping
            # align='C' ensures both lines are centered relative to each other
            self.set_xy(lx, current_lane_y - (line_height * 2) - 1)
            self.multi_cell(
                w=text_w,
                h=line_height,
                text=label_txt,
                border=0,
                align='C'
            )
        self.set_text_color(50, 50, 50)

        # ── F. GRID LINES + AXIS TICK LABELS ────────────────────────────────────
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.1)
        self.set_text_color(50, 50, 50)
        self.set_font("Helvetica", "", 7)

        # Vertical grid: one line per minute
        for m in range(0, int(T_MAX) + 1):
            xm = scale_x(float(m))
            self.line(xm, y_pos, xm, y_pos + height)
            self.text(xm - 2, y_pos + height + 5, f"{m}'")

        # Horizontal grid: ROR ticks on left axis (every 5 °C/min)
        for r in range(int(ROR_MIN), int(ROR_MAX) + 1, 5):
            yr = scale_ror(float(r))
            self.line(x_pos, yr, x_pos + width, yr)
            self.text(x_pos - 10, yr + 2, f"{r}")

        # BT tick labels on right axis (every 20 °C) — NO extra grid lines,
        # they would duplicate the ROR grid and create the confusing double-line look.
        for bt_tick in range(BT_MIN, BT_MAX + 1, 20):
            yt = scale_bt(float(bt_tick))
            # Only draw tick label if it falls inside the graph rectangle
            if y_pos <= yt <= y_pos + height:
                self.text(x_pos + width + 3, yt + 2, f"{bt_tick}°{self.mode}")

        # ── G. GRAPH BORDER ─────────────────────────────────────────────────────
        self.set_draw_color(100, 100, 100)
        self.set_line_width(0.3)
        self.rect(x_pos, y_pos, width, height, style="D")

        # Axis title labels
        self.set_font("Helvetica", "B", 7)
        self.text(
            x_pos - 15, y_pos - 5,
            QApplication.translate("Label", "RoR") +
            f" (°{self.mode}" +
            QApplication.translate("Label", "/min") + ")"
        )
        self.text(
            x_pos + width + 3, y_pos - 5,
            QApplication.translate("Label", "BT") + f": (°{self.mode})")
        self.text(
            x_pos + width / 2 - 5, y_pos + height + 12,
            QApplication.translate("Table", "Time") + " (min)"
        )

        # ── H. LEGEND ────────────────────────────────────────────────────────────
        leg_y = y_pos + height + 20
        self.set_font("Helvetica", "", 8)

        # Row 1 ─ left half: historical ROR (blue solid) + variance box
        #         right half: historical BT (dark red dashed)
        self.set_draw_color(0, 50, 150)
        self.set_line_width(0.8)
        self.set_dash_pattern()
        self.line(x_pos, leg_y, x_pos + 10, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 13, leg_y + 2.5,
                  QApplication.translate("Label", "RoR") +
                  QApplication.translate("tilauscope_roast_plan", " Average (hist.)"))

        self.set_fill_color(200, 220, 255)
        self.rect(x_pos + 58, leg_y - 2, 8, 5, style="F")
        self.set_draw_color(150, 170, 220)
        self.set_line_width(0.3)
        self.rect(x_pos + 58, leg_y - 2, 8, 5, style="D")
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 68, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "RoR variance"))

        self.set_draw_color(0, 160, 0)
        self.set_line_width(0.4)
        self.set_dash_pattern(dash=1.5, gap=1.0)
        self.line(x_pos + 110, leg_y, x_pos + 120, leg_y)
        self.set_dash_pattern()
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 123, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "BT Average (hist.)"))

        # Row 2 (only when plan curve exists) ─ planned BT solid + planned ROR dashed
        if bt_plan_curve:
            leg_y += 7
            self.set_draw_color(210, 100, 0)
            self.set_line_width(0.8)
            self.set_dash_pattern()
            self.line(x_pos, leg_y, x_pos + 10, leg_y)
            self.set_text_color(0, 0, 0)
            self.text(x_pos + 13, leg_y + 2.5,
                      QApplication.translate("tilauscope_roast_plan", "Planned BT (PCHIP)"))

            self.set_draw_color(200, 120, 20)
            self.set_line_width(0.4)
            self.set_dash_pattern(dash=2.5, gap=1.5)
            self.line(x_pos + 65, leg_y, x_pos + 75, leg_y)
            self.set_dash_pattern()
            self.set_text_color(0, 0, 0)
            self.text(x_pos + 78, leg_y + 2.5,
                      QApplication.translate("tilauscope_roast_plan", "Planned RoR"))

        # Row 3 ─ phase colour chips
        leg_y += 8
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(0, 0, 0)

        self.set_fill_color(255, 252, 230)
        self.rect(x_pos, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 6, leg_y + 1,
                  QApplication.translate("tilauscope_roast_plan", "Drying (DRY)"))

        self.set_fill_color(255, 240, 210)
        self.rect(x_pos + 45, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 51, leg_y + 1,
                  QApplication.translate("Label", "Maillard"))

        self.set_fill_color(245, 230, 220)
        self.rect(x_pos + 85, leg_y - 2, 4, 4, style="F")
        self.text(x_pos + 91, leg_y + 1,
                  QApplication.translate("Label", "Development"))

    # The levers at each milestone are shared with the tablet (tilaucore.roast_plan_view).
    _phase_pct = staticmethod(phase_pct)
    entry_levels = staticmethod(entry_levels)
    _control_trajectories = staticmethod(control_trajectories)

    def _entry_settings(self, plan_data: dict) -> "list[tuple[str, list[str]]]":
        """Rows for the phase-entry table: what each lever must READ when the
        milestone is crossed — at CHARGE, at DRY END, at FIRST CRACK.

        Deliberately not the phase average. A figure like 59 % for Maillard is
        the mean of a descent, and the operator never dials a mean; reading it
        as an instruction posts the middle of the ramp at the start of the
        phase, half a phase too low too early. The entry values are read off the
        same trajectories the section 5 chart draws, so table and chart cannot
        disagree.

        The burner can therefore show the same value at CHARGE and at DRY END.
        That is the doctrine made visible: the drying fire is held through dry
        end, and the descent starts just after it.
        """
        levels = self.entry_levels(plan_data)
        ctx = self._roaster_ctx

        def _fmt(values: list, label_fn) -> list:
            out = []
            for v in values:
                if v is None:
                    out.append("N/A")
                    continue
                raw = f"{v:.0f}%"
                out.append(self._fmt_ctrl(raw, label_fn) if ctx is not None else raw)
            return out

        def _phase(key: str, cols: "tuple[int, int, int]") -> "list[float | None]":
            parts = str(plan_data.get(key, "")).split('|')
            out: "list[float | None]" = []
            for c in cols:
                try:
                    out.append(float(parts[c].strip().rstrip('%')))
                except (ValueError, IndexError):
                    out.append(None)
            return out

        rows: "list[tuple[str, list[str]]]" = []
        if levels["heater"]:
            rows.append((QApplication.translate("tilauscope_common", "Heater") + " (%)",
                         _fmt(levels["heater"], ctx.pct_to_heater_label if ctx else None)))
        if levels["airflow"]:
            rows.append((QApplication.translate("tilauscope_roast_plan", "Airflow") + " (%)",
                         _fmt(levels["airflow"], ctx.pct_to_airflow_label if ctx else None)))
        # Drum is a SETUP value: one setting for the whole roast, so its three
        # columns are the same figure by construction, not by accident.
        if levels["drum"]:
            rows.append((QApplication.translate("Label", "Drum Speed") + " (%)",
                         _fmt(levels["drum"], ctx.pct_to_drum_label if ctx else None)))
        # AirWave: posted at CHARGE and at DRY END, then carried by the Dev Ramp
        # — so the value at FC entry is still the Maillard one, as for airflow.
        if str(plan_data.get("Extraction (%) (Dry|Mai|Dev)", "")).strip():
            _ext = _phase("Extraction (%) (Dry|Mai|Dev)", (0, 1, 1))
            rows.append((QApplication.translate("tilauscope_common", "AirWave")
                         + " (% " + QApplication.translate("ComboBox", "Fan") + ")",
                         _fmt(_ext, None)))
        return rows

    def _control_gestures(self, plan_data: dict) -> "list[dict]":
        """Every lever change the plan asks for, in order.

        One row per gesture rather than one per lever: at the machine the
        question is always "what do I do next", and two levers moving at the
        same threshold are two distinct hands on two distinct knobs.
        """
        heater, airflow, ms = self._control_trajectories(plan_data)
        if not heater and not airflow:
            return []
        curve = plan_data.get("bt_plan_curve") or {}
        times = list(curve.get("time_min") or [])
        bts = list(curve.get("bt_plan") or [])

        def bt_at(t: float) -> "float | None":
            for i in range(len(times)):
                if times[i] >= t:
                    return bts[i]
            return bts[-1] if bts else None

        t_de = float(ms.get("dry_end") or 0.0)
        t_fc = float(ms.get("fc_start") or 0.0)
        out: "list[dict]" = []
        for points, lever in ((heater, QApplication.translate("tilauscope_common", "Heater")),
                              (airflow, QApplication.translate("tilauscope_roast_plan", "Airflow"))):
            for i in range(1, len(points)):
                out.append({"t": points[i][0], "lever": lever,
                            "frm": points[i - 1][1], "to": points[i][1],
                            "bt": bt_at(points[i][0])})
        out.sort(key=lambda g: g["t"])
        for g in out:
            g["phase"] = (QApplication.translate("Label", "Dry") if g["t"] < t_de
                          else QApplication.translate("Label", "Maillard") if g["t"] < t_fc
                          else QApplication.translate("Label", "Development"))
        return out

    @staticmethod
    def _mmss(t_min: float) -> str:
        total = int(round(float(t_min) * 60.0))
        return f"{total // 60:d}:{total % 60:02d}"

    def draw_control_ramp_graph(self, plan_data: dict, x_pos: float, y_pos: float,
                                 width: float, height: float) -> bool:
        """Heater (red) and airflow (blue) setpoints over the whole roast.

        Returns False when the plan carries no trajectory to draw, so the caller
        can skip the section rather than print an empty frame.
        """
        heater, airflow, ms = self._control_trajectories(plan_data)
        if not heater and not airflow:
            return False

        t_end = float(ms.get("t_end") or 0.0)
        if t_end <= 0.0:
            return False

        def sx(t: float) -> float:
            return x_pos + (max(0.0, min(t_end, t)) / t_end) * width

        def sy(pct: float) -> float:
            return y_pos + height - (max(0.0, min(100.0, pct)) / 100.0) * height

        # ── Phase bands (same palette as the BT/RoR graph, so the two pages
        # read as one document) ──────────────────────────────────────────────
        for name, t0, t1, rgb in (
            ("DRY", 0.0, ms.get("dry_end", 0.0), (255, 252, 230)),
            ("MAILLARD", ms.get("dry_end", 0.0), ms.get("fc_start", 0.0), (255, 240, 210)),
            ("DEVELOPMENT", ms.get("fc_start", 0.0), t_end, (245, 230, 220)),
        ):
            if t1 <= t0:
                continue
            self.set_fill_color(*rgb)
            self.rect(sx(t0), y_pos, sx(t1) - sx(t0), height, style="F")

        # ── Grid: every 20 % and every 2 min ─────────────────────────────────
        self.set_draw_color(205, 205, 205)
        self.set_line_width(0.15)
        self.set_dash_pattern()
        self.set_font("Helvetica", "", 7)
        self.set_text_color(90, 90, 90)
        for pct in range(0, 101, 20):
            y = sy(pct)
            self.line(x_pos, y, x_pos + width, y)
            self.text(x_pos - 8, y + 1.2, f"{pct}%")
        _t = 0.0
        while _t <= t_end + 1e-9:
            x = sx(_t)
            self.line(x, y_pos, x, y_pos + height)
            self.text(x - 3, y_pos + height + 4, f"{int(_t)}'")
            _t += 2.0

        # ── Milestone verticals (DRY END, FC) ────────────────────────────────
        self.set_line_width(0.4)
        self.set_dash_pattern(dash=1.2, gap=1.2)
        self.set_draw_color(120, 120, 120)
        for key, label in (("dry_end", QApplication.translate("Button", "DRY END")),
                           ("fc_start", QApplication.translate("Button", "FC START"))):
            t = float(ms.get(key) or 0.0)
            if t <= 0.0 or t >= t_end:
                continue
            self.line(sx(t), y_pos, sx(t), y_pos + height)
            self.set_font("Helvetica", "B", 6)
            self.set_text_color(110, 110, 110)
            self.text(sx(t) + 1, y_pos + 3.5, label)
        self.set_dash_pattern()

        def _staircase(points: list, rgb: tuple, label_above: bool) -> None:
            """Hold-then-step: horizontal to the next change, then vertical to
            the new value. The last value is held to the drop."""
            if not points:
                return
            self.set_draw_color(*rgb)
            self.set_line_width(0.9)
            self.set_dash_pattern()
            last_label_x = -99.0
            for i, (t, v) in enumerate(points):
                t_next = points[i + 1][0] if i + 1 < len(points) else t_end
                self.line(sx(t), sy(v), sx(t_next), sy(v))
                if i + 1 < len(points):
                    self.line(sx(t_next), sy(v), sx(t_next), sy(points[i + 1][1]))
                # Label sparsely: a value every 9 mm stays readable, and the
                # operator reads levels off the axis anyway.
                if sx(t) - last_label_x >= 9.0:
                    self.set_font("Helvetica", "B", 6)
                    self.set_text_color(*rgb)
                    self.text(sx(t) + 0.6,
                              sy(v) - 1.6 if label_above else sy(v) + 3.4,
                              f"{v:.0f}")
                    last_label_x = sx(t)
            # The value held to the DROP, in the right margin: it is the one the
            # operator finishes on, and the spacing rule above would drop it
            # whenever the last steps bunch up in development. Outside the plot
            # so the two curves cannot collide here even when they cross.
            self.set_font("Helvetica", "B", 7)
            self.set_text_color(*rgb)
            self.text(x_pos + width + 1.5, sy(points[-1][1]) + 1.0,
                      f"{points[-1][1]:.0f}%")

        _RED = (200, 40, 40)
        _BLUE = (40, 90, 200)
        _staircase(airflow, _BLUE, label_above=False)
        _staircase(heater, _RED, label_above=True)

        # ── Border ───────────────────────────────────────────────────────────
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.3)
        self.set_dash_pattern()
        self.rect(x_pos, y_pos, width, height, style="D")

        # ── Legend ───────────────────────────────────────────────────────────
        leg_y = y_pos + height + 10
        self.set_font("Helvetica", "", 8)
        self.set_draw_color(*_RED)
        self.set_line_width(0.9)
        self.line(x_pos, leg_y, x_pos + 10, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 13, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "Heater (%)"))
        self.set_draw_color(*_BLUE)
        self.line(x_pos + 55, leg_y, x_pos + 65, leg_y)
        self.set_text_color(0, 0, 0)
        self.text(x_pos + 68, leg_y + 2.5,
                  QApplication.translate("tilauscope_roast_plan", "Airflow (%)"))
        self.set_text_color(0, 0, 0)
        return True

    def _draw_step_sequence(self, plan_data: dict) -> None:
        """The heat ladder as a checklist instead of a run-on line of pairs.

        This is the moved 'Heater ramp (anticipated)' and 'Heater source' from
        section 4: the same data, one gesture per row, next to the chart it
        belongs with.
        """
        gestures = self._control_gestures(plan_data)
        if not gestures:
            return
        _HEAD = (225, 225, 225)
        _ALT = (246, 246, 246)
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, QApplication.translate("tilauscope_roast_plan", "Step sequence"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

        cols = [14, 20, 22, 28, 34, 44]
        heads = ["#",
                 QApplication.translate("Table", "Time"),
                 QApplication.translate("Label", "BT"),
                 QApplication.translate("tilauscope_roast_plan", "Lever"),
                 QApplication.translate("tilauscope_roast_plan", "Change"),
                 QApplication.translate("tilauscope_roast_plan", "Phase")]
        self.set_font('helvetica', 'B', 8.5)
        self.set_fill_color(*_HEAD)
        for w, h in zip(cols, heads):
            self.cell(w, 5.5, h, 1, align='C', fill=True)
        self.ln()

        self.set_font('helvetica', '', 8.5)
        for i, g in enumerate(gestures):
            self.ensure_space(12)
            self.set_fill_color(*(_ALT if i % 2 else (255, 255, 255)))
            bt = f"{g['bt']:.0f}°{self.mode}" if g.get('bt') is not None else "-"
            row = [str(i + 1), self._mmss(g['t']), bt, g['lever'],
                   f"{g['frm']:.0f} -> {g['to']:.0f}%", g['phase']]
            for w, v in zip(cols, row):
                self.cell(w, 5.0, v, 1, align='C', fill=True)
            self.ln()

        # Provenance, kept with the ladder it qualifies.
        _hsrc = str(plan_data.get("Heater Source", "grid"))
        _hfc = str(plan_data.get("Heater FC Source", "grid"))
        if _hfc != "grid":
            _hsrc = f"{_hsrc}  |  pre-FC: {_hfc}"
        _lead = plan_data.get("FC Anticipation (s)", "")
        self.ln(1.5)
        self.set_font('helvetica', '', 8.5)
        _line = QApplication.translate("tilauscope_roast_plan", "Heater source") + f": {_hsrc}"
        if _lead:
            _line += "   |   " + QApplication.translate(
                "tilauscope_roast_plan", "last step {0} s before FC").format(_lead)
        self.multi_cell(0, 5, _line, new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)
        self.ln(2)

    def _draw_plan_recap(self, plan_data: dict) -> None:
        """The five figures worth carrying in your head, under the sequence:
        where you charge, where you drop, and how long each phase should take."""
        _deg = f" °{self.mode}"
        rows = [
            [(QApplication.translate("Label", "CHARGE"), f"{plan_data.get('Charge Temp', 'N/A')}{_deg}"),
             (QApplication.translate("Label", "DROP"), f"{plan_data.get('Drop Temp', 'N/A')}{_deg}"),
             (QApplication.translate("Button", "FC START"), f"{plan_data.get('First Crack Temp', 'N/A')}{_deg}"),
             (QApplication.translate("tilauscope_roast_plan", "Total time"), str(plan_data.get('Total Time', 'N/A')))],
            [(QApplication.translate("Label", "Dry"), f"{plan_data.get('Dry Phase', 'N/A')} ({plan_data.get('Dry Phase %', '-')}%)"),
             (QApplication.translate("Label", "Maillard"), f"{plan_data.get('Maillard Phase', 'N/A')} ({plan_data.get('Maillard Phase %', '-')}%)"),
             (QApplication.translate("Label", "Development"), f"{plan_data.get('Development Phase', 'N/A')} ({plan_data.get('Development Phase %', '-')}%)"),
             (QApplication.translate("tilauscope_roast_plan", "Resulting DTR (%)"), f"{plan_data.get('Target DTR', 'N/A')}%")],
        ]
        self.ensure_space(30)
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, QApplication.translate("tilauscope_roast_plan", "At a glance"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)
        widths = [40, 40, 42, 40]
        for row in rows:
            self.set_font('helvetica', '', 7.5)
            self.set_text_color(110, 110, 110)
            for w, (k, _v) in zip(widths, row):
                self.cell(w, 4, "  " + k.upper(), 0, align='L')
            self.ln()
            self.set_font('helvetica', 'B', 10)
            self.set_text_color(0, 0, 0)
            for w, (_k, v) in zip(widths, row):
                self.cell(w, 6, "  " + str(v), 0, align='L')
            self.ln(7)
        self.set_text_color(0, 0, 0)

    def ensure_space(self, needed_height:int):
        if self.get_y() + needed_height > self.page_break_trigger:
            self.add_page()

    @staticmethod
    def _destination_label(key: Any) -> str:
        """Human name of the brewing destination the plan was built for."""
        return {
            "filter":   QApplication.translate("tilauscope_roast_plan", "Filter"),
            "omni":     QApplication.translate("tilauscope_roast_plan", "Omni"),
            "espresso": QApplication.translate("tilauscope_common", "Espresso"),
        }.get(str(key or "").lower(), "")

    @staticmethod
    def _humidity_text(plan_data: dict) -> str:
        """This lot's humidity, followed by the inherited harvest's when both are measured."""
        text = str(plan_data.get("Bean Humidity"))
        prev = plan_data.get("Previous Harvest") or {}
        if prev.get("humidity") and float(plan_data.get("Bean Humidity") or 0) > 0:
            text += f"   ({prev['crop']}: {prev['humidity']:.1f})"
        return text

    def create_comparison_page(self, plan_a: dict, label_a: str, plan_b: dict, label_b: str) -> None:
        """One page setting two plans of the same coffee side by side: A is the
        pinned plan, B the current one, whose full report follows. Rows that
        differ are bold, with B − A in the last column."""
        self._target = str(plan_b.get("Target Roast Level", ""))
        self._roaster = str(plan_b.get("Roaster", ""))
        self._destination = ""
        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)
        unit = f"°{self.mode}"

        self.set_font('helvetica', 'B', 13)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan", "Plan comparison")
                  + f" — {plan_b.get('Bean Name', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(3)

        # A and B, named once; every column below refers to them.
        box_w = 93
        y0 = self.get_y()
        for i, (tag, label) in enumerate((
                (QApplication.translate("tilauscope_roast_plan", "A — pinned"), label_a),
                (QApplication.translate("tilauscope_roast_plan", "B — current"), label_b))):
            x0 = self.l_margin + i * (box_w + 4)
            if i:
                self.set_fill_color(242, 242, 242)
            else:
                self.set_fill_color(255, 255, 255)
            self.rect(x0, y0, box_w, 15, style="DF")
            self.set_xy(x0 + 3, y0 + 2)
            self.set_font('helvetica', 'B', 8)
            self.cell(box_w - 6, 4, tag)
            self.set_xy(x0 + 3, y0 + 7)
            self.set_font('helvetica', 'B', 11)
            self.cell(box_w - 6, 6, label)
        self.set_xy(self.l_margin, y0 + 19)

        rows = plan_comparison_rows(plan_a, plan_b, unit)

        widths = (64, 42, 42, 42)
        _row_h = 6.5

        def _section(title: str) -> None:
            self.ln(2)
            self.set_fill_color(220, 220, 220)
            self.set_font('helvetica', 'B', 12)
            self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
            self.ln(1)

        def _head(cols: "tuple[str, ...]") -> None:
            self.set_fill_color(238, 238, 238)
            self.set_font('helvetica', 'B', 10)
            for i, col in enumerate(cols):
                last = i == len(cols) - 1
                self.cell(widths[i], 7, col, 1, align='L' if i == 0 else 'C', fill=True,
                          new_x=XPos.LMARGIN if last else XPos.RIGHT, new_y=YPos.NEXT if last else YPos.TOP)

        _section(QApplication.translate("tilauscope_roast_plan", "1. What changes between A and B"))
        _head((QApplication.translate("tilauscope_roast_plan", "Milestone"), "A", "B", "B − A"))
        for label, a, b, delta in rows:
            self.set_font('helvetica', 'B' if a != b else '', 10)
            self.cell(widths[0], _row_h, label, 1)
            self.cell(widths[1], _row_h, a, 1, align='C')
            self.cell(widths[2], _row_h, b, 1, align='C')
            self.cell(widths[3], _row_h, delta or "—", 1, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font('helvetica', 'I', 8.5)
        self.multi_cell(0, 4.5, QApplication.translate("tilauscope_roast_plan",
            "Rows in bold differ between A and B. All temperatures are in BT (Bean Temperature) "
            "and times in Minutes:Seconds."), border=0)

        _section(QApplication.translate("tilauscope_roast_plan", "2. Machine settings at phase entry"))
        _head((QApplication.translate("Label", "Control"),
               QApplication.translate("tilauscope_roast_plan", "At CHARGE"),
               QApplication.translate("Button", "DRY END"), QApplication.translate("Button", "FC START")))
        la, lb = self.entry_levels(plan_a), self.entry_levels(plan_b)
        for key, name in (("heater", QApplication.translate("tilauscope_common", "Heater")),
                          ("airflow", QApplication.translate("tilauscope_roast_plan", "Airflow")),
                          ("drum", QApplication.translate("Label", "Drum Speed"))):
            va, vb = la.get(key) or [], lb.get(key) or []
            if not va and not vb:
                continue
            cells = []
            for i in range(3):
                a = va[i] if i < len(va) else None
                b = vb[i] if i < len(vb) else None
                fa = "N/A" if a is None else f"{a:.0f}%"
                fb = "N/A" if b is None else f"{b:.0f}%"
                cells.append(fb if fa == fb else f"{fa} → {fb}")
            self.set_font('helvetica', 'B' if any("→" in c for c in cells) else '', 10)
            self.cell(widths[0], _row_h, name + " (%)", 1)
            for i, c in enumerate(cells):
                last = i == 2
                self.cell(widths[i + 1], _row_h, c, 1, align='C',
                          new_x=XPos.LMARGIN if last else XPos.RIGHT, new_y=YPos.NEXT if last else YPos.TOP)
        self.set_font('helvetica', 'I', 8.5)
        self.multi_cell(0, 4.5, QApplication.translate("tilauscope_roast_plan",
            "A setting that differs reads “A → B”."), border=0)

        _section(QApplication.translate("tilauscope_roast_plan", "3. Planned bean temperature"))
        self._draw_comparison_curves(plan_a, plan_b, self.l_margin, self.get_y() + 2,
                                     self.w - self.l_margin - self.r_margin,
                                     max(60.0, self.page_break_trigger - self.get_y() - 14))

    def _draw_comparison_curves(self, plan_a: dict, plan_b: dict, x: float, y: float,
                                width: float, height: float) -> None:
        """Both planned BT curves on one chart: A dashed grey, B solid."""
        curves = []
        for plan in (plan_a, plan_b):
            curve = plan.get("bt_plan_curve") or {}
            t, bt = list(curve.get("time_min") or []), list(curve.get("bt_plan") or [])
            curves.append(list(zip(t, bt)) if len(t) >= 2 and len(t) == len(bt) else [])
        points = [p for c in curves for p in c]
        if not points:
            return
        t_max = max(p[0] for p in points)
        lo = min(p[1] for p in points)
        hi = max(p[1] for p in points)
        lo = math.floor(lo / 25.0) * 25.0
        hi = math.ceil(hi / 25.0) * 25.0
        if t_max <= 0 or hi <= lo:
            return

        def sx(t: float) -> float:
            return x + 12 + (t / t_max) * (width - 14)

        def sy(v: float) -> float:
            return y + height - 8 - (v - lo) / (hi - lo) * (height - 10)

        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.1)
        self.set_font('helvetica', '', 7)
        for minute in range(0, int(t_max) + 1, 2):
            self.line(sx(minute), sy(lo), sx(minute), sy(hi))
            self.text(sx(minute) - 1, sy(lo) + 4, f"{minute}")
        v = lo
        while v <= hi + 1e-6:
            self.line(sx(0), sy(v), sx(t_max), sy(v))
            self.text(x, sy(v) + 1, f"{v:.0f}")
            v += 25.0

        for i, (curve, rgb) in enumerate(zip(curves, ((140, 140, 140), (30, 30, 30)))):
            if not curve:
                continue
            self.set_draw_color(*rgb)
            self.set_line_width(0.6 if i else 0.4)
            for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
                # A is drawn dashed by skipping every other segment.
                if i == 0 and int(t0 * 6) % 2:
                    continue
                self.line(sx(t0), sy(v0), sx(t1), sy(v1))

        self.set_line_width(0.2)
        self.set_draw_color(0, 0, 0)
        self.set_font('helvetica', '', 8)
        self.text(x + 12, y + height, "- - -  A        ——  B        " + QApplication.translate("tilauscope_roast_plan", "minutes"))

    def create_pdf_report(self, plan_data:dict, graph_data, crashes, flicks)->None:
        """Fills the PDF with the calculated roast plan data in a clear, structured format,
        including phase percentages."""

        self._target = plan_data["Target Roast Level"]
        self._roaster = plan_data["Roaster"]
        self._destination = self._destination_label(plan_data.get("Roast Destination"))

        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)

        # A4 vertical budget: with the header (~35 mm) the 4 sections + note
        # must stay under the 282 mm break trigger even with the two extra
        # AirWave rows — hence the 5.5 mm data rows and tight spacers below.
        _row_h = 5.5

        # just below the automatic header/title generated by the FPDF class's Header() method.
        self.ln(4)

        # 1. Bean & Ambient Information
        # Set up basic font
        self.set_font('helvetica', '', 10)

        # Set background color for section header
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'1. Bean and Environment Information'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)

        info_data = [
            (QApplication.translate("Label","Roaster"), plan_data.get("Roaster")),
            (QApplication.translate("tilauscope_roast_plan","Bean Name"), plan_data.get("Bean Name")),
            (QApplication.translate("tilauscope_roast_plan","Process Type"), plan_data.get("Process Type")),
            (QApplication.translate("Label","Density")+" (g/L)", plan_data.get("Density")),
            (QApplication.translate("tilauscope_roast_plan","Bean Humidity")+" (%)", self._humidity_text(plan_data)),
            (QApplication.translate("tilauscope_roast_plan","Ambient Temp")+f" (°{self.mode})", plan_data.get("Ambient Temp")),
            (QApplication.translate("HTML Report Template","Ambient Humidity")+" (%)", plan_data.get("Ambient Humidity")),
            (QApplication.translate("tilauscope_roast_plan","Weight to roast")+" (g)", plan_data.get("Weight")),
            (QApplication.translate("tilauscope_roast_plan","Intended use"), self._destination),
        ]

        self.set_font('helvetica', '', 10)
        for label, value in info_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 2. Temperature & Timing Profile
        self.ln(2)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'2. Thermal Profile & Timing'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)

        # Helper function to combine Time and Phase % for presentation
        def get_phase_info(time_key:str, percent_key:str)->str:
            time = plan_data.get(time_key, "N/A")
            percent:str = plan_data.get(percent_key, "N/A")
            if percent != "N/A" and percent is not None:
                # Formatting to ensure the percentage has one decimal place, e.g., (35.4%)
                try:
                    percent_value = float(percent)
                    percent_str = f" ({percent_value:.1f}%)"
                except (ValueError, TypeError):
                    percent_str = f" ({percent}%)"
            else:
                percent_str = ""

            return f"{time}{percent_str}"

        profile_data = [
            (QApplication.translate("tilauscope_roast_plan","Charge Temp")+f" (°{self.mode})", plan_data.get("Charge Temp")),
            (QApplication.translate("tilauscope_roast_plan","End of Dry Temp")+f" (°{self.mode})", plan_data.get("End of Dry Temp")),
            (QApplication.translate("tilauscope_roast_plan","First Crack Temp")+f" (°{self.mode})", plan_data.get("First Crack Temp")),
            (QApplication.translate("tilauscope_roast_plan","First Crack source"), plan_data.get("FC Temp Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Phase timing source"), plan_data.get("Phase Timing Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Drop Temp")+f" (°{self.mode})", plan_data.get("Drop Temp")),
            (QApplication.translate("tilauscope_roast_plan","Drop RoR source"), plan_data.get("Drop ROR Source", "grid")),  # item A
            # --- PHASE TIME & % COMBINED ---
            (QApplication.translate("tilauscope_roast_plan","Dry Phase Time")+" (%)", get_phase_info("Dry Phase", "Dry Phase %")),
            (QApplication.translate("tilauscope_roast_plan","Maillard Phase Time")+" (%)", get_phase_info("Maillard Phase", "Maillard Phase %")),
            (QApplication.translate("tilauscope_roast_plan","Development Phase Time")+" (%)", get_phase_info("Development Phase", "Development Phase %")), # Assumes a key for Dev Phase Time/Duration
            # --- END OF PHASE TIME & % COMBINED ---
            (QApplication.translate("tilauscope_roast_plan","First Crack Time")+" ("+QApplication.translate("Label","FC")+")", plan_data.get("FC Time")),
            (QApplication.translate("HTML Report Template","Total Time")+" ("+QApplication.translate("Tooltip","Drop")+")", plan_data.get("Total Time")),
        ]

        self.set_font('helvetica', '', 10)
        for label, value in profile_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 3. Development Ratios (DTR) and Rates of Rise (RoR)
        self.ln(2)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'3. Development Ratios (DTR) and Rates of Rise (RoR)'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)

        ratio_data = [
            (QApplication.translate("tilauscope_roast_plan","Target Agtron Profile"), plan_data.get("Target Agtron")),
            (QApplication.translate("tilauscope_roast_plan","Target weight loss (%)"), plan_data.get("Target Weight Loss")),
            (QApplication.translate("tilauscope_roast_plan","History support"), plan_data.get("History Support", "grid only")),
            (QApplication.translate("tilauscope_roast_plan","History profile"), plan_data.get("History Profile Source", "grid")),
            (QApplication.translate("tilauscope_roast_plan","Resulting DTR (%)"), plan_data.get("Target DTR")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Maillard")+f" (°{self.mode}/min)", plan_data.get("Target ROR Maillard")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR Dev")+" ("+QApplication.translate("tilauscope_roast_plan","Average")+f" °{self.mode}/min)", plan_data.get("Target ROR Dev (Avg)")),
            (QApplication.translate("tilauscope_roast_plan","Target ROR at Drop")+f" (°{self.mode}/min)", plan_data.get("Target ROR at Drop")),
        ]

        self.set_font('helvetica', '', 10)
        for label, value in ratio_data:
            self.cell(80, _row_h, label + ':', border=0)
            self.cell(0, _row_h, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, border=0)

        # 4. Machine settings AT PHASE ENTRY — see _entry_settings.
        self.ln(3)
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",
            '4. Machine Settings at Phase Entry (what to be on when you cross the milestone)'),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(1)
        self.set_font('helvetica', 'I', 8.5)
        self.multi_cell(0, 4, QApplication.translate("tilauscope_roast_plan",
            "The value the machine must read as each phase begins. Between these points the "
            "plan steps the levers: the full sequence is in section 5."), border=0)
        self.ln(1)

        _entry_rows = self._entry_settings(plan_data)
        col_widths = [42, 38, 38, 42]

        # Table Header
        self.set_fill_color(220, 220, 220)
        self.set_font('helvetica', 'B', 10)
        self.cell(col_widths[0], 7, QApplication.translate("Label","Control"), 1, align='C', fill=True)
        self.cell(col_widths[1], 7, QApplication.translate("tilauscope_roast_plan","At CHARGE"), 1, align='C', fill=True)
        self.cell(col_widths[2], 7, QApplication.translate("Button","DRY END"), 1, align='C', fill=True)
        self.cell(col_widths[3], 7, QApplication.translate("Button","FC START"), 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C', fill=True)

        # Table Rows
        self.set_font('helvetica', '', 10)
        for label, values in _entry_rows:
            v = (list(values) + ['N/A', 'N/A', 'N/A'])[:3]
            self.cell(col_widths[0], _row_h, label, 1)
            self.cell(col_widths[1], _row_h, v[0], 1, align='C')
            self.cell(col_widths[2], _row_h, v[1], 1, align='C')
            self.cell(col_widths[3], _row_h, v[2], 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        # AirWave mode is a regime for the phase, not a value crossed at an
        # instant, so it keeps its per-phase reading and says so.
        _awm = str(plan_data.get("AirWave Mode (Dry|Mai|Dev)", "")).strip()
        if _awm:
            _m = (_awm.split(' | ') + ['N/A', 'N/A', 'N/A'])[:3]
            self.cell(col_widths[0], _row_h,
                      QApplication.translate("tilauscope_roast_plan","AirWave Mode")
                      + " " + QApplication.translate("tilauscope_roast_plan","(per phase)"), 1)
            self.cell(col_widths[1], _row_h, _m[0], 1, align='C')
            self.cell(col_widths[2], _row_h, _m[1], 1, align='C')
            self.cell(col_widths[3], _row_h, _m[2], 1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        self.ln(3)
        self.set_font('helvetica', 'I', 9)
        self.multi_cell(0, 4,
                        QApplication.translate("tilauscope_roast_plan","Note: The plan is generated for a Target Agtron profile of ")+
                        f"{plan_data.get('Target Agtron', 'N/A')} (Resulting DTR: {plan_data.get('Target DTR', 'N/A')}). "+
                        QApplication.translate("tilauscope_roast_plan","All temperatures are in BT (Bean Temperature) and times in Minutes:Seconds."),
                        border=0)

        # 5. Control ramps — the section 4 table gives one value per phase, which
        # is unreadable as a gesture sequence: the heater ramp alone is up to a
        # dozen "x% @ y°" pairs in a run-on line. Drawn over time, the same data
        # says at a glance when to move, by how much, and in which direction.
        # Its own page: it is what the operator keeps in front of them.
        try:
            # Ask for the trajectories BEFORE opening the page: a plan with
            # nothing to draw must not leave a titled blank page behind.
            _h_traj, _a_traj, _ = self._control_trajectories(plan_data)
        except Exception as e:
            _logd.error(f"error building control trajectories : {e}")
            _h_traj, _a_traj = [], []

        if _h_traj or _a_traj:
            try:
                self.add_page()
                self.set_fill_color(220, 220, 220)
                self.set_font('helvetica', 'B', 12)
                self.cell(0, 7, QApplication.translate(
                    "tilauscope_roast_plan", '5. Control Ramps (Heater & Airflow)'),
                    new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
                self.ln(4)
                self.set_font('helvetica', 'I', 9)
                self.multi_cell(0, 4, QApplication.translate(
                    "tilauscope_roast_plan",
                    "Each level is held until the next step: the plan asks for one move at a time, "
                    "then time to read its effect. Steps are anchored on bean temperature and shown "
                    "here at the time the planned curve reaches them."),
                    border=0)
                self.ln(4)
                if self.draw_control_ramp_graph(
                        plan_data, x_pos=self.get_x() + 12, y_pos=self.get_y(),
                        width=160, height=62):
                    self.set_y(self.get_y() + 82)
                self._draw_step_sequence(plan_data)
                self._draw_plan_recap(plan_data)
            except Exception as e:
                _logd.error(f"error drawing control ramp graph : {e}")

        # 6. Historical Feedback (Notes and Actions)
        notes = plan_data.get("notes", [])
        actions = plan_data.get("actions", [])

        if notes is not None and len(notes)>0:
            self.add_page(same=True)
            try:
                self.set_fill_color(220, 220, 220)
                self.set_font('helvetica', 'B', 12)
                self.cell(0, 7, QApplication.translate("tilauscope_roast_plan",'6. Historical Feedback & Actions'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
                self.ln(2)

                # Standard loop for lists of strings
                for i in range(len(notes)):
                    # Warning Note
                    self.ensure_space(12)
                    self.set_font('helvetica', 'B', 10)
                    self.set_text_color(200, 0, 0) # Red for warnings
                    self.cell(0, 6, f"{notes[i]}",new_x=XPos.LMARGIN, new_y=YPos.NEXT,)

                    # Associated Action
                    if i < len(actions):
                        self.ensure_space(12)
                        self.set_font('helvetica', 'I', 10)
                        self.set_text_color(0, 0, 0) # Back to black
                        self.cell(0, 6, f"{actions[i]}",new_x=XPos.LMARGIN, new_y=YPos.NEXT,)

                    self.ln(2)

        # Reset text color for any following content
                self.set_text_color(0, 0, 0)
            except Exception as e:
                _logd.error(f"error printing pdf : {e}")

        # --- APPEL DU NOUVEAU GRAPHIQUE ---
        if graph_data:
            self.add_page()
            self.set_font("helvetica", "B", 14)
            self.cell(0, 10, QApplication.translate("tilauscope_roast_plan", "Historical Profile vs. Calculated Plan"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(5)
            self.ensure_space(80) # S'assure qu'il y a de la place pour le graph

            # Positionnement du graphique
            x_graph = self.get_x() + 10
            y_graph = self.get_y() + 20

            # Appel de la méthode améliorée (A, B, C)
            self.draw_enhanced_roast_graph(
                master_data   = graph_data,
                x_pos         = x_graph,
                y_pos         = y_graph,
                width         = 160,
                height        = 70,
                bt_plan_curve = plan_data.get("bt_plan_curve"),  # PCHIP planned curve
            )

            # On déplace le curseur après le graphique pour la suite (notes)
            self.set_y(y_graph + 85)
