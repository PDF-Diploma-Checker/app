async function load() {
  const status = document.querySelector('#status');
  const queue = document.querySelector('#queue');
  try {
    const response = await fetch('/admin/queue');
    if (!response.ok) throw new Error(`Queue unavailable (${response.status})`);
    const rows = await response.json();
    queue.replaceChildren();
    status.textContent = rows.length ? `${rows.length} pending (oldest first, up to 200)` : 'No pending proposals';
    for (const row of rows) {
      const item = document.createElement('p');
      const label = document.createElement('span');
      label.textContent = `${row.word} — ${row.created} `;
      item.append(label);
      for (const decision of ['approved', 'rejected']) {
        const button = document.createElement('button');
        button.textContent = decision === 'approved' ? 'Approve' : 'Reject';
        button.onclick = async () => {
          item.querySelectorAll('button').forEach(b => b.disabled = true);
          try {
            const result = await fetch('/admin/review', {
              method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dictionary-Review': '1'},
              body: JSON.stringify({id: row.id, decision})
            });
            if (!result.ok) throw new Error(`Review failed (${result.status}); refresh the queue`);
            await load();
          } catch (error) {
            status.textContent = error.message;
            item.querySelectorAll('button').forEach(b => b.disabled = false);
          }
        };
        item.append(button);
      }
      queue.append(item);
    }
  } catch (error) { status.textContent = error.message; }
}
document.querySelector('#refresh').onclick = load;
load();
