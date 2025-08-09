from app.database import SessionLocal, Base, engine
from app.models.user import AdminUser
from app.core.security import get_password_hash

# Ensure tables exist
Base.metadata.create_all(bind=engine)

db = SessionLocal()

username = input("Enter superuser username: ")
password = input("Enter superuser password: ")

hashed_password = get_password_hash(password)

superuser = AdminUser(
    username=username,
    password_hash=hashed_password,
    is_superuser=True
)

db.add(superuser)
db.commit()
db.close()

print("Superuser created successfully!")