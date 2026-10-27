"""Real rendering tests: ffmpeg actually builds video files (only the network is faked)."""
import json

import pytest
import time
from pathlib import Path

from PIL import Image

from app import pipeline, render, thumbnail
from app.jobs import JobManager

from .conftest import make_audio


def test_caption_overlay_has_text_in_lower_part(tmp_path):
    p = render.caption_png("Some fish make their own light.", (1280, 720), tmp_path / "c.png")
    img = Image.open(p)
    assert img.size == (1280, 720) and img.mode == "RGBA"
    bbox = img.getbbox()
    assert bbox and bbox[1] > 720 * 0.5, "caption should sit in the lower half"


def test_long_caption_still_fits_inside_frame(tmp_path):
    p = render.caption_png("word " * 60, (1080, 1920), tmp_path / "c.png")
    left, top, right, bottom = Image.open(p).getbbox()
    assert left >= 0 and right <= 1080 and bottom <= 1920


def test_scene_renders_at_exact_length_with_and_without_footage(tmp_path, sample_clip):
    cap = render.caption_png("Hello", (1280, 720), tmp_path / "c.png")
    audio = make_audio(tmp_path / "a.mp3", 1.5)
    with_clip = render.render_scene(clip=sample_clip, caption=cap, audio=audio, seconds=3.0,
                                    size=(1280, 720), out=tmp_path / "p1.mp4")
    no_clip = render.render_scene(clip=None, caption=cap, audio=audio, seconds=2.0,
                                  size=(1280, 720), out=tmp_path / "p2.mp4")
    # the 2s sample clip is looped to fill 3s; audio is padded with silence
    assert abs(render.duration(with_clip) - 3.0) < 0.15
    assert abs(render.duration(no_clip) - 2.0) < 0.15
    joined = render.concat([with_clip, no_clip], tmp_path / "joined.mp4")
    assert abs(render.duration(joined) - 5.0) < 0.25


def test_thumbnail_without_photo_uses_red_background(tmp_path):
    out = thumbnail.make("Deep sea creatures that make their own light", tmp_path / "t.jpg")
    img = Image.open(out).convert("RGB")
    assert img.size == (1280, 720)
    r, g, b = img.getpixel((1200, 100))
    assert r > 100 and r > g * 2, "right side should be red"


@pytest.mark.parametrize("title, hook", [
    ("Deep sea creatures that make their own light", "DEEP SEA CREATURES"),
    ("Why octopuses are smarter than you think: the science", "WHY OCTOPUSES ARE SMARTER"),
    ("Volcanoes", "VOLCANOES"),
])
def test_hook_words_never_end_on_a_dangling_word(title, hook):
    assert thumbnail.hook_words(title) == hook


def test_full_pipeline_produces_video_thumbnail_and_metadata(tmp_path, fake_services):
    stages = []
    result = pipeline.run(pipeline.Options(title="Deep sea creatures"), tmp_path / "job",
                          lambda stage, pct, msg: stages.append((stage, pct)))
    job = tmp_path / "job"
    files = sorted(p.name for p in job.iterdir())
    assert files == sorted([result["video"], result["thumbnail"], result["metadata"]]), "temp files cleaned up"

    # captions never include stage directions
    assert all("Narrator" not in s["narration"] and "[" not in s["narration"] for s in result["scenes"])
    # video length = sum of scene lengths
    assert abs(render.duration(job / result["video"]) - result["seconds"]) < 0.3
    # progress only moves forward and covers every stage
    pcts = [p for _, p in stages]
    assert pcts == sorted(pcts)
    assert {s for s, _ in stages} == {k for k, _ in pipeline.STAGES}
    # Pexels credit is added to the description and saved in the metadata file
    meta = json.loads((job / result["metadata"]).read_text())
    assert "Jane Doe via Pexels" in meta["description"]
    assert meta["hashtags"] == ["#ocean", "#deepsea", "#science"]
    # each scene gets its own clip
    assert fake_services["n"] == 3


def test_shorts_format_is_vertical(tmp_path, fake_services):
    result = pipeline.run(pipeline.Options(title="Deep sea", format="shorts"), tmp_path / "j", lambda *a: None)
    first_frame = tmp_path / "frame.png"
    render.run(["-i", str(tmp_path / "j" / result["video"]), "-frames:v", "1", str(first_frame)])
    assert Image.open(first_frame).size == (1080, 1920)


def wait_for(job, seconds=60):
    end = time.time() + seconds
    while job.status in ("queued", "running") and time.time() < end:
        time.sleep(0.05)
    return job


def test_job_manager_reports_success_and_failure(tmp_path, monkeypatch):
    def runner(opts, workdir, progress):
        progress("script", 0.5, "half")
        if opts.title == "boom":
            raise RuntimeError("Pexels is down")
        workdir.mkdir(parents=True, exist_ok=True)
        return {"video": "v.mp4"}

    m = JobManager(runner=runner, out_dir=tmp_path, workers=1)
    ok = wait_for(m.submit(pipeline.Options(title="fine"), "a"))
    bad = wait_for(m.submit(pipeline.Options(title="boom"), "a"))
    assert ok.status == "done" and ok.progress == 1.0
    assert bad.status == "failed" and bad.error == "Pexels is down"
    assert not (tmp_path / bad.id).exists(), "failed job leaves no files behind"


def test_old_jobs_are_deleted(tmp_path):
    m = JobManager(runner=lambda o, w, p: (w.mkdir(parents=True), {})[1], out_dir=tmp_path, workers=1)
    job = wait_for(m.submit(pipeline.Options(title="x"), "a"))
    assert (tmp_path / job.id).exists()
    assert m.sweep_once(now=time.time() + 10 * 3600) == 1
    assert not (tmp_path / job.id).exists() and m.get(job.id) is None
