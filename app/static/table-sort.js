document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.stats-table').forEach(table => {
    const ths = table.querySelectorAll('th');
    ths.forEach((th, index) => {
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => sortTable(table, index, th.dataset.type));
    });
  });
});

function sortTable(table, col, type) {
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const th = table.querySelectorAll('th')[col];
  const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
  th.dataset.dir = dir;
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
}
