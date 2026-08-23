import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { catalogAll } from "../api";

function formatCategoryName(category) {
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function CatalogView() {
  const [grouped, setGrouped] = useState(null);
  const [error, setError] = useState(false);
  const navigate = useNavigate();

  // Pure UI convenience: composes a natural-language message and hands it
  // to the Chat view as pre-filled (unsent) input. From there it's just a
  // normal chat message — same classifier, same recommend()/confirm/
  // gate/order pipeline as anything the buyer types themselves. No new
  // backend logic, no special-casing.
  function askAboutProduct(product) {
    navigate("/", { state: { prefillMessage: `Tell me about the ${product.name}` } });
  }

  useEffect(() => {
    let cancelled = false;
    catalogAll()
      .then((data) => {
        if (!cancelled) setGrouped(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="catalog">
        <p className="loading">Couldn't load the catalog. Is the server running?</p>
      </main>
    );
  }

  if (!grouped) {
    return (
      <main className="catalog">
        <p className="loading">Loading catalog…</p>
      </main>
    );
  }

  const categories = Object.keys(grouped).sort();

  return (
    <main className="catalog">
      {categories.length === 0 && <p className="loading">No products found.</p>}
      {categories.map((category) => (
        <section className="category-section" key={category}>
          <h2 className="category-heading">{formatCategoryName(category)}</h2>
          <div className="product-grid">
            {grouped[category].map((product) => (
              <div className="product-card" key={product.id}>
                <h3 className="product-name">{product.name}</h3>
                <div className="product-price">Rs.{(product.price_paise / 100).toFixed(2)}</div>
                <div className="product-stock">Stock: {product.stock}</div>
                <p className="product-spec">{product.spec}</p>
                <button className="ask-about-btn" onClick={() => askAboutProduct(product)}>
                  Ask about this →
                </button>
              </div>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
