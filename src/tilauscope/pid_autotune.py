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


# Script de configuration automatique du Gain Scheduling PID
# Cibles : 60°C, 100°C, 150°C
import logging
import time as _time
from typing import Final
from artisanlib.pid_control import PIDcontrol
from artisanlib.util import fromCtoFstrict
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser, QWidget,
                             QLabel, QGroupBox, QFormLayout, QApplication, QFrame)
from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, pyqtSlot
from tilauscope.tilauscope_types import RoastingPhase, THEME
from artisanlib.main import ApplicationWindow

_log: Final[logging.Logger] = logging.getLogger(__name__)

from tilauscope.theme_qss import apply_tilau_theme


class PIDAutotune(QDialog):
    def __init__(self, parent: QWidget, aw:ApplicationWindow):
        super().__init__()
        # ground=False: the grounded base would paint the rectangle opaque and
        # square off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(False)

        # Variables de monitoring
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.is_monitoring = False

        self.error_integral = 0.0  # Pour le suivi kI
        self.last_error = 0.0      # Pour le suivi kD

        self.aw = aw
        self.pid:PIDcontrol = aw.pidcontrol
        self.unit = aw.qmc.mode     # °C or °F

        self.last_bt = 0.0
        self.last_update_time: float = _time.monotonic()
        self._kp_adjustment_integral: float = 0.0   # accumulateur pour convergence Kp
        self._ki_error_window: list[float] = []   # fenêtre glissante des erreurs
        _KI_WINDOW_SIZE: int = 10                 # 10 cycles × 2 s = 20 s d'historique
        _KI_TRIGGER_ABS: float = 3.0             # seuil en °C·s (somme) pour déclencher
        _KI_DECAY: float = 0.95                  # decay par cycle si pas de déclenchement
        self._ror_history: list[float] = []
        _ROR_SMOOTH_N: int = 4   # moyenne glissante sur 4 valeurs brutes

        self.init_presets()
        self.setup_ui()
        self.aw.PIDAutotuneMenuAction.setChecked(True)

    def _smooth_ror(self, raw_ror: float) -> float:
        """Lisse le RoR par moyenne glissante pour réduire le bruit capteur."""
        _ROR_SMOOTH_N = 4
        self._ror_history.append(raw_ror)
        if len(self._ror_history) > _ROR_SMOOTH_N:
            self._ror_history.pop(0)
        return sum(self._ror_history) / len(self._ror_history)

    def _compute_ror(self, bt: float) -> float:
        """Calcule le RoR (°C/min) en mesurant le delta-temps réel entre appels."""
        now = _time.monotonic()
        dt_s = now - self.last_update_time          # secondes écoulées
        if dt_s < 0.1:                              # garde-fou anti-division par zéro
            ror = 0.0
        else:
            ror = (bt - self.last_bt) / dt_s * 60.0
        self.last_bt = bt
        self.last_update_time = now
        return ror

    def init_presets(self):
        if self.aw is None or self.aw.qmc.temp2 is None or len(self.aw.qmc.temp2) < 2 or len(self.aw.qmc.timeindex)==0 or self.aw.qmc.timeindex[RoastingPhase.CHARGE]==-1:
            self.default_presets = {
                185:  {'kp': 12, 'ki': 0.02, 'kd': 180.0, 'beta': 0.0, 'gamma': 0.0}
            }
            self.pid.pidGainScheduling = False
            self.pid.pidGainSchedulingQuadratic = False
            self.pid.pidGainSchedulingSV = True
            self.preheating = True

            # preheating or not starting and not charged
        else:
            self.default_presets = {
                95:  {'kp': 12, 'ki': 0.05, 'kd': 40.0,  'beta': 0.3, 'gamma': 0.0},
                150: {'kp': 10, 'ki': 0.04, 'kd': 60.0,  'beta': 0.3, 'gamma': 0.0},
                185: {'kp': 8, 'ki': 0.02, 'kd': 120.0, 'beta': 0.3, 'gamma': 0.0}
            }
            self.preheating = False
        self.filtered_ror = 0.0

    # ── Unités ────────────────────────────────────────────────────────────────
    # BT, SV et RoR arrivent ici en unité d'AFFICHAGE (qmc.temp2, pidSchedule*),
    # et les libellés les réaffichent tels quels. Les seuils du réglage sont en
    # doctrine °C : ils sont convertis vers le natif au point de comparaison.
    @property
    def _delta_scale(self) -> float:
        """Facteur d'échelle pour un ÉCART ou un RoR exprimé en °C."""
        return 1.8 if self.aw.qmc.mode == 'F' else 1.0

    def _abs_native(self, temp_c: float) -> float:
        """Température ABSOLUE °C ramenée à l'unité d'affichage."""
        return fromCtoFstrict(temp_c) if self.aw.qmc.mode == 'F' else temp_c

    def is_stable(self, window_size: int = 5, max_spread: float = 0.4) -> bool:
        """Stabilité sur une fenêtre temporelle cohérente avec le cycle Artisan
        (window_size points temp2, max_spread en °C — mis à l'échelle en °F)."""
        temps = self.aw.qmc.temp2
        if len(temps) < window_size:
            return False
        recent = temps[-window_size:]
        return (max(recent) - min(recent)) < max_spread * self._delta_scale

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        # Set margins to at least 10 to provide "breathing room" for the rounded corners
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 20px;
            }}
        """)

        self.content_layout = QVBoxLayout(self.container)
        self.main_layout.addWidget(self.container)

        # Header with Help Button
        header = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_pid","<b>Monitoring & Tuning</b>").upper())
        title_lbl.setStyleSheet(f"color: white; font-size: 18px; font-weight: 900; ")

        # close button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        self.close_btn.clicked.connect(self.fade_out_and_close)
        self.close_btn.setStyleSheet(f"QPushButton {{ background: {THEME['SURFACE']}; color: white; border-radius: 15px; border: 1px solid {THEME['BORDER']}; }} QPushButton:hover {{ background: {THEME['CRITICAL']}; }}")

        # help button
        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        help_btn.setStyleSheet(
            f"border-radius: 12px; background-color: {THEME['ACCENT']};"
            f" color: {THEME['BG']}; font-weight: bold;")
        help_btn.clicked.connect(self.show_help)

        header.addWidget(title_lbl); header.addWidget(help_btn); header.addStretch(); header.addWidget(self.close_btn)
        self.content_layout.addLayout(header)

        # 2. MONITORING GRID (Original Parameters)
        mon_layout = QHBoxLayout()

        # Temperatures Group
        temp_group = self.create_group(QApplication.translate("tilauscope_pid","Temperatures"))
        self.lbl_bt = self.add_row(temp_group, QApplication.translate("tilauscope_pid","Current Bean Temperature"))
        self.lbl_sv = self.add_row(temp_group, QApplication.translate("tilauscope_pid","Artisan PID SV"))
        self.lbl_error = self.add_row(temp_group,QApplication.translate("tilauscope_pid","PID Delta (BT-SV)"))

        # PID Values Group
        pid_group = self.create_group("PID Parameters")
        self.lbl_kp = self.add_row(pid_group, "kP (Prop)")
        self.lbl_ki = self.add_row(pid_group, "kI (Int)")
        self.lbl_kd = self.add_row(pid_group, "kD (Deriv)")

        mon_layout.addWidget(temp_group)
        mon_layout.addWidget(pid_group)
        self.content_layout.addLayout(mon_layout)

        # 3. ADVANCED (BETA/GAMMA)
        adv_group = self.create_group(QApplication.translate("tilauscope_pid","Configuration Structure (2-DOF)"))
        self.lbl_beta = self.add_row(adv_group, "Beta")
        self.lbl_gamma = self.add_row(adv_group, "Gamma")
        self.content_layout.addWidget(adv_group)

        # 4. STATUS & CONSOLE
        self.lbl_status = QLabel(QApplication.translate("tilauscope_pid","Ready"))
        self.lbl_status.setStyleSheet(f"color: {THEME['ACCENT']}; font-weight: bold; border: none;")
        self.content_layout.addWidget(self.lbl_status)        # Status et Boutons

        # 5. BUTTONS
        btn_layout = QHBoxLayout()
        self.btn_preset = self.create_btn(QApplication.translate("tilauscope_pid","Load Presets").upper(), THEME['WARNING'], self.apply_default_presets)
        self.btn_start = self.create_btn(QApplication.translate("tilauscope_pid","Start").upper(), THEME['ACCENT'], self.start_monitoring)
        self.btn_stop = self.create_btn(QApplication.translate("tilauscope_pid","Stop").upper(), THEME['ACCENT'], self.stop_monitoring)
        self.btn_stop.setEnabled(False)

        btn_layout.addWidget(self.btn_preset)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        self.content_layout.addLayout(btn_layout)

        self.resize(350, 480)

    def create_group(self, title):
        group = QGroupBox(title)
        # Target QGroupBox::title specifically to ensure it isn't black
        group.setStyleSheet(f"""
            QGroupBox {{
                color: {THEME['SUBTEXT']};
                font-weight: bold;
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: {THEME['ACCENT']}; /* Or SUBTEXT */
            }}
        """)
        QFormLayout(group)
        return group

    def add_row(self, group, label_text):
        # Create the field label (the text on the left)
        field_lbl = QLabel(label_text)
        field_lbl.setProperty('variant', 'secondary') # Set color here

        # The value label (the text on the right)
        lbl = QLabel("-")
        lbl.setStyleSheet(f"color: {THEME['TEXT']}; border: none;")

        group.layout().addRow(field_lbl, lbl)
        return lbl

    def create_btn(self, text, color, slot):
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.clicked.connect(slot)
        btn.setStyleSheet(f"QPushButton {{ background-color: {color}; color: {THEME['BG']}; border-radius: 8px; font-weight: bold; border: none; }} QPushButton:hover {{ background-color: white; }}")
        return btn

    def apply_default_presets(self):
        """Applique les réglages optimisés au contrôleur Artisan"""
        try:
            if not self.preheating:
                # Point 1 (Schedule 0)
                self.pid.pidKp = self.default_presets[95]['kp']
                self.pid.pidKi = self.default_presets[95]['ki']
                self.pid.pidKd = self.default_presets[95]['kd']
                self.pid.confPIDweights(self.default_presets[95]["beta"], self.default_presets[95]["gamma"])
                self.pid.pidSchedule0 = 95.0

                # Point 2 (Schedule 1)
                self.pid.pidKp1 = self.default_presets[150]['kp']
                self.pid.pidKi1 = self.default_presets[150]['ki']
                self.pid.pidKd1 = self.default_presets[150]['kd']
                self.pid.confPIDweights(self.default_presets[150]["beta"], self.default_presets[150]["gamma"])
                self.pid.pidSchedule1 = 150.0

                # Point 3 (Schedule 2)
                self.pid.pidKp2 = self.default_presets[185]['kp']
                self.pid.pidKi2 = self.default_presets[185]['ki']
                self.pid.pidKd2 = self.default_presets[185]['kd']
                self.pid.pidSchedule2 = 185.0

                # Activation des modes requis
                self.pid.pidGainScheduling = True
                self.pid.pidGainSchedulingQuadratic = True
                self.pid.pidGainSchedulingSV = True
            else:
                self.pid.pidKp = self.default_presets[185]['kp']
                self.pid.pidKi = self.default_presets[185]['ki']
                self.pid.pidKd = self.default_presets[185]['kd']
                self.pid.pidSchedule0 = 185.0
            # prefer PoM and DoM not PoE and DoE
            self.pid.pidPsetpointWeight = 0.0
            self.pid.pidDsetpointWeight = 0.0
            self.lbl_status.setText(QApplication.translate("tilauscope_pid","Presets loaded"))
            _log.info("Presets PID appplied")
        except Exception as e:
            _log.error(f"Error while setting PID presets: {e}")

    def start_monitoring(self):
        self.is_monitoring = True
        self.error_integral = 0.0
        self.last_error = 0.0
        self.timer.start(2000) # Intervalle de 2s
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        #self.btn_reset.setEnabled(False)
        self.lbl_status.setText(QApplication.translate("tilauscope_pid","Analysing..."))

    def stop_monitoring(self):
        self.is_monitoring = False
        self.timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        #self.btn_reset.setEnabled(True)
        self.lbl_status.setText(QApplication.translate("tilauscope_pid","Monitoring stopped"))

    def get_active_pid_slots(self, bt:float):
        """Determines which PID attributes to modify based on scheduling."""
        try:
            if not self.pid.pidGainScheduling:
                return "pidKp", "pidKi", "pidKd"
            if bt <= self.pid.pidSchedule0 : # slot 0 if scheduling in interval or not scheduling
                return "pidKp", "pidKi", "pidKd"
            elif bt <= self.pid.pidSchedule1: # slot x1
                return "pidKp1", "pidKi1", "pidKd1"
            else: # slot x2
                return "pidKp2", "pidKi2", "pidKd2"
        except AttributeError:
            return "pidKp", "pidKi", "pidKd" # Fallback to default

    def _adjust_kp(self, kp_val: float, error: float, attr_p: str, attr_i: str, attr_d: str) -> str:
        """Ajustement Kp par pas absolu (pas multiplicatif) pour éviter la dérive
        exponentielle ; pas proportionnel à l'erreur résiduelle, avec borne."""
        # Pas absolu ≤ 0.05 — insensible à la valeur courante de Kp
        step = min(abs(error) * 0.002, 0.05)
        delta = step if error > 0 else -step
        new_kp = max(0.5, min(kp_val + delta, 30.0))   # bornes durables
        setattr(self.pid, attr_p, new_kp)
        self.pid.setPID(kp=new_kp, ki=getattr(self.pid, attr_i), kd=getattr(self.pid, attr_d)) # Update PID with new values
        _log.info(f"AUTOTUNE > Kp: {kp_val:.4f} → {new_kp:.4f}  (err={error:.2f})")
        return "Adjust Kp"

    def _adjust_ki(self, ki_val: float, error: float, attr_p:str, attr_i: str, attr_d: str) -> str | None:
        """
        Ajuste Ki à partir d'une fenêtre glissante avec decay.
        Évite la dérive lente due à un integral sans borne temporelle.
        """
        _KI_WINDOW_SIZE = 10
        _KI_TRIGGER_ABS = 3.0
        _KI_DECAY        = 0.95

        self._ki_error_window.append(error)
        if len(self._ki_error_window) > _KI_WINDOW_SIZE:
            self._ki_error_window.pop(0)

        integral = sum(self._ki_error_window)

        if abs(integral) > _KI_TRIGGER_ABS:
            # Pas absolu sur Ki (pas multiplicatif) pour éviter la divergence
            step = 0.002 if integral > 0 else -0.002
            new_ki = max(0.002, min(ki_val + step, 0.5))
            setattr(self.pid, attr_i, new_ki)
            self.pid.setPID(kp=getattr(self.pid, attr_p), ki=new_ki, kd=getattr(self.pid, attr_d)) # Update PID with new values
            _log.info(f"AUTOTUNE > Ki: {ki_val:.4f} → {new_ki:.4f}  (Σerr={integral:.2f})")
            self._ki_error_window.clear()   # reset fenêtre après action
            return "Adjust Ki"

        # Decay doux de l'intégrale (les erreurs passées comptent moins avec le temps)
        self._ki_error_window = [e * _KI_DECAY for e in self._ki_error_window]
        return None

    def _decay_kd(self, kd_val: float, attr_p:str, attr_i: str, attr_d: str) -> None:
        """Réduit Kd quand la consigne est tenue, avec plancher absolu."""
        _KD_MIN = 10.0
        new_kd = max(kd_val * 0.99, _KD_MIN)
        setattr(self.pid, attr_d, new_kd)
        self.pid.setPID(kp=getattr(self.pid, attr_p), ki=getattr(self.pid, attr_i), kd=new_kd) # Update PID with new values
        _log.debug(f"AUTOTUNE > Kd decay: {kd_val:.1f} → {new_kd:.1f}")

    def _preheat_adjust(
        self,
        kp_val: float, kd_val: float,
        attr_p: str, attr_d: str,
        error: float
    ) -> str:
        """Ajustements preheating avec bornes strictes : Kd monte doucement
        (plafond 300), Kp descend doucement (plancher 4)."""
        _KD_MAX_PREHEAT = 300.0
        _KD_STEP        = 5.0    # pas absolu montant
        _KP_MIN_PREHEAT = 4.0
        _KP_STEP        = 0.3    # pas absolu descendant

        new_kd = min(kd_val + _KD_STEP, _KD_MAX_PREHEAT)
        new_kp = max(kp_val - _KP_STEP, _KP_MIN_PREHEAT)

        setattr(self.pid, attr_d, new_kd)
        setattr(self.pid, attr_p, new_kp)
        _log.info(
            f"AUTOTUNE > Preheat — Kp: {kp_val:.3f}→{new_kp:.3f}, "
            f"Kd: {kd_val:.1f}→{new_kd:.1f}  (err={error:.2f})"
        )
        return "Preheat: Kp↓ Kd↑"

    def _near_target_threshold(self, bt: float) -> float:
        """Seuil d'erreur pour "près de la consigne" : ±4.0 sous 95°C (Turning
        Point), ±3.0 sous 150°C (Maillard), ±2.0 au-delà (finition). `bt` est
        en unité d'affichage ; bandes et seuil sont convertis depuis le °C."""
        if bt <= self._abs_native(95.0):
            return 4.0 * self._delta_scale
        if bt <= self._abs_native(150.0):
            return 3.0 * self._delta_scale
        return 2.0 * self._delta_scale

    def update_logic(self) -> None:   # type: ignore[override]
        if not self.isVisible() or self.aw is None:
            self.stop_monitoring()
            return
        try:
            if not hasattr(self.aw.qmc, 'temp2') or len(self.aw.qmc.temp2) < 2:
                return
            if not self.pid.pidActive:
                self.stop_monitoring()
                return

            bt  = self.aw.qmc.temp2[-1]

            # ── Point 3 + 11 : RoR réel lissé ──────────────────────────────────
            raw_ror     = self._compute_ror(bt)
            current_ror = self._smooth_ror(raw_ror)

            # ── SV selon mode scheduling ─────────────────────────────────────────
            sv = self.pid.svValue
            if self.pid.pidGainScheduling:
                if self.pid.pidGainSchedulingQuadratic:
                    if bt <= self.pid.pidSchedule0:
                        sv = self.pid.pidSchedule0
                    elif bt <= self.pid.pidSchedule1:
                        sv = self.pid.pidSchedule1
                    else:
                        sv = self.pid.pidSchedule2
                else:
                    sv = self.pid.pidSchedule0 if bt <= self.pid.pidSchedule0 else self.pid.pidSchedule1

            error = sv - bt

            # ── UI temperatures ──────────────────────────────────────────────────
            self.lbl_bt.setText(f"{bt:.2f}")
            self.lbl_sv.setText(f"{sv:.2f}")
            self.lbl_error.setText(f"{error:.2f}")

            # ── Slots actifs ─────────────────────────────────────────────────────
            attr_p, attr_i, attr_d = self.get_active_pid_slots(bt)
            kp_val = getattr(self.pid, attr_p)
            ki_val = getattr(self.pid, attr_i)
            kd_val = getattr(self.pid, attr_d)

            mode  = "sv" if not self.pid.pidGainScheduling else "sch"
            mode1 = ("x2" if self.pid.pidGainSchedulingQuadratic else "x") if self.pid.pidGainScheduling else ""
            _log.info(
                f"AUTOTUNE > mode:{mode}{mode1} BT:{bt:.1f} SV:{sv:.1f} "
                f"Err:{error:.1f} RoR:{current_ror:.1f} | PID:{kp_val:.2f}/{ki_val:.3f}/{kd_val:.1f}"
            )

            # ── Point 12 : seuil adaptatif ───────────────────────────────────────
            if self.preheating:
                is_near_target = abs(error) <= 10.0 * self._delta_scale
            else:
                threshold      = self._near_target_threshold(bt)
                # Point 4 : la stabilité est intégrée dans la condition
                is_near_target = abs(error) <= threshold and self.is_stable()

            ignore_braking  = bt < self._abs_native(90.0)
            is_overspeeding = current_ror > 50.0 * self._delta_scale and not ignore_braking

            # ── Ramping : pas encore à la consigne ──────────────────────────────
            if not is_near_target:
                p = QApplication.translate("tilauscope_pid", "preheating ") if self.preheating else ""
                self.lbl_status.setText(
                    QApplication.translate("tilauscope_pid", "Ramping") + f"... {p}RoR:{current_ror:.1f}"
                )
                self.lbl_kp.setText(f"{kp_val:.4f}")
                self.lbl_ki.setText(f"{ki_val:.4f}")
                self.lbl_kd.setText(f"{kd_val:.4f}")
                return

            # ── Ajustements ─────────────────────────────────────────────────────
            action = QApplication.translate("tilauscope_pid", "Stable")

            if self.preheating:
                # Point 8 : pas absolus avec bornes
                action = self._preheat_adjust(kp_val, kd_val, attr_p, attr_d, error)

            else:
                # Point 5 : ajustement Kp convergent
                if abs(error) > 0.5:
                    action = self._adjust_kp(kp_val, error, attr_p, attr_i, attr_d)
                    kp_val = getattr(self.pid, attr_p)   # valeur mise à jour

                # Point 6 : ajustement Ki avec fenêtre glissante + decay
                ki_action = self._adjust_ki(ki_val, error, attr_p, attr_i, attr_d)
                if ki_action:
                    action = ki_action
                    ki_val = getattr(self.pid, attr_i)

                # Point 7 : freinage ou decay Kd borné
                if is_overspeeding:
                    new_kd = min(kd_val + 2.0, 250.0)   # pas absolu, pas multiplicatif
                    setattr(self.pid, attr_d, new_kd)
                    self.pid.setPID(kp=getattr(self.pid, attr_p), ki=getattr(self.pid, attr_i), kd=new_kd) # Update PID with new values
                    _log.info(f"AUTOTUNE > Braking: RoR={current_ror:.1f} Kd:{kd_val:.1f}→{new_kd:.1f}")
                    action = "Braking (Kd+)"
                elif abs(error) < 0.2:
                    self._decay_kd(kd_val, attr_p, attr_i, attr_d)

            # ── UI PID values ────────────────────────────────────────────────────
            self.lbl_status.setText(action)
            self.lbl_kp.setText(f"{getattr(self.pid, attr_p):.4f}")
            self.lbl_ki.setText(f"{getattr(self.pid, attr_i):.4f}")
            self.lbl_kd.setText(f"{getattr(self.pid, attr_d):.4f}")

        except Exception as e:
            _log.error(f"Erreur autotune: {e}")

    def show_help(self):
        """Opens a resizable help window with PID explanations."""
        help_window = HelpDialog(self)
        help_window.exec() # Use .exec() for a modal window or .show() for non-modal

    def fade_out_and_close(self):
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0); self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.close)
        self.anim.start()

    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        delta = QPoint(event.globalPosition().toPoint() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()

    def closeEvent(self, event):
        """Ensures everything stops when the user closes the window."""
        self.stop_monitoring()
        self.aw.PIDAutotuneMenuAction.setChecked(False)
        _log.info("PID Autotune monitor closed and timer stopped.")
        event.accept()


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(None) # Detach from parent to ensure frameless consistency
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule

        # Window Configuration
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(550, 500)

        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        # Main Styled Container
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame#MainContainer {{
                background-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 20px;
            }}
            QLabel {{ border: none; }} /* Force-remove borders from all child labels */
        """)
        self.container.setObjectName("MainContainer") # Specific ID prevents style leaking
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(25, 20, 25, 25)
        self.main_layout.addWidget(self.container)

        # Header
        header = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_pid","PID Parameters Help").upper())
        title_lbl.setStyleSheet(f"color: white; font-size: 16px; font-weight: 900; ")

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['SURFACE']}; color: white; border-radius: 15px; border: 1px solid {THEME['BORDER']};
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; }}
        """)
        header.addWidget(title_lbl); header.addStretch(); header.addWidget(self.close_btn)
        self.content_layout.addLayout(header)

        # Themed Text Display
        self.text_display = QTextBrowser()
        self.text_display.setOpenExternalLinks(True)
        self.text_display.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 12px;
                padding: 15px;
                font-family: 'Segoe UI', sans-serif;
                line-height: 1.5;
            }}
            /* Custom Scrollbar Styling */
            QScrollBar:vertical {{
                border: none; background: transparent; width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['BORDER']}; border-radius: 4px; min-height: 20px;
            }}
        """)

        # HTML Content
        self.text_display.setHtml(QApplication.translate("tilauscope_pid","""
         <h3>PID Parameters Glossary</h3>
        <p><b>kP (Proportional):</b> Determines the immediate correction strength.
        If the temperature is far from the target, kP applies a strong corrective action.</p>
        <p><b>kI (Integral):</b> Eliminates long-term residual errors.
        It accumulates small deviations over time to ensure the temperature reaches the exact target.</p>
        <p><b>kD (Derivative):</b> Acts as a 'brake'. It anticipates overshoots by
        reacting to the rate of change (RoR) to stabilize the system before it exceeds the target.</p>
        <hr>
        <h3>Advanced Settings</h3>
        <p><b>Beta (P-Weighting):</b> Adjusts how much the Proportional action reacts to changes
        in the Setpoint (SV) vs. changes in the actual temperature (BT).</p>
        <p><b>Gamma (D-Weighting):</b> Adjusts how much the Derivative action reacts to Setpoint changes
        to prevent sudden spikes in output when you move the target temperature.</p>
        <p><b>Gain Scheduling:</b> Automatically switches PID values based on the current temperature
        range to optimize stability at different roasting phases.</p>
        <hr>
        <h3>How to use</h3>
        <p><b>Choose between SV or Scheduling mode</b> Adjusts in Artisan PID dialog the usage mode
        either Regular SV (scheduling uncked), scheduling mode in linear (x), quadratic (x2) modes.
        close Dialog and run the PID Autotune windows.</p>
        <p><b>Load presents</b>: Click on the <b>Load Peeset</b> button to inject the default PID
        settings to start tunning. This is not mandatory, you can start the process without changing the
        current values.</p>
        <p><b>Click on Start</b> to start the PID Autotune process, that is spying what Artisan does and
        could adjust the settings on the fly if it detects that they are not optimal. The routine updates
        kP, kI, kD, beta and gamme if required. You can stop it and restart it at any time while Artisan PID
        is running.</p>
        """))

        self.content_layout.addWidget(self.text_display)

        # Footer Button
        btn_close = QPushButton(QApplication.translate("tilauscope_pid", "CLOSE"))
        btn_close.setFixedHeight(40)
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME['ACCENT']}; color: {THEME['BG']};
                border-radius: 10px; font-weight: bold; border: none; margin-top: 10px;
            }}
            QPushButton:hover {{ background-color: {THEME['LAVENDER']}; }}
        """)
        self.content_layout.addWidget(btn_close)

    # Mouse Events for dragging the frameless window
    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        delta = QPoint(event.globalPosition().toPoint() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()
