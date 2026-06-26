# Ecommerce Clone

An Amazon-style ecommerce platform built with a React frontend and OpenViper backend.

## Features

- **Product Browsing**: Browse products by category or search by name
- **Shopping Cart**: Add, update, and remove items
- **Checkout**: Place orders with shipping address
- **Order Tracking**: View order history and status
- **Product Reviews**: Submit and view product reviews
- **Authentication**: JWT-based user registration and login

## Project Structure

```
ecommerce_clone/
├── ecommerce_clone/        # Project config (settings, routes, asgi)
├── users/                  # User authentication app
├── products/               # Product & category app
├── cart/                   # Shopping cart app
├── orders/                 # Order management app
├── reviews/                # Product reviews app
├── frontend/               # React frontend
├── templates/              # HTML templates
├── static/                 # Static assets (css, js, images)
├── media/                  # Uploaded media (product images)
└── viperctl.py             # Management CLI
```

## Backend API

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login, returns JWT token |
| GET | `/api/auth/profile` | Get current user profile |

### Products
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products` | List all products |
| GET | `/api/products?category=<id>` | Filter by category |
| GET | `/api/products?search=<term>` | Search products |
| GET | `/api/products/<id>` | Get product detail |
| GET | `/api/products/categories` | List categories |

### Cart
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cart` | Get current cart |
| POST | `/api/cart/add` | Add item to cart |
| POST | `/api/cart/update` | Update item quantity |
| POST | `/api/cart/remove` | Remove item from cart |

### Orders
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/orders/checkout` | Place order from cart |
| GET | `/api/orders` | List user's orders |
| GET | `/api/orders/<id>` | Get order details |

### Reviews
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reviews` | Submit a review |
| GET | `/api/reviews/product/<id>` | Get reviews for a product |

## Running the Project

### Backend

```bash
cd examples/ecommerce_clone
pip install openviper

# Run the server
python viperctl.py start-server
# or
uvicorn ecommerce_clone.asgi:app --reload
```

### Frontend

```bash
cd examples/ecommerce_clone/frontend
npm install
npm start
```

The frontend runs at `http://localhost:3000` and connects to the backend at `http://localhost:8000/api`.

## Authentication

The API uses JWT tokens. Include the token in the `Authorization` header:

```
Authorization: Bearer <token>
```

## Running with Docker Compose

This project includes a complete Docker Compose configuration that runs the React frontend, OpenViper backend, Dramatiq worker, PostgreSQL database, Redis, and an Nginx reverse proxy.

### 1. Set your Gemini API Key

Create a `.env` file in the root of the project (`examples/ecommerce_clone/.env`) and add your Gemini API key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Start the Services

Build and run the entire platform with:

```bash
docker compose up --build
```

On startup, the web container will automatically run database migrations, collect static assets, and seed initial product data using the `seed_products.py` script.

### 3. Access the Application

- **React Frontend:** `http://localhost:8080` (served through Nginx)
- **Admin:** `http://localhost:8080/admin`
- **Swagger API Docs:** `http://localhost:8080/open-api/docs`
