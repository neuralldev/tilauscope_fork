# Labels and QR

!!! abstract "Artisan does / TilauScope adds"
    **Artisan does** — nothing here. Artisan has no concept of a printed label or a
    scannable record.

    **TilauScope adds** — printed labels for a roast, a coffee or a storage sack, each
    carrying a QR code, and two ways to scan one back open: a webcam in BeanCave, or a
    phone's own camera.

Labels are covered here as **objects that get printed and scanned**. What a sack label
tracks — the pool of ids, assigning and releasing one — is covered in
[Sacks, stock and conservation](sacks-and-storage.md).

---

## What each label carries

| Label | Printed from | What it shows | Its QR opens |
|---|---|---|---|
| **Roast label** | A roast's record → **Print label** | Bean, origin, roast date, key roast figures, flavour notes, a QR | The roast's record |
| **Green bean label** | A coffee's record → **Print label** | Supplier, crop, process, altitude, density, cupping notes, a QR | The coffee's record |
| **Sack label** | The sack labels tool (see [Sacks, stock and conservation](sacks-and-storage.md)) | A label id and a QR — nothing else | Whichever coffee currently holds that id |

Roast and bean labels print as a PDF, sized to a full page with cut guides, so they can be
printed on any printer and trimmed by hand. Sack labels print directly to a Niimbot thermal
printer, sized for its 50×30 mm roll.

<!-- CAPTURE 4.1 — a printed roast label PDF, full page with cut guides visible.
CAPTURE 4.2 — a printed green bean label PDF. CAPTURE 4.3 — a sack label, actual size,
QR and id both legible. -->

---

## Printing on the Niimbot

Roast labels can also print directly to a paired Niimbot thermal printer, in two sizes: a
full spec sheet on an 80 mm roll, or a condensed card on a 30 mm roll (small enough that the
QR is dropped — there is no room to make it useful at that size). Sack labels always use the
30 mm roll.

**🖨 Print label** opens a preview with a copies count, then prints in the background —
a status strip tracks progress without blocking the rest of the window. Printing is refused,
with a plain explanation rather than a silent failure, when the roll is out of labels, when
the loaded paper isn't recognised, or when it doesn't match the size the label needs.

!!! info "Hardware — Niimbot B21S"
    Printing needs a paired Niimbot B21S. The printer identifies its own paper roll
    automatically; recognising a roll it has never seen needs an internet connection the
    first time, after which that roll size is remembered.

<!-- CAPTURE 4.4 — the print preview with the copies count. CAPTURE 4.5 — the background
print progress strip. CAPTURE 4.6 — a print blocked with a plain-language reason (wrong
paper size). -->

---

## Scanning a label

A printed label can be opened back up two ways.

**From BeanCave, with a webcam.** **📷 SCAN** opens a live camera preview; holding a label
up to it decodes the QR and opens straight to what it points to — the roast card, or the
coffee's record. The camera runs only while this window is open, and stops the moment it
closes.

**From a phone, with its own camera app.** No app or pairing is needed: the label's QR is a
plain web address. Opening it on a phone already on the same network as TilauScope shows the
same record — bean details, or a roast's curve, figures and tasting notes — as a page in the
phone's browser.

!!! note
    The phone needs to be on the same local network as the computer running TilauScope.
    Off that network, the page simply doesn't load — there is no remote access built into
    this feature.

A sack label works the same way as the other two: scanning it, from either path, opens
whichever coffee currently holds that label. A label not currently attached to any coffee
says so plainly rather than opening a blank or wrong record.

<!-- CAPTURE 4.7 — the 📷 SCAN camera preview, mid-scan. CAPTURE 4.8 — a roast record page
open in a phone's browser. CAPTURE 4.9 — a bean record page open in a phone's browser. -->

---

## Next

- What a sack label tracks, and managing the pool of ids: see
  [Sacks, stock and conservation](sacks-and-storage.md).
- The coffee records these labels point to: see [BeanCave](beancave.md).
- Any unfamiliar term: see the [Glossary](glossary.md).
