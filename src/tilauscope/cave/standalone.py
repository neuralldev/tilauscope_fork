# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The Artisan window BeanCave runs against when it runs alone.

Inside TilauScope, BeanCave is handed Artisan's ApplicationWindow (`aw`) and its
canvas (`aw.qmc`). Alone, it gets these two stand-ins instead, so BeanCave's code
stays the same in both programs (wiki/BeanCave-Standalone-Spec.md). They hold
exactly what BeanCave reads: test_standalone_window fails on any attribute
BeanCave starts using that they lack.

Nothing here samples, roasts or drives a machine: the canvas is idle for good,
and opening a roast hands the file to the operator's own Artisan. Roast Setup
writes a roast's properties on the canvas as it does on Artisan's; BeanCave then
hands them to Artisan as a prepared roast (prepare_in_artisan).
"""

from __future__ import annotations

import codecs

import logging
from pathlib import Path
from typing import Any, Final

from PyQt6.QtCore import QLocale, QSettings, QStandardPaths, QUrl
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtWidgets import QApplication, QWidget

from artisanlib.scale import ScaleManager
from tilaucore.artisan_compat import events_internal_to_external_value
from tilauscope.ai_support import TilauAIConfig
from tilauscope.cave import standalone_settings
from tilauscope.mqttbridge import MQTTConfig

_log: Final[logging.Logger] = logging.getLogger(__name__)

#: What a recorded roast carries that a prepared one must not: Artisan records them anew.
_RECORDED: Final[tuple[str, ...]] = (
    'timex', 'temp1', 'temp2', 'extratimex', 'extratemp1', 'extratemp2', 'specialevents', 'specialeventstype',
    'specialeventsvalue', 'specialeventsStrings', 'computed', 'roastUUID', 'backgroundUUID', 'backgroundpath',
    'roastbatchnr', 'roastbatchpos', 'roastingnotes', 'cuppingnotes', 'ground_color', 'whole_color')


def prepared_profile(base: dict | None, properties: dict, reference: str | None = None) -> dict:
    """A roast for Artisan to record: the setup of `base`, a roast of the same
    machine, without anything it recorded, and the properties Roast Setup chose.
    `reference` becomes its background: Artisan reloads a profile's backgroundpath
    itself, where a second "?template" file open is lost on its way through macOS."""
    profile = {k: v for k, v in (base or {}).items() if k not in _RECORDED}
    # The content changes, so the base's hash no longer matches: Artisan would ask
    # whether to load a "modified profile". Its signature stays (it names the build).
    profile.pop('hash', None)
    profile['timeindex'] = [-1, 0, 0, 0, 0, 0, 0, 0]
    profile.update(properties)
    if reference:
        profile['backgroundpath'] = reference
    # Artisan stores these escaped (encodeLocal) and unescapes them on load: raw, an
    # accented "Variété" comes back as "VariÃ©tÃ©".
    for key in ('title', 'beans', 'backgroundpath'):
        if isinstance(profile.get(key), str):
            profile[key] = codecs.unicode_escape_encode(profile[key])[0].decode('utf8')
    return profile


class _Signal:
    """An Artisan signal nothing listens to here."""

    def __init__(self, slot: Any = None) -> None:
        self._slot = slot

    def emit(self, *args: Any) -> None:
        if self._slot is not None:
            self._slot(*args)


class _Figure:
    """Artisan's matplotlib figure: nothing to draw here."""

    class canvas:  # noqa: N801  (Artisan's shape: qmc.fig.canvas.draw())
        @staticmethod
        def draw() -> None:
            pass


class _PidControl:
    """Artisan's PID: no machine is driven here."""

    pidSource: int = 1  # noqa: N815  (Artisan's name)

    def setSV(self, *_args: Any) -> None:  # noqa: N802  (Artisan's name)
        pass


class StandaloneCanvas:
    """Artisan's canvas (`qmc`), idle: the RoR and display settings BeanCave reads.

    Values are Artisan's own defaults (artisanlib/canvas.py).
    """

    def __init__(self) -> None:
        self.mode: str = 'C'
        self.device_logging: bool = False   # read when a new scale is connected
        # rate of rise, standard method (tilauscope.ror)
        self.curvefilter: int = 3
        self.interpolateDropsflag: bool = True
        self.optimalSmoothing: bool = False
        self.deltaETspan: int = 20
        self.deltaBTspan: int = 20
        self.deltaETsamples: int = 6
        self.deltaBTsamples: int = 6
        self.deltaETfilter: int = 7
        self.deltaBTfilter: int = 7
        self.median_filter_factor_RoR: int = 3
        self.filterDropOuts: bool = True
        self.RoRlimitFlag: bool = True
        self.RoRlimit: int = 45
        self.RoRlimitm: int = -10
        self.maxRoRlimit: int = 170
        # display
        self.etypes: list[str] = [QApplication.translate('ComboBox', 'Air'),
                                  QApplication.translate('ComboBox', 'Drum'),
                                  QApplication.translate('ComboBox', 'Damper'),
                                  QApplication.translate('ComboBox', 'Burner'),
                                  '--']
        self.EvalueColor: list[str] = ['#43a7cf', '#49b160', '#800080', '#ad0427']
        self.color_systems: list[str] = ['', 'Tonino', 'ColorTest', 'Colorette', 'ColorTrack', 'Agtron']
        self.color_system_idx: int = 0
        self.palette: dict[str, str] = {}   # TilauScope's curve falls back on its own colours
        # machine setup, as roasters.apply_roaster_to_artisan writes it
        self.roastertype: str = ''
        self.roastertype_setup: str = ''
        self.machinesetup: str = ''
        self.roastersize: float = 0.0
        self.roastersize_setup: float = 0.0
        self.roastersize_setup_default: float = 0.0
        self.roasterheating: int = 0
        self.roasterheating_setup: int = 0
        self.roasterheating_setup_default: int = 0
        self.operator: str = ''
        self.operator_setup: str = ''
        # no roast, ever
        self.flagon: bool = False
        self.flagstart: bool = False
        self.timeindex: list[int] = [-1, 0, 0, 0, 0, 0, 0, 0]
        self.timex: list[float] = []
        self.temp1: list[float] = []
        self.temp2: list[float] = []
        self.backgroundprofile: Any = None
        self.timeB: list[float] = []
        self.temp1B: list[float] = []
        self.temp2B: list[float] = []
        self.beans: str = ''
        self.backgroundpath: str = ''
        self.tilau_mqtt_ports: Any = None
        # the roast Roast Setup prepares, as Artisan's canvas holds one
        self.title: str = ''
        self.title_show_always: bool = False
        self.weight: tuple[float, float, str] = (0.0, 0.0, 'g')
        self.density: tuple[float, str, float, str] = (0.0, 'g', 1.0, 'l')
        self.moisture_greens: float = 0.0
        self.greens_temp: float = 0.0
        self.beansize_min: int = 0
        self.beansize_max: int = 0
        self.ambientTemp: float = 0.0
        self.ambient_humidity: float = 0.0
        self.ambient_pressure: float = 0.0
        self.elevation: int = 0
        self.ground_color: float = 0
        self.whole_color: float = 0
        self.roasted_defects_weight: float = 0.0
        self.autosaveprefix: str = ''
        self.batchcounter: int = 0
        self.batchprefix: str = '#'
        self.roastbatchnr: int = 0
        self.roastbatchpos: int = 1
        self.roastbatchprefix: str = '#'
        self.background: bool = False
        self.titleB: str = ''
        self.roastbatchnrB: int = 0
        self.roastbatchprefixB: str = ''
        self.phases: list[int] = [150, 150, 200, 230]
        self.statisticstimes: list[float] = [0, 0, 0, 0, 0]
        self.autoChargeFlag: bool = True
        self.autoDropFlag: bool = True
        self.extrabuttonactions: list[int] = []
        self.extrabuttonactionstrings: list[str] = []
        self.xextrabuttonactions: list[int] = []
        self.xextrabuttonactionstrings: list[str] = []
        self.locale_str: str = QLocale().name().split('_')[0]
        self.fig = _Figure()

    @staticmethod
    def eventsInternal2ExternalValue(v: float | None) -> int:  # noqa: N802  (Artisan's name)
        return events_internal_to_external_value(v)

    def redraw(self, *_args: Any, **_kwargs: Any) -> None:
        """Nothing is drawn: BeanCave draws its own curves."""

    def reset(self, *_args: Any, **_kwargs: Any) -> bool:
        """Nothing is recorded, so nothing is ever lost."""
        return True

    def fileDirty(self) -> None:  # noqa: N802  (Artisan's name)
        pass

    def setProfileTitle(self, *_args: Any) -> None:  # noqa: N802  (Artisan's name)
        pass

    def setProfileBackgroundTitle(self, *_args: Any) -> None:  # noqa: N802  (Artisan's name)
        pass

    def properties(self) -> dict:
        """What Roast Setup chose, in a roast file's keys."""
        return {'mode': self.mode, 'title': self.title, 'beans': self.beans, 'weight': list(self.weight),
                'density': list(self.density), 'moisture_greens': self.moisture_greens,
                # Artisan writes the screen size as text, and refuses a roast file holding it as a number.
                'greens_temp': self.greens_temp, 'beansize_min': str(self.beansize_min),
                'beansize_max': str(self.beansize_max), 'ambientTemp': self.ambientTemp,
                'ambient_humidity': self.ambient_humidity, 'ambient_pressure': self.ambient_pressure}


class StandaloneWindow(QWidget):
    """Artisan's main window (`aw`), as BeanCave alone sees it. A widget, never
    shown: BeanCave's dialogs take it as their parent."""

    #: Read by BeanCave where it acts differently alone.
    tilau_standalone: bool = True

    def __init__(self) -> None:
        super().__init__()
        self.app = QApplication.instance()
        self.qmc = StandaloneCanvas()
        self.curFile: str | None = None
        self.beancaveWindow: Any = None
        self.beanCaveMenuAction = QAction(self)   # TilauScope's menu entry: kept, never shown
        self.tilauscope_main: Any = None
        self.tilau_web_host: Any = None
        self.tilau_roaster: str = ''
        self._tilau_roast_context: Any = None
        self._tilau_roast_context_name: str | None = None
        self._tilau_inlet_air_mode: Any = None
        self._tilau_has_et: bool = True
        self.TilauScopeFCTreshold: int = 4
        self.eventslidervisibilities: list[int] = [1, 1, 1, 1]   # every lane a stored roast carries
        self.tilauPreheatingPid: Any = None
        self._tilaupid_user_disabled: bool = False
        self.bleNiimbotDeviceName: str | None = None
        self.bleNiimbotDeviceslist: list[str] = []
        self.bleRoastSeeAGDeviceName: str | None = None
        self.bleRoastSeeDeviceName: str | None = None
        self.bleTilauScopeDeviceName: str | None = None
        self.bleTilauAmbientDeviceslist: list[str] | None = None
        self.bleRoastSeeDeviceslist: list[str] | None = None
        self.bleRoastSeeAGDeviceslist: list[str] | None = None
        self.bleScaleDeviceslist: list[str] | None = None
        self.scale1_model: int | None = None
        self.scale1_id: str | None = None
        self.scale1_name: str | None = None
        # The settings window snapshots these for Cancel; BeanCave alone never uses them.
        self.bleAirwaveDeviceName: str | None = None
        self.bleSkywalkerDeviceName: str | None = None
        self.bleAirwavepidRamp: int = 5
        self.bleAirwaveEmulateOmniflux: bool = False
        self.bleAirwavepidparms: dict = {}
        self.TilauScopeAnnotation: bool = False
        self.TilauScopeNotification: bool = False
        self.TilauScopeFCWindow: int = 0
        self.TilauScopeFCHalfBand: float = 0.0
        self.TilauScopeDEMarkFlag: bool = False
        self.TilauScopeFCMarkFlag: bool = False
        self.pidcontrol = _PidControl()
        self.clearBackgroundSignal = _Signal()
        self.scale_manager = ScaleManager(lambda *_a: None, lambda *_a: None)
        settings = QSettings()
        standalone_settings.load(self, settings)
        if self.scale1_model is not None and self.scale1_id:
            self.scale_manager.set_scale1_signal.emit(self.scale1_model, str(self.scale1_id),
                                                      str(self.scale1_name or ''))
        # Under TilauScope's Device group, where TilauScope keeps them too.
        ai, mqtt = settings.value('Device/tilauai', None), settings.value('Device/tilaumqttbridge', None)
        self.tilau_aiConfig, self.mqttConfig = TilauAIConfig(), MQTTConfig()
        # A damaged entry falls back on the defaults, as Artisan's own settings load does.
        try:
            if isinstance(ai, dict):
                self.tilau_aiConfig = TilauAIConfig.from_dict(ai)
        except Exception:  # noqa: BLE001
            _log.exception('AI settings not read')
        try:
            if isinstance(mqtt, dict):
                self.mqttConfig = MQTTConfig.from_dict(mqtt)
        except Exception:  # noqa: BLE001
            _log.exception('MQTT settings not read')
        from tilauscope.ai_service import TilauAIService  # noqa: PLC0415
        self.tilau_ai_service = TilauAIService(self.tilau_aiConfig, parent=self)

    def save_settings(self) -> None:
        """What the settings window chose: TilauScope's Artisan writes it on quit, BeanCave at once."""
        standalone_settings.save(self, QSettings())

    def alarmconfig(self, _: bool = False) -> None:
        """Artisan's alarm editor: there is none here."""

    def tilauscopeCall(self, *_args: Any) -> None:  # noqa: N802  (TilauScope's name)
        """There is no TilauScope here."""

    def getProfile(self, *_args: Any, **_kwargs: Any) -> dict:  # noqa: N802  (Artisan's name)
        return prepared_profile(None, self.qmc.properties())

    def fileSave(self, *_args: Any) -> bool:  # noqa: N802  (Artisan's name)
        """No roast is held here to save."""
        return False

    def loadAlarms(self, filename: str) -> None:  # noqa: N802  (Artisan's name)
        """Hand an alarm set to the operator's Artisan."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(filename))

    def prepare_in_artisan(self, base: dict | None, alarms: str | None, reference: str | None) -> bool:
        """Hand Artisan the roast Roast Setup prepared, the reference roast as its
        background inside it, then the plan's alarms. False when the system did not take the roast."""
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'prepared roast.alog'
        path.write_text(repr(prepared_profile(base, self.qmc.properties(), reference)), encoding='utf-8')
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            return False
        if reference:
            self.qmc.backgroundpath = reference
        if alarms:
            self.loadAlarms(alarms)
        return True

    def window(self) -> None:
        """No main window: BeanCave is the only one."""

    def loadFile(self, filename: str, quiet: bool = False) -> None:  # noqa: N802, ARG002  (Artisan's name)
        """Open a roast in the application the system opens roasts with.

        `curFile` names it only once the system took it: BeanCave reads it to tell
        a load that failed, as with Artisan's own loadFile.
        """
        if QDesktopServices.openUrl(QUrl.fromLocalFile(filename)):
            self.curFile = filename

    def loadAndRedrawBackgroundUUID(self, filename: str, *_args: Any) -> None:  # noqa: N802  (Artisan's name)
        """Open a roast as the background curve of the operator's Artisan."""
        url = QUrl.fromLocalFile(filename)
        url.setQuery('template')
        if QDesktopServices.openUrl(url):
            self.qmc.backgroundpath = filename
