function formatCategoryName(category) {
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function renderProductCard(product) {
  const card = document.createElement("div");
  card.className = "product-card";

  const name = document.createElement("h3");
  name.className = "product-name";
  name.textContent = product.name;

  const price = document.createElement("div");
  price.className = "product-price";
  price.textContent = `Rs.${(product.price_paise / 100).toFixed(2)}`;

  const stock = document.createElement("div");
  stock.className = "product-stock";
  stock.textContent = `Stock: ${product.stock}`;

  const spec = document.createElement("p");
  spec.className = "product-spec";
  spec.textContent = product.spec;

  card.appendChild(name);
  card.appendChild(price);
  card.appendChild(stock);
  card.appendChild(spec);
  return card;
}

async function loadCatalog() {
  const container = document.getElementById("catalog");
  container.innerHTML = "<p class='loading'>Loading catalog…</p>";

  try {
    const resp = await fetch("/catalog/all");
    if (!resp.ok) throw new Error(`status ${resp.status}`);
    const grouped = await resp.json();

    container.innerHTML = "";
    const categories = Object.keys(grouped).sort();

    if (categories.length === 0) {
      container.innerHTML = "<p class='loading'>No products found.</p>";
      return;
    }

    for (const category of categories) {
      const section = document.createElement("section");
      section.className = "category-section";

      const heading = document.createElement("h2");
      heading.className = "category-heading";
      heading.textContent = formatCategoryName(category);
      section.appendChild(heading);

      const grid = document.createElement("div");
      grid.className = "product-grid";
      for (const product of grouped[category]) {
        grid.appendChild(renderProductCard(product));
      }
      section.appendChild(grid);

      container.appendChild(section);
    }
  } catch (err) {
    container.innerHTML = "<p class='loading'>Couldn't load the catalog. Is the server running?</p>";
  }
}

loadCatalog();
