import json
import re
import unittest

from meta_sonata.web import (
    LOCALIZATION_DIR,
    SUPPORTED_LOCALES,
    localized_messages,
    resolve_locale,
)


PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


class LocalizationTest(unittest.TestCase):
    def test_all_nine_locales_are_present_and_complete(self):
        self.assertEqual(
            SUPPORTED_LOCALES,
            ("en", "zh-Hans", "zh-Hant", "ja", "ko", "fr", "de", "es", "pt-BR"),
        )
        english = json.loads((LOCALIZATION_DIR / "en.json").read_text(encoding="utf-8"))
        self.assertGreater(len(english), 100)

        for locale in SUPPORTED_LOCALES:
            messages = json.loads(
                (LOCALIZATION_DIR / f"{locale}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(messages), set(english), locale)
            self.assertTrue(all(value.strip() for value in messages.values()), locale)
            for key, source in english.items():
                self.assertEqual(
                    set(PLACEHOLDER.findall(messages[key])),
                    set(PLACEHOLDER.findall(source)),
                    f"{locale}:{key}",
                )

    def test_locale_resolution_handles_regions_and_scripts(self):
        cases = {
            "zh-CN": "zh-Hans",
            "zh-SG": "zh-Hans",
            "zh-Hant": "zh-Hant",
            "zh-TW": "zh-Hant",
            "zh-HK": "zh-Hant",
            "en-GB": "en",
            "fr-CA": "fr",
            "de-AT": "de",
            "es-MX": "es",
            "pt-PT": "pt-BR",
            "unknown": "en",
        }
        for requested, expected in cases.items():
            self.assertEqual(resolve_locale(requested), expected)

    def test_localized_messages_fall_back_to_english(self):
        self.assertEqual(localized_messages("unknown")["panel.input"], "Input")
        self.assertEqual(localized_messages("ja")["panel.input"], "入力")


if __name__ == "__main__":
    unittest.main()
