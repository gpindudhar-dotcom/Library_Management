/* =====================================================
   Kalpataru Institute of Technology - Library JavaScript
   - Chart.js rendering
   - Delete confirmation
   - Table search / sort / pagination
   ===================================================== */

/* ---------- Delete confirmation ---------- */
function confirmDelete(bookId) {
  if (confirm("Are you sure you want to delete this book? This action cannot be undone.")) {
    window.location.href = "/delete_book/" + bookId;
  }
}

/* ---------- Chart.js rendering ---------- */
function renderCategoryChart(labels, data) {
  const canvas = document.getElementById("categoryChart");
  if (!canvas) return;
  return new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        label: "Books per category",
        data: data,
        backgroundColor: ["#1f4e8c", "#3a6fb5", "#0d9488", "#d97706", "#dc3545", "#6f42c1", "#198754", "#0dcaf0"],
        borderWidth: 2,
        borderColor: "#ffffff",
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderBorrowedChart(labels, data) {
  const canvas = document.getElementById("borrowedChart");
  if (!canvas) return;
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Times issued",
        data: data,
        backgroundColor: "#1f4e8c",
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } },
    },
  });
}

/* ---------- Table search / sort / pagination (books.html) ---------- */
(function () {
  const table = document.getElementById("booksTable");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const searchInput = document.getElementById("tableSearch");
  const pageSizeSelect = document.getElementById("pageSize");
  const pagination = document.getElementById("pagination");

  let currentPage = 1;
  let sortKey = null;
  let sortAsc = true;
  let filteredRows = rows;

  const colIndex = {
    book_id: 0,
    title: 1,
    author: 2,
    category: 3,
  };

  function applyFilter() {
    const q = (searchInput.value || "").trim().toLowerCase();
    filteredRows = rows.filter((row) => row.textContent.toLowerCase().includes(q));
    if (sortKey) {
      const idx = colIndex[sortKey];
      filteredRows.sort((a, b) => {
        const av = a.cells[idx].textContent.trim();
        const bv = b.cells[idx].textContent.trim();
        const cmp = av.localeCompare(bv, undefined, { numeric: true });
        return sortAsc ? cmp : -cmp;
      });
    }
    currentPage = 1;
    render();
  }

  function render() {
    const size = parseInt(pageSizeSelect.value, 10) || 10;
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / size));
    if (currentPage > totalPages) currentPage = totalPages;
    const start = (currentPage - 1) * size;
    const pageRows = filteredRows.slice(start, start + size);

    tbody.innerHTML = "";
    pageRows.forEach((row) => tbody.appendChild(row));

    if (filteredRows.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="10" class="text-center text-muted py-4">No books match your search.</td>';
      tbody.appendChild(tr);
    }

    renderPagination(totalPages);
  }

  function renderPagination(totalPages) {
    pagination.innerHTML = "";
    const prev = document.createElement("li");
    prev.className = "page-item" + (currentPage === 1 ? " disabled" : "");
    prev.innerHTML = '<a class="page-link" href="#"><i class="bi bi-chevron-left"></i></a>';
    prev.onclick = (e) => { e.preventDefault(); if (currentPage > 1) { currentPage--; render(); } };
    pagination.appendChild(prev);

    for (let i = 1; i <= totalPages; i++) {
      const li = document.createElement("li");
      li.className = "page-item" + (i === currentPage ? " active" : "");
      const a = document.createElement("a");
      a.className = "page-link";
      a.href = "#";
      a.textContent = i;
      a.onclick = (e) => { e.preventDefault(); currentPage = i; render(); };
      li.appendChild(a);
      pagination.appendChild(li);
    }

    const next = document.createElement("li");
    next.className = "page-item" + (currentPage === totalPages ? " disabled" : "");
    next.innerHTML = '<a class="page-link" href="#"><i class="bi bi-chevron-right"></i></a>';
    next.onclick = (e) => { e.preventDefault(); if (currentPage < totalPages) { currentPage++; render(); } };
    pagination.appendChild(next);
  }

  // Sortable headers
  table.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", function () {
      const key = th.getAttribute("data-sort");
      if (sortKey === key) {
        sortAsc = !sortAsc;
      } else {
        sortKey = key;
        sortAsc = true;
      }
      applyFilter();
    });
  });

  if (searchInput) searchInput.addEventListener("input", applyFilter);
  if (pageSizeSelect) pageSizeSelect.addEventListener("change", render);

  render();
})();

/* ---------- Auto-init charts on dashboard ---------- */
document.addEventListener("DOMContentLoaded", function () {
  const categoryData = document.getElementById("categoryData");
  if (categoryData) {
    try {
      const rows = JSON.parse(categoryData.textContent);
      renderCategoryChart(
        rows.map((r) => r.Category || r.category),
        rows.map((r) => r.Count || r.count)
      );
    } catch (e) {
      console.error("Could not parse category data", e);
    }
  }

  const borrowedData = document.getElementById("borrowedData");
  if (borrowedData) {
    try {
      const rows = JSON.parse(borrowedData.textContent);
      renderBorrowedChart(
        rows.map((r) => (r["Book ID"] || r.book_id) + " - " + (r["Title"] || r.title || "")),
        rows.map((r) => r["Times Issued"] || r.times_issued)
      );
    } catch (e) {
      console.error("Could not parse borrowed data", e);
    }
  }
});
