(() => {
  const input = document.querySelector('#query');
  const results = document.querySelector('#results');
  if (!input || !results) return;
  const query = new URLSearchParams(location.search).get('q') || '';
  input.value = query;
  fetch('assets/search-index.json').then((response) => response.json()).then((entries) => {
    const show = (value) => {
      const term = value.trim().toLowerCase();
      results.replaceChildren(...entries.filter((item) => term && item.name.toLowerCase().includes(term)).slice(0, 20).map((item) => {
        const row = document.createElement(item.href ? 'a' : 'span');
        row.className = 'result'; row.textContent = item.name;
        if (item.href) row.href = item.href;
        const status = document.createElement('small');
        status.className = 'status'; status.textContent = item.status === 'mapped' ? 'Mapped' : 'Searchable only';
        row.append(status); return row;
      }));
    };
    input.addEventListener('input', () => show(input.value)); show(query);
  });
})();
