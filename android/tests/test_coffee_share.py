# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A coffee in one file on the tablet: opened from a .tilaucoffee, browsed in the library, sent to the computer."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
import zipfile

from tilaucore import coffee_share as core, tasting_log
from tilaucore.archive import ArchiveError
from tilaucore.beans import BrewSample, GreenBean, RoastTasting
from tilaucore.coffee_library import PAGE_SIZE, Card, LibraryError, card_to_json, machine_key, search_key
from tilauscope_mobile import alog, coffee_share, config
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.session import Session

UUID = "94ee0778-f239-4457-91d6-d33153c17e6f"
THEIRS = "b" * 8 + "-1111-2222-3333-" + "c" * 12
OWN = "a" * 32
RELAY = "https://relay.test"


def roast(roast_uuid: str, bean_uuid: str = UUID, **more) -> dict:
    return {"roastUUID": roast_uuid, "roastepoch": 1791709165, "roastisodate": "2026-11-12", "title": "Catuai - Washed - 2024", "mode": "C",
            "roastertype": "Skywalker V2", "beans": f"Catuai\nuuid: {bean_uuid}", "weight": [300.0, 258.0, "g"],
            "timex": [0.0, 60.0, 238.0, 417.0, 478.0], "temp2": [175.6, 109.0, 150.0, 182.0, 190.4],
            "temp1": [200.0, 160.0, 170.0, 195.0, 205.0], "timeindex": [0, 2, 3, 0, 0, 0, 4, 0],
            "computed": {"DROP_time": 478.0, "FCs_time": 417.0, "DROP_BT": 190.4, "FCs_BT": 182.0}, **more}


ARMED = {"alarmflag": [1, 1], "alarmtime": [0, 5], "alarmtemperature": [0, 0], "alarmaction": [8, 1], "alarmstrings": ["rm -rf ~", "x"],
         "externalprogram": "/bin/evil", "externaloutprogram": "/bin/evil2", "alarmsets": [[1]]}


def bean(**more) -> GreenBean:
    return GreenBean(**{"name": "Catuai", "country": "Honduras", "process": "Washed", "crop": 2024,
                        "flavour_notes": "Fruits rouges, Chocolat", "uuid": UUID, **more})


def write(path: Path, mode: str = core.SHARE, roasts=(), tastings=None, brews=(), version="4.3", build=59, record=None, files=None) -> Path:
    """A package as the desktop writes it, its roast files made here; `files`: roast dicts by name."""
    sources = []
    for index, profile in enumerate(roasts):
        source = path.parent / f"source-{index}.alog"
        source.write_text(repr(profile), encoding="utf-8")
        sources.append(source)
    core.write_package(path, mode=mode, bean=record or bean(), roasts=sources, tastings=tastings or {}, brews=brews,
                       version=version, build=build, clean=(lambda t: t) if mode == core.SHARE else None)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.files = self.dir / "files"
        self.files.mkdir()
        self.demo = Demo(str(self.files / "session.journal"), str(self.files / "config.json"), str(self.files / "beancave"))
        self.inbox = self.dir / "inbox"
        self.inbox.mkdir()

    def package(self, name="catuai.tilaucoffee", **kwargs) -> str:
        return str(write(self.inbox / name, **kwargs))

    def tree(self) -> set[str]:
        return {p.relative_to(self.files).as_posix() for p in self.files.rglob("*") if p.is_file()}

    def shared_files(self) -> list[Path]:
        return sorted((self.files / "roasts-shared").glob("*.alog"))


class PackagingTests(unittest.TestCase):
    """Chaquopy packages `tilauscope_mobile/**` and `tilaucore/**` of src: every import of the coffee modules must land there."""

    def test_the_coffee_modules_import_only_what_the_apk_carries(self):
        root = Path(__file__).resolve().parents[2]
        build = (root / "android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn('"tilaucore/**"', build)
        seen, todo, outside = set(), ["tilaucore.coffee_library", "tilaucore.coffee_share", "tilaucore.archive", "tilaucore.tasting_log"], set()
        while todo:
            module = todo.pop()
            if module in seen:
                continue
            seen.add(module)
            path = root / "src" / (module.replace(".", "/") + ".py")
            self.assertTrue(path.is_file(), f"{module} is not a module of src/tilaucore")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module, *(f"{node.module}.{a.name}" for a in node.names)] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
                for name in names:
                    if name.split(".")[0] == "tilaucore":
                        if (root / "src" / (name.replace(".", "/") + ".py")).is_file():
                            todo.append(name)
                    elif name.split(".")[0] not in sys.stdlib_module_names:
                        outside.add((module, name))
        self.assertEqual(outside, set(), "a module the tablet cannot import")
        self.assertTrue({"tilaucore.coffee_library", "tilaucore.coffee_share", "tilaucore.archive"} <= seen)


class ImportTests(Base):
    def test_a_shared_package_comes_into_an_empty_cave(self):
        path = self.package(roasts=[roast(THEIRS, **ARMED)], tastings={THEIRS: RoastTasting(bean_uuid=UUID, verdict="yes", notes="sweet")})
        reply = json.loads(self.demo.coffee_import(path))
        self.assertEqual((reply["imported"], reply["name"]), (UUID, "Catuai"))
        coffee = next(c for c in reply["coffees"] if c["uuid"] == UUID)
        self.assertEqual((coffee["stock_g"], coffee["shared"]), (0, True)) # it arrives without stock, marked shared
        self.assertEqual(self.demo.cave.state()["tastings"], 1)
        (file,) = self.shared_files()
        written = ast.literal_eval(file.read_text(encoding="utf-8"))
        self.assertTrue(written["tilau_exclude_learning"])
        self.assertEqual(written["tilau_shared"]["roaster"], "Skywalker V2")

    def test_alarms_and_programs_are_gone_from_the_written_roast(self):
        # A package written by anything: the arming is removed again on arrival, not only by the sender
        hostile = roast(THEIRS, **ARMED)
        path = self.dir / "armed.tilaucoffee"
        write(path, roasts=[hostile])
        with zipfile.ZipFile(path) as archive: # put the arming back past the sender's own disarm
            members = {n: archive.read(n) for n in archive.namelist()}
        name = next(n for n in members if n.startswith("roasts/"))
        members[name] = repr(hostile).encode()
        manifest = json.loads(members["manifest.json"])
        manifest["files"][name] = core._digest(members[name])
        members["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for n, data in members.items():
                archive.writestr(n, data)
        self.demo.coffee_import(str(path))
        written = ast.literal_eval(self.shared_files()[0].read_text(encoding="utf-8"))
        self.assertEqual([k for k in written if k.startswith("alarm")], [])
        self.assertEqual((written["externalprogram"], written["externaloutprogram"]), ("", ""))

    def test_a_coffee_already_held_is_never_replaced_and_only_what_is_missing_comes(self):
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "My own Catuai", "uuid": UUID.upper(), "weight_left": 1200.0}]}), "beancave.json")
        self.demo.roasts.store("tablet", "mine.alog", roast(OWN))
        before = self.demo.cave.path.read_bytes()
        tasting_log.record(str(self.demo.cave.directory), THEIRS, RoastTasting(bean_uuid=UUID, verdict="no", notes="mine"))
        path = self.package(roasts=[roast(OWN), roast(THEIRS)], tastings={THEIRS: RoastTasting(bean_uuid=UUID, verdict="yes"),
                                                                           "d" * 32: RoastTasting(bean_uuid=UUID, verdict="almost")})
        reply = json.loads(self.demo.coffee_import(path))
        self.assertEqual(self.demo.cave.path.read_bytes(), before) # the record, its stock and its name are untouched
        self.assertEqual(len(reply["coffees"]), 1)
        self.assertEqual([p.name for p in (self.files / "roasts").iterdir()], ["mine.alog"]) # the roast held is not written again
        self.assertEqual(len(self.shared_files()), 1) # THEIRS only
        kept = tasting_log.load(self.demo.cave.directory).entries
        self.assertEqual((kept[THEIRS].verdict, kept[THEIRS].notes), ("no", "mine")) # a tasting held is kept
        self.assertEqual(kept["d" * 32].verdict, "almost") # one lacking comes

    def test_importing_twice_changes_nothing(self):
        path = self.package(roasts=[roast(THEIRS)])
        self.demo.coffee_import(path)
        first = {n: (self.files / n).read_bytes() for n in self.tree() if n.endswith((".alog", "beancave.json"))}
        self.assertEqual(json.loads(self.demo.coffee_import(path))["imported"], UUID)
        self.assertEqual({n: (self.files / n).read_bytes() for n in first}, first)

    def test_a_hostile_roast_id_and_date_still_land_in_the_roast_folder(self):
        hostile = roast("../../../evil/" + "e" * 40, roastisodate="../../../x/2026-11-12")
        path = self.package(roasts=[hostile], record=bean(name="../../Catuai/../" + "n" * 300))
        self.demo.coffee_import(path)
        (file,) = self.shared_files()
        self.assertEqual(file.parent, self.files / "roasts-shared")
        self.assertLessEqual(len(file.name), 255)
        written = [p for p in self.dir.rglob("*") if p.is_file() and not p.is_relative_to(self.inbox)]
        self.assertEqual([p for p in written if p.suffix == ".alog"], [file]) # no roast anywhere else
        self.assertEqual([p for p in written if not p.is_relative_to(self.files)], []) # nothing outside the app's folder

    def test_damaged_and_newer_packages_are_refused_and_change_nothing(self):
        (self.inbox / "bad.tilaucoffee").write_bytes(b"PK not a zip")
        newer_version = self.package("newer.tilaucoffee", version="9.0", build=1, roasts=[roast(THEIRS)])
        with zipfile.ZipFile(self.package("format.tilaucoffee", roasts=[roast(THEIRS)])) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        manifest = json.loads(members["manifest.json"])
        manifest["format"] = 2
        members["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.inbox / "format.tilaucoffee", "w") as archive:
            for n, data in members.items():
                archive.writestr(n, data)
        torn = self.package("torn.tilaucoffee", roasts=[roast(THEIRS)])
        with zipfile.ZipFile(torn) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        members["bean.json"] = b'{"name": "changed after the checksum"}'
        with zipfile.ZipFile(torn, "w") as archive:
            for n, data in members.items():
                archive.writestr(n, data)
        for name, state in (("bad.tilaucoffee", "damaged"), ("torn.tilaucoffee", "damaged"), ("newer.tilaucoffee", "newer"), ("format.tilaucoffee", "newer")):
            self.assertEqual(json.loads(self.demo.coffee_preview(str(self.inbox / name))), {"state": state}, name)
            with self.assertRaises(ArchiveError):
                self.demo.coffee_import(str(self.inbox / name))
        self.assertFalse(self.demo.cave.path.exists()) # nothing written: no cave, no roast, no tasting
        self.assertFalse((self.files / "roasts-shared").exists())

    def test_a_package_of_the_same_tilauscope_version_and_any_build_is_read(self):
        self.assertEqual(json.loads(self.demo.coffee_preview(self.package(build=400)))["state"], "ok")

    def test_the_version_the_tablet_reads_is_the_one_its_roasts_say(self):
        written = alog.profile(Session(), levers={})
        self.assertEqual((written["version"], written["recording_version"]), (coffee_share.VERSION,) * 2)


class PreviewTests(Base):
    def test_the_preview_says_what_comes(self):
        path = self.package(roasts=[roast(THEIRS)], tastings={THEIRS: RoastTasting(bean_uuid=UUID, verdict="yes")},
                            record=bean())
        self.demo.save_setup(json.dumps({**config.default(), "machine": "skywalker-v2"}))
        view = json.loads(self.demo.coffee_preview(path))
        self.assertEqual((view["state"], view["mode"], view["owner"], view["existing"]), ("ok", "share", "tablet", False))
        self.assertEqual((view["roasts"], view["new_roasts"], view["tastings"]), (1, 1, 1))
        card = view["card"]
        self.assertEqual((card["batch_g"], card["total_s"], card["after_fc_s"], card["drop_c"], card["same_machine"]), (300, 478, 61, 190, True))
        self.assertFalse(self.files.joinpath("roasts-shared").exists()) # looking changes nothing

    def test_another_machine_is_not_like_yours(self):
        self.demo.save_setup(json.dumps({**config.default(), "machine": "skywalker-v1"}))
        self.assertFalse(json.loads(self.demo.coffee_preview(self.package(roasts=[roast(THEIRS)])))["card"]["same_machine"])

    def test_the_computer_owning_the_cave_is_told_and_the_import_is_local(self):
        self.demo.save_setup(json.dumps({**config.default(), "cave_owner": "computer"}))
        path = self.package(roasts=[roast(THEIRS)])
        self.assertEqual(json.loads(self.demo.coffee_preview(path))["owner"], "computer")
        reply = json.loads(self.demo.coffee_import(path))
        self.assertFalse(reply["editable"]) # still the computer's cave; nothing else was asked of it
        self.assertEqual(reply["imported"], UUID)
        self.assertEqual({n for n in self.tree() if not n.startswith("alog_index")} - {"config.json"},
                         {"beancave/beancave.json", "beancave/beancave.note.json"} | {f"roasts-shared/{p.name}" for p in self.shared_files()})


class SharedRoastTests(Base):
    def test_a_shared_roast_is_never_one_of_the_tablets_own(self):
        self.demo.roasts.store("tablet", "mine.alog", roast(OWN))
        self.demo.coffee_import(self.package(roasts=[roast(THEIRS)]))
        rows = {r["origin"]: r for r in json.loads(self.demo.get_roasts())["roasts"]}
        self.assertEqual(set(rows), {"tablet", "shared"})
        self.assertTrue(rows["shared"]["excluded"]) # outside learning
        self.assertEqual([p.name for p in (self.files / "roasts").iterdir()], ["mine.alog"]) # what the tablet sends as its own
        records = {origin: meta for origin, meta in self.demo.roasts.records()}
        self.assertTrue(records["shared"].shared and records["shared"].exclude_learning)
        coffee = json.loads(self.demo.get_coffees())["coffees"][0]
        self.assertEqual(coffee["memory"]["count"], 1) # counted: the tablet's own roast only, never the shared one

    def test_a_coffee_with_only_a_shared_roast_is_not_roasted_yet(self):
        self.demo.coffee_import(self.package(roasts=[roast(THEIRS)]))
        self.assertIsNone(json.loads(self.demo.get_coffees())["coffees"][0]["memory"])

    def test_the_coffees_sheet_gets_their_roast(self):
        self.demo.coffee_import(self.package(roasts=[roast(THEIRS)]))
        theirs = json.loads(self.demo.coffee_theirs(UUID))
        self.assertEqual((theirs["card"]["total_s"], theirs["shared_on"][:4]), (478, "2026"))
        self.assertEqual(json.loads(self.demo.coffee_theirs("nobody")), {"uuid": "nobody", "card": None, "shared_on": ""})

    def test_a_shared_roast_can_be_followed_as_the_reference_curve(self):
        # The existing mechanism (set_follow, and the coffee's reference ★) takes a roast of any folder
        from test_automation import PROFILE
        theirs = {**PROFILE, "roastUUID": THEIRS, "beans": f"Catuai\nuuid: {UUID}", "title": "Catuai", "tilau_exclude_learning": True,
                  "tilau_shared": {"shared_on": "2026-11-12", "roaster": "Skywalker V2"}}
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "Catuai", "uuid": UUID, "reference_roast_uuid": THEIRS}]}), "x")
        self.demo.roasts.store("shared", "theirs.alog", theirs)
        plan = json.loads(self.demo.set_follow(json.dumps({"origin": "shared", "name": "theirs.alog"})))
        self.assertEqual(plan["follow"]["roast"]["origin"], "shared")
        self.demo._follow_pick = None # and by the coffee's ★, once the coffee is chosen
        self.demo.choose_coffee(UUID)
        self.assertEqual(self.demo._follow_source(), ("shared", "theirs.alog"))


class SendTests(Base):
    def test_a_move_package_reads_back_with_the_tablets_roasts(self):
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "Catuai", "uuid": UUID, "weight_left": 900.0, "reference_roast_uuid": THEIRS}]}), "x")
        self.demo.roasts.store("tablet", "mine.alog", roast(OWN))
        self.demo.roasts.store("tablet", "simulated.alog", roast("5" * 32, tilau_simulated=True))
        self.demo.roasts.store("computer", "fromcomputer.alog", roast("6" * 32))
        self.demo.roasts.store("shared", "theirs.alog", roast(THEIRS, tilau_shared={"shared_on": "x"}, tilau_exclude_learning=True))
        self.demo.roasts.store("tablet", "other.alog", roast("7" * 32, bean_uuid="another-coffee"))
        tasting_log.record(str(self.demo.cave.directory), OWN, RoastTasting(bean_uuid=UUID, verdict="yes"))
        tasting_log.record(str(self.demo.cave.directory), "7" * 32, RoastTasting(bean_uuid="another-coffee", verdict="no"))
        self.demo.cave.add_brews(UUID, [BrewSample(method_id="v60", iso_date="2026-11-01", dose_g=15.0)])
        out = Path(self.demo.coffee_send(UUID, str(self.dir / "cache" / "coffee-share")))
        self.assertEqual(out.suffix, ".tilaucoffee")
        package = core.read_package(out, version="4.3", build=59) # the desktop's own reader, at the desktop's own version
        self.assertEqual(package.mode, core.MOVE)
        self.assertEqual(set(package.roasts), {OWN, THEIRS}) # its own, and the shared reference; not the simulated, the computer's or another coffee's
        self.assertEqual(set(package.tastings), {OWN})
        self.assertEqual((package.bean.weight_left, package.bean.reference_roast_uuid), (900.0, THEIRS))
        self.assertEqual([b.method_id for b in package.brews], ["v60"])
        self.assertTrue(package.roasts[THEIRS]["tilau_shared"]) # still marked shared on the computer
        self.assertFalse((self.files / "roasts-computer" / out.name).exists())

    def test_only_the_last_package_is_kept(self):
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "Catuai", "uuid": UUID}, {"name": "Huila", "uuid": "h-1"}]}), "x")
        folder = self.dir / "cache" / "coffee-share"
        self.demo.coffee_send(UUID, str(folder))
        self.demo.coffee_send("h-1", str(folder))
        self.assertEqual([p.name for p in folder.iterdir()], ["Huila.tilaucoffee"])

    def test_an_unknown_coffee_is_refused(self):
        self.demo.cave.replace(json.dumps({"green_beans": []}), "x")
        with self.assertRaises(ValueError):
            self.demo.coffee_send(UUID, str(self.dir / "cache"))


def card(name="Catuai", roaster="Skywalker V2", **more) -> dict:
    base = Card(name=name, country="Honduras", process="Washed", crop=2024, roaster=roaster, batch_g=300, total_s=596, after_fc_s=102,
                drop_c=189, flavours=("Fruits rouges",), verdict="yes", curve=((0, 185.7), (300, 150.0), (596, 188.6)))
    return {**card_to_json(base), "id": "0" * 31 + "1", "published": "2026-11-12", **more}


class Relay:
    """A fake relay: the core's own `fetch` hook, nothing on the network."""

    def __init__(self, rows=(), packages=None, error=None, next="", total=None, status=200, body=None):
        self.rows, self.packages, self.error, self.calls = list(rows), packages or {}, error, []
        self.next, self.total, self.status, self.body = next, total, status, body

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if self.error:
            raise LibraryError(self.error)
        where = urlsplit(url)
        if where.path == "/v1/coffees": # one page of the search, as the relay answers it: the rows given, unfiltered
            page = {"v": 1, "coffees": self.rows, "next": self.next, "total": len(self.rows) if self.total is None else self.total}
            return self.status, {}, self.body if self.body is not None else json.dumps(page).encode()
        data = self.packages.get(url.rsplit("/", 1)[1])
        return (200, {}, data) if data is not None else (404, {}, b"{}")


class LibraryTests(Base):
    def connect(self, relay: Relay) -> Relay:
        self.demo.library = coffee_share.Browser(RELAY, relay)
        return relay

    def page(self, **request):
        return json.loads(self.demo.library_page(json.dumps(request)))

    def asked(self, relay: Relay) -> dict:
        """What the last search asked the relay."""
        url = urlsplit(relay.calls[-1][1])
        return {"path": url.path, **{k: v[0] for k, v in parse_qs(url.query).items()}}

    def test_a_page_comes_with_its_cards_the_next_cursor_and_the_total(self):
        self.connect(Relay([card(), card("Barazilie", roaster="Aillio Bullet", id="0" * 31 + "2")], next="c10", total=27))
        page = self.page(seq=4)
        self.assertEqual([c["name"] for c in page["cards"]], ["Catuai", "Barazilie"])
        self.assertEqual(page["cards"][0]["curve"][0], [0, 185.7])
        self.assertEqual((page["next"], page["total"], page["seq"]), ("c10", 27, 4))

    def test_the_text_and_the_cursor_are_the_relays_to_search_nothing_is_filtered_here(self):
        relay = self.connect(Relay([card(), card("Barazilie", country="Brazil", id="0" * 31 + "2")]))
        page = self.page(text="CATUAI honduras", cursor="c10", mine=False)
        self.assertEqual(len(page["cards"]), 2) # the relay's rows, as it answered them
        asked = self.asked(relay)
        self.assertEqual((asked["path"], asked["q"], asked["cursor"]), ("/v1/coffees", search_key("CATUAI honduras"), "c10"))
        self.assertNotIn("machine", asked)
        self.assertEqual(asked.get("limit", str(PAGE_SIZE)), str(PAGE_SIZE))

    def test_my_machine_asks_the_relay_for_the_configured_roaster_only(self):
        relay = self.connect(Relay([card(), card("Barazilie", roaster="Aillio Bullet", id="0" * 31 + "2")]))
        self.page(mine=True)
        self.assertNotIn("machine", self.asked(relay)) # no machine set: every machine
        self.demo.save_setup(json.dumps({**config.default(), "machine": "skywalker-v2"}))
        mine = self.page(mine=True)
        self.assertEqual((self.asked(relay)["machine"], mine["machine"]), (machine_key("Skywalker V2"), "Skywalker V2"))
        self.page(mine=False)
        self.assertNotIn("machine", self.asked(relay))
        self.assertEqual([(c["same_machine"], c["other_machine"], c["roaster_name"]) for c in mine["cards"]],
                         [(True, False, "Skywalker V2"), (False, True, "Aillio Bullet")])

    def test_a_row_out_of_bounds_is_left_out(self):
        self.connect(Relay([card(), card("Broken", total_s=5)]))
        self.assertEqual([c["name"] for c in self.page()["cards"]], ["Catuai"])

    def test_the_library_kinds_come_back_with_the_seq(self):
        self.connect(Relay(error="offline"))
        self.assertEqual(self.page(seq=2), {"error": "offline", "seq": 2})
        self.connect(Relay(status=500))
        self.assertEqual(self.page(seq=3), {"error": "refused", "seq": 3})
        self.connect(Relay(status=429))
        self.assertEqual(self.page()["error"], "rate")
        self.connect(Relay(body=b"not json"))
        self.assertEqual(self.page()["error"], "refused")

    def test_a_coffee_is_downloaded_to_the_cache_then_imported_like_a_file(self):
        package = Path(self.package(roasts=[roast(THEIRS, **ARMED)])).read_bytes()
        relay = self.connect(Relay([card()], {"0" * 31 + "1": package}))
        cache = self.dir / "cache" / "coffee-library"
        got = json.loads(self.demo.library_get("0" * 31 + "1", str(cache)))
        self.assertEqual(Path(got["path"]).parent, cache)
        self.assertEqual(json.loads(self.demo.coffee_preview(got["path"]))["state"], "ok")
        self.assertEqual(json.loads(self.demo.coffee_import(got["path"]))["imported"], UUID)
        self.assertEqual([k for k in ast.literal_eval(self.shared_files()[0].read_text()) if k.startswith("alarm")], [])
        self.assertEqual([c[0] for c in relay.calls], ["GET"]) # the tablet never publishes

    def test_the_library_cannot_be_reached(self):
        self.connect(Relay(error="offline"))
        self.assertEqual(json.loads(self.demo.library_get("0" * 32, str(self.dir / "c"))), {"error": "offline"})

    def test_no_relay_address_is_offline(self):
        self.demo.library = coffee_share.Browser("")
        self.assertEqual(self.page()["error"], "offline")

    def test_a_coffee_the_library_no_longer_holds(self):
        self.connect(Relay([card()]))
        self.assertEqual(json.loads(self.demo.library_get("f" * 32, str(self.dir / "c"))), {"error": "unknown"})

    def test_a_bad_id_never_builds_an_address(self):
        relay = self.connect(Relay())
        self.assertEqual(json.loads(self.demo.library_get("../../v1/index", str(self.dir / "c"))), {"error": "refused"})
        self.assertEqual(relay.calls, [])


class LibraryRoastTests(Base):
    """A selected card's roast: its package read in the cache, then drawn as the Roasts tab draws a roast of this tablet."""

    ID = "0" * 31 + "1"

    def connect(self, relay: Relay) -> Relay:
        self.demo.library = coffee_share.Browser(RELAY, relay)
        return relay

    def card(self, coffee_id=ID) -> dict:
        return json.loads(self.demo.library_card(coffee_id, str(self.cache)))

    def setUp(self):
        super().setUp()
        self.cache = self.dir / "cache" / "coffee-library-cards"
        self.good = Path(self.package(roasts=[roast(THEIRS)])).read_bytes()

    def test_the_roast_comes_as_the_roasts_tab_detail_and_its_package_is_gone(self):
        self.connect(Relay([card()], {self.ID: self.good}))
        reply = self.card()
        self.assertEqual(reply["id"], self.ID)
        detail = reply["detail"]
        local = self.demo.roasts
        local.store("shared", "x.alog", roast(THEIRS))
        mine = local.detail("shared", "x.alog")
        self.assertEqual({k: v for k, v in mine.items() if k not in ("origin", "name", "tiles")},
                         {k: v for k, v in detail.items() if k not in ("tiles", "colours")}) # the same curve, marks, points, lanes
        self.assertEqual(detail["tiles"], [t for t in mine["tiles"] if t["caption"] != "Energy"]) # their energy is not shown
        self.assertEqual(detail["marks"], {"charge": 0.0, "dry_end": 238.0, "first_crack": 417.0, "drop": 478.0})
        self.assertIn("grain", detail["colours"])
        self.assertEqual(list(self.cache.iterdir()), []) # the package went once read

    def test_the_tiles_follow_the_unit_shown(self):
        self.connect(Relay([card()], {self.ID: self.good}))
        self.demo.save_setup(json.dumps({**config.default(), "unit": "F"}))
        drop = next(t for t in self.card()["detail"]["tiles"] if t["caption"] == "Drop temperature")
        self.assertEqual(drop["value"], "375 °F")

    def test_a_roast_is_read_once_per_session(self):
        relay = self.connect(Relay([card()], {self.ID: self.good}))
        first, again = self.card(), self.card()
        self.assertEqual(first, again)
        self.assertEqual(len(relay.calls), 1)

    def test_a_failure_is_not_kept_and_the_next_selection_retries(self):
        relay = self.connect(Relay(error="offline"))
        self.assertEqual(self.card(), {"id": self.ID, "error": "offline"})
        relay.error, relay.packages = None, {self.ID: self.good}
        self.assertIn("detail", self.card())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_the_library_kinds_and_this_tablets_own_failure(self):
        self.connect(Relay([card()], {"f" * 32: self.good, "e" * 32: b"PK not a zip", "d" * 32: b"x" * (600 << 10),
                                      "c" * 32: Path(self.package("newer.tilaucoffee", version="9.0", build=1, roasts=[roast(THEIRS)])).read_bytes(),
                                      "b" * 32: Path(self.package("empty.tilaucoffee")).read_bytes()}))
        self.assertEqual(self.card("a" * 32)["error"], "unknown")         # withdrawn
        self.assertEqual(self.card("d" * 32)["error"], "too_large")       # above the library's own limit, never read
        self.assertEqual(self.card("e" * 32)["error"], "local")           # damaged
        self.assertEqual(self.card("c" * 32)["error"], "local")           # written by a newer TilauScope
        self.assertEqual(self.card("b" * 32)["error"], "local")           # without a roast
        self.assertEqual(self.card("../../v1/index")["error"], "refused")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_the_cache_cannot_be_written(self):
        self.connect(Relay([card()], {self.ID: self.good}))
        blocked = self.dir / "file"
        blocked.write_text("")
        self.assertEqual(json.loads(self.demo.library_card(self.ID, str(blocked / "cards"))), {"id": self.ID, "error": "local"})


if __name__ == "__main__":
    unittest.main()
