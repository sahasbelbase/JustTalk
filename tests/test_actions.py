"""Tests for ActionRouter and intent parsing in Fn+Shift mode."""

from just_talk.ai.actions import ActionRouter


def test_standard_formatting_intent():
    intent = ActionRouter.parse_intent("can you email me the update", is_action_mode=False)
    assert intent.action_type == "format"
    assert intent.target_payload == "can you email me the update"


def test_translate_intent():
    # "translate this to spanish: hello friend"
    intent = ActionRouter.parse_intent("translate this to Spanish: hello how are you", is_action_mode=True)
    assert intent.action_type == "translate"
    assert intent.target_language.lower() == "spanish"
    assert "hello how are you" in intent.target_payload

    # "how do you say good morning in french"
    intent2 = ActionRouter.parse_intent("how do you say good morning in French", is_action_mode=True)
    assert intent2.action_type == "translate"
    assert intent2.target_language.lower() == "french"
    assert intent2.target_payload == "good morning"


def test_rewrite_intent():
    intent = ActionRouter.parse_intent("rewrite this professionally: hey dude need that report asap", is_action_mode=True)
    assert intent.action_type == "rewrite"
    assert intent.target_payload == "hey dude need that report asap"


def test_summarize_intent():
    intent = ActionRouter.parse_intent("summarize this: we had a three hour meeting discussing budgets and decided to keep it the same", is_action_mode=True)
    assert intent.action_type == "summarize"
