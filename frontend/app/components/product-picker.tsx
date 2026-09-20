"use client";

import { formatEur, type CategoryNode, type Product } from "@/lib/api";
import { CheckIcon } from "@/app/components/icons";

type ProductPickerProps = {
  products: Product[];
  selection: Record<number, number>;
  search: string;
  categoryId: number | null;
  categoryTree: CategoryNode[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  onSearchChange: (value: string) => void;
  onCategoryChange: (value: number | null) => void;
  onPageChange: (page: number) => void;
  onToggle: (productId: number) => void;
  onQuantityChange: (productId: number, quantity: number) => void;
};

export function ProductPicker({
  products,
  selection,
  search,
  categoryId,
  categoryTree,
  total,
  page,
  pageSize,
  loading,
  onSearchChange,
  onCategoryChange,
  onPageChange,
  onToggle,
  onQuantityChange,
}: ProductPickerProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const selectedTopLevel = categoryTree.find((node) =>
    node.id === categoryId || node.children.some((child) => child.id === categoryId),
  );
  const selectedTopLevelId = selectedTopLevel?.id ?? null;

  return (
    <fieldset className="product-fieldset">
      <legend>Izberite izdelke</legend>
      <div className="picker-heading">
        <div>
          <span className="eyebrow">1. Košarica</span>
          <h2>Sestavite nakup</h2>
        </div>
        <div className="catalog-filters">
          <label className="search-field">
            <span className="sr-only">Išči med izdelki</span>
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <circle cx="8.5" cy="8.5" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="m12.3 12.3 4 4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
            </svg>
            <input
              type="search"
              value={search}
              maxLength={100}
              placeholder="Išči izdelek …"
              onChange={(event) => onSearchChange(event.target.value)}
            />
          </label>
        </div>
      </div>

      <div className="category-navigation" role="group" aria-label="Filtriranje po kategoriji">
        <label className="category-field" htmlFor="top-level-category">
          <span>Glavna kategorija</span>
          <select
            id="top-level-category"
            value={selectedTopLevelId ?? ""}
            disabled={categoryTree.length === 0}
            onChange={(event) => onCategoryChange(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">
              Vse kategorije ({categoryTree.reduce((sum, node) => sum + node.productCount, 0)})
            </option>
            {categoryTree.map((node) => (
              <option key={node.id} value={node.id}>{node.name} ({node.productCount})</option>
            ))}
          </select>
        </label>
        {selectedTopLevel && selectedTopLevel.children.length > 0 && (
          <label className="category-field" htmlFor="subcategory">
            <span>Podkategorija</span>
            <select
              id="subcategory"
              value={categoryId ?? selectedTopLevel.id}
              onChange={(event) => onCategoryChange(Number(event.target.value))}
            >
              <option value={selectedTopLevel.id}>
                Vse v {selectedTopLevel.name} ({selectedTopLevel.productCount})
              </option>
              {selectedTopLevel.children.map((node) => (
                <option key={node.id} value={node.id}>{node.name} ({node.productCount})</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {loading && <p className="catalog-loading" role="status">Osvežujem izdelke …</p>}
      {products.length === 0 ? (
        <p className="inline-empty">Za ta iskalni niz ni izdelkov.</p>
      ) : (
        <div className="product-grid">
          {products.map((product) => {
            const quantity = selection[product.id];
            const selected = quantity !== undefined;
            const detailsId = `product-details-${product.id}`;
            const category = product.categoryPath.length
              ? product.categoryPath.join(" / ")
              : product.category;
            return (
              <article className={`product-card${selected ? " is-selected" : ""}`} key={product.id}>
                <label className="product-select">
                  <input
                    type="checkbox"
                    checked={selected}
                    aria-describedby={detailsId}
                    onChange={() => onToggle(product.id)}
                  />
                  <span className="custom-check" aria-hidden="true"><CheckIcon /></span>
                  <span className="product-copy">
                    <strong>{product.name}</strong>
                    <small>{[category, product.unit].filter(Boolean).join(" · ") || "Izdelek"}</small>
                  </span>
                </label>

                <div className="product-details" id={detailsId} role="tooltip">
                  <strong>{product.name}</strong>
                  {product.offers.length ? (
                    <>
                      <p>Aktualne cene po trgovinah</p>
                      <ul className="product-offers">
                        {product.offers.map((offer, index) => (
                          <li key={offer.storeId} className={index === 0 ? "is-cheapest" : ""}>
                            <span>{offer.store}</span>
                            <b>{formatEur(offer.price)}</b>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p>Cena trenutno ni na voljo.</p>
                  )}
                </div>

                {selected && (
                  <div className="quantity-control">
                    <button
                      type="button"
                      aria-label={`Zmanjšaj količino: ${product.name}`}
                      disabled={quantity <= 1}
                      onClick={() => onQuantityChange(product.id, quantity - 1)}
                    >
                      −
                    </button>
                    <label>
                      <span className="sr-only">Količina za {product.name}</span>
                      <input
                        type="number"
                        min="1"
                        max="99"
                        inputMode="numeric"
                        value={quantity}
                        onChange={(event) =>
                          onQuantityChange(product.id, Math.min(99, Math.max(1, event.currentTarget.valueAsNumber || 1)))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      aria-label={`Povečaj količino: ${product.name}`}
                      disabled={quantity >= 99}
                      onClick={() => onQuantityChange(product.id, quantity + 1)}
                    >
                      +
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
      {total > 0 && (
        <nav className="catalog-pagination" aria-label="Strani izdelkov">
          <button type="button" disabled={page === 0 || loading} onClick={() => onPageChange(page - 1)}>
            Prejšnja
          </button>
          <span>Stran {page + 1} od {pageCount} · {total} izdelkov</span>
          <button
            type="button"
            disabled={page + 1 >= pageCount || loading}
            onClick={() => onPageChange(page + 1)}
          >
            Naslednja
          </button>
        </nav>
      )}
    </fieldset>
  );
}
