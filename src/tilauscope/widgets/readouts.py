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
# TiLau 2026

"""Large-format numbers, read at arm's length from in front of the machine."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QRectF, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from tilauscope.tilauscope_types import THEME


class ExtraCounterWidget(QFrame):
    def __init__(self, name, color=THEME['ACCENT']):
        super().__init__()

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(2)

        self.name_lbl = QLabel(name.upper())
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_lbl.setStyleSheet(f"color: {THEME['OVERLAY0']}; font-size: 10px; font-weight: 800; border: none;")

        self.val_lbl = QLabel("0.0")
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.val_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-family: 'JetBrains Mono'; font-weight: bold; border: none;")

        self.layout.addWidget(self.name_lbl)
        self.layout.addWidget(self.val_lbl)
        self.setMinimumWidth(75)

    def update_value(self, value):
        self.val_lbl.setText(f"{value}")


class LCDReadout(QFrame):
    """Custom LCD-style widget for Roaster Metrics.

    Alert background system
    -----------------------
    Lorsque alert_target est défini, le fond du compteur évolue progressivement
    au fur et à mesure que la valeur courante s'approche de la cible :

      - En dehors de la plage (valeur < target - range) : fond neutre #1a1a1a
      - Dans la plage d'approche [target-range … target] :
          0 %  → jaune foncé (#2a2200)  — « attention »
          50 % → orange foncé (#2a1000)
          100% → rouge intense (#3a0000)  — « danger »
      - Au-delà de la cible (dépassement) : rouge pulsant via QPropertyAnimation

    Appeler set_alert_value(float) à chaque rafraîchissement de mesure.
    Appeler reset_alert() pour revenir à l'état neutre (fin de rôtissage, OFF, etc.).
    """

    # Couleur de fond neutre (repos)
    _BG_NEUTRAL   = QColor("#1a1a1a")
    # Palier intermédiaires de l'alerte (approche)
    _BG_WARN      = QColor("#2a2200")   # jaune très sombre
    _BG_HOT       = QColor("#2a1000")   # orange sombre
    _BG_DANGER    = QColor("#3a0000")   # rouge sombre
    # Couleur de pulsation (dépassement total)
    _BG_OVERSHOT  = QColor("#5a0000")   # rouge vif

    def __init__(self, label: str, color: str, is_main: bool = False,
                 alert_target: float | None = None,
                 alert_range: float = 30.0):
        """
        Parameters
        ----------
        label        : texte du titre (ex. "BT °C")
        color        : couleur du texte / titre
        is_main      : True pour le compteur RoR (plus grand)
        alert_target : valeur seuil déclenchant l'alerte (ex. 230 pour BT/ET, 20 pour RoR)
                       None = pas d'alerte
        alert_range  : plage (en unité de la valeur) en-deçà de la cible où débute l'alerte
                       ex. 30 → alerte commence à target-30 (200°C si target=230°C)
        """
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._value_color   = color
        self._alert_target  = alert_target
        self._alert_range   = alert_range
        self._last_ratio    = -1.0   # Ratio précédent : évite les repaints inutiles
        self._last_ror_color = None  # Couleur RoR précédente : évite un reparse de style à chaque échantillon

        # Define hierarchy: Main (RoR) is larger, others are smaller
        # The readouts stretch to fill the row, and at the previous
        # sizes the digits floated in a mostly empty box. Widest reading is
        # "-100.5" (6 chars ≈ 101 px at 28 px in JetBrains Mono) against a
        # ~118 px column, so the block still fits with room to spare.
        font_size_val = 28 if not is_main else 30
        font_size_lab = 12
        # Single authority for the value size: set_ror_color() rewrites the whole
        # sheet on a colour change and must not resize the readout doing so.
        self._value_font_px = font_size_val

        self.setMinimumWidth(80) # Sécurité minimale
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # Statique, posée une seule fois. La bordure transparente n'est pas
        # décorative : elle réserve le pixel que paintEvent dessine, ce qui
        # garde le rectangle de contenu identique à la version feuille-de-style.
        self.setStyleSheet(
            'QFrame { border: 1px solid transparent; border-radius: 6px; }'
            'QLabel { border: none; background: transparent; }'
        )
        self._current_bg = QColor(self._BG_NEUTRAL)
        self._apply_bg(self._BG_NEUTRAL)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8) # Marges internes
        layout.setSpacing(2)                  # Espace réduit entre titre et valeur
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Label (Title)
        self.lbl_title = QLabel(label.upper()) # Upper pour le look pro
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet(
            f"color: {color};"
            f""
            f"font-weight: bold;"
            f"font-size: {font_size_lab}px; "
            "background: transparent;"
        )

        # Value (Data)
        self.lbl_value = QLabel("--")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # On utilise une largeur de ligne fixe (ex: 3 chiffres + point + 1 décimale)
        self.lbl_value.setStyleSheet(
            f"color: {color};"
            f"font-family: 'JetBrains Mono';"
            f"font-size: {font_size_val}px;"
            f"font-weight: 800; " # Plus épais pour la lisibilité
            "background: transparent;"
        )

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

        # --- Animation de pulsation pour le dépassement ---
        self._pulse_anim = QPropertyAnimation(self, b"_bg_color_prop", self)
        self._pulse_anim.setDuration(800)
        self._pulse_anim.setLoopCount(-1)   # boucle infinie
        self._pulse_anim.setKeyValueAt(0.0, self._BG_DANGER)
        self._pulse_anim.setKeyValueAt(0.5, self._BG_OVERSHOT)
        self._pulse_anim.setKeyValueAt(1.0, self._BG_DANGER)
        self._pulsing = False

    # ------------------------------------------------------------------
    # Propriété Qt animable pour la couleur de fond
    # ------------------------------------------------------------------

    def _get_bg_color(self) -> QColor:
        return self._current_bg

    def _set_bg_color(self, color: QColor) -> None:
        # _apply_bg owns the attribute; assigning it here too would make the
        # unchanged-colour shortcut below always fire and freeze the pulse.
        self._apply_bg(color)

    # pyqtProperty doit être déclaré après les accesseurs
    _bg_color_prop = pyqtProperty(QColor, fget=_get_bg_color, fset=_set_bg_color)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _apply_bg(self, color: QColor) -> None:
        """Repeindre le fond du compteur dans la couleur donnée.

        Repeint, ne restyle pas. L'animation de pulsation appelle ceci à la
        fréquence d'image : une feuille de style est réanalysée — widget et
        enfants — à chaque affectation, alors qu'un QPainter lit la couleur
        directement dans l'attribut.
        """
        if color == self._current_bg:
            return
        self._current_bg = color
        self.update()

    def paintEvent(self, event) -> None:
        """Dessiner la boîte arrondie que décrivait la feuille de style.

        Géométrie inchangée : la bordure transparente déclarée dans __init__
        réserve toujours le même pixel, donc le rectangle de contenu — et
        donc la position des deux libellés — est celui d'avant.
        """
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Bord légèrement plus clair que le fond pour rester lisible
        painter.setPen(self._current_bg.lighter(140))
        painter.setBrush(self._current_bg)
        # Demi-pixel : un trait de 1 px est centré sur le tracé, et c'est ce
        # décalage qui le fait tomber sur la même colonne de pixels que la
        # bordure CSS d'avant plutôt qu'un pixel en dedans.
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

    @staticmethod
    def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
        """Interpolation linéaire entre deux QColor (t ∈ [0, 1])."""
        t = max(0.0, min(1.0, t))
        r = int(c1.red()   + (c2.red()   - c1.red())   * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue()  + (c2.blue()  - c1.blue())  * t)
        return QColor(r, g, b)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def set_alert_value(self, value: float) -> None:
        """Mettre à jour la couleur de fond en fonction de la proximité de la cible.

        À appeler à chaque rafraîchissement de la valeur courante.
        Sans alert_target configuré, la méthode ne fait rien.
        """
        if self._alert_target is None:
            return

        delta = self._alert_target - value   # positif = on n'a pas encore atteint la cible

        # --- Dépassement : démarrer la pulsation ---
        if delta <= 0:
            if not self._pulsing:
                self._pulsing = True
                self._pulse_anim.start()
            return

        # --- Retour sous la cible : arrêter la pulsation avant tout autre test ---
        # Le cache de ratio date d'avant le dépassement, et la valeur peut
        # revenir là où elle a quitté la plage : passé le raccourci ci-dessous,
        # la pulsation restait allumée sur une valeur redevenue normale. La
        # sentinelle force aussi le repaint — l'animation a laissé le fond au
        # rouge de sa dernière image.
        if self._pulsing:
            self._pulsing = False
            self._pulse_anim.stop()
            self._last_ratio = -1.0

        # --- Hors plage d'alerte : fond neutre ---
        if delta >= self._alert_range:
            ratio = 0.0
        else:
            # ratio 0.0 (début de la plage) → 1.0 (juste avant la cible)
            ratio = 1.0 - (delta / self._alert_range)

        # Optimisation : ne repeindre que si le ratio a significativement changé
        if abs(ratio - self._last_ratio) < 0.01:
            return
        self._last_ratio = ratio

        # Interpolation en deux segments pour une transition douce
        #   0.0 → 0.5 : neutre → jaune-avertissement
        #   0.5 → 0.8 : jaune → orange
        #   0.8 → 1.0 : orange → rouge-danger
        if ratio < 0.5:
            bg = self._lerp_color(self._BG_NEUTRAL, self._BG_WARN, ratio / 0.5)
        elif ratio < 0.8:
            bg = self._lerp_color(self._BG_WARN, self._BG_HOT, (ratio - 0.5) / 0.3)
        else:
            bg = self._lerp_color(self._BG_HOT, self._BG_DANGER, (ratio - 0.8) / 0.2)

        self._apply_bg(bg)

    def reset_alert(self) -> None:
        """Revenir au fond neutre (appeler en fin de rôtissage ou lors du passage OFF)."""
        if self._pulsing:
            self._pulsing = False
            self._pulse_anim.stop()
        self._last_ratio = -1.0
        self._apply_bg(self._BG_NEUTRAL)

    # Paliers de couleur RoR (seuils en °C, adaptés si mode F)
    _ROR_PALETTE = [
        (0,   "#4FC3F7"),  # bleu  — négatif / nul
        (5,   THEME['OVERLAY0']),  # gris  — 0–5
        (10,  "#A6E3A1"),  # vert  — 5–10  (idéal)
        (15,  THEME['YELLOW']),  # jaune — 10–15
        (20,  "#FAB387"),  # orange — 15–20
    ]
    _ROR_RED = THEME['CRITICAL']   # rouge — ≥ 20°C/min

    def set_ror_color(self, ror_value: float, mode: str = 'C') -> None:
        """Colorise lbl_value selon la valeur du RoR.
        Seuils en °C — multipliés par 1.8 si mode == 'F'.
        """
        factor = 1.8 if mode == 'F' else 1.0
        color = self._ROR_RED
        for threshold, col in reversed(self._ROR_PALETTE):
            if ror_value < threshold * factor:
                color = col
        # Fires on every RoR sample (even while only monitoring); the band —
        # hence the colour — changes rarely. Skip the stylesheet reparse when
        # the colour is unchanged.
        if color == self._last_ror_color:
            return
        self._last_ror_color = color
        self.lbl_value.setStyleSheet(
            f"color: {color}; font-family: 'JetBrains Mono';"
            f"font-size: {self._value_font_px}px; "
            "font-weight: 800; background: transparent;"
        )

    def init_minmax(self) -> None:
        """Réinitialise les trackers min/max — appeler au CHARGE."""
        self._mm_min: float | None = None
        self._mm_max: float | None = None
        # Restaurer le texte de base du titre (sans la ligne min/max)
        base = self.lbl_title.property("_base_text")
        if base:
            self.lbl_title.setText(base)
        self.lbl_title.setTextFormat(Qt.TextFormat.RichText)

    def update_minmax(self, value: float) -> None:
        """Met à jour min/max. Affiche en sous-titre discret dans lbl_title."""
        if not hasattr(self, '_mm_min') or self._mm_min is None:
            self._mm_min = value
            self._mm_max = value
        else:
            new_min = min(self._mm_min, value)
            new_max = max(self._mm_max, value)
            # Appelé à chaque échantillon BT/ET ; les extrêmes bougent rarement.
            # Sauter la reconstruction du rich-text quand aucune borne ne change.
            if new_min == self._mm_min and new_max == self._mm_max:
                return
            self._mm_min = new_min
            self._mm_max = new_max
        # Afficher ↓min / ↑max en petite ligne sous le label titre
        base_text = self.lbl_title.property("_base_text") or self.lbl_title.text()
        if not self.lbl_title.property("_base_text"):
            self.lbl_title.setProperty("_base_text", base_text)
        self.lbl_title.setText(
            f'{base_text}<br>'
            f'<span style="font-size:9px;color:{THEME["SURFACE2"]};font-weight:400;">'
            f'↓{self._mm_min:.1f}  ↑{self._mm_max:.1f}</span>'
        )
        self.lbl_title.setTextFormat(Qt.TextFormat.RichText)
