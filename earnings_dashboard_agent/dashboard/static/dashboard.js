const $ = (selector) => document.querySelector(selector);
const tableBody = $('#stock-rows');
const statusLine = $('#status');
const lastUpdated = $('#last-updated');

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
}
function valueOf(entry) {
  if (entry === null || entry === undefined) return 'N/A';
  if (typeof entry === 'object' && Object.hasOwn(entry, 'value')) {
    const value = entry.value;
    if (value === 'N/A' || value === null || value === undefined) return 'N/A';
    if (typeof value === 'object') return Object.entries(value).map(([key, part]) => `${key}: ${part}`).join(' · ');
    return String(value);
  }
  return String(entry);
}
function display(entry) {
  const text = valueOf(entry);
  const source = entry && typeof entry === 'object' ? [entry.source, entry.observed_at].filter(Boolean).join(' | ') : 'Source not available';
  return `<span class="${text === 'N/A' ? 'na' : ''}" title="${escapeHtml(source)}">${escapeHtml(text)}</span>`;
}
function metricGroup(group, keys) { return keys.map((key) => `<div><b>${key.toUpperCase()}</b> ${display(group?.[key])}</div>`).join(''); }
function renderRows(rows) {
  const sortKey = $('#sort-filter').value;
  rows = rows.slice().sort((left, right) => {
    if (left.priority !== right.priority) return left.priority === 'A' ? -1 : 1;
    if (sortKey === 'company') return left.company.localeCompare(right.company);
    return left.symbol.localeCompare(right.symbol);
  });
  tableBody.innerHTML = rows.map((row) => {
    const technical = row.technical || {}, returns = row.post_results_returns || {}, scenario = row.reaction_scenario || {};
    return `<tr class="${row.priority === 'A' ? 'priority-a' : ''}">
      <td><a class="symbol-link" href="/stocks/${encodeURIComponent(row.symbol)}">${escapeHtml(row.exchange)}:${escapeHtml(row.symbol)}</a><span class="company">${escapeHtml(row.company)}</span><span class="priority ${row.priority === 'A' ? 'a' : ''}">Priority ${escapeHtml(row.priority)}</span></td>
      <td>${display(row.announcement_date)}</td><td>${metricGroup(row.previous_quarter,['revenue','ebitda','pat'])}</td>
      <td>${metricGroup(row.consensus,['revenue','ebitda','pat','eps'])}</td><td>${metricGroup(row.actual_results,['revenue','ebitda','pat','eps'])}</td>
      <td>${metricGroup(row.surprise_pct,['revenue','ebitda','pat','eps'])}</td><td>${display(row.beat_miss_history)}</td><td>${display(row.guidance)}</td>
      <td>${display(row.pre_results_close)}</td><td><div>1D ${display(returns.one_day)}</div><div>5D ${display(returns.five_day)}</div></td>
      <td><div>RVOL ${display(technical.relative_volume)}</div><div>RSI ${display(technical.rsi_14)}</div><div>ADX ${display(technical.adx_14)}</div><div>VWAP ${display(technical.session_vwap)}</div></td>
      <td><span class="scenario">${escapeHtml(scenario.label || 'N/A')}</span><div class="view">${escapeHtml(scenario.commentary || scenario.view || '')}</div></td><td>${display(row.investment_view)}</td>
    </tr>`;
  }).join('');
  statusLine.textContent = `${rows.length} stocks · ${rows.filter((row) => row.priority === 'A').length} Priority A`;
  lastUpdated.textContent = `Snapshot ${new Date().toLocaleTimeString()}`;
}
async function loadStocks() {
  const params = new URLSearchParams();
  if ($('#priority-filter').value) params.set('priority', $('#priority-filter').value);
  if ($('#search').value.trim()) params.set('search', $('#search').value.trim());
  try {
    const response = await fetch(`/api/stocks?${params}`);
    if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
    renderRows((await response.json()).stocks);
  } catch (error) { statusLine.textContent = `Could not load data: ${error.message}`; }
}
$('#priority-filter').addEventListener('change', loadStocks);
$('#sort-filter').addEventListener('change', loadStocks);
$('#search').addEventListener('input', loadStocks);
$('#refresh').addEventListener('click', async () => {
  $('#refresh').disabled = true;
  statusLine.textContent = 'Refresh queued; external sources may take a few minutes.';
  try { await fetch('/api/refresh', {method:'POST'}); window.setTimeout(loadStocks, 4000); }
  finally { window.setTimeout(() => { $('#refresh').disabled = false; }, 2000); }
});
loadStocks();
window.setInterval(loadStocks, 5 * 60 * 1000);