const $ = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const size = 100;
let source, filtered = [], page = 0;
function node(tag, attrs = {}) {
  const element = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  return element;
}
function identity(row) { return row.genre_id ?? row.artist_id; }
function select(row) {
  const support = row.training_feature_positives ?? row.feature_tracks;
  $('selected').textContent = `${row.name} — native FMA ${$('kind').value === 'genres' ? 'genre' : 'artist'} ${identity(row)}. ${support} ${$('kind').value === 'genres' ? 'training source-positive tracks' : 'native tracks with finite descriptors'}. ${row.position ? `PC1 ${row.position[0].toFixed(3)}, PC2 ${row.position[1].toFixed(3)}.` : `Position unavailable: ${row.abstention}.`}`;
  for (const point of $('map').querySelectorAll('circle')) point.classList.toggle('chosen', point.dataset.id === String(identity(row)));
}
function results() {
  const count = Math.max(1, Math.ceil(filtered.length / size));
  page = Math.max(0, Math.min(page, count - 1));
  $('results').replaceChildren();
  $('results').start = page * size + 1;
  for (const row of filtered.slice(page * size, (page + 1) * size)) {
    const item = document.createElement('li'), button = document.createElement('button');
    button.type = 'button';
    button.textContent = `${row.name} (FMA ${identity(row)})${row.position ? '' : ' — position unavailable'}`;
    button.addEventListener('click', () => select(row));
    item.append(button); $('results').append(item);
  }
  $('page').textContent = `Page ${page + 1} of ${count}`;
  $('previous').disabled = page === 0; $('next').disabled = page + 1 >= count;
}
function render() {
  const rows = source[$('kind').value];
  const query = $('search').value.normalize('NFKC').toLowerCase();
  filtered = rows.filter(row => `${row.name} ${identity(row)}`.normalize('NFKC').toLowerCase().includes(query));
  $('status').textContent = `${filtered.length} of ${rows.length} native ${$('kind').value}; ${rows.filter(row => row.position).length} positioned, ${rows.filter(row => !row.position).length} unavailable. Complete results include unavailable positions.`;
  $('map').replaceChildren();
  const positioned = rows.filter(row => row.position);
  const x = positioned.map(row => row.position[0]), y = positioned.map(row => row.position[1]);
  const xmin = Math.min(...x), xmax = Math.max(...x), ymin = Math.min(...y), ymax = Math.max(...y);
  const px = value => 55 + 900 * (value - xmin) / (xmax - xmin || 1);
  const py = value => 620 - 570 * (value - ymin) / (ymax - ymin || 1);
  $('map').append(node('line', {x1:55, y1:620, x2:955, y2:620}), node('line', {x1:55, y1:50, x2:55, y2:620}));
  for (const [label, xpos, ypos] of [['PC1', 940, 660], ['PC2', 5, 30]]) {
    const text = node('text', {x:xpos, y:ypos}); text.textContent = label; $('map').append(text);
  }
  for (const row of filtered) {
    if (!row.position) continue;
    const point = node('circle', {cx:px(row.position[0]), cy:py(row.position[1]), r:$('kind').value === 'genres' ? 4 : 2});
    point.dataset.id = String(identity(row));
    const title = node('title'); title.textContent = `${row.name} (FMA ${identity(row)})`;
    point.append(title); point.addEventListener('click', () => select(row)); $('map').append(point);
  }
  results();
}
$('controls').addEventListener('submit', event => event.preventDefault());
$('controls').addEventListener('input', () => {page = 0; if (source) render();});
$('controls').addEventListener('change', () => {page = 0; if (source) render();});
$('controls').addEventListener('reset', () => setTimeout(() => {page = 0; if (source) render();}, 0));
$('previous').addEventListener('click', () => {page--; results();});
$('next').addEventListener('click', () => {page++; results();});
document.querySelector('.skip').addEventListener('click', event => {event.preventDefault(); $('main').focus(); $('main').scrollIntoView();});
try {
  const response = await fetch('./coordinates.json');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  source = await response.json();
  $('method').textContent = JSON.stringify({axes:source.axes, training:source.pca_training, denominators:source.denominators, sensitivity:source.component_bucket_sensitivity}, null, 2);
  render();
} catch (error) { $('status').textContent = `Source map could not load: ${error.message}`; }
