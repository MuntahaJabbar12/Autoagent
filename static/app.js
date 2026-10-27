(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const STEPS = ["topic", "ideas", "style", "making", "done"];
  const STAGES = [
    ["script", "Writing the script"],
    ["seo", "Writing title, description and tags"],
    ["voice", "Recording the voiceover"],
    ["footage", "Finding footage"],
    ["render", "Editing the video"],
    ["finish", "Making the thumbnail"],
  ];
  const state = { topic: "", title: "", options: null, jobId: null, timer: null };

  // ---------- helpers ----------
  async function api(path, body) {
    const res = await fetch(path, body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {});
    let data = null;
    try { data = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg.replace(/^Value error, /, "")).join(" ");
      throw new Error(msg || `The server replied with an error (${res.status}). Try again.`);
    }
    return data;
  }

  function show(step) {
    $$(".panel").forEach((p) => { p.hidden = true; p.classList.remove("enter"); });
    const panel = $(`#step-${step}`);
    panel.hidden = false;
    void panel.offsetWidth;
    if (step !== "topic") panel.classList.add("enter");
    const i = STEPS.indexOf(step);
    $$(".steps li").forEach((li, n) => {
      li.classList.toggle("is-done", i > -1 && n < i);
      li.classList.toggle("is-current", n === i);
      li.toggleAttribute("aria-current", n === i);
    });
    if (step !== "topic") window.scrollTo({ top: 0, behavior: "smooth" });
    const h = panel.querySelector("h1, h2");
    if (h && step !== "topic") { h.tabIndex = -1; h.focus({ preventScroll: true }); }
  }

  function busy(btn, on) { btn && btn.setAttribute("aria-busy", on ? "true" : "false"); }
  function error(el, msg) { el.textContent = msg || ""; el.hidden = !msg; }
  function text(el, value) { el.textContent = value; return el; }

  // ---------- viewfinder timecode ----------
  const tc = $("#timecode");
  const t0 = performance.now();
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function tick() {
    const ms = performance.now() - t0;
    const f = Math.floor((ms % 1000) / (1000 / 30));
    const s = Math.floor(ms / 1000);
    const pad = (n) => String(n).padStart(2, "0");
    tc.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}:${pad(f)}`;
    if (!$("#step-topic").hidden) requestAnimationFrame(tick);
    else setTimeout(() => requestAnimationFrame(tick), 500);
  }
  if (!reduce) requestAnimationFrame(tick);

  // ---------- status / setup ----------
  let voices = [
    { id: "andrew", label: "Andrew · warm, US" }, { id: "ava", label: "Ava · bright, US" },
    { id: "ryan", label: "Ryan · calm, UK" }, { id: "sonia", label: "Sonia · clear, UK" },
  ];
  function renderVoices() {
    const box = $("#voices");
    box.innerHTML = "";
    voices.forEach((v, i) => {
      const [name, desc] = v.label.split(" · ");
      const label = document.createElement("label");
      label.innerHTML = `<input type="radio" name="voice" value=""><span></span>`;
      const input = label.querySelector("input");
      input.value = v.id;
      input.checked = i === 0;
      const span = label.querySelector("span");
      span.append(document.createTextNode(name));
      const small = document.createElement("small");
      small.textContent = desc || "";
      span.append(small);
      box.append(label);
    });
  }
  renderVoices();
  api("/api/status").then((s) => {
    if (s.voices && s.voices.length) { voices = s.voices; renderVoices(); }
    if (!s.ready) error($("#topic-error"), `This app isn't set up yet. Missing: ${s.missing.join(", ")}. See the README.`);
  }).catch(() => {});

  // ---------- 1. topic ----------
  const topicForm = $("#topic-form");
  const topicInput = $("#topic");
  topicForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const topic = topicInput.value.trim();
    if (topic.length < 2) { error($("#topic-error"), "Type a topic of at least 2 characters."); return; }
    error($("#topic-error"), "");
    const btn = topicForm.querySelector("button");
    busy(btn, true);
    try {
      const data = await api("/api/ideas", { topic });
      state.topic = topic;
      renderIdeas(data);
      show("ideas");
    } catch (err) {
      error($("#topic-error"), err.message);
    } finally { busy(btn, false); }
  });
  $$(".chip").forEach((c) => c.addEventListener("click", () => {
    topicInput.value = c.textContent;
    topicForm.requestSubmit();
  }));

  // ---------- 2. ideas ----------
  function renderIdeas(data) {
    text($("#topic-echo"), data.topic);
    const list = $("#ideas");
    list.innerHTML = "";
    data.ideas.forEach((idea) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "idea";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", "false");
      b.innerHTML = "<b></b><small></small><span class='go'>Use this</span>";
      text(b.querySelector("b"), idea.title);
      text(b.querySelector("small"), idea.angle || "");
      b.addEventListener("click", () => chooseTitle(idea.title));
      list.append(b);
    });
    const tr = $("#trending");
    const ul = $("#trending-list");
    ul.innerHTML = "";
    (data.trending || []).forEach((t) => {
      const li = document.createElement("li");
      li.textContent = t.channel ? `${t.title} (${t.channel})` : t.title;
      ul.append(li);
    });
    tr.hidden = !(data.trending && data.trending.length);
    $("#own-title").value = "";
  }
  $("#use-own").addEventListener("click", () => {
    const v = $("#own-title").value.trim();
    if (v.length < 3) { $("#own-title").focus(); return; }
    chooseTitle(v);
  });
  $("#own-title").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#use-own").click(); });

  function chooseTitle(title) {
    state.title = title;
    text($("#chosen-title"), title);
    show("style");
  }

  // ---------- 3. style ----------
  $("#style-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    state.options = {
      title: state.title,
      format: f.get("format"), length: f.get("length"), tone: f.get("tone"), voice: f.get("voice"),
    };
    await start();
  });

  async function start() {
    const btn = $("#style-form button[type=submit]");
    busy(btn, true);
    error($("#style-error"), "");
    try {
      const job = await api("/api/videos", state.options);
      state.jobId = job.id;
      renderStages(job);
      text($("#making-title"), state.options.title);
      show("making");
      poll();
    } catch (err) {
      if (!$("#step-failed").hidden) failed(err.message);
      else error($("#style-error"), err.message);
    } finally { busy(btn, false); }
  }

  // ---------- 4. making ----------
  function renderStages(job) {
    const ol = $("#stages");
    if (!ol.children.length) {
      STAGES.forEach(([key, label]) => {
        const li = document.createElement("li");
        li.dataset.stage = key;
        li.textContent = label;
        ol.append(li);
      });
    }
    const idx = STAGES.findIndex(([k]) => k === job.stage);
    $$("#stages li").forEach((li, i) => {
      const done = job.status === "done" || (idx > -1 && i < idx);
      li.classList.toggle("done", done);
      li.classList.toggle("active", !done && i === idx && job.status === "running");
    });
    const pct = Math.round((job.progress || 0) * 100);
    $("#fill").style.width = `${pct}%`;
    $("#playhead").style.left = `${pct}%`;
    text($("#pct"), `${pct}%`);
    let msg = job.message || "";
    if (job.status === "queued" && job.queue_position) {
      msg = job.queue_position === 1 ? "You're next in line" : `${job.queue_position} videos ahead of yours`;
    }
    text($("#status-line"), msg);
  }

  function poll() {
    clearTimeout(state.timer);
    state.timer = setTimeout(async () => {
      try {
        const job = await api(`/api/videos/${state.jobId}`);
        renderStages(job);
        if (job.status === "done") { setTimeout(() => showResult(job.result), 500); return; }
        if (job.status === "failed") { failed(job.error); return; }
      } catch (err) {
        if (/expired|exist/.test(err.message)) { failed(err.message); return; }
      }
      poll();
    }, 1200);
  }

  function failed(reason) {
    text($("#fail-reason"), reason || "Something went wrong while making the video.");
    show("making");
    $$(".panel").forEach((p) => { p.hidden = true; });
    $("#step-failed").hidden = false;
  }
  $("#retry").addEventListener("click", () => { $("#stages").innerHTML = ""; start(); });

  // ---------- 5. done ----------
  function fileUrl(name, download) {
    return `/files/${state.jobId}/${encodeURIComponent(name)}${download ? "?download=1" : ""}`;
  }
  function showResult(r) {
    const tall = r.format === "shorts";
    $("#player-wrap").classList.toggle("tall", tall);
    const v = $("#player");
    v.src = fileUrl(r.video);
    v.poster = fileUrl(r.thumbnail);
    $("#thumb").src = fileUrl(r.thumbnail);
    $("#dl-video").href = fileUrl(r.video, true);
    $("#dl-thumb").href = fileUrl(r.thumbnail, true);
    $("#dl-meta").href = fileUrl(r.metadata, true);
    const mins = Math.floor(r.seconds / 60);
    const secs = Math.round(r.seconds % 60);
    text($("#done-meta"), `${mins ? `${mins} min ` : ""}${secs} sec, ${r.scenes.length} scenes, ${tall ? "Shorts 9:16" : "16:9"}`);

    const seo = r.seo;
    text($("#seo-title"), seo.title);
    text($("#seo-desc"), seo.description + (seo.hashtags && seo.hashtags.length ? `\n\n${seo.hashtags.join(" ")}` : ""));
    text($("#seo-tags"), seo.tags.join(", "));
    const checks = $("#checks");
    checks.innerHTML = "";
    seo.checks.forEach((c) => {
      const li = document.createElement("li");
      li.className = c.ok ? "" : "no";
      li.textContent = c.label;
      checks.append(li);
    });
    text($("#score-num"), seo.score);
    requestAnimationFrame(() => $("#score").style.setProperty("--v", seo.score));

    const sl = $("#script-list");
    sl.innerHTML = "";
    r.scenes.forEach((s) => {
      const li = document.createElement("li");
      li.textContent = s.narration;
      const sm = document.createElement("small");
      sm.textContent = `Footage: ${s.visual}`;
      li.append(sm);
      sl.append(li);
    });
    show("done");
  }

  $$(".copy").forEach((b) => b.addEventListener("click", async () => {
    const value = $(`#${b.dataset.copy}`).textContent;
    try {
      await navigator.clipboard.writeText(value);
      b.textContent = "Copied";
      b.classList.add("copied");
      setTimeout(() => { b.textContent = "Copy"; b.classList.remove("copied"); }, 1600);
    } catch { b.textContent = "Select and copy"; }
  }));

  // ---------- navigation ----------
  $$("[data-go]").forEach((b) => b.addEventListener("click", () => {
    show(b.dataset.go);
    if (b.dataset.go === "topic") topicInput.focus();
  }));
  $("#again").addEventListener("click", () => {
    $("#stages").innerHTML = "";
    $("#player").removeAttribute("src");
    topicInput.value = "";
    show("topic");
    topicInput.focus();
  });
})();
