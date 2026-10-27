# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""What the Niimbot roast label says, the same on the desktop and the tablet.

Each app draws it (Pillow on the desktop, a canvas on the tablet); the values and
the lines come from here. Texts are marked for translation (QT_TRANSLATE_NOOP):
the desktop passes its translate, the tablet prints them in English.
"""

from collections.abc import Callable

from tilaucore.bean_qualifiers import QT_TRANSLATE_NOOP
from tilaucore.beans import GreenBean

Text = tuple[str, str]


def _english(text: Text) -> str:
    return text[1]


def _fmt_seconds(s: int) -> str:
    """Formate une durée en secondes → 'm:ss'."""
    return f"{s // 60}:{s % 60:02d}"


def label_data(bean: GreenBean, data: dict, qr_base_url: Callable[[], str]
               ) -> tuple[dict[str, str], str, dict[str, float]]:
    """Retourne (roast_data, qr_url, phases).

    ``phases`` contient les durées brutes (s) et les pourcentages.
    Lève ``ValueError`` si les points clés sont manquants/invalides.
    """
    computed = data.get("computed", {})
    mode     = data.get("mode", "C")

    t_dry  = computed.get("DRY_time")
    t_fcs  = computed.get("FCs_time")
    t_drop = computed.get("DROP_time")

    if None in (t_dry, t_fcs, t_drop) or t_drop <= 0:
        raise ValueError(
            "Données de torréfaction incomplètes (DRY/FCs/DROP) — "
            "impossible de calculer les phases."
        )

    drying     = float(t_dry)
    maillard   = float(t_fcs)  - float(t_dry)
    development= float(t_drop) - float(t_fcs)
    total      = float(t_drop)

    phases: dict[str, float] = {
        "drying":          drying,
        "maillard":        maillard,
        "development":     development,
        "total":           total,
        "drying_pct":      round(100 * drying     / total, 1),
        "maillard_pct":    round(100 * maillard   / total, 1),
        "development_pct": round(100 * development/ total, 1),
    }

    roast_iso  = data.get("roastisodate", "N/A")
    roast_date = (
        f"{roast_iso[8:10]}-{roast_iso[5:7]}-{roast_iso[:4]}"
        if roast_iso != "N/A" else "N/A"
    )

    weightin  = computed.get("weightin",  "N/A")
    weightout = computed.get("weightout", "N/A")
    wloss     = computed.get("weight_loss","N/A")

    # Ground when measured, else whole — never the lighter of the two.
    colour = next((c for c in (data.get('ground_color'), data.get('whole_color'))
                   if isinstance(c, (int, float)) and c > 0), 'N/A')

    roast_data: dict[str, str] = {
        "Bean":        (bean.name[:27] + "…") if len(bean.name) > 30 else bean.name,
        "Origin":      bean.country,
        "Process":     bean.process,
        "Variety":     bean.varieties,
        "Roaster":     bean.supplier,
        "Farm":        bean.farm,
        "Density":     f"{bean.density} g/l" if bean.density > 0 else str(data.get("density", ["-"])[0]),
        "Altitude":    f"{bean.altitude} m" if bean.altitude > 0 else "-",
        "Date":        roast_date,
        "Time":        data.get("roasttime", "N/A"),
        "SCA Score":   str(bean.sca),
        "Weight In":   f"{weightin} g",
        "Weight Out":  f"{weightout} g",
        "Weight Loss": f"{wloss} %",
        "Agtron Color":f"{colour} {data.get('color_system','')}".strip(),
        "Total Time":  _fmt_seconds(int(computed.get("totaltime", 0))),
        "DTR":         f"{round(computed.get('finishphasetime',0) / computed.get('totaltime',1) * 100, 1)}%",
        "Drop BT":     f"{computed.get('DROP_BT','N/A')}°{mode}",
        "RoR DEV":     f"{computed.get('finish_phase_ror','N/A')}°{mode}/min",
        "Notes (Aro.)":data.get("Aroma_Notes",   "N/A"),
        "Notes (Fls.)":bean.flavour_notes,
        "Notes (M.F.)":data.get("Mouthfeel_Notes","N/A"),
    }

    # Tasting notes consolidées
    notes_parts = []
    for key in ("Notes (Aro.)", "Notes (Fls.)", "Notes (M.F.)"):
        val = roast_data[key]
        if val and val != "N/A":
            initial = key.replace("Notes (", "").replace(".)", "")[:1]
            notes_parts.append(f"{initial}: {val}")
    roast_data["Tasting Notes"] = "; ".join(notes_parts)

    # QR encodes the same http record URL as the PDF label and the bean/sack
    # labels, so any label can be scanned (webcam or phone) to open the record.
    roast_uuid = str(data.get("roastUUID") or "")
    qr_url = f"{qr_base_url()}/roast/{roast_uuid}" if roast_uuid else ""

    return roast_data, qr_url, phases


def lines_30mm(roast_data: dict[str, str], translate: Callable[[Text], str] = _english) -> dict:
    """The texts of the 30 mm label, top to bottom; a detail the coffee has no value for has no line."""
    details = [(translate(label), value) for label, value in (
        (QT_TRANSLATE_NOOP("tilauscope_common", "Process"),   roast_data["Process"]),
        (QT_TRANSLATE_NOOP("tilauscope_common", "Altitude"),  roast_data["Altitude"]),
        (QT_TRANSLATE_NOOP("Label", "Density"),   roast_data["Density"]),
        (QT_TRANSLATE_NOOP("tilauscope_common", "SCA score"), roast_data["SCA Score"]),
    ) if value not in ("", "-", "0.0")]
    return {
        "origin_farm": f"{roast_data['Origin']} {roast_data['Farm']}",
        "bean": translate(QT_TRANSLATE_NOOP("Label", "Beans")) + f": {roast_data['Bean']}",
        "details": details,
        "date": translate(QT_TRANSLATE_NOOP("tilauscope_label", "Roasted on")) + f": {roast_data['Date']}",
        "notes_header": translate(QT_TRANSLATE_NOOP("tilauscope_common", "Tasting notes")) + ": ",
        "notes": roast_data["Tasting Notes"],
    }
