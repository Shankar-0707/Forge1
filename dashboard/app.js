// app.js - Premium Live Cockpit

const $ = (id) => document.getElementById(id);
function set(id, v) { 
  const el = $(id); 
  if (el && el.textContent !== String(v)) {
    if (el.hasAttribute('data-val')) {
      const start = parseInt(el.getAttribute('data-val') || 0, 10);
      const end = parseInt(v || 0, 10);
      if (!isNaN(start) && !isNaN(end) && start !== end) {
        animateValue(el, start, end, 500);
      } else {
        el.textContent = v;
      }
    } else {
      el.textContent = (v === undefined || v === null) ? "0" : v; 
    }
  }
}

function animateValue(obj, start, end, duration) {
  let startTimestamp = null;
  const step = (timestamp) => {
    if (!startTimestamp) startTimestamp = timestamp;
    const progress = Math.min((timestamp - startTimestamp) / duration, 1);
    obj.innerHTML = Math.floor(progress * (end - start) + start);
    if (progress < 1) {
      window.requestAnimationFrame(step);
    } else {
      obj.setAttribute('data-val', end);
    }
  };
  window.requestAnimationFrame(step);
}

function pathOnly(url) {
  if(!url) return "";
  try {
    if(!url.startsWith('http')) url = 'http://' + url;
    const u = new URL(url);
    let p = u.pathname;
    if(p.length > 40) p = p.substring(0, 15) + "..." + p.substring(p.length - 20);
    return p;
  } catch(e) { return url; }
}

function updatePipeline(stageId) {
  const stages = ['st-load', 'st-graph', 'st-anchors', 'st-topics', 'st-entities', 'st-recommendations', 'st-saved'];
  let found = false;
  for(let id of stages) {
    const el = $(id);
    if(!el) continue;
    if(id === stageId) {
      el.className = 'stage active';
      found = true;
    } else if(!found) {
      el.className = 'stage done';
    } else {
      el.className = 'stage';
    }
  }
  if(stageId === 'st-saved') {
    $('st-saved').className = 'stage done';
    const d = $('main-dot');
    if(d) d.className = 'dot done';
  }
}

let runStartTime = null;

function paint(RUN) {
  if(!RUN) return;
  if(RUN.site) set("site", RUN.site);
  if(RUN.status) set("status", RUN.status);
  
  if(!runStartTime && RUN.status !== 'idle') {
    runStartTime = Date.now();
    setInterval(() => {
      if(RUN.status === 'done') return;
      const s = Math.floor((Date.now() - runStartTime)/1000);
      const m = Math.floor(s / 60);
      set("uptime", `${m.toString().padStart(2,'0')}:${(s%60).toString().padStart(2,'0')}`);
    }, 1000);
  }

  const g = RUN.graph_stats, a = RUN.anchors, e = RUN.entities, s = RUN.summary;
  if(g) {
    set("k-links", g.internal_links); set("k-orphans", g.orphan_pages);
    set("k-broken", g.broken_internal_links);
    set("g-pages", g.pages_total); set("g-idx", g.pages_indexable);
    set("g-depth", g.max_crawl_depth); set("g-avg", g.avg_inlinks);
    set("g-deep", g.deepest_pages); set("g-under", g.under_linked_pages);
    set("g-over", g.over_linked_pages); set("g-redir", g.redirect_internal_links);
    set("g-nofol", g.nofollow_internal_links);

    if(RUN.broken_links_list && RUN.broken_links_list.length > 0) {
      let h = `<div class="table-wrapper"><table><tr><th>Source</th><th>Destination</th><th>Status</th></tr>`;
      RUN.broken_links_list.slice(0, 20).forEach(l => {
        const sc = l.status;
        const color = sc >= 500 ? 'var(--dark-red)' : 'var(--red)';
        h += `<tr><td class="truncate" title="${l.source}">${pathOnly(l.source)}</td><td class="truncate" title="${l.destination}">${pathOnly(l.destination)}</td><td style="color:${color};font-weight:bold">${sc}</td></tr>`;
      });
      h += `</table></div>`;
      $("broken-links").innerHTML = h;
    }
  }

  if(a) {
    set("k-generic", a.generic); set("a-total", a.total);
    set("a-generic", a.generic); set("a-empty", a.empty_or_image_only);
    set("a-over", a.over_optimized);
    
    if(RUN.generic_list || RUN.over_optimized_list) {
      let h = `<div class="table-wrapper"><table><tr><th>Type</th><th>Source</th><th>Anchor Text</th></tr>`;
      if(RUN.over_optimized_list) {
        RUN.over_optimized_list.slice(0, 10).forEach(l => {
          h += `<tr><td><span class="tag hub">Over-Opt</span></td><td class="truncate" title="${l.source}">${pathOnly(l.source)}</td><td><b>${l.anchor}</b></td></tr>`;
        });
      }
      if(RUN.generic_list) {
        RUN.generic_list.slice(0, 10).forEach(l => {
          h += `<tr><td><span class="tag scattered">Generic</span></td><td class="truncate" title="${l.source}">${pathOnly(l.source)}</td><td>${l.anchor}</td></tr>`;
        });
      }
      h += `</table></div>`;
      $("anchor-issues").innerHTML = h;
    }
  }

  if(e) { set("e-pages", e.pages_with_entities); }
  if(RUN.model_calls) { set("e-calls", RUN.model_calls); }

  if(RUN.clusters) {
    set("k-clusters", RUN.clusters.length);
    const maxSz = Math.max(...RUN.clusters.map(c => c.size), 1);
    const html = RUN.clusters.map(c => {
      const w = Math.max((c.size / maxSz) * 100, 2);
      return `<div class="cl">
        <div>
          <strong>${c.name || c.key}</strong>
          <div class="bar-chart"><div class="bar-fill" style="width:${w}%"></div></div>
        </div>
        <div style="text-align:right">
          <span class="st">${c.size} pgs</span><br/>
          <span class="tag ${c.authority}">${c.authority}</span>
        </div>
      </div>`;
    }).join("");
    $("clusters").innerHTML = html || '<div class="empty">No clusters yet.</div>';
  }

  if(RUN.recommendations !== undefined && RUN.recommendations !== null) {
    set("k-recs", typeof RUN.recommendations === "number" ? RUN.recommendations : RUN.recommendations);
  }
  if(s) set("k-recs", s.link_recommendations);

  if(RUN.recs_list && RUN.recs_list.length > 0) {
    let h = `<div class="table-wrapper"><table>
      <tr><th>Source</th><th>Target</th><th>Anchor</th><th>Rel</th><th>Reason</th></tr>`;
    RUN.recs_list.slice(0, 30).forEach(r => {
      h += `<tr>
        <td class="truncate mono" title="${r.source}">${pathOnly(r.source)}</td>
        <td class="truncate mono" title="${r.target}">${pathOnly(r.target)}</td>
        <td><span class="badge">${r.suggested_anchor || '(none)'}</span></td>
        <td>${r.relatedness ? r.relatedness.toFixed(2) : ''}</td>
        <td class="st truncate" title="${r.reason}">${r.reason}</td>
      </tr>`;
    });
    h += `</table></div>`;
    $("recs").innerHTML = h;
  }
}

function feed(line, type="info") {
  const f = $("feed"); if(!f) return;
  const d = document.createElement("div");
  d.className = "feed-item";
  
  const time = document.createElement("div");
  time.className = "feed-time";
  time.textContent = new Date().toLocaleTimeString();
  
  const dot = document.createElement("div");
  dot.className = `f-dot ${type}`;
  
  const text = document.createElement("div");
  text.textContent = line;
  
  d.appendChild(time);
  d.appendChild(dot);
  d.appendChild(text);
  
  f.prepend(d);
  while(f.childNodes.length > 100) f.removeChild(f.lastChild);
}

let RUN = {};
function onEvent(evt){
  const { event, data } = evt;
  if(event === "snapshot"){ RUN = Object.assign({}, RUN, data || {}); paint(RUN); feed("Connected to live telemetry", "success"); return; }
  
  if(event === "loaded"){ RUN.site = data.site; RUN.urls = data.urls; feed(`Loaded ${data.urls} pages`, "success"); updatePipeline('st-graph'); }
  if(event === "graph"){ RUN.graph_stats = data; feed(`Graph built: ${data.orphan_pages.length} orphans, ${data.broken_internal_links} broken`); updatePipeline('st-anchors'); }
  if(event === "anchors"){ RUN.anchors = data; feed(`Anchor analysis: ${data.generic} generic anchors`); updatePipeline('st-topics'); }
  if(event === "topics"){ RUN.clusters = data.clusters; feed(`Clustering: Formed ${data.clusters.length} topical clusters`); updatePipeline('st-entities'); }
  if(event === "entities"){ RUN.entities = data; feed(`Entity extraction: Processed ${data.pages_with_entities} pages`); }
  if(event === "enrichment"){ feed(`Enrichment [${data.stage}]: ${data.detail}`, "info"); updatePipeline('st-recommendations'); }
  if(event === "recommendations"){ RUN.recommendations = data.count; feed(`Generated ${data.count} contextual link recommendations`, "success"); }
  if(event === "saved"){ RUN.status = "done"; feed("Report artifacts successfully saved", "success"); updatePipeline('st-saved'); }
  
  // Need to fetch full state to get arrays if they aren't sent in the individual payload
  if(["graph", "anchors", "entities", "recommendations", "saved"].includes(event)) {
    fetch("/state").then(r=>r.json()).then(d=>{
      RUN = Object.assign({}, RUN, d);
      paint(RUN);
    }).catch(()=>{});
  } else {
    paint(RUN);
  }
}

function connect(){
  try{
    updatePipeline('st-load');
    const es = new EventSource("/events");
    es.onmessage = (m) => { try{ onEvent(JSON.parse(m.data)); }catch(e){} };
    es.onerror = () => { es.close(); setTimeout(poll, 1500); feed("Connection lost. Retrying...", "err"); };
  }catch(e){ poll(); }
}
function poll(){
  fetch("/state").then(r=>r.json()).then(d=>{ RUN = Object.assign({}, RUN, d); paint(RUN); }).catch(()=>{});
  setTimeout(poll, 3000);
}
connect();
