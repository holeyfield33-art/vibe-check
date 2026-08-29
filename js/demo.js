(() => {
  const reportFiles = {
    clean: "demo/clean.json",
    messy: "demo/messy.json",
    supply: "demo/supply-chain.json",
  };
  const state = { active: "clean", report: null };
  const els = {
    title: document.querySelector("[data-demo-title]"),
    source: document.querySelector("[data-demo-source]"),
    commit: document.querySelector("[data-demo-commit]"),
    disposition: document.querySelector("[data-demo-disposition]"),
    integrity: document.querySelector("[data-demo-integrity]"),
    supply: document.querySelector("[data-demo-supply]"),
    hard: document.querySelector("[data-demo-hard]"),
    observations: document.querySelector("[data-demo-observations]"),
    copy: document.querySelector("[data-copy-json]"),
    tabs: [...document.querySelectorAll("[data-demo-tab]")],
  };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  function setTab(next) {
    state.active = next;
    els.tabs.forEach((btn) => btn.setAttribute("aria-selected", String(btn.dataset.demoTab === next)));
    loadDemo(next);
  }

  function dispositionClass(v) {
    if (v === "FAST_TRACK") return "fast";
    if (v === "STANDARD_TRIAGE") return "standard";
    return "deep";
  }

  function metricBlock(label, value, cls = "") {
    return `<div class="metric"><div class="label">${esc(label)}</div><div class="value ${cls}">${esc(value)}</div></div>`;
  }

  function renderObservations(report) {
    const obs = report.triage.observations || {};
    const sections = [
      ["duplication", "Duplication", obs.duplication],
      ["stubs", "Stubs", obs.stubs],
      ["unreferenced_definitions", "Dead Code", obs.unreferenced_definitions],
      ["giant_files", "Structural", obs.giant_files],
      ["circular_imports", "Circular Imports", obs.circular_imports],
      ["comment_buzzwords", "Comment Buzzwords", obs.comment_buzzwords],
      ["readme_hype_files", "Readme Hype", obs.readme_hype_files],
      ["unreferenced_exports_js", "JS/TS Exports", obs.unreferenced_exports_js],
    ];
    return sections.map(([key, label, value]) => {
      const count = typeof value === "number" ? value : (value && value.count) || 0;
      const details = value && typeof value === "object" && !Array.isArray(value)
        ? Object.entries(value).filter(([k]) => k !== "count" && k !== "note").map(([k, v]) => `<div><strong>${esc(k)}</strong>: ${esc(Array.isArray(v) ? v.join(", ") : JSON.stringify(v))}</div>`).join("")
        : "";
      return `<details><summary>${esc(label)} <span>(${count})</span></summary><div class="finding">${details || "No additional details."}</div></details>`;
    }).join("");
  }

  function render(report) {
    const triage = report.triage || {};
    const axes = triage.axes || {};
    const summary = report.summary || {};
    const hard = summary.hard_signals || {};
    const soft = summary.soft_signals || {};
    els.title.textContent = report.demo?.title || state.active;
    els.source.textContent = report.demo?.source_fixture || "Bundled fixtures";
    els.commit.textContent = report.demo?.generated_from || report.demo?.scanner_sha || "n/a";
    els.disposition.innerHTML = `<span class="tag ${dispositionClass(triage.disposition)}">${esc(triage.disposition || "FAST_TRACK")}</span>`;
    els.integrity.innerHTML = `<strong>${esc(axes.integrity?.status || "PASS")}</strong><div class="reason">${esc((axes.integrity?.reasons || []).join("; ") || "No blocking integrity findings.")}</div>`;
    els.supply.innerHTML = `<strong>${esc(axes.supply_chain?.status || "CLEAN")}</strong><div class="reason">${esc((axes.supply_chain?.reasons || []).join("; ") || "No supply-chain findings.")}</div>`;
    els.hard.innerHTML = [
      metricBlock("Syntax", hard.syntax_errors || 0, hard.syntax_errors ? "red" : "green"),
      metricBlock("Duplicates", hard.duplicate_blocks || 0, hard.duplicate_blocks ? "red" : "green"),
      metricBlock("Package Risks", hard.package_risks || 0, hard.package_risks ? "red" : "green"),
      metricBlock("Stubs", hard.stubs || 0, hard.stubs ? "amber" : "green"),
    ].join("");
    els.observations.innerHTML = [
      metricBlock("Comment Buzzwords", soft.comment_buzzwords || 0, soft.comment_buzzwords ? "amber" : "green"),
      metricBlock("Giant Files", soft.giant_files || 0, soft.giant_files ? "amber" : "green"),
      metricBlock("Dead Code", soft.unreferenced_definitions || 0, soft.unreferenced_definitions ? "amber" : "green"),
      metricBlock("Readme Hype", soft.readme_hype_files || 0, soft.readme_hype_files ? "amber" : "green"),
    ].join("") + `<div style="grid-column:1/-1">${renderObservations(report)}</div>`;
    els.copy.onclick = async () => {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
      els.copy.textContent = "Copied";
      setTimeout(() => (els.copy.textContent = "Copy JSON"), 1200);
    };
  }

  async function loadDemo(key) {
    const res = await fetch(reportFiles[key], { cache: "no-store" });
    const report = await res.json();
    state.report = report;
    render(report);
  }

  els.tabs.forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.demoTab)));
  setTab(state.active);
})();
