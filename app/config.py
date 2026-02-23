import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # MongoDB connection string (server-level URI)
    # Example: mongodb://localhost:27017
    # Or: mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")

    # Master DB where we store tenants/users/shops
    MASTER_DB_NAME = os.environ.get("MASTER_DB_NAME") or os.environ.get("MONGO_DB") or "master_db"
