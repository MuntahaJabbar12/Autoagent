"""Unit tests: the small rules each agent depends on."""
import time

import pytest

from app import ideas, llm, media, script, seo
from app.jobs import LimitError, RateLimiter


# ---- script ---------------------------------------------------------------
@pytest.mark.parametrize("raw, spoken", [
    ("Narrator: Hello there.", "Hello there."),
    ("[music swells] The sea is deep.", "The sea is deep."),
    ("**Fact:** fish glow (sometimes).", "Fact: fish glow."),
    ("VISUALS: ocean", "ocean"),
])
def test_clean_narration_keeps_only_spoken_words(raw, spoken):
    assert script.clean_narration(raw) == spoken


def test_validate_scenes_drops_empty_and_fills_missing_visual():
    raw = {"scenes": [{"narration": "One.", "visual": ""}, {"narration": "[sfx]"},
                      {"narration": "Two!", "visual": "city, at night!!"}]}
    scenes = script.validate_scenes(raw, "topic hint")
    assert [s["narration"] for s in scenes] == ["One.", "Two!"]
    assert scenes[0]["visual"] == "topic hint"
    assert scenes[1]["visual"] == "city at night"


def test_validate_scenes_rejects_a_one_line_script():
    with pytest.raises(llm.LLMError):
        script.validate_scenes({"scenes": [{"narration": "Only one."}]}, "x")


# ---- llm json -------------------------------------------------------------
@pytest.mark.parametrize("reply", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here you go: {"a": 1} Hope that helps.',
])
def test_parse_json_tolerates_wrapping(reply):
    assert llm.parse_json(reply) == {"a": 1}


def test_parse_json_raises_readable_error():
    with pytest.raises(llm.LLMError, match="not valid JSON"):
        llm.parse_json("no json here")


def test_chat_without_key_fails_clearly(no_keys):
    with pytest.raises(llm.LLMError, match="GROQ_API_KEY"):
        llm.chat("hi")


# ---- ideas ----------------------------------------------------------------
def test_clean_title_removes_hashtags_and_entities():
    assert ideas.clean_title("Top 10 Facts &amp; Myths #shorts #viral | Explained") == "Top 10 Facts & Myths Explained"


def test_trending_is_skipped_without_youtube_key(keys):
    assert ideas.trending_on_youtube("cats") == []


# ---- seo ------------------------------------------------------------------
def test_checklist_scores_good_metadata_full_marks():
    title = "Deep sea creatures that make their own light"
    desc = "Deep sea creatures glow in the dark. " * 7 + "Subscribe for more."
    tags = [f"tag {i}" for i in range(10)]
    checks = seo.checklist(title, desc, tags)
    assert seo.score(checks) == 100


def test_checklist_flags_shouting_and_short_description():
    checks = {c["label"]: c["ok"] for c in seo.checklist("THE SHOCKING TRUTH about fish", "short", [])}
    assert checks["Title has no all-caps shouting"] is False
    assert checks["Description is 200+ characters"] is False
    assert checks["8–15 tags"] is False


def test_tags_are_cleaned_deduplicated_and_fit_youtube_limit():
    tags = seo._clean_tags(["#Ocean", "ocean", "<b>fish</b>", "x"] + ["a" * 40] * 3 + [f"{'b' * 39}{i}" for i in range(20)])
    assert tags[:2] == ["ocean", "bfish/b"]
    assert len(tags) <= 15
    assert sum(map(len, tags)) + len(tags) - 1 <= 500


def test_seo_falls_back_when_ai_fails(monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("down")
    monkeypatch.setattr(llm, "chat_json", boom)
    meta = seo.optimize("Why octopuses are so smart", [{"narration": "Octopuses solve puzzles."}] * 3)
    assert meta["title"] == "Why octopuses are so smart"
    assert "subscribe" in meta["description"].lower()
    assert 0 <= meta["score"] <= 100


# ---- media ----------------------------------------------------------------
FILES = [
    {"link": "a", "width": 3840, "height": 2160},
    {"link": "b", "width": 1280, "height": 720},
    {"link": "c", "width": 1080, "height": 1920},
    {"link": "d", "width": 720, "height": 1280},
]


def test_pick_file_matches_orientation_and_size():
    assert media.pick_file(FILES, portrait=False, target=1280)["link"] == "b"
    assert media.pick_file(FILES, portrait=True, target=1920)["link"] == "c"
    assert media.pick_file([FILES[1]], portrait=True, target=1920) is None


# ---- rate limit -----------------------------------------------------------
def test_rate_limiter_blocks_after_limit_and_resets_after_an_hour():
    rl = RateLimiter(2)
    now = time.time()
    rl.check("ip", now)
    rl.check("ip", now + 1)
    with pytest.raises(LimitError, match="2 videos this hour"):
        rl.check("ip", now + 2)
    rl.check("other-ip", now + 2)          # other visitors aren't affected
    rl.check("ip", now + 3601)             # an hour later it's allowed again


def test_json_mode_rejected_retries_without_it(keys, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, "bad"

        def json(self):
            return self._body

    def fake_post(url, headers, json, timeout):
        calls.append("response_format" in json)
        if "response_format" in json:
            return Resp(400, {})
        return Resp(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.chat_json("x") == {"ok": True}
    assert calls == [True, False]


def test_rate_limited_ai_gives_a_clear_message(keys, monkeypatch):
    class Resp:
        status_code, text = 429, "slow down"
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: Resp())
    with pytest.raises(llm.LLMError, match="busy"):
        llm.chat("x")
