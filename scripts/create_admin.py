import getpass

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.security import hash_password


email = input("Admin email: ").strip().lower()
password = getpass.getpass("Password: ")

if not email or len(password) < 12:
    raise ValueError("Email required; password must be at least 12 characters.")

with SessionLocal() as db:
    if db.scalar(select(User).where(User.email == email)):
        raise ValueError("User already exists.")

    db.add(User(
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        role="admin",
    ))
    db.commit()

print("Administrator account created.")
