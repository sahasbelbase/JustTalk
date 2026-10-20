"""The "not" check on translations (rules from Just Notes' lab/translate_bench, measured there)."""

from just_talk.ai.negation import english_cues, flipped, nepali_cues


def test_nepali_not_in_its_common_forms():
    for text in ("राम सोमबारसम्म रिपोर्ट पठाउनुहुन्न।", "उहाँले बजेट माग्नुभएको छैन।", "हामी भोलि बैठक गर्दैनौँ।",
                 "सीताले पाँच वटा फाइल पठाइनन्।", "ग्राहकले मूल्य स्वीकार गर्नुभएन।", "तिमीले यो कुरा म्यानेजरलाई नभन्नू।",
                 "Client ले final design approve गर्नुभएन।"):
        assert nepali_cues(text), text


def test_affirmative_look_alikes_are_not_taken_for_not():
    for text in ("उहाँले बजेट माग्नुभएको छ।", "सीताले पाँच वटा फाइल पठाइन्।", "नगरपालिकाले नयाँ नदी पुल बनायो।",
                 "भीमसेन स्पेन र ब्रिटेन गए।", "नरहरि भोलि आउनुहुन्छ।", "हामीले bug fix गरिसक्यौँ।"):
        assert not nepali_cues(text), text


def test_english_not_words():
    assert english_cues("He hasn't sent the report.") and english_cues("They did not come.")
    assert english_cues("The client declined the price.")
    assert not english_cues("He has asked for the budget.")


def test_a_flipped_translation_is_caught_both_ways():
    assert flipped("उहाँले बजेट माग्नुभएको छैन।", "He has asked for the budget.")
    assert flipped("उहाँले बजेट माग्नुभएको छ।", "He has still not asked for the budget.")
    assert not flipped("उहाँले बजेट माग्नुभएको छैन।", "He hasn't asked for the budget.")
    assert not flipped("उहाँले बजेट माग्नुभएको छ।", "He has asked for the budget.")


def test_english_words_in_mixed_speech_count_as_said():
    assert not flipped("यो not ready छ।", "This is not ready.")
