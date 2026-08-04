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

import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QDialog, QHBoxLayout, QPushButton, QApplication, QFrame, QLabel
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFont, QFontMetrics, QPainterPath

# Import THEME from your project file
from tilauscope.tilauscope_types import THEME

FLAVOR_WHEEL_DATA = {
    "Enzymatic": {
        "color": "#8B3A2B",
        "groups": {
            "Fruits": {
                "color": "#D35400",
                "subgroups": {
                    "Citric": {"color": "#E67E22", "notes": ["Orange", "Blood orange", "Orange peel", "Tangerine", "Grapefruit", "Yuzu", "Bergamot", "Lemon", "Green Lemon", "Lemon peel", "Lime", "Physalis"]},
                    "Stone fruits": {"color": "#C0392B", "notes": ["Peach", "Yellow peach", "Nispero", "Apricot", "Black plum", "Yellow plum", "Red plum", "Red cherry", "Black cherry", "Nectarine"]},
                    "Berries": {"color": "#922B21", "notes": ["Strawberry", "Blueberry", "Raspberry", "Redcurrant", "Blackcurrant", "Blackberry", "Red mulberry", "Red grape", "White grape"]},
                    "Yellow fruits": {"color": "#F4D03F", "notes": ["Apple", "Red Apple", "Green Apple", "Golden Apple", "Pomegranate", "Pear", "Coffee cherry", "Blueberry raisins", "Grape raisin"]},
                    "Other fruits": {"color": "#D2B4DE", "notes": ["Raisins", "Prunes", "Dried Peaches", "Dried apple", "Dehydrated pear", "Dehydrated strawberry"]},
                    "Tropical fruits": {"color": "#F39C12", "notes": ["Pineapple", "Banana", "Semi-Ripe Banana", "Passion Fruit", "Mango", "Papaya", "Kiwi", "Melon", "Watermelon", "Coconut", "Guava", "Tamarind", "Starfruit", "Lychee", "Persimmon"]}
                }
            },
            "Fragrances": {
                "color": "#F9E79F",
                "subgroups": {
                    "Floral": {"color": "#FEF9E7", "notes": ["Hibiscus", "Camellia", "Azalea", "Lilly", "Dark rose", "Rose", "Jasmine", "White flower"]},
                    "Herbal": {"color": "#D4EFDF", "notes": ["Chamomile", "Violet", "Rhubarb", "Black Tea", "Green Tea"]}
                }
            },
            "Alcohols": {
                "color": "#FADBD8",
                "subgroups": {
                    "Winey": {"color": "#FDEDEC", "notes": ["White wine", "Rosé wine", "Red wine", "Champagne", "Porto"]},
                    "Liqueurs": {"color": "#F5EEF8", "notes": ["Whisky", "Rum", "Anise liqueur", "Almond liqueur"]}
                }
            },
            "Fermentation": {
                "color": "#D5DBDB",
                "subgroups": {
                    "Acetic": {"color": "#E5E8E8", "notes": ["Yogurt", "Over ripe fruit"]},
                    "Lactic": {"color": "#F2F3F4", "notes": ["Yogurt"]}
                }
            }
        }
    },
    "Caramelization": {
        "color": "#2B4C8B",
        "groups": {
            "Sweets": {
                "color": "#2E86C1",
                "subgroups": {
                    "Sugars": {"color": "#AED6F1", "notes": ["Cane sugar", "Muscovado sugar", "Panela", "Molasses", "Maple Syrup", "Honey", "Dulce de leche"]},
                    "Caramels": {"color": "#3498DB", "notes": ["Light brown caramel", "Dark brown caramel", "Toffee"]}
                }
            },
            "Chocolates": {
                "color": "#4A235A",
                "subgroups": {
                    "Chocolaty": {"color": "#5B2C6F", "notes": ["Butter", "Vanilla", "White chocolate", "Milk chocolate", "Dark chocolate", "Cocoa"]}
                }
            },
            "Nutty": {
                "color": "#5499C7",
                "subgroups": {
                    "Nutty": {"color": "#85C1E9", "notes": ["Marzipan", "Hazelnut", "Roasted almond", "Almond", "Peanuts", "Walnut", "Macadamia"]}
                }
            },
            "Cereals": {
                "color": "#A9CCE3",
                "subgroups": {
                    "Cereals": {"color": "#D4E6F1", "notes": ["Malt", "Wheat", "Toasted bread", "Oat", "Biscuit"]}
                }
            }
        }
    },
    "Dry distillation": {
        "color": "#1E4D2B",
        "groups": {
            "Spices": {
                "color": "#7D6608",
                "subgroups": {
                    "Spicy": {"color": "#9A7D0A", "notes": ["Pepper", "Ginger", "Nutmeg", "Cinnamon", "Anise", "Clove"]},
                    "Woody": {"color": "#1D8348", "notes": ["Cedar", "Tobacco", "Pipe tobacco"]}
                }
            },
            "Vegetables": {
                "color": "#145A32",
                "subgroups": {
                    "Vegetables": {"color": "#1E8449", "notes": ["Cucumber", "Tomato", "Pumpkin", "Carrot", "Olive oil", "Peas", "Mushroom"]},
                    "Aromatic herbs": {"color": "#A9DFBF", "notes": ["Basil", "Mint", "Lemon grass", "Fennel", "Thyme", "Rosemary", "Bay leaf"]}
                }
            }
        }
    }
}

class FlavorArc:
    def __init__(self, name, level, color, start_angle, span_angle, inner_r, outer_r, leaf_notes):
        self.name = name
        self.level = level # 0:Core, 1:Group, 2:Subgroup, 3:Note
        self.color = color
        self.start_angle = start_angle
        self.span_angle = span_angle
        self.inner_r = inner_r
        self.outer_r = outer_r
        self.leaf_notes = leaf_notes

class FlavorWheelWidget(QWidget):
    selectionChanged = pyqtSignal(str)

    def __init__(self, current_notes_str="", parent=None):
        super().__init__(parent)
        self.setMinimumSize(900, 900)
        self.setMouseTracking(True)
        self.selected_notes = set()
        self.hovered_arc = None
        self.arcs = []
        self._initialize_arcs()
        self.parse_existing_notes(current_notes_str)

    def _initialize_arcs(self):
        # Precise radii for the 4 concentric rings
        R0, R1, R2, R3, R_EXT = 0.12, 0.28, 0.48, 0.68, 0.96
        
        total_leaves = sum(len(sub["notes"]) for cat in FLAVOR_WHEEL_DATA.values() 
                          for grp in cat["groups"].values() 
                          for sub in grp["subgroups"].values())
        
        angle_unit = 360.0 / total_leaves
        curr_angle = 90.0

        for cat_name, cat_data in FLAVOR_WHEEL_DATA.items():
            cat_leaves, cat_start = [], curr_angle
            for grp_name, grp_data in cat_data["groups"].items():
                grp_leaves, grp_start = [], curr_angle
                for sub_name, sub_data in grp_data["subgroups"].items():
                    sub_leaves = [n.lower() for n in sub_data["notes"]]
                    sub_span = len(sub_leaves) * angle_unit
                    
                    # Level 3: Individual Notes (Outer ring)
                    note_angle = curr_angle
                    for note in sub_data["notes"]:
                        self.arcs.append(FlavorArc(note, 3, sub_data["color"], note_angle, angle_unit, R3, R_EXT, [note.lower()]))
                        note_angle -= angle_unit
                    
                    # Level 2: Subgroups
                    self.arcs.append(FlavorArc(sub_name, 2, sub_data["color"], curr_angle, sub_span, R2, R3, sub_leaves))
                    grp_leaves.extend(sub_leaves)
                    curr_angle -= sub_span
                
                # Level 1: Groups
                self.arcs.append(FlavorArc(grp_name, 1, grp_data["color"], grp_start, len(grp_leaves)*angle_unit, R1, R2, grp_leaves))
                cat_leaves.extend(grp_leaves)

            # Level 0: Core
            self.arcs.append(FlavorArc(cat_name, 0, cat_data["color"], cat_start, len(cat_leaves)*angle_unit, R0, R1, cat_leaves))

    def parse_existing_notes(self, notes_str):
        if notes_str:
            self.selected_notes = {n.strip().lower() for n in notes_str.split(",") if n.strip()}

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        r_max = min(self.width(), self.height()) / 2 * 0.98
        painter.fillRect(self.rect(), QColor(THEME['BG']))

        for arc in self.arcs:
            is_active = any(n in self.selected_notes for n in arc.leaf_notes)
            is_hovered = (arc == self.hovered_arc)
            
            color = QColor(arc.color)
            if is_hovered:
                color = color.lighter(140) # Brighten on hover
            elif not is_active:
                color.setAlpha(45) # Dim inactive paths
            
            # Annulus sector path
            path = QPainterPath()
            outer_rect = QRectF(center.x() - r_max * arc.outer_r, center.y() - r_max * arc.outer_r, 
                                r_max * arc.outer_r * 2, r_max * arc.outer_r * 2)
            inner_rect = QRectF(center.x() - r_max * arc.inner_r, center.y() - r_max * arc.inner_r, 
                                r_max * arc.inner_r * 2, r_max * arc.inner_r * 2)
            
            path.arcMoveTo(outer_rect, arc.start_angle)
            path.arcTo(outer_rect, arc.start_angle, -arc.span_angle)
            path.arcTo(inner_rect, arc.start_angle - arc.span_angle, arc.span_angle)
            path.closeSubpath()

            painter.fillPath(path, QBrush(color))
            painter.setPen(QPen(QColor("#11111b"), 0.5))
            painter.drawPath(path)

            if arc.span_angle > 0.4:
                # Pass 'color' so the label knows how bright the background is
                self._draw_label(painter, center, r_max, arc, is_active or is_hovered, color)
                
    def get_contrast_color(self, bg_color):
        """Returns black for light backgrounds and white for dark backgrounds."""
        # Calculate luminance: 0.299*R + 0.587*G + 0.114*B
        luminance = (0.299 * bg_color.red() + 0.587 * bg_color.green() + 0.114 * bg_color.blue())
        return QColor("#11111b") if luminance > 160 else QColor("#FFFFFF")

    def _draw_label(self, painter, center, r_max, arc, is_highlighted, current_bg_color):
        painter.save()
        mid_angle = arc.start_angle - (arc.span_angle / 2)
        rad = math.radians(mid_angle)
        dist = r_max * (arc.inner_r + arc.outer_r) / 2
        painter.translate(center.x() + dist * math.cos(rad), center.y() - dist * math.sin(rad))
        
        rot = -mid_angle
        if 90 < (mid_angle % 360) < 270: 
            rot += 180
        painter.rotate(rot)
        
        # Determine text color based on the brightness of the arc behind it
        if is_highlighted:
            text_color = self.get_contrast_color(current_bg_color)
        else:
            text_color = QColor(THEME['SUBTEXT'])
            
        painter.setPen(QPen(text_color))
        font_weight = QFont.Weight.Bold if is_highlighted else QFont.Weight.Normal
        painter.setFont(QFont("JetBrains Mono", 10 if arc.level == 3 else 9, font_weight))
        
        metrics = QFontMetrics(painter.font())
        name = arc.name[:18] + ".." if len(arc.name) > 20 else arc.name
        painter.drawText(int(-metrics.horizontalAdvance(name)/2), int(metrics.height()/3), name)
        painter.restore()

    def _get_arc_at_pos(self, pos):
        dx, dy = pos.x() - self.width()/2, (self.height()/2) - pos.y()
        radius = math.sqrt(dx*dx + dy*dy) / (min(self.width(), self.height())/2 * 0.98)
        
        # Standard angle: 0 is Right, 90 is Top
        mouse_angle = (math.degrees(math.atan2(dy, dx)) + 360) % 360
        
        for arc in self.arcs:
            if arc.inner_r <= radius <= arc.outer_r:
                # Calculate the difference between start_angle and mouse_angle correctly with wrap-around
                diff = (arc.start_angle - mouse_angle + 360) % 360
                if diff <= arc.span_angle:
                    return arc
        return None

    def mouseMoveEvent(self, event):
        new_hover = self._get_arc_at_pos(event.position())
        if new_hover != self.hovered_arc:
            self.hovered_arc = new_hover
            self.update()

    def mousePressEvent(self, event):
        arc = self._get_arc_at_pos(event.position())
        # Selection restricted to external ring (Level 3)
        if arc and arc.level == 3:
            note = arc.name.lower()
            if note in self.selected_notes: self.selected_notes.remove(note)
            else: self.selected_notes.add(note)
            self.update()
            self.selectionChanged.emit(", ".join(sorted(self.selected_notes)))

class FlavorSelectorDialog(QDialog):
    """
    Dialog Flavor Wheel — V2.
    Conserve FlavorWheelWidget intact.
    Corrige le doublon header/close_btn présent en V1.
    Contrat d'interface inchangé : FlavorSelectorDialog(current_notes, parent) → exec() → get_notes().
    """

    def __init__(self, current_notes: str = "", parent=None) -> None:
        super().__init__(parent)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── Root layout avec marge pour l'ombre border ──────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Conteneur principal (fond + border-radius) ───────────────────────
        container = QFrame()
        container.setObjectName("FWContainer")
        container.setStyleSheet(f"""
            #FWContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 15px;
            }}
        """)
        root.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 10, 20, 16)
        inner.setSpacing(8)

        # ── Header ───────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 4, 0, 6)

        title = QLabel(
            QApplication.translate("tilauscope_window", "TILAUSCOPE — FLAVOR SELECTOR")
        )
        title.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:16px;font-weight:800;"
            f"font-family:'JetBrains Mono';border:none;background:transparent;"
        )

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']};
                color: {THEME['CRITICAL']};
                border-radius: 15px;
                border: 1px solid {THEME['CRITICAL']};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {THEME['CRITICAL']};
                color: {THEME['BG']};
            }}
        """)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        inner.addLayout(header)

        # ── Roue — FlavorWheelWidget inchangée ──────────────────────────────
        self.wheel = FlavorWheelWidget(current_notes, container)
        inner.addWidget(self.wheel, 1)

        # ── Barre de sélection + validation ─────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(10)

        self._sel_label = QLabel()
        self._sel_label.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;font-family:'JetBrains Mono';"
        )
        self._update_sel_label()
        self.wheel.selectionChanged.connect(self._on_selection_changed)

        validate_btn = QPushButton(
            QApplication.translate("tilauscope_window", "VALIDATE SELECTION")
        )
        validate_btn.setToolTip(
            QApplication.translate(
                "tilauscope_window",
                "Click to confirm your flavor selection and copy it into the bean record. "
                "Close the window to cancel."
            )
        )
        validate_btn.setStyleSheet(
            f"background-color:{THEME['ACCENT']};color:{THEME['BG']};"
            f"font-weight:bold;padding:12px 24px;border-radius:6px;font-size:13px;"
        )
        validate_btn.clicked.connect(self.accept)

        footer.addWidget(self._sel_label, 1)
        footer.addWidget(validate_btn)
        inner.addLayout(footer)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _on_selection_changed(self, notes_str: str) -> None:
        self._update_sel_label()

    def _update_sel_label(self) -> None:
        n = len(self.wheel.selected_notes)
        if n == 0:
            self._sel_label.setText(
                QApplication.translate("tilauscope_window", "No notes selected — click outer ring to select")
            )
        else:
            self._sel_label.setText(
                QApplication.translate("tilauscope_window", "%n note(s) selected", None, n)
            )

    def get_notes(self) -> str:
        """Contrat d'interface inchangé : retourne les notes triées séparées par virgule."""
        return ", ".join(sorted(self.wheel.selected_notes))