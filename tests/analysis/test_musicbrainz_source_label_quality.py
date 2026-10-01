from __future__ import annotations

import unittest

from scripts.review_musicbrainz_source_label_quality import (
    _family,
    _family_groups,
    _lexical_features,
    _manual_category,
    _training_rows,
)


class MusicBrainzSourceLabelQualityTests(unittest.TestCase):
    def test_family_key_groups_alias_spellings_and_subgenre_heads(self) -> None:
        self.assertEqual(_family("death thrash"), _family("death-thrash"))
        self.assertEqual(_family("progressive metal"), _family("doom metal"))
        self.assertNotEqual(_family("prairie hip hop"), _family("prairie folk"))
        labels = ["hiphop", "hip hop", "progressive hip hop", "bluegrass", "blue grass"]
        family_by_label = dict(zip(labels, _family_groups(labels), strict=True))
        self.assertEqual(family_by_label["hiphop"], family_by_label["hip hop"])
        self.assertEqual(family_by_label["hip hop"], family_by_label["progressive hip hop"])
        self.assertEqual(family_by_label["bluegrass"], family_by_label["blue grass"])

    def test_unicode_word_features_preserve_diacritics_greek_and_cyrillic(self) -> None:
        self.assertEqual(_family("Norteño"), "norteño")
        self.assertEqual(_family("Ελληνικό ροκ"), "ροκ")
        self.assertEqual(_family("Русский рок"), "рок")
        features = _lexical_features("Norteño Ελληνικό Русский")
        self.assertIn("w:norteño", features)
        self.assertIn("w:ελληνικό", features)
        self.assertIn("w:русский", features)

    def test_review_categories_keep_ambiguous_music_related_labels_unresolved(self) -> None:
        examples = {
            "french metal": "musical_style_candidate",
            "comfy synth": "musical_style_candidate",
            "denpa": "musical_style_candidate",
            "countertenor": "performance_role",
            "french orchestra": "performance_role",
            "france": "pure_place_language",
            "multiple vgmdb profiles": "editorial_technical",
            "romanticism": "unknown",
            "hololive": "unknown",
            "string quartet": "unknown",
            "tge24": "unknown",
        }
        for label, expected in examples.items():
            with self.subTest(label=label):
                category, _rationale = _manual_category(label, native_positive=False)
                self.assertEqual(category, expected)

    def test_model_margin_alone_does_not_assign_a_style_category(self) -> None:
        category, rationale = _manual_category("random phrase", native_positive=False)
        self.assertEqual(category, "unknown")
        self.assertIn("regardless of lexical margin", rationale)

    def test_dictionary_names_are_weak_positives_and_conflicts_are_excluded(self) -> None:
        texts, labels, families, origins = _training_rows({"ambient", "british"})
        rows = dict(zip(texts, labels, strict=True))
        self.assertEqual(rows["ambient"], 1)
        self.assertNotIn("british", rows)
        self.assertEqual(len(texts), len(set(texts)))
        self.assertEqual(len(families), len(texts))
        self.assertEqual(origins["ambient"], "native_musicbrainz_genre_name")


if __name__ == "__main__":
    unittest.main()
