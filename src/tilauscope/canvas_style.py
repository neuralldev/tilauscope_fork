"""
Ajustements typographiques du canvas Artisan pour TilauScope : ramène le titre
du roast et la ligne de stats à une taille raisonnable en JetBrains Mono, sans modifier canvas.py, en ré-appliquant le réglage après chaque redraw.

Installation :
    self._canvas_style_hook = CanvasStyleHook(self.aw)
    self._canvas_style_hook.install()
    self._canvas_style_hook.apply_now()

Retrait :
    self._canvas_style_hook.remove()
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

_TITLE_FONTSIZE = 13
_XLABEL_FONTSIZE = 9
_MPL_FONT_FAMILY: str | None = None


def _mpl_mono_font_family() -> str:
    """Register the bundled JetBrains Mono with matplotlib's own font manager.

    Registering the font with Qt (see displayscope._mono_font_family) does not
    make it available to matplotlib — it resolves fonts through its own
    font_manager, independent of QFontDatabase.
    """
    global _MPL_FONT_FAMILY
    if _MPL_FONT_FAMILY:
        return _MPL_FONT_FAMILY
    try:
        from matplotlib import font_manager
        path = os.path.join(os.path.dirname(__file__), 'JetBrainsMono-Regular.ttf')
        font_manager.fontManager.addfont(path)
        _MPL_FONT_FAMILY = font_manager.FontProperties(fname=path).get_name()
    except Exception as exc:  # noqa: BLE001
        _log.warning('_mpl_mono_font_family: falling back to monospace: %s', exc)
        _MPL_FONT_FAMILY = 'monospace'
    return _MPL_FONT_FAMILY


def _needs_restyle(artist: object, fontsize: int, family: str) -> bool:
    """True when the artist has drifted back to Artisan's own font settings.

    `redraw()` calls `setProfileTitle()`, so both hooks fire for a single
    redraw; without this check the second pass would re-measure and schedule a
    draw for nothing, every second of a roast.
    """
    try:
        current_family = artist.get_fontfamily()  # type: ignore[attr-defined]
        if isinstance(current_family, (list, tuple)):
            current_family = current_family[0] if current_family else ''
        return (artist.get_fontsize() != fontsize  # type: ignore[attr-defined]
                or str(current_family) != family)
    except Exception:
        return True


def _apply_canvas_fonts(aw: object) -> None:
    qmc = aw.qmc  # type: ignore[attr-defined]
    family = _mpl_mono_font_family()
    renderer = None
    try:
        renderer = qmc.fig.canvas.get_renderer()
    except Exception:
        pass

    changed = False
    title_artist = getattr(qmc, 'title_artist', None)
    if title_artist is not None and _needs_restyle(title_artist, _TITLE_FONTSIZE, family):
        changed = True
        try:
            title_artist.set_fontsize(_TITLE_FONTSIZE)
            title_artist.set_fontfamily(family)
            if renderer is not None:
                # title_width is used elsewhere to lay out other overlays next
                # to the title — stale after a fontsize change, so recompute.
                qmc.title_width = title_artist.get_window_extent(renderer=renderer).width
        except Exception as exc:
            _log.warning('_apply_canvas_fonts: title failed: %s', exc)

    xlabel_artist = getattr(qmc, 'xlabel_artist', None)
    if xlabel_artist is not None and _needs_restyle(xlabel_artist, _XLABEL_FONTSIZE, family):
        changed = True
        try:
            xlabel_artist.set_fontsize(_XLABEL_FONTSIZE)
            xlabel_artist.set_fontfamily(family)
            if renderer is not None:
                # xlabel_width drives fit_titles()'s truncation on the next
                # draw_event — must reflect the new, smaller font's metrics,
                # else Artisan keeps truncating as if it were still 'medium'.
                qmc.xlabel_width = xlabel_artist.get_window_extent(renderer=renderer).width
        except Exception as exc:
            _log.warning('_apply_canvas_fonts: xlabel failed: %s', exc)

    if not changed:
        return
    try:
        qmc.fig.canvas.draw_idle()
    except Exception as exc:
        _log.warning('_apply_canvas_fonts: draw_idle failed: %s', exc)


class CanvasStyleHook:
    """Ré-applique la typo du titre et de la ligne de stats après chaque
    `qmc.redraw()` **et** chaque `qmc.setProfileTitle()`, car ce dernier est aussi appelé directement par `OnMonitor`/`OffMonitor` sans passer par `redraw()`.
    """

    def __init__(self, aw: object) -> None:
        self._aw = aw
        self._original_redraw: object | None = None
        self._original_set_title: object | None = None

    def apply_now(self) -> None:
        _apply_canvas_fonts(self._aw)

    def install(self) -> None:
        if self._original_redraw is not None:
            return  # already installed — idempotent

        qmc = self._aw.qmc  # type: ignore[attr-defined]
        self._original_redraw = qmc.redraw
        self._original_set_title = qmc.setProfileTitle

        aw = self._aw
        original_redraw = self._original_redraw
        original_set_title = self._original_set_title

        def _hooked_redraw(*args, **kwargs):
            result = original_redraw(*args, **kwargs)  # type: ignore[misc,operator]
            _apply_canvas_fonts(aw)
            return result

        def _hooked_set_title(*args, **kwargs):
            result = original_set_title(*args, **kwargs)  # type: ignore[misc,operator]
            _apply_canvas_fonts(aw)
            return result

        qmc.redraw = _hooked_redraw
        qmc.setProfileTitle = _hooked_set_title
        _log.debug('CanvasStyleHook: installed')

    def remove(self) -> None:
        if self._original_redraw is None:
            return
        try:
            qmc = self._aw.qmc  # type: ignore[attr-defined]
            qmc.redraw = self._original_redraw
            if self._original_set_title is not None:
                qmc.setProfileTitle = self._original_set_title
        except Exception as exc:
            _log.warning('CanvasStyleHook: could not restore: %s', exc)
        finally:
            self._original_redraw = None
            self._original_set_title = None
        _log.debug('CanvasStyleHook: removed')
