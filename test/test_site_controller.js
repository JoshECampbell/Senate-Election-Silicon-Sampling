/* Tests run:
 * - Check state selectors, daily summaries, model toggles and historical overview paths.
 * - Keep response, validation and overview controls independent.
 * - Reject stale fetch results and clear old data when a fetch fails.
 * Uses prepared local assets and a minimal DOM substitute; no network requests.
 * Usage: deno run --no-config --allow-read=docs test/test_site_controller.js
 */
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const history = JSON.parse(Deno.readTextFileSync("docs/data/history.json"));
const element = (props = {}) => ({ textContent:"", innerHTML:"", hidden:false, style:{}, dataset:{},
  listeners:{}, addEventListener(name, fn) { this.listeners[name] = fn; }, ...props });
const keys = Object.keys(history.models);
const groups = keys.map(key => element({dataset:{model:key}}));
const rows = keys.map(key => element({dataset:{model:key}}));
const ids = Object.fromEntries(["response-chart","model-empty","odds-status",
  "chart-announcement","overview-asof","response-means"].map(key => [key,element()]));
ids["response-state"] = element({value:"georgia"});
ids["validation-state"] = element({value:"alabama"});
ids["overview-date"] = element({value:"latest"});
ids["response-chart"].querySelectorAll = () => groups;
ids["response-means"].querySelectorAll = () => rows;
const toggles = keys.map(key => element({checked:true,dataset:{modelToggle:key}}));
const summary = element();
const images = history.features.map(f => element({dataset:{feature:f.key},src:`${history.validation_prefix}/alabama-${f.key}.svg`}));
const metrics = history.features.map(f => element({dataset:{metric:f.key}}));
const overview = Object.keys(history.states).map(key => element({dataset:{state:key},src:`${history.overview.latest.prefix}/${key}.svg`}));
globalThis.document = {
  getElementById(id) { assert(id in ids, `Unexpected element: ${id}`); return ids[id]; },
  querySelector(selector) { assert(selector === ".accessible-summary",selector); return summary; },
  querySelectorAll(selector) {
    const table = {"[data-model-toggle]":toggles,"[data-model-toggle]:checked":toggles.filter(t => t.checked),
      "[data-feature]":images,"[data-metric]":metrics,"[data-state]":overview};
    assert(selector in table,`Unexpected section selector: ${selector}`); return table[selector];
  }
};
let fail = false;
let holdAlaska = false;
let release;
const fetched = [];
globalThis.fetch = async path => {
  assert(path === "data/history.json" || path.startsWith(`figures/${history.date}/responses/`),`Unexpected request: ${path}`);
  fetched.push(path);
  if (holdAlaska && path.includes("alaska-p_democrat")) await new Promise(resolve => { release=resolve; });
  return {ok:!fail,json:async () => history,text:async () => Deno.readTextFileSync(`docs/${path}`)};
};
new Function(Deno.readTextFileSync("docs/assets/site.js"))();
for (let i=0;i<12;i++) await Promise.resolve();
assert(typeof ids["response-state"].listeners.change === "function","Controls not initialized");
assert(ids["response-means"].innerHTML.includes("Perplexity"),"Model means not initialized");
for (const day of history.dates) assert(ids["response-means"].innerHTML.includes(day),"Historical mean missing");
ids["response-state"].value="alaska";
await ids["response-state"].listeners.change();
assert(ids["response-chart"].innerHTML.includes("Alaska"),"State chart did not update");
assert(fetched.filter(p => p.startsWith("figures/")).length===4,"Expected four panels");
assert(images.every(img => img.src.includes("alabama")),"Response selector changed validation");
const originalGrid = overview.map(img => img.src).join();
toggles[1].checked=false;
toggles[1].listeners.change();
assert(groups[1].style.display==="none" && rows[1].style.display==="none","Model toggle failed");
assert(groups[0].style.display==="","Other model unexpectedly hidden");
assert(overview.map(img => img.src).join()===originalGrid,"Toggle changed the state grid");
for (const t of toggles) t.checked=false;
toggles[0].listeners.change();
assert(ids["response-chart"].hidden && summary.hidden && !ids["model-empty"].hidden,"Empty selection failed");
for (const t of toggles) t.checked=true;
toggles[0].listeners.change();
ids["overview-date"].value=history.dates[0];
ids["overview-date"].listeners.change();
assert(overview.length===35 && overview.every(img => img.src.includes(`/${history.dates[0]}/states/`)),"Historical overview failed");
assert(ids["response-state"].value==="alaska","Grid changed the time-series state");
ids["overview-date"].value="latest";
ids["overview-date"].listeners.change();
assert(overview.every(img => img.src.startsWith(history.overview.latest.prefix+"/")),"Latest overview failed");
ids["validation-state"].value="wyoming";
ids["validation-state"].listeners.change();
assert(images.length===5 && images.every(img => img.src.includes("wyoming")),"Validation coverage failed");
assert(ids["response-state"].value==="alaska","Validation changed response state");
// Resolve an old request last. The newer state and table must remain visible.
holdAlaska=true;
const old=ids["response-state"].listeners.change();
ids["response-state"].value="georgia";
await ids["response-state"].listeners.change();
release(); await old;
assert(ids["response-chart"].innerHTML.includes("Georgia"),"A stale fetch replaced the newer state");
holdAlaska=false; fail=true;
ids["response-state"].value="alaska";
await ids["response-state"].listeners.change();
assert(ids["response-chart"].innerHTML==="" && ids["response-means"].innerHTML==="","Failed fetch left stale data");
assert(ids["chart-announcement"].textContent.includes("Could not load"),"Failure was not announced");
console.log("Controller checks passed: configured models and benchmark, daily means, dated grid, all validation fields, section isolation, stale fetches and failure handling. No network calls.");
