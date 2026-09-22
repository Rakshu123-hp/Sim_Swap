"""Seed the SQLite DB with demo customers and default users.

Idempotent: safe to run repeatedly (python -m backend.db.seed). Re-running
never duplicates users, customers, or user<->customer links.
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


def _customer_name_for_user(username):
    return {"sim-customer": "Simulated Customer",
            "analyst": "Demo Analyst",
            "admin": "System Admin"}.get(username, username.title())


def seed():
    models.init_db()

    users_created = 0
    customers_created = 0
    links_created = 0

    for u in DEMO_USERS:
        user = models.get_user_by_username(u["username"])
        if user is None:
            user_id = models.create_user(u["username"], generate_password_hash(u["password"]),
                                         role=u["role"], name=u["name"])
            users_created += 1
        else:
            user_id = user["id"]
        if models.get_customer_by_user(user_id) is None:
            models.create_customer(
                name=_customer_name_for_user(u["username"]),
                email=f"{u['username']}@securebank.test",
                home_city="Haveri",
                user_id=user_id,
            )
            links_created += 1
            customers_created += 1

    for c in DEMO_CUSTOMERS:
        if models.get_customer_by_email(c["email"]) is None:
            models.create_customer(**c)
            customers_created += 1

    print(f"Seeded customers={len(models.list_customers())} "
          f"(+{customers_created} created), users={len(models.list_users())} "
          f"(+{users_created} created), user-customer links (+{links_created}).")


if __name__ == "__main__":
    seed()