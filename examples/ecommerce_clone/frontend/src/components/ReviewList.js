import React from 'react';

const RatingStars = ({ rating, max = 5 }) => (
  <span style={{ color: '#f0c040', fontSize: '1.2rem' }}>
    {'★'.repeat(rating)}{'☆'.repeat(max - rating)}
  </span>
);

const ReviewList = ({ reviews }) => {
  if (!reviews || reviews.length === 0) {
    return <p style={{ color: '#888' }}>No reviews yet. Be the first to review!</p>;
  }

  return (
    <div>
      {reviews.map((r) => (
        <div key={r.id} style={{ padding: '0.75rem 0', borderBottom: '1px solid #eee' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
            <RatingStars rating={r.rating} />
            <small style={{ color: '#888' }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}</small>
          </div>
          {r.comment && <p style={{ margin: 0 }}>{r.comment}</p>}
        </div>
      ))}
    </div>
  );
};

export { RatingStars };
export default ReviewList;
