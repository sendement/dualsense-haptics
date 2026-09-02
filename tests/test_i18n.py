"""Tests for the translation tables and the I18n manager.

The desktop table currently has full parity: every language carries exactly
the English key set, with matching format placeholders. These tests freeze
that property, so adding a string to one language and forgetting the other
eight fails CI instead of silently falling back to English at runtime."""
import string

import pytest

import i18n
from i18n import LANGUAGES, STRINGS, I18n, detect_system_language

EN_KEYS = set(STRINGS["en"])
NON_ENGLISH = sorted(set(STRINGS) - {"en"})


def _format_fields(s):
    return {field for _, field, _, _ in string.Formatter().parse(s) if field is not None}


class TestTableIntegrity:
    def test_language_list_matches_string_tables(self):
        assert sorted(code for code, _ in LANGUAGES) == sorted(STRINGS)

    def test_english_is_the_reference_language(self):
        assert "en" in STRINGS and EN_KEYS

    @pytest.mark.parametrize("lang", NON_ENGLISH)
    def test_full_key_parity_with_english(self, lang):
        keys = set(STRINGS[lang])
        assert keys - EN_KEYS == set(), f"{lang} has keys English lacks (dead strings)"
        assert EN_KEYS - keys == set(), f"{lang} is missing translations"

    @pytest.mark.parametrize("lang", sorted(STRINGS))
    def test_no_empty_strings(self, lang):
        # I18n.t()'s `or`-fallback treats "" as missing, so an empty
        # translation would silently show English - keep them out entirely
        empty = [k for k, v in STRINGS[lang].items() if not isinstance(v, str) or not v]
        assert empty == []

    @pytest.mark.parametrize("lang", NON_ENGLISH)
    def test_format_placeholders_match_english(self, lang):
        mismatched = [
            key for key, value in STRINGS[lang].items()
            if key in STRINGS["en"] and _format_fields(value) != _format_fields(STRINGS["en"][key])
        ]
        assert mismatched == [], f"{lang}: placeholder sets diverge from English"


class TestI18nManager:
    def test_unknown_language_falls_back_to_english(self):
        assert I18n("tlh").lang == "en"

    def test_translates_in_selected_language(self):
        mgr = I18n("ru")
        assert mgr.t("nav_home") == STRINGS["ru"]["nav_home"]

    def test_unknown_key_returns_the_key_itself(self):
        assert I18n("en").t("no_such_key_ever") == "no_such_key_ever"

    def test_kwargs_are_formatted_in(self):
        msg = I18n("en").t("status_error", msg="boom")
        assert "boom" in msg

    def test_set_language_emits_changed(self):
        mgr = I18n("en")
        fired = []
        mgr.changed.connect(lambda: fired.append(True))
        mgr.set_language("ru")
        assert mgr.lang == "ru"
        assert fired == [True]

    def test_set_language_ignores_unknown_and_noop_changes(self):
        mgr = I18n("en")
        fired = []
        mgr.changed.connect(lambda: fired.append(True))
        mgr.set_language("tlh")
        mgr.set_language("en")
        assert mgr.lang == "en"
        assert fired == []


class TestDetectSystemLanguage:
    def _locale(self, name):
        class FakeLocale:
            @staticmethod
            def system():
                class L:
                    @staticmethod
                    def name():
                        return name
                return L()
        return FakeLocale

    def test_known_locale_maps_to_language_code(self, monkeypatch):
        monkeypatch.setattr(i18n, "QLocale", self._locale("ru_RU"))
        assert detect_system_language() == "ru"

    def test_unknown_locale_falls_back_to_english(self, monkeypatch):
        monkeypatch.setattr(i18n, "QLocale", self._locale("tlh_QO"))
        assert detect_system_language() == "en"
