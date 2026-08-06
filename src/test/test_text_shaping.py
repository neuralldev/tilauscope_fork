"""Fonts and text preparation shared by everything TilauScope prints.

Three renderers draw operator-facing text: the roast plan report (fpdf), the two
A4 label sheets (QPainter) and the Niimbot bitmaps (Pillow). Only Qt shapes text
by itself. These tests cover the part the other two depend on — that a bean name
in a non-latin script reaches the paper as written, joined, and in the right
order.

The failure they guard against is silent by construction: a label prints, it
just prints the wrong thing, and nobody who cannot read the script will notice.
"""

import unicodedata

import pytest

from fontTools.ttLib import TTFont
from PIL import Image

from tilauscope import text_shaping as ts


# ── the bundled faces actually cover what we claim ───────────────────────────

def _codepoints(path) -> set:
    font = TTFont(str(path), fontNumber=0, lazy=True)
    try:
        return {cp for table in font['cmap'].tables for cp in table.cmap}
    finally:
        font.close()


@pytest.mark.parametrize(('script', 'sample'), [
    ('latin',      'Café'),
    ('vietnamese', 'Cà phê'),
    ('cyrillic',   'Кофе'),
    ('greek',      'Καφές'),
    ('hebrew',     'קפה'),
])
def test_the_body_face_covers_the_scripts_the_labels_promise(script, sample) -> None:
    """A missing glyph is not an exception, it is a blank box on a printed label.

    Checked against the font's own character map rather than by looking at
    pixels: a missing glyph still draws ink — the .notdef box — so an
    ink-counting test would pass on exactly the case it exists to catch.
    """
    covered = _codepoints(ts.sans_path())
    missing = [c for c in sample if not c.isspace() and ord(c) not in covered]
    assert not missing, f'{script}: {missing!r} would print as empty boxes'


def test_the_body_face_covers_joined_arabic() -> None:
    """Joining produces presentation forms (FE70–FEFF), a different block.

    Covering plain Arabic is not enough: what actually gets drawn after the
    reshaping step is the contextual form, and a face can carry one without the
    other.
    """
    covered = _codepoints(ts.sans_path())
    shaped = ts.shape_bidi('قهوة عربية')
    missing = [c for c in shaped if not c.isspace() and ord(c) not in covered]
    assert not missing, f'joined Arabic is not covered: {missing!r}'


@pytest.mark.parametrize(('script', 'sample'), [
    ('chinese',  '咖啡豆'),
    ('japanese', 'コーヒー豆'),
    ('korean',   '커피 원두'),
])
def test_the_cjk_face_covers_cjk(script, sample) -> None:
    """DejaVu has no CJK at all, which is why a second face is bundled."""
    covered = _codepoints(ts.cjk_path())
    missing = [c for c in sample if not c.isspace() and ord(c) not in covered]
    assert not missing, f'{script}: {missing!r} would print as empty boxes'


def test_thai_is_the_known_gap() -> None:
    """Documents the one script no bundled face covers, so it is a decision.

    Thai prints blank. That is a gap, not a crash, and it is the same on the
    roast plan. If a Thai-capable face is ever bundled, delete this test rather
    than discovering the limitation again from a user report.
    """
    covered = _codepoints(ts.sans_path()) | _codepoints(ts.cjk_path())
    assert not any(ord(c) in covered for c in 'กาแฟ'), (
        'Thai is now covered — update the documentation and drop this test'
    )


# ── the bidirectional pass ───────────────────────────────────────────────────

def test_left_to_right_text_is_returned_untouched() -> None:
    """The common path must not pay for, or risk, the RTL machinery."""
    assert ts.shape_bidi('Ethiopia Guji 200 °C') == 'Ethiopia Guji 200 °C'
    assert ts.shape_bidi('') == ''
    assert ts.shape_bidi(None) is None


def test_arabic_letters_come_out_joined() -> None:
    """Unjoined Arabic is readable-ish but wrong; joined uses FE70–FEFF."""
    shaped = ts.shape_bidi('قهوة')
    assert any(0xFE70 <= ord(c) <= 0xFEFF for c in shaped), (
        f'no contextual forms in {shaped!r} — the letters will print isolated'
    )


def test_a_number_inside_an_arabic_sentence_stays_inside_it() -> None:
    """The reordering step is what this is for.

    Without it the digits are drawn where they appear in logical order, which in
    a right-to-left line puts a charge temperature at the far end of the phrase.
    """
    shaped = ts.shape_bidi('تحميل 200 درجة')
    assert '200' in shaped
    assert not shaped.startswith('200') and not shaped.endswith('200'), (
        f'200 landed on the edge of the line: {shaped!r}'
    )


def test_hebrew_is_reordered_but_not_reshaped() -> None:
    """Hebrew does not join; running the reshaper on it would be wrong."""
    source = 'קפה'
    shaped = ts.shape_bidi(source)
    assert shaped == source[::-1], f'expected a plain reversal, got {shaped!r}'


def test_the_two_steps_are_not_interchangeable() -> None:
    """Reshaping AFTER reordering computes joining on a reversed string.

    The result looks plausible and is not: the letters come apart again. This
    pins the order so a tidy-up cannot swap them.
    """
    import arabic_reshaper
    from bidi import get_display

    source = 'قهوة عربية'
    correct = get_display(arabic_reshaper.reshape(source))
    reversed_order = arabic_reshaper.reshape(get_display(source))
    assert ts.shape_bidi(source) == correct
    assert correct != reversed_order, 'the two orders agree — the test is moot'


def test_detection_is_by_content_not_by_locale() -> None:
    """A bean name can be Arabic in an English session."""
    assert ts.shape_bidi('Guji قهوة') != 'Guji قهوة'
    assert ts.has_script('咖啡', ts.CJK_RANGES)
    assert not ts.has_script('Guji', ts.RTL_RANGES)


# ── the Pillow drawing surface ───────────────────────────────────────────────

class _Recorder:
    """Stands in for a real ImageDraw method to capture what it was handed."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return 0


@pytest.fixture
def draw():
    return ts.shaping_draw(Image.new('1', (400, 60), 1))


@pytest.mark.parametrize('method', ['text', 'textlength', 'textbbox'])
def test_every_pillow_text_method_shapes(method, draw) -> None:
    """Measuring and drawing must agree.

    ``textlength`` decides whether a bean name fits a 50 mm roll. If it measured
    the unshaped string and ``text`` drew the shaped one, the fitting logic would
    silently work on a different string than the one printed.
    """
    recorder = _Recorder()
    setattr(draw, method, ts._shaping_wrapper(recorder))

    if method == 'textlength':
        getattr(draw, method)('قهوة', font=ts.pil_font(20))
    else:
        getattr(draw, method)((0, 0), 'قهوة', font=ts.pil_font(20))

    (args, kwargs) = recorder.calls[0]
    passed = kwargs.get('text', args[-1] if method == 'textlength' else args[1])
    assert any(0xFE70 <= ord(c) <= 0xFEFF for c in passed), (
        f'{method} received unshaped text: {passed!r}'
    )


def test_the_string_is_located_not_assumed(draw) -> None:
    """text() takes it second, textlength() first, and both accept ``text=``.

    An override with a fixed signature is how the roast plan lost its graph
    labels once already, so every call style is covered here.
    """
    recorder = _Recorder()
    draw.text = ts._shaping_wrapper(recorder)

    draw.text((0, 0), 'قهوة', font=ts.pil_font(20))
    draw.text((0, 0), text='قهوة', font=ts.pil_font(20))

    for args, kwargs in recorder.calls:
        passed = kwargs.get('text', args[1] if len(args) > 1 else None)
        assert any(0xFE70 <= ord(c) <= 0xFEFF for c in passed), (
            f'this call style escaped the shaping pass: {args!r} {kwargs!r}'
        )


def test_cjk_swaps_the_face_because_pillow_has_no_fallback(draw) -> None:
    """Pillow is built here without Raqm: no shaping, and no font fallback.

    On a latin-only face a Chinese bean name is a row of empty boxes with no
    error anywhere, so the face is chosen from the string itself.
    """
    recorder = _Recorder()
    draw.text = ts._shaping_wrapper(recorder)
    latin = ts.pil_font(20)

    draw.text((0, 0), '咖啡豆', font=latin)
    draw.text((0, 0), 'Guji', font=latin)

    cjk_call, latin_call = recorder.calls
    assert cjk_call[1]['font'].path == str(ts.cjk_path()), (
        'the CJK string kept the latin face and will print blank'
    )
    assert latin_call[1]['font'] is latin, 'latin text must not pay for the swap'


def test_the_swapped_face_keeps_the_requested_size() -> None:
    """A silent size change would break every layout the builders compute."""
    for size in (12, 20, 24):
        assert ts._cjk_twin(ts.pil_font(size)).size == size


# ── degradation ──────────────────────────────────────────────────────────────

def test_a_checkout_without_fonts_still_draws(monkeypatch) -> None:
    """Typography may degrade; a label must still come out of the printer."""
    monkeypatch.setattr(ts, 'sans_path', lambda **_: None)
    monkeypatch.setattr(ts, 'cjk_path', lambda: None)
    ts.pil_font.cache_clear()
    try:
        assert ts.pil_font(20) is not None
    finally:
        ts.pil_font.cache_clear()


def test_bidi_failure_returns_the_original_text(monkeypatch) -> None:
    """A missing optional import must not take a label down with it."""
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name in ('arabic_reshaper', 'bidi'):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, '__import__', boom)
    assert ts.shape_bidi('قهوة') == 'قهوة'


# ── the label path no longer flattens text ───────────────────────────────────

@pytest.mark.parametrize('sample', ['Café', '커피 원두', 'قهوة', 'Cà phê', 'Кофе'])
def test_label_text_reaches_the_printer_as_written(sample) -> None:
    """The old stripper was written for French and damaged everything else.

    Decomposing a Hangul syllable and dropping the non-base characters leaves
    loose jamo; doing the same to Devanagari or Arabic removes the vowel signs
    and changes the word.
    """
    from tilauscope.label_printer import _brew_clean

    assert _brew_clean(sample) == unicodedata.normalize('NFC', sample)
