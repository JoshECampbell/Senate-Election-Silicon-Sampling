/* Offline selectors only: all estimates, dated charts and coverage are prepared
   by Python. This controller never queries a provider or calculates an average. */
(() => {
  "use strict";
  let history;
  let requestNumber = 0;
  const byId = id => document.getElementById(id);
  const columns = ["p_democrat", "p_republican", "p_third_party", "p_would_not_vote"];
  const fmt = value => value == null ? "Not measured" : `${(value * 100).toFixed(1)}%`;
  const esc = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function responseSummary() {
    const state = byId("response-state").value;
    const rows = [];
    for (const day of history.dates) {
      for (const [key, model] of Object.entries(history.models)) {
        const entry = history.snapshots[day].models[key];
        const value = entry?.states[state];
        const cells = value?.eligible
          ? columns.map(c => {
            const sem = value.bootstrap?.[c]?.sem;
            const uncertainty = sem == null ? "" : ` ± ${(sem * 100).toFixed(1)} pp`;
            return `<td data-category="${c}">${fmt(value.means[c])}${uncertainty}</td>`;
          }).join("")
          : `<td colspan="4">Unavailable: ${esc(value?.reason || "Not collected")}</td>`;
        const source = entry?.carried_forward ? ` title="Reused external forecast from ${esc(entry.source_date)}"` : "";
        rows.push(`<tr data-model="${esc(key)}"><td${source}>${day}${entry?.carried_forward ? "*" : ""}</td><th scope="row">${esc(model.label)}</th>${cells}</tr>`);
      }
    }
    byId("response-means").innerHTML = rows.join("");
  }

  function applyModelSelection() {
    const selected = new Set([...document.querySelectorAll("[data-model-toggle]:checked")].map(el => el.dataset.modelToggle));
    // Model checkboxes affect only this section, never the headline or state grid.
    for (const container of [byId("response-chart"), byId("response-means")]) {
      container.querySelectorAll("[data-model]").forEach(group => {
        group.style.display = selected.has(group.dataset.model) ? "" : "none";
      });
    }
    byId("response-chart").hidden = selected.size === 0;
    byId("model-empty").hidden = selected.size !== 0;
    document.querySelector(".accessible-summary").hidden = selected.size === 0;
    byId("response-summary-note").hidden = selected.size === 0;

  }

  async function changeResponseState() {
    const number = ++requestNumber;
    const key = byId("response-state").value;
    const state = history.states[key];
    try {
      const figures = await Promise.all(columns.map(async column => {
        const response = await fetch(`figures/${history.date}/responses/${key}-${column}.svg`);
        if (!response.ok) throw new Error("Figure unavailable");
        return `<div class="response-panel">${await response.text()}</div>`;
      }));
      if (number !== requestNumber) return; // A newer selection wins a slow fetch.
      byId("response-chart").innerHTML = figures.join("");
      responseSummary();
      applyModelSelection();
      byId("chart-announcement").textContent = `Response figures updated to ${state.name}.`;
    } catch (error) {
      if (number !== requestNumber) return;
      byId("response-chart").innerHTML = "";
      byId("response-means").innerHTML = "";
      byId("chart-announcement").textContent = `Could not load ${state.name}: ${error.message}`;
    }
  }

  function changeValidationState() {
    const key = byId("validation-state").value;
    const state = history.states[key];
    // The table follows the same state selector as the distribution plots.
    byId("validation-comparison-caption").textContent = `${state.name}: TVD by cohort size`;
    byId("validation-comparison-body").innerHTML = history.features.map(feature => {
      const cells = [25, 50, 100].map(size =>
        `<td>${state.validation_cohorts[size][feature.key].toFixed(3)}</td>`).join("");
      return `<tr><th scope="row">${esc(feature.name)}</th>${cells}</tr>`;
    }).join("");
    document.querySelectorAll("[data-feature]").forEach(img => {
      img.src = `${history.validation_prefix}/${key}-${img.dataset.feature}.svg`;
      img.alt = `${state.name}: ${img.dataset.feature} persona distribution versus weighted CES reference`;
    });
    document.querySelectorAll("[data-metric]").forEach(label => {
      const metric = state.validation[label.dataset.metric];
      label.textContent = `TV ${(metric.tv * 100).toFixed(1)}% · Largest gap ${metric.max_gap_pp.toFixed(1)} pp`;
    });
  }

  function changeOverviewDate() {
    const selection = byId("overview-date").value;
    const view = history.overview[selection];
    document.querySelectorAll("[data-state]").forEach(img => {
      img.src = `${view.prefix}/${img.dataset.state}.svg`;
      img.alt = `${history.states[img.dataset.state].name}: ${view.label}; all study models`;
    });
    byId("overview-asof").textContent = view.label;
  }

  async function initialize() {
    try {
      const response = await fetch("data/history.json");
      if (!response.ok) throw new Error("Prepared history unavailable");
      history = await response.json();
      byId("response-state").addEventListener("change", changeResponseState);
      byId("validation-state").addEventListener("change", changeValidationState);
      byId("overview-date").addEventListener("change", changeOverviewDate);
      byId("evaluation-state")?.addEventListener("change", () => {
        const state = byId("evaluation-state").value;
        document.querySelectorAll("[data-evaluation-state]").forEach(section => {
          section.hidden = section.dataset.evaluationState !== state;
        });
      });
      document.querySelectorAll("[data-model-toggle]").forEach(input => input.addEventListener("change", applyModelSelection));
      responseSummary();
      applyModelSelection();
    } catch (error) {
      byId("chart-announcement").textContent = error.message;
    }
  }
  initialize();
})();
