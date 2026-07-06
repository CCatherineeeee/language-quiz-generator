"""Seed the two v1 accounts (decision log #5). Idempotent — safe to re-run."""

from .db import SessionLocal
from .models import User

ACCOUNTS = [
    User(id=1, display_name="Catherine", is_demo=False),
    User(id=2, display_name="Demo", is_demo=True),
]


def main() -> None:
    with SessionLocal() as session:
        for account in ACCOUNTS:
            if session.get(User, account.id) is None:
                session.add(account)
                print(f"created user {account.id}: {account.display_name}")
            else:
                print(f"user {account.id} already exists, skipping")
        session.commit()


if __name__ == "__main__":
    main()
