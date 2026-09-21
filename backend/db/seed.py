"""Seed the SQLite DB with a handful of demo customers and default users.

Idempotent: safe to run repeatedly.
"""

from werkzeug.security import generate_password_hash

from backend.db import models

DEMO_CUSTOMERS = [
    {"name": "Ananya Hegde", "phone": "+919000000001", "email": "ananya.demo@securebank.test",
     "home_city": "Haveri"},
    {"name": "Rahul Naik", "phone": "+919000000002", "email": "rahul.demo@securebank.test",
     "home_city": "Bengaluru"},
    {"name": "Sneha Patil", "phone": "+919000000003", "email": "sneha.demo@securebank.test",
     "home_city": "Mysuru"},
    {"name": "Arjun Kulkarni", "phone": "+919000000004", "email": "arjun.demo@securebank.test",
     "home_city": "Hubballi"},
    {"name": "Meena Fernandes", "phone": "+919000000005", "email": "meena.demo@securebank.test",
     "home_city": "Mangaluru"},
]

DEMO_USERS = [
    {"username": "analyst", "password": "demo123", "role": "analyst", "name": "Demo Analyst"},
    {"username": "sim-customer", "password": "demo123", "role": "customer", "name": "Simulated Customer"},
    {"username": "admin", "password": "demo123", "role": "admin", "name": "System Admin"},
]


def seed():
    models.init_db()
    for u in DEMO_USERS:
        if not models.get_user_by_username(u["username"]):
            models.create_user(u["username"], generate_password_hash(u["password"]),
                               role=u["role"], name=u["name"])
    if not models.list_customers():
        for c in DEMO_CUSTOMERS:
            models.create_customer(**c)
    print(f"Seeded {len(models.list_customers())} customers and {len(DEMO_USERS)} users.")


if __name__ == "__main__":
    seed()