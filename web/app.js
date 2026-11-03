/* Dastavez front end: plain JavaScript, no libraries. All text from the server is inserted with
   textContent / createTextNode, never as HTML. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  function h(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
    return e;
  }

  const LANGS = [["hi-IN", "हिन्दी", "Hindi"], ["kn-IN", "ಕನ್ನಡ", "Kannada"], ["ta-IN", "தமிழ்", "Tamil"], ["te-IN", "తెలుగు", "Telugu"],
    ["mr-IN", "मराठी", "Marathi"], ["bn-IN", "বাংলা", "Bengali"], ["gu-IN", "ગુજરાતી", "Gujarati"], ["ml-IN", "മലയാളം", "Malayalam"],
    ["pa-IN", "ਪੰਜਾਬੀ", "Punjabi"], ["od-IN", "ଓଡ଼ିଆ", "Odia"], ["en-IN", "English", "English"]];
  const lang = (code) => LANGS.find((l) => l[0] === code) || LANGS[0];
  const langLabel = (l) => (l[2] === "English" ? "English" : `${l[1]}  (${l[2]})`);
  const SUGGEST = ["What is this document about?", "Who is it addressed to?", "What dates or deadlines are mentioned?", "Is any amount of money mentioned?"];
  const STEPS = [["text", "Reading the text"], ["fields", "Finding the key fields"], ["summary", "Writing the summary"]];

  const S = { mode: "choose", tab: "upload", file: null, sample: null, code: "hi-IN", samples: [], steps: {}, result: null,
    rtab: "text", target: "en-IN", trans: {}, chat: [], error: null, busy: false, preview: null };

  const panel = $("#panel"), paperView = $("#paperView"), paperEmpty = $("#paperEmpty"), scanLine = $("#scanLine"), paperCap = $("#paperCap");

  /* ---------- paper (left) ---------- */
  function renderPaper() {
    const src = S.sample ? { url: `/samples/${S.sample.file}`, name: S.sample.file, pdf: false }
      : S.file ? { url: S.preview, name: S.file.name, pdf: /\.pdf$/i.test(S.file.name) } : null;
    paperEmpty.hidden = !!src;
    paperView.hidden = !src;
    paperView.replaceChildren();
    if (src) paperView.append(src.pdf ? h("iframe", { src: src.url, title: "PDF preview" }) : h("img", { src: src.url, alt: "Your document" }));
    paperCap.textContent = src ? src.name : "";
    scanLine.hidden = S.mode !== "reading";
  }

  /* ---------- helpers ---------- */
  const errorBox = (msg) => h("div", { class: "errbox", role: "alert" }, msg);
  async function api(path, body) {
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 120000);  // never hang forever
    let r;
    try { r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal }); }
    catch (e) { throw new Error(e.name === "AbortError" ? "This is taking too long. The service may be busy, please try again." : "Could not reach the server."); }
    finally { clearTimeout(timer); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "Something went wrong. Please try again.");
    return j;
  }
  function download(name, text, mime = "text/plain") {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` })), download: name });
    document.body.append(a); a.click(); a.remove();
  }
  const baseName = () => (S.result.name || "document").replace(/\.[^.]+$/, "");
  const rowsText = (rows) => rows.map((r) => r.join(" | ")).join("\n");

  /* ---------- choose ---------- */
  function setFile(f) {
    if (!f) return;
    if (!/\.(png|jpe?g|pdf)$/i.test(f.name)) { S.error = "Please choose a PNG, JPG or PDF file."; return render(); }
    if (f.size > 25 * 1024 * 1024) { S.error = "That file is larger than 25 MB."; return render(); }
    if (S.preview) URL.revokeObjectURL(S.preview);
    S.file = f; S.sample = null; S.error = null; S.preview = URL.createObjectURL(f);
    render();
  }
  function pickSample(s) { S.sample = s; S.file = null; S.code = s.language_code; S.error = null; render(); }

  function chooseView() {
    const tabBar = h("div", { class: "tabs", role: "tablist" }, [["upload", "Upload your own"], ["sample", "Try a sample"]].map(([id, label]) =>
      h("button", { class: "tab", role: "tab", "aria-selected": String(S.tab === id), onclick: () => { S.tab = id; render(); } }, label)));

    let body;
    if (S.tab === "upload") {
      const input = h("input", { type: "file", accept: ".png,.jpg,.jpeg,.pdf", hidden: true, onchange: (e) => setFile(e.target.files[0]) });
      const icon = h("span", {});
      icon.innerHTML = '<svg viewBox="0 0 48 48" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M24 34V10M14 20l10-10 10 10M8 34v7h32v-7"/></svg>'; // constant markup, no user data
      const drop = h("div", { class: "drop" + (S.file ? " has" : ""), tabindex: "0", role: "button", "aria-label": "Choose a file",
        onclick: () => input.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } },
        ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); }, ondragleave: () => drop.classList.remove("over"),
        ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); setFile(e.dataTransfer.files[0]); } },
        icon,
        h("b", {}, S.file ? S.file.name : "Drop a photo or PDF here"),
        h("span", {}, S.file ? "Click to choose a different file" : "or click to browse · PNG, JPG or PDF · up to 25 MB"));
      body = h("div", {}, drop, input);
    } else {
      body = h("div", { class: "samples" }, S.samples.map((s) => {
        const l = lang(s.language_code);
        return h("button", { class: "sample", "aria-pressed": String(S.sample && S.sample.file === s.file), onclick: () => pickSample(s) },
          h("img", { src: `/samples/${s.file}`, alt: "", loading: "lazy" }),
          h("span", {}, `${l[1]} · ${s.template === "fee" ? "Fee notice" : "Admit card"}`));
      }));
    }

    const select = h("select", { id: "langSel", onchange: (e) => { S.code = e.target.value; } },
      LANGS.map((l) => h("option", { value: l[0], selected: l[0] === S.code }, langLabel(l))));
    const ready = !!(S.file || S.sample);
    const go = h("button", { class: "btn btn-primary", disabled: !ready, onclick: read }, "Read this document ", h("span", { class: "arr" }, "→"));

    return h("div", {},
      h("p", { class: "panel-title" }, "Step 1 · Pick a document"), tabBar,
      S.error ? errorBox(S.error) : null, body,
      h("div", { class: "row-controls" }, h("div", { class: "field" }, h("label", { for: "langSel" }, "Language of the document"), select), go));
  }

  /* ---------- reading ---------- */
  function readingView() {
    const firstOpen = STEPS.findIndex(([k]) => !S.steps[k]);
    return h("div", {},
      h("p", { class: "panel-title" }, "Step 2 · Reading"),
      h("ol", { class: "steps-live" }, STEPS.map(([k, label], i) => {
        const done = !!S.steps[k], active = i === firstOpen;
        return h("li", { class: done ? "done" : active ? "active" : "" },
          h("span", { class: "no" }, String(i + 1).padStart(2, "0")), h("span", { class: "t" }, label),
          h("span", { class: "st" }, done ? "Done" : active ? "Working…" : "Waiting"));
      })),
      h("p", { class: "wait-note" }, "This usually takes 20 to 40 seconds. Blurry photos take a little longer."));
  }

  async function read() {
    S.mode = "reading"; S.error = null; S.steps = {}; render();
    const fd = new FormData();
    fd.append("language_code", S.code);
    if (S.sample) fd.append("sample", S.sample.file); else fd.append("file", S.file);
    try {
      const r = await fetch("/api/analyze", { method: "POST", body: fd });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || "Could not start the analysis.");
      poll(j.job);
    } catch (e) { fail(e.message); }
  }
  function fail(msg) { S.mode = "choose"; S.error = msg; render(); }
  function poll(job) {
    const timer = setInterval(async () => {
      try {
        const j = await (await fetch(`/api/job/${job}`)).json();
        S.steps = j.steps || {};
        if (j.status === "done") {
          clearInterval(timer);
          Object.assign(S, { result: j.result, mode: "result", rtab: "text", trans: {}, chat: [], target: j.result.code === "en-IN" ? "hi-IN" : "en-IN" });
          render();
        } else if (j.status === "error") { clearInterval(timer); fail(j.error); }
        else render();
      } catch { clearInterval(timer); fail("Lost connection to the server. Is it still running?"); }
    }, 900);
  }

  /* ---------- result ---------- */
  function table(rows, withHead) {
    return h("table", { class: "doc-table" }, h("tbody", {}, rows.map((r) =>
      h("tr", {}, r.length === 1 ? h("td", { colspan: "2", class: "big" }, r[0]) : r.map((c) => h("td", {}, c))))));
  }

  function textTab() {
    return h("div", {}, table(S.result.rows),
      h("p", { class: "note" }, h("button", { class: "link", style: "background:none;border:0;cursor:pointer",
        onclick: (e) => { navigator.clipboard.writeText(rowsText(S.result.rows)); e.target.textContent = "Copied ✓"; } }, "Copy the text")));
  }

  function translateTab() {
    const r = S.result, targets = LANGS.filter((l) => l[0] !== r.code);
    if (!targets.some((l) => l[0] === S.target)) S.target = targets[0][0];
    const sel = h("select", { id: "trSel", onchange: (e) => { S.target = e.target.value; render(); } },
      targets.map((l) => h("option", { value: l[0], selected: l[0] === S.target }, langLabel(l))));
    const done = S.trans[S.target];
    const btn = h("button", { class: "btn " + (done ? "btn-ghost" : "btn-primary"), disabled: S.busy, onclick: translate },
      S.busy ? "Translating…" : done ? "Translate again" : `Translate into ${lang(S.target)[2]}`);
    const out = h("div", {});
    if (done) {
      let flagged = false;
      const body = done.map((row) => {
        const cell = (get) => row.map((c, i) => [i ? "  ·  " : "", get(c)]);
        return h("tr", {}, h("td", { class: "orig" }, cell((c) => c.src)),
          h("td", {}, row.map((c, i) => [i ? "  ·  " : "", c.ok ? c.out : (flagged = true, h("mark", { title: "Numbers changed in translation" }, c.out + " ⚠"))])));
      });
      out.append(h("table", { class: "doc-table" }, h("thead", {}, h("tr", {}, h("th", {}, "Original"), h("th", {}, lang(S.target)[2]))), h("tbody", {}, body)));
      if (flagged) out.append(h("div", { class: "warnbox" }, "Some numbers changed during translation (marked ⚠). Check them against the original."));
      out.append(h("p", { class: "note" }, "IDs, dates and amounts are copied exactly as written, not translated. Machine translation can be imperfect, especially for names."));
    } else out.append(h("p", { class: "note" }, S.busy ? "Translating line by line. This is usually a few seconds, but can take up to a minute when the service is busy."
      : "Pick a language and press the button. It takes a few seconds."));
    return h("div", {}, h("div", { class: "tr-bar" }, h("div", { class: "field" }, h("label", { for: "trSel" }, "Translate this document into"), sel), btn),
      S.error ? errorBox(S.error) : null, out);
  }
  async function translate() {
    S.busy = true; S.error = null; render();
    try { S.trans[S.target] = (await api("/api/translate", { id: S.result.id, target: S.target })).rows; }
    catch (e) { S.error = e.message; }
    S.busy = false; render();
  }

  function askTab() {
    const input = h("input", { class: "input", id: "q", placeholder: "e.g. What is the last date to pay the fee?", maxlength: "500", autocomplete: "off", "aria-label": "Your question" });
    const form = h("form", { class: "ask", onsubmit: (e) => { e.preventDefault(); ask(input.value); } }, input,
      h("button", { class: "btn btn-primary", disabled: S.busy }, S.busy ? "Thinking…" : "Ask"));
    return h("div", {},
      h("div", { class: "chips" }, SUGGEST.map((q) => h("button", { type: "button", disabled: S.busy, onclick: () => ask(q) }, q))),
      form, S.error ? errorBox(S.error) : null,
      [...S.chat].reverse().map((m) => h("div", { class: "msg" }, h("div", { class: "q" }, m.q), h("div", { class: "a" }, m.a))),
      h("p", { class: "note" }, "Answers come only from this document. Ask in English or in the document's own language."));
  }
  async function ask(q) {
    q = (q || "").trim(); if (!q || S.busy) return;
    S.busy = true; S.error = null; render();
    try { S.chat.push({ q, a: (await api("/api/ask", { id: S.result.id, question: q })).answer }); }
    catch (e) { S.error = e.message; }
    S.busy = false; render();
    const inp = $("#q"); if (inp) inp.focus();
  }

  function downloadTab() {
    const r = S.result, b = baseName();
    const items = [["Key fields (.json)", () => download(`${b}_fields.json`, JSON.stringify(r.fields, null, 2), "application/json")],
      ["Extracted text (.txt)", () => download(`${b}_text.txt`, rowsText(r.rows))]];
    for (const [code, rows] of Object.entries(S.trans)) items.push([`${lang(code)[2]} translation (.txt)`, () => download(`${b}_${code}.txt`, rowsText(rows.map((row) => row.map((c) => c.out))))]);
    return h("div", {}, h("div", { class: "dl" }, items.map(([label, fn]) => h("button", { class: "btn btn-ghost", onclick: fn }, label))),
      h("p", { class: "note" }, "Translations appear here after you create them in the Translate tab."));
  }

  function resultView() {
    const r = S.result, f = r.fields, ledger = Object.entries(f).filter(([k]) => k !== "document_type" && k !== "organisation");
    const tabs = [["text", "Text"], ["translate", "Translate"], ["ask", "Ask"], ["download", "Download"]];
    const content = { text: textTab, translate: translateTab, ask: askTab, download: downloadTab }[S.rtab]();
    return h("div", {},
      h("div", { class: "res-head" }, h("span", { class: "k" }, "Document type"), h("h3", {}, f.document_type || "Your document"),
        h("div", { class: "res-meta" }, f.organisation ? h("span", { class: "chip" }, f.organisation) : null, h("span", { class: "chip" }, lang(r.code)[2]))),
      ledger.length ? h("div", { class: "ledger" }, ledger.map(([k, v], i) => h("div", { class: "r", style: `animation-delay:${i * 70}ms` },
        h("span", { class: "k" }, k.replace(/_/g, " ")), h("span", { class: "dots" }), h("span", { class: "v" }, v)))) : h("p", { class: "note" }, "No key fields were found in this document."),
      h("div", { class: "quote" }, h("span", { class: "k" }, "In plain English"), h("p", {}, r.summary)),
      h("div", { class: "after-quote" }, h("div", { class: "tabs", role: "tablist" }, tabs.map(([id, label]) =>
        h("button", { class: "tab", role: "tab", "aria-selected": String(S.rtab === id), onclick: () => { S.rtab = id; S.error = null; render(); } }, label))), content),
      h("div", { class: "restart" }, h("button", { class: "btn btn-ghost", onclick: restart }, "← Read another document")),
      h("p", { class: "note" }, "AI can make mistakes. Check important values (amounts, dates, ID numbers) against the original."));
  }
  function restart() {
    if (S.preview) URL.revokeObjectURL(S.preview);
    Object.assign(S, { mode: "choose", file: null, sample: null, preview: null, result: null, error: null, trans: {}, chat: [] });
    render();
    $("#try").scrollIntoView({ behavior: "smooth" });
  }

  /* ---------- render ---------- */
  function render() {
    const view = S.mode === "reading" ? readingView() : S.mode === "result" ? resultView() : chooseView();
    panel.replaceChildren(view);
    renderPaper();
  }

  /* ---------- results section ---------- */
  function countUp(el, to) {
    const dec = String(to).includes(".") ? 1 : 0, t0 = performance.now();
    const step = (t) => { const p = Math.min(1, (t - t0) / 1400), e = 1 - Math.pow(1 - p, 3); el.textContent = (to * e).toFixed(dec) + "%"; if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  function renderEval(d) {
    const hard = d.hard;
    if (hard) {
      $("#statHardFields").dataset.count = hard.fields; $("#statHardQa").dataset.count = hard.qa;
      $("#statHardFields").nextElementSibling.querySelector(".mono").textContent = `(${Math.round(hard.fields * hard.field_count / 100)} of ${hard.field_count})`;
      $("#statHardQa").nextElementSibling.querySelector(".mono").textContent = `(${Math.round(hard.qa * hard.documents / 100)} of ${hard.documents})`;
      const bars = $("#chartBars"), labels = h("div", { class: "glabels" });
      for (const lvl of ["mild", "medium", "harsh"]) {
        const v = hard.by_level[lvl]; if (!v) continue;
        bars.append(h("div", { class: "grp" }, h("div", { class: "bar k1", "data-v": `${Math.round(v.fields)}%`, "data-h": v.fields }), h("div", { class: "bar k2", "data-v": `${Math.round(v.qa)}%`, "data-h": v.qa })));
        labels.append(h("span", {}, lvl));
      }
      bars.after(labels);
      $("#mistakeCount").textContent = `(${hard.wrong_fields.length} fields, ${hard.wrong_qa.length} answers)`;
      const t = (head, rows, keys) => h("div", { class: "tbl-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map((x) => h("th", {}, x)))),
        h("tbody", {}, rows.map((r) => h("tr", {}, keys.map((k) => h("td", {}, r[k] || "(empty)")))))));
      $("#mistakeTables").append(h("h4", {}, "Wrong fields"), t(["File", "Field", "Expected", "Got"], hard.wrong_fields, ["file", "field", "expected", "got"]),
        h("h4", {}, "Wrong answers"), t(["File", "Question", "Expected", "Answer"], hard.wrong_qa, ["file", "question", "expected", "answer"]));
    }
  }

  /* ---------- scroll effects ---------- */
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (!en.isIntersecting) return;
    en.target.classList.add("in");
    if (en.target.classList.contains("stat-grid")) en.target.querySelectorAll("[data-count]").forEach((n) => countUp(n, parseFloat(n.dataset.count)));
    if (en.target.classList.contains("proof-body")) en.target.querySelectorAll(".bar").forEach((b) => (b.style.height = b.dataset.h + "%"));
    io.unobserve(en.target);
  }), { threshold: 0.18 });

  /* ---------- start ---------- */
  render();
  fetch("/api/samples").then((r) => r.json()).then((s) => { S.samples = s; if (S.mode === "choose") render(); }).catch(() => {});
  fetch("/api/results").then((r) => r.json()).then(renderEval).catch(() => {}).finally(() => document.querySelectorAll(".reveal").forEach((el) => io.observe(el)));
})();
