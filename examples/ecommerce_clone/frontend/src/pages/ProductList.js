import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getProducts, getCategories } from '../api';
import ProductCard from '../components/ProductCard';

const PAGE_SIZE = 12;

/** Build a compact page list with ellipsis, e.g.: 1 … 4 5 6 … 12 */
function pageWindows(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set([1, total, current]);
  for (let i = current - 2; i <= current + 2; i++) { if (i > 1 && i < total) pages.add(i); }
  const sorted = [...pages].sort((a, b) => a - b);
  const result = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) result.push('…');
    result.push(p);
    prev = p;
  }
  return result;
}

const ProductList = () => {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [loading, setLoading] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get('search') || '');
  const category = searchParams.get('category') || '';
  const page = parseInt(searchParams.get('page') || '1', 10);

  // Keep the search input in sync with the URL (e.g. back/forward navigation)
  useEffect(() => {
    setSearch(searchParams.get('search') || '');
  }, [searchParams]);

  useEffect(() => {
    setLoading(true);
    const params = { page, page_size: PAGE_SIZE };
    if (category) params.category = category;
    if (searchParams.get('search')) params.search = searchParams.get('search');

    Promise.all([
      getProducts(params),
      getCategories(),
    ]).then(([productData, catData]) => {
      if (productData && Array.isArray(productData.items)) {
        setProducts(productData.items);
        setPagination({ page: productData.page, pages: productData.pages, total: productData.total });
      } else {
        setProducts(Array.isArray(productData) ? productData : []);
      }
      setCategories(Array.isArray(catData) ? catData : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [searchParams]);

  const handleSearch = (e) => {
    e.preventDefault();
    const p = {};
    if (search.trim()) p.search = search.trim();
    if (category) p.category = category;
    // Reset to page 1 on new search
    setSearchParams(p);
  };

  const goToPage = (p) => {
    const params = {};
    if (category) params.category = category;
    if (searchParams.get('search')) params.search = searchParams.get('search');
    params.page = p;
    setSearchParams(params);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const selectCategory = (cat) => {
    const params = {};
    if (cat) params.category = cat;
    if (searchParams.get('search')) params.search = searchParams.get('search');
    setSearchParams(params);
  };

  const pages = pageWindows(page, pagination.pages);

  return (
    <div className="page">
      <h1 className="page__title">Products</h1>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="search-bar">
        <input
          type="text"
          placeholder="Search products…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="btn btn--dark">Search</button>
        {search && (
          <button type="button" className="btn btn--ghost" onClick={() => {
            setSearch('');
            const p = {};
            if (category) p.category = category;
            setSearchParams(p);
          }}>✕ Clear</button>
        )}
      </form>

      {/* Active search label */}
      {searchParams.get('search') && (
        <p className="search-label">Results for "<strong>{searchParams.get('search')}</strong>"</p>
      )}

      {/* Category pills */}
      <div className="pills">
        <button onClick={() => selectCategory('')} className={`pill${!category ? ' pill--active' : ''}`}>All</button>
        {categories.map((c) => (
          <button key={c.id} onClick={() => selectCategory(c.id)}
            className={`pill${category === c.id ? ' pill--active' : ''}`}>
            {c.name}
          </button>
        ))}
      </div>

      {/* Results */}
      {loading ? (
        <p className="loading-text">Loading products…</p>
      ) : products.length === 0 ? (
        <p className="empty-text">No products found.</p>
      ) : (
        <div className="grid">{products.map((p) => <ProductCard key={p.id} product={p} />)}</div>
      )}

      {/* Pagination */}
      {!loading && pagination.pages > 1 && (
        <div className="pagination">
          <button className="pagination__btn" onClick={() => goToPage(page - 1)} disabled={page <= 1}>
            ← Prev
          </button>
          {pages.map((p, i) =>
            p === '…' ? (
              <span key={`ellipsis-${i}`} className="pagination__ellipsis">…</span>
            ) : (
              <button
                key={p}
                className={`pagination__btn${p === page ? ' pagination__btn--active' : ''}`}
                onClick={() => goToPage(p)}
              >
                {p}
              </button>
            )
          )}
          <button className="pagination__btn" onClick={() => goToPage(page + 1)} disabled={page >= pagination.pages}>
            Next →
          </button>
        </div>
      )}

      {!loading && pagination.total > 0 && (
        <p className="pagination__info">
          Page {page} of {pagination.pages} · {pagination.total} product{pagination.total !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  );
};

export default ProductList;
