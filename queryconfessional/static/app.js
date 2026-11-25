'use strict';
const $ = id => document.getElementById(id);
let accessToken = '';
let loading = false;
const num = n => Number(n).toLocaleString();
const date = stamp => stamp == null ? '—' : new Date(stamp * 1000).toLocaleString();
function params() {
  const values = new URLSearchParams();
  for (const name of ['device', 'domain', 'qtype']) if ($(name).value) values.set(name, $(name).value);
  for (const name of ['after', 'before']) if ($(name).value) values.set(name, new Date($(name).value).toISOString());
  return values;
}
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
async function request(url) {
  const result = await fetch(url, {headers: accessToken ? {Authorization: `Bearer ${accessToken}`} : {}});
  if (result.status === 401) { $('login').hidden = false; throw new Error('Enter the server access token to view private data.'); }
  if (!result.ok) { const data = await result.json(); throw new Error(data.error || 'Request failed'); }
  $('login').hidden = true;
  return result;
}
function options(id, values, label) {
  const current = $(id).value;
  const first = new Option(label, '');
  $(id).replaceChildren(first, ...values.map(value => new Option(value, value)));
  if (values.includes(current)) $(id).value = current;
}
function cell(value, click) {
  const td = document.createElement('td');
  if (click) { const button = document.createElement('button'); button.className = 'cell-button'; button.type = 'button'; button.textContent = value; button.addEventListener('click', click); td.append(button); }
  else td.textContent = value;
  return td;
}
function table(id, rows, build) {
  $(id).replaceChildren(...rows.map(row => { const tr = document.createElement('tr'); tr.append(...build(row)); return tr; }));
}
async function refresh() {
  if (loading) return;
  loading = true; error(''); $('status').textContent = 'Reading local inventory…';
  try {
    const data = await (await request(`/api/dashboard?${params()}`)).json();
    options('device', data.all_devices, 'All devices'); options('qtype', data.all_types, 'All types');
    for (const name of ['queries', 'devices', 'domains']) $(`count-${name}`).textContent = num(data.stats[name]);
    $('empty').hidden = data.stats.queries !== 0;
    $('coverage').textContent = data.stats.queries ? `Matching records: ${date(data.stats.first)} to ${date(data.stats.last)}. Table times use your browser timezone.` : '';
    $('status').textContent = data.last_import ? `Last import: ${new Date(data.last_import).toLocaleString()}. Data changes only when you import logs.` : 'No logs have been imported yet.';
    table('domains', data.domains, row => [cell(row.domain, () => { $('domain').value = row.domain; refresh(); }), cell(num(row.queries)), cell(num(row.devices)), cell(date(row.last))]);
    table('devices', data.devices, row => [cell(row.device, () => { $('device').value = row.device; refresh(); }), cell(num(row.queries)), cell(num(row.domains)), cell(date(row.last))]);
    table('recent', data.recent, row => [cell(date(row.timestamp)), cell(row.device), cell(row.domain), cell(row.qtype)]);
    const max = Math.max(1, ...data.activity.map(day => day.queries));
    $('activity').replaceChildren(...data.activity.map(day => {
      const box = document.createElement('div'); box.className = 'day';
      const label = document.createElement('span'); label.textContent = day.day;
      const count = document.createElement('strong'); count.textContent = num(day.queries);
      const meter = document.createElement('meter'); meter.min = 0; meter.max = max; meter.value = day.queries; meter.setAttribute('aria-label', `${day.day}: ${num(day.queries)} queries`);
      box.append(label, count, meter); return box;
    }));
  } catch (e) { error(e.message); $('status').textContent = 'Could not update the inventory. Existing results may reflect earlier filters.'; }
  finally { loading = false; }
}
$('filters').addEventListener('submit', event => { event.preventDefault(); refresh(); });
$('reset').addEventListener('click', () => { $('filters').reset(); refresh(); });
$('unlock').addEventListener('click', () => { accessToken = $('token').value; $('token').value = ''; refresh(); });
$('export').addEventListener('click', async () => {
  error('');
  try {
    const response = await request(`/api/export.csv?${params()}`);
    const objectURL = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = objectURL; link.download = 'dns-queries.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
  } catch (e) { error(e.message); }
});
refresh();
