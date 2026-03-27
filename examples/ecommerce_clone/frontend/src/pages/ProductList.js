import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getProducts, getCategories } from '../api';
import ProductCard from '../components/ProductCard';

const PAGE_SIZE = 12;

/**
 * Build a window of up to 8 page numbers with ellipsis gaps.
 * Always includes the first two, last two, and pages around current.
 */
function buildPageWindow(current, total) {
  if (total <= 8) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const set = new Set([1, 2, total - 1, total]);
  for (let i = current - 2; i <= current + 2; i++) {
    if (i >= 1 && i <= total) set.add(i);
  }
  const pages = [...set].sort((a, b) => a - b);
  const result = [];
  pages.forEach((p, i) => {
    if (i > 0 && p - pages[i - 1] > 1) result.push('\u2026');
    result.push(p);
  });
  return result;
}

const ProductList = () => {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get('search') || '');

  // Cursor stack: each entry is { cursor, page } before a forward step.
  const cursorHistoryRef = useRef([]);

  const category = searchParams.get('category') || '';
  const activeCursor = searchParams.get('cursor') || null;
  const currentPage = Math.max(1, parseInt(searchParams.get('page') || '1', 10));
  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  // Keep search input in sync with URL (back/forward navigation).
  useEffect(() => {
    setSearch(searchParams.get('search') || '');
  }, [searchParams]);

  // Reset cursor history when filters change so history never crosses filter boundaries.
  const filtersKey = `${category}|${searchParams.get('search') || ''}`;
  const prevFiltersRef = useRef(filtersKey);
  if (prevFiltersRef.current !== filtersKey) {
    prevFiltersRef.current = filtersKey;
    cursorHistoryRef.current = [];
  }

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = { page: currentPage, page_size: PAGE_SIZE };
    if (activeCursor) params.cursor = activeCursor;
    if (category) params.category = category;
    const searchVal = searchParams.get('search');
    if (searchVal) params.search = searchVal;

    Promise.all([getProducts(params), getCategories()])
      .then(([productData, catData]) => {
        if (productData && Array.isArray(productData.results)) {
          setProducts(productData.results);
          setTotal(productData.count ?? 0);
          setNextCursor(productData.next_cursor ?? null);
        } else {
          setProducts([]);
          setTotal(0);
          setNextCursor(null);
        }
        setCategories(Array.isArray(catData) ? catData : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [searchParams]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build shared params that survive filter state across navigation.
  const baseParams = () => {
    const p = { page_size: String(PAGE_SIZE) };
    if (category) p.category = category;
    const searchVal = searchParams.get('search');
    if (searchVal) p.search = searchVal;
    return p;
  };

  const handleSearch = (e) => {
    e.preventDefault();
    const p = { page: '1', page_size: String(PAGE_SIZE) };
    if (search.trim()) p.search = search.trim();
    if (category) p.category = category;
    setSearchParams(p);
  };

  // Sequential forward: keyset cursor keeps navigation O(log N).
  const goNext = () => {
    if (!nextCursor) return;
    cursorHistoryRef.current.push({ cursor: activeCursor, page: currentPage });
    setSearchParams({ ...baseParams(), cursor: nextCursor, page: String(currentPage + 1) });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Sequential back: restore the previous cursor from the stack.
  const goPrev = () => {
    const entry = cursorHistoryRef.current.pop();
    const p = { ...baseParams(), page: String((entry?.page) ?? currentPage - 1) };
    if (entry?.cursor) p.cursor = entry.cursor;
    setSearchParams(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Direct page jump: drop cursor so backend uses OFFSET for the requested page.
  const goToPage = (n) => {
    cursorHistoryRef.current = [];
    setSearchParams({ ...baseParams(), page: String(n) });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const selectCategory = (cat) => {
    const p = { page: '1', page_size: String(PAGE_SIZE) };
    if (cat) p.category = cat;
    const searchVal = searchParams.get('search');
    if (searchVal) p.search = searchVal;
    setSearchParams(p);
  };

  const hasPrev = currentPage > 1;
  const hasNext = !!nextCursor || currentPage < totalPages;
  const pageWindow = buildPageWindow(currentPage, totalPages);

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
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setSearch('');
              const p = { page: '1', page_size: String(PAGE_SIZE) };
              if (category) p.category = category;
              setSearchParams(p);
            }}
          >
            ✕ Clear
          </button>
        )}
      </form>

      {/* Active search label */}
      {searchParams.get('search') && (
        <p className="search-label">
          Results for "<strong>{searchParams.get('search')}</strong>"
        </p>
      )}

      {/* Category pills */}
      <div className="pills">
        <button
          onClick={() => selectCategory('')}
          className={`pill${!category ? ' pill--active' : ''}`}
        >
          All
        </button>
        {categories.map((c) => (
          <button
            key={c.id}
            onClick={() => selectCategory(String(c.id))}
            className={`pill${category === String(c.id) ? ' pill--active' : ''}`}
          >
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
        <div className="grid">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} />
          ))}
        </div>
      )}

      {/* Pagination — Prev · page numbers · Next */}
      {!loading && totalPages > 1 && (
        <div className="pagination">
          <button
            className="pagination__btn"
            onClick={goPrev}
            disabled={!hasPrev}
          >
            ← Prev
          </button>

          {pageWindow.map((entry, idx) =>
            entry === '\u2026' ? (
              <span key={`ellipsis-${idx}`} className="pagination__ellipsis">…</span>
            ) : (
              <button
                key={entry}
                className={`pagination__btn${entry === currentPage ? ' pagination__btn--active' : ''}`}
                onClick={() => entry !== currentPage && goToPage(entry)}
                disabled={entry === currentPage}
              >
                {entry}
              </button>
            )
          )}

          <button
            className="pagination__btn"
            onClick={goNext}
            disabled={!hasNext}
          >
            Next →
          </button>
        </div>
      )}

      {!loading && total > 0 && (
        <p className="pagination__info">
          Page {currentPage} of {totalPages} — {total.toLocaleString()} product{total !== 1 ? 's' : ''}
        </p>
      )}
    </div>
  );
};

export default ProductList;
