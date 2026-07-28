# The project file for the Tilauscope application.
# based on Artisan Roaster Scope Fork

# not sure if the following is strictly needed (might be needed for accent characters in source of translations)
CODECFORSRC = UTF-8
CODECFORTR = UTF-8

# Note: pylupdate6pro.py only uses these entries to derive their parent directory
# (it passes whole directories to pylupdate6), so a single glob per directory is enough
# and new files added under these directories don't require editing this list.
SOURCES = \
    artisanlib/*.py \
    help/*.py \
    plus/*.py \
    tilauscope/*.py

# the list of translation has to be synced with the script pylupdate6pro (for pylupdate6)
TRANSLATIONS = \
	translations/artisan_ar.ts \
    translations/artisan_bg.ts \
    translations/artisan_cs.ts \
	translations/artisan_da.ts \
	translations/artisan_de.ts \
	translations/artisan_el.ts \
	translations/artisan_es.ts \
	translations/artisan_fa.ts \
	translations/artisan_fi.ts \
	translations/artisan_fr.ts \
	translations/artisan_gd.ts \
	translations/artisan_he.ts \
	translations/artisan_hu.ts \
	translations/artisan_id.ts \
	translations/artisan_it.ts \
	translations/artisan_ja.ts \
	translations/artisan_ko.ts \
	translations/artisan_lv.ts \
	translations/artisan_nl.ts \
	translations/artisan_no.ts \
	translations/artisan_pl.ts \
	translations/artisan_pt_BR.ts \
	translations/artisan_pt.ts \
	translations/artisan_ru.ts \
	translations/artisan_sk.ts \
	translations/artisan_sv.ts \
	translations/artisan_th.ts \
	translations/artisan_tr.ts \
	translations/artisan_uk.ts \
	translations/artisan_vi.ts \
	translations/artisan_zh_CN.ts \
	translations/artisan_zh_TW.ts