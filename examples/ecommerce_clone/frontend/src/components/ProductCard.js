import React from 'react';
import { Link } from 'react-router-dom';
import { addToCart } from '../api';
import { useCart } from '../context/CartContext';

const ProductCard = ({ product }) => {
  const { refreshCart } = useCart();

  const handleAddToCart = async () => {
    await addToCart({ product_id: product.id, quantity: 1 });
    refreshCart();
    alert('Added to cart!');
  };

  const imgSrc = product.image || product.image_url;

  return (
    <div className="card">
      {imgSrc && (
        <img src={imgSrc} alt={product.name} style={{ width: '100%', height: '160px', objectFit: 'cover' }} />
      )}
      <div className="card__body">
        <h3 className="card__title">
          <Link to={`/products/${product.id}`} style={{ textDecoration: 'none', color: '#232f3e' }}>
            {product.name}
          </Link>
        </h3>
        <p className="card__price">${product.price}</p>
        <p className="card__stock">
          {product.stock > 0 ? `${product.stock} in stock` : <span style={{ color: 'red' }}>Out of stock</span>}
        </p>
        <button onClick={handleAddToCart} disabled={product.stock === 0} className="btn btn--primary btn--full btn--sm">
          Add to Cart
        </button>
      </div>
    </div>
  );
};

export default ProductCard;
