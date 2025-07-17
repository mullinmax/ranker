document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.stats-table').forEach(table => {
    const ths = table.querySelectorAll('th');
    ths.forEach((th, index) => {
      th.classList.add('sortable');
      th.insertAdjacentHTML('beforeend', '<span class="sort-arrow"></span>');
      th.addEventListener('click', () => sortTable(table, index, th.dataset.type));
    });
  });
});

function sortTable(table, col, type) {
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const ths = table.querySelectorAll('th');
  const th = ths[col];
  const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
  th.dataset.dir = dir;
  ths.forEach((header,i) => { if(i !== col) header.removeAttribute('data-dir'); });
  rows.sort((a, b) => {
    let x = a.children[col].textContent.trim();
    let y = b.children[col].textContent.trim();
    if (type === 'number') {
      x = parseFloat(x) || 0;
      y = parseFloat(y) || 0;
    }
    if (x > y) return dir === 'asc' ? 1 : -1;
    if (x < y) return dir === 'asc' ? -1 : 1;
    return 0;
  });
  rows.forEach(r => tbody.appendChild(r));
  ths.forEach(header => {
    const arrow = header.querySelector('.sort-arrow');
    if(!arrow) return;
    if(header.dataset.dir === 'asc') arrow.textContent = '▲';
    else if(header.dataset.dir === 'desc') arrow.textContent = '▼';
    else arrow.textContent = '';
  });
}
