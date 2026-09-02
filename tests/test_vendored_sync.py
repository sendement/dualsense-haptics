"""Guard against drift between the root modules and the copies vendored into
deck-plugin/py_modules/ (the Decky plugin ships its own copy of the shared
engine - see README's Steam Deck section).

Five of the six are documented as vendored *unchanged*, so they must stay
byte-identical. i18n.py is the deliberate exception - the Deck copy drops
desktop-only strings - so for it the rule is: a strict subset of the desktop
keys, with every shared string identical, in the same set of languages."""
from pathlib import Path

import pytest

import i18n as desktop_i18n

REPO_ROOT = Path(__file__).resolve().parent.parent
PY_MODULES = REPO_ROOT / "deck-plugin" / "py_modules"

VENDORED_UNCHANGED = [
    "bt_hid_proxy.py",
    "config.py",
    "haptics_engine.py",
    "presets.py",
    "triggers.py",
]


@pytest.mark.parametrize("name", VENDORED_UNCHANGED)
def test_vendored_module_is_byte_identical(name):
    root = (REPO_ROOT / name).read_bytes()
    vendored = (PY_MODULES / name).read_bytes()
    assert root == vendored, (
        f"{name} differs between the repo root and deck-plugin/py_modules/ - "
        f"these are documented as vendored unchanged; copy the updated file over"
    )


def _load_deck_i18n():
    """Execute the Deck copy in its own namespace (importing it would clash
    with the desktop i18n module already loaded under the same name)."""
    source = (PY_MODULES / "i18n.py").read_text(encoding="utf-8")
    namespace = {}
    exec(compile(source, str(PY_MODULES / "i18n.py"), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def deck():
    return _load_deck_i18n()


class TestDeckI18n:
    def test_same_language_set_as_desktop(self, deck):
        assert sorted(deck["STRINGS"]) == sorted(desktop_i18n.STRINGS)
        assert deck["LANGUAGES"] == desktop_i18n.LANGUAGES

    @pytest.mark.parametrize("lang", sorted(desktop_i18n.STRINGS))
    def test_keys_are_a_subset_of_desktop(self, deck, lang):
        extra = set(deck["STRINGS"][lang]) - set(desktop_i18n.STRINGS[lang])
        assert extra == set(), f"deck i18n[{lang}] has keys the desktop table lacks"

    @pytest.mark.parametrize("lang", sorted(desktop_i18n.STRINGS))
    def test_shared_strings_are_identical(self, deck, lang):
        desktop = desktop_i18n.STRINGS[lang]
        diverged = [
            key for key, value in deck["STRINGS"][lang].items()
            if key in desktop and value != desktop[key]
        ]
        assert diverged == [], (
            f"deck i18n[{lang}] diverged from desktop for these keys - "
            f"update both copies together"
        )

    def test_every_language_trims_the_same_keys(self, deck):
        # the Deck copy drops desktop-only strings; whatever it drops, it
        # must drop consistently in all 9 languages
        trimmed_per_lang = {
            lang: frozenset(set(desktop_i18n.STRINGS[lang]) - set(deck["STRINGS"][lang]))
            for lang in desktop_i18n.STRINGS
        }
        assert len(set(trimmed_per_lang.values())) == 1, trimmed_per_lang
