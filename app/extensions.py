from __future__ import annotations

from pymongo import MongoClient, ASCENDING
from flask import current_app

def get_mongo_client() -> MongoClient:
    client = current_app.extensions.get("mongo_client")
    if client is None:
        raise RuntimeError("Mongo client is not initialized. Call init_mongo(app) inside create_app().")
    return client

def get_master_db():
    client = get_mongo_client()
    return client[current_app.config["MASTER_DB_NAME"]]

def init_mongo(app):
    """
    Initializes MongoClient and ensures master indexes.
    """
    client = MongoClient(app.config["MONGO_URI"])
    app.extensions["mongo_client"] = client

    master_db = client[app.config["MASTER_DB_NAME"]]

    # Ensure indexes (safe to call multiple times)
    master_db.tenants.create_index([("slug", ASCENDING)], unique=True, name="uniq_tenant_slug")
    master_db.tenants.create_index([("db_name", ASCENDING)], unique=True, name="uniq_tenant_db_name")
    master_db.users.create_index([("tenant_id", ASCENDING), ("email", ASCENDING)], unique=True, name="uniq_user_email_per_tenant")
    master_db.shops.create_index([("tenant_id", ASCENDING)], name="idx_shop_tenant_id")
