import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getProducts, getCategories } from '../api';
import ProductCard from '../components/ProductCard';

const Home = () => {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    getProducts({ page: 1, page_size: 8 }).then((data) => {
      const items = data?.items ?? (Array.isArray(data) ? data : []);
      setProducts(items);
    });
    getCategories().then((data) => setCategories(Array.isArray(data) ? data : []));
  }, []);

  return (
    <div className="page">
      <div className="hero">
        <h1>Welcome to EcommerceClone</h1>
        <p>Discover thousands of products at great prices</p>
        <Link to="/products" className="btn btn--primary">Shop Now</Link>
      </div>

      <h2 className="page__title">Categories</h2>
      <div className="pills">
        {categories.map((c) => (
          <Link key={c.id} to={`/products?category=${c.id}`} className="pill">{c.name}</Link>
        ))}
      </div>

      <h2 className="page__title">Featured Products</h2>
      <div className="grid">
        {products.map((p) => <ProductCard key={p.id} product={p} />)}
      </div>
    </div>
  );
};

export default Home;
