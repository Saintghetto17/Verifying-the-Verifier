const state = { run: null, detail: null };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[c]);

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function metric(label, value) { return `<div class="metric"><b>${escapeHtml(value ?? "—")}</b><span>${escapeHtml(label)}</span></div>`; }

function outcomeOf(sample) { return sample.comparison ? sample.comparison.faithfulness : "incomplete"; }

function showSummary(run, samples) {
  const s = run.summary || {};
  const counts = { win: 0, tie: 0, inversion: 0 };
  for (const sample of samples) if (sample.comparison) counts[sample.comparison.faithfulness] += 1;
  const done = counts.win + counts.tie + counts.inversion;
  $("#run-summary").innerHTML = [
    metric("run", run.display_name || run.run_id), metric("prompt", run.prompt?.version), metric("model", run.config?.model),
    metric("status", run.status), metric("pairs", s.pairs), metric("complete", s.complete),
    metric("PSR (F)", done ? `${(100 * counts.win / done).toFixed(1)}%` : "—"), metric("ties", counts.tie), metric("inversions", counts.inversion),
    metric("cost, USD", Number(s.cost_usd || 0).toFixed(4)),
  ].join("");
}

function filteredSamples() {
  const text = $("#pair-filter").value.trim().toLowerCase();
  const wanted = $("#outcome-filter").value;
  return state.run.samples.filter((sample) => (!text || sample.pair_id.toLowerCase().includes(text)) && (!wanted || outcomeOf(sample) === wanted));
}

function renderList() {
  const list = $("#pair-list"); list.innerHTML = "";
  for (const sample of filteredSamples()) {
    const template = $("#pair-template").content.cloneNode(true);
    const button = template.querySelector("button");
    const dir = sample.pair_id.replaceAll("/", "__");
    button.querySelector("strong").textContent = sample.pair_id;
    button.querySelector("span").textContent = `${outcomeOf(sample)} · F ${sample.orig?.scores?.faithfulness ?? "—"} vs ${sample.fail?.scores?.faithfulness ?? "—"}`;
    if (state.detail === dir) button.classList.add("active");
    button.onclick = () => loadDetail(dir);
    list.append(template);
  }
}

function scoreCards(side) {
  const result = side?.result;
  const scores = result?.computed?.scores;
  if (!scores) return `<p class="muted">${escapeHtml(result?.status || "no result")}</p>`;
  const c = result.computed.counts;
  return `<div class="scores">${["faithfulness", "clarity", "compactness", "style", "overall"].map((name) => `<div class="score"><b>${escapeHtml(scores[name])}</b><span>${name}</span></div>`).join("")}</div>
    <p class="muted">P=${c.P} · M=${c.M} · U=${c.U} · R<sub>bad</sub>=${c.R_bad} · L<sub>bad</sub>=${c.L_bad} · D=${c.D} · coverage=${c.coverage}</p>`;
}

function sideDetail(name, side) {
  const ledger = side?.result?.ledger;
  return `<section><h3>${name}</h3>${scoreCards(side)}
    ${ledger ? `<details open><summary>Evidence ledger</summary><pre>${escapeHtml(JSON.stringify(ledger, null, 2))}</pre></details>` : ""}
    <details><summary>Result</summary><pre>${escapeHtml(JSON.stringify(side?.result, null, 2))}</pre></details>
    <details><summary>Request (no base64)</summary><pre>${escapeHtml(JSON.stringify(side?.request, null, 2))}</pre></details>
  </section>`;
}

async function loadDetail(directory) {
  state.detail = directory; renderList();
  const detail = await json(`/api/runs/${encodeURIComponent(state.run.run.run_id)}/samples/${encodeURIComponent(directory)}`);
  const pair = detail.pair;
  const img = (path) => path ? `/data/${path.split("/").map(encodeURIComponent).join("/")}` : "";
  $("#detail").innerHTML = `<h2>${escapeHtml(pair.pair_id)}</h2><p>${escapeHtml(pair.paper?.title || "")} · ${escapeHtml(pair.paper?.figure || "")}</p>
    <details open><summary>Caption and source text</summary><p>${escapeHtml(pair.caption)}</p><pre>${escapeHtml(pair.text_block)}</pre></details>
    <div class="image-grid"><figure class="image-card"><img src="${img(pair.images?.orig)}" alt="reference"><figcaption>reference (V+)</figcaption></figure><figure class="image-card"><img src="${img(pair.images?.fail)}" alt="corrupted"><figcaption>corrupted (V−)</figcaption></figure></div>
    <details><summary>Injected defect (never shown to the verifier)</summary><pre>${escapeHtml(JSON.stringify(pair.defect, null, 2))}</pre></details>
    <div class="image-grid">${sideDetail("reference", detail.orig)}${sideDetail("corrupted", detail.fail)}</div>`;
}

async function loadRun(runId) {
  state.detail = null;
  state.run = await json(`/api/runs/${encodeURIComponent(runId)}`);
  showSummary(state.run.run, state.run.samples); renderList();
  $("#detail").innerHTML = "<p class=\"muted\">Select a pair on the left.</p>";
}

async function init() {
  try {
    const runs = await json("/api/runs");
    const select = $("#run-select"); select.innerHTML = "";
    if (!runs.length) { select.innerHTML = "<option>No runs yet</option>"; return; }
    for (const run of runs) {
      const option = document.createElement("option"); option.value = run.run_id; option.textContent = `${run.display_name || run.run_id} · ${run.status}`; select.append(option);
    }
    select.onchange = () => loadRun(select.value).catch(showError);
    $("#pair-filter").oninput = renderList; $("#outcome-filter").onchange = renderList;
    await loadRun(select.value);
  } catch (error) { showError(error); }
}

function showError(error) { $("#detail").innerHTML = `<p class="bad">Viewer error: ${escapeHtml(error.message || error)}</p>`; }
init();
