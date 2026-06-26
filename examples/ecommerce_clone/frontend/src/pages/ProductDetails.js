import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getProduct, getProductReviews, addToCart, submitReview } from '../api';
import ReviewList from '../components/ReviewList';
import { useAuth } from '../context/AuthContext';

const ProductDetails = () => {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [product, setProduct] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [reviewForm, setReviewForm] = useState({ rating: 5, comment: '' });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getProduct(id), getProductReviews(id)]).then(([p, r]) => {
      setProduct(p);
      setReviews(Array.isArray(r) ? r : []);
      setLoading(false);
    });
  }, [id]);

  const handleAddToCart = async () => {
    if (!user) { navigate('/login'); return; }
    await addToCart({ product_id: id, quantity: 1 });
    navigate('/cart');
  };

  const handleReviewSubmit = async (e) => {
    e.preventDefault();
    if (!user) { navigate('/login'); return; }
    const result = await submitReview({ product_id: id, ...reviewForm });
    if (result.id) {
      setReviews([result, ...reviews]);
      setReviewForm({ rating: 5, comment: '' });
    }
  };

  if (loading) return <div className="page">Loading...</div>;
  if (!product || product.error) return <div className="page" style={{ color: 'red' }}>Product not found.</div>;

  return (
    <div className="page" style={{ maxWidth: 900, margin: '0 auto' }}>
      <div className="product-detail">
        {(product.image || product.image_url) && (
          <img src={product.image || product.image_url} alt={product.name} className="product-detail__image" />
        )}
        <div className="product-detail__info">
          <h1>{product.name}</h1>
          <p className="product-detail__price">${product.price}</p>
          <p style={{ color: '#555' }}>{product.description}</p>
          <p>Stock: {product.stock > 0
            ? <span style={{ color: 'green' }}>{product.stock} available</span>
            : <span style={{ color: 'red' }}>Out of stock</span>}
          </p>
          <button onClick={handleAddToCart} disabled={product.stock === 0} className="btn btn--primary">
            Add to Cart
          </button>
        </div>
      </div>

      <h2>Reviews</h2>
      <ReviewList reviews={reviews} />

      {user && (
        <form onSubmit={handleReviewSubmit} className="review-form">
          <h3 style={{ margin: '0 0 1rem' }}>Write a Review</h3>
          <div className="form-group">
            <label>Rating</label>
            <select value={reviewForm.rating} onChange={(e) => setReviewForm({ ...reviewForm, rating: Number(e.target.value) })}>
              {[5, 4, 3, 2, 1].map((r) => <option key={r} value={r}>{r} ★</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Comment</label>
            <textarea value={reviewForm.comment} onChange={(e) => setReviewForm({ ...reviewForm, comment: e.target.value })}
              placeholder="Share your experience..." rows={4} />
          </div>
          <button type="submit" className="btn btn--primary">Submit Review</button>
        </form>
      )}
    </div>
  );
};

export default ProductDetails;
