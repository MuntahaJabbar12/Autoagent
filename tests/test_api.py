"""API tests: what a visitor's browser sees, including errors and abuse cases."""
import time

import pytest
from fastapi.testclient import TestClient

from app import ideas, main
from app.jobs import JobManager


@pytest.fixture
def client(tmp_path, keys, monkeypatch):
    def runner(opts, workdir, progress):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "v.mp4").write_bytes(b"video")
        (workdir / "t.jpg").write_bytes(b"jpg")
        (workdir / "m.json").write_text("{}")
        (tmp_path / "secret.txt").write_text("nope")
        return {"video": "v.mp4", "thumbnail": "t.jpg", "metadata": "m.json"}

    monkeypatch.setattr(main, "manager", JobManager(runner=runner, out_dir=tmp_path, workers=1))
    monkeypatch.setattr(main, "idea_limiter", main.RateLimiter(30))
    return TestClient(main.app)


def test_home_page_and_status(client):
    assert "One topic in." in client.get("/").text
    s = client.get("/api/status").json()
    assert s["ready"] is True and len(s["voices"]) == 4


def test_status_reports_missing_keys(no_keys):
    s = TestClient(main.app).get("/api/status").json()
    assert s["ready"] is False and s["missing"] == ["GROQ_API_KEY", "PEXELS_API_KEY"]


def test_unconfigured_app_refuses_politely(no_keys):
    r = TestClient(main.app).post("/api/ideas", json={"topic": "cats"})
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


@pytest.mark.parametrize("topic", ["", " ", "x" * 81])
def test_bad_topics_are_rejected(client, topic):
    assert client.post("/api/ideas", json={"topic": topic}).status_code == 422


def test_ideas_endpoint(client, monkeypatch):
    monkeypatch.setattr(ideas, "ideas_for", lambda t: {"topic": t, "trending": [], "ideas": [{"title": "A"}]})
    r = client.post("/api/ideas", json={"topic": "  deep   sea "})
    assert r.status_code == 200 and r.json()["topic"] == "deep sea"


def test_unknown_options_fall_back_to_safe_defaults(client):
    r = client.post("/api/videos", json={"title": "Deep sea", "voice": "hacker", "format": "8k", "tone": "x"})
    assert r.status_code == 202
    job = main.manager.get(r.json()["id"])
    assert (job.options.voice, job.options.format, job.options.tone) == ("andrew", "landscape", "curious")


def test_video_flow_and_downloads(client):
    job_id = client.post("/api/videos", json={"title": "Deep sea creatures"}).json()["id"]
    for _ in range(100):
        s = client.get(f"/api/videos/{job_id}").json()
        if s["status"] == "done":
            break
        time.sleep(0.05)
    assert s["status"] == "done"
    r = client.get(f"/files/{job_id}/v.mp4?download=1")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_files_cannot_escape_the_job_folder(client):
    job_id = client.post("/api/videos", json={"title": "Deep sea creatures"}).json()["id"]
    time.sleep(0.3)
    for name in ["../secret.txt", "..%2Fsecret.txt", "secret.txt"]:
        assert client.get(f"/files/{job_id}/{name}").status_code == 404


def test_unknown_job_is_404(client):
    assert client.get("/api/videos/doesnotexist").status_code == 404


def test_per_visitor_limit(client, monkeypatch):
    monkeypatch.setattr(main.manager.limiter, "per_hour", 2)
    hdr = {"x-forwarded-for": "9.9.9.9"}
    codes = [client.post("/api/videos", json={"title": "Deep sea"}, headers=hdr).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
    other = client.post("/api/videos", json={"title": "Deep sea"}, headers={"x-forwarded-for": "1.1.1.1"})
    assert other.status_code == 202
