# How to provide or improve translations

____
**Important: TilauScope is licensed under the [GNU Affero General Public License v3 or later](https://www.gnu.org/licenses/agpl-3.0.html), and the code inherited from Artisan keeps its original [GPL](https://www.gnu.org/licenses/gpl-3.0.html) terms. Copies of TilauScope and derivative works are subject to these licenses. Be sure to review them to understand your legal obligations and please respect them.**
____

### Two interfaces, two projects

TilauScope's screens come from two places, and each is translated separately.

| What you see | Who translates it | How |
|---|---|---|
| **The TilauScope interface** — bean cave, roast assistant, roast plan, bags and stock, brewing guide, phone remote… (~2900 phrases) | TilauScope users, with the **TilauScope Translator** app | this page |
| **The Artisan core** — the roasting scope itself, its menus, its device dialogs | the Artisan project | [Artisan's own guide](https://github.com/artisan-roaster-scope/artisan/blob/master/wiki/HowToImproveTranslations.md) |

Work sent to TilauScope for the Artisan contexts cannot be kept: those files are
re-imported wholesale from upstream at every sync, and the contribution would be
destroyed. Send it to the Artisan project instead, where it will live.

### The TilauScope Translator

A small standalone application for macOS and Windows. You do **not** need
TilauScope installed, a GitHub account, or any developer tooling. It never
uploads anything: it only downloads the current strings, and you decide what to
do with the file it produces.

Its own interface is in English.

#### 1. Download it

From the [releases page of the public repository](https://github.com/neuralldev/tilauscope_fork/releases),
look for the entry named **TilauScope Translator** — currently
[version 1.0.0](https://github.com/neuralldev/tilauscope_fork/releases/tag/translator-v1.0.0).

- **macOS** — `TilauScopeTranslator-<version>.dmg`, signed and notarized.
- **Windows** — `TilauScopeTranslator-<version>-windows.zip`, a single portable
  `.exe`. It is **not** code-signed, so SmartScreen will show *"Windows
  protected your PC"*: choose *More info*, then *Run anyway*. A `.sha256` file
  is published next to each download if you want to verify it.

#### 2. Choose a language

The first screen lists every language TilauScope ships, with how much of it is
already done. Pick yours and open it.

If your language is not there, use **Start a new language…**: give the
[ISO 639-1](https://en.wikipedia.org/wiki/ISO_639-1) code and the name of the
language as it is written in that language, and you start from an empty file.

#### 3. Translate, or review

The editor shows the English phrase and your language side by side, grouped into
sections that match the parts of the application — *Bean cave*, *Roast
assistant*, *Alarms*, and so on. Each phrase is in one of three states:

- **to translate** — nothing written yet;
- **to review** — a translation exists but nobody has confirmed it;
- **done** — confirmed.

**Reviewing is real work, and often the most useful.** German, Spanish, Italian
and both Chinese variants were machine-translated to give those users a usable
interface quickly; not one phrase has been read by a native speaker. Accepting a
correct phrase is one keystroke, and correcting a wrong one takes a few seconds.

The panel below the table shows what you are translating, where it appears in
the application, and a note when the phrase needs one. A phrase containing a
placeholder such as `%1` is replaced at runtime — by a temperature, a bean name,
a number of seconds — so **keep every placeholder in your translation**. The
editor warns you if one goes missing.

Your work is saved as you go. You can close the application and pick up where
you left off; there is no need to finish a language in one sitting, or at all.

#### 4. Export and send

**Finish and export…** asks for the name you want to be credited under
(optional), lets you leave a note for the maintainer, and saves a small `.zip`
file wherever you choose. Send that zip, whole and unopened, by whatever channel
suits you:

- open an [issue](https://github.com/neuralldev/tilauscope_fork/issues) or a
  [discussion](https://github.com/neuralldev/tilauscope_fork/discussions) on
  GitHub and drag the file into the comment field, or
- e-mail it to the maintainer.

The zip carries only the phrases you changed, keyed one by one. That is what
lets a contribution started months ago still apply cleanly: it is merged onto
whatever the current file is, so phrases added, removed or reworded in the
meantime sort themselves out instead of an old file overwriting a newer one.
Nothing you send expires.

Your work is integrated and ships with the next build. Contributors are credited
in [Translators.md](Translators.md) and in the release notes, under the name you
gave — or anonymously, if you gave none.

Thanks for your contributions!
