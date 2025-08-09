from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from app.database import SessionLocal
from app.models.user import AdminUser
from app.core.security import verify_password


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        db = SessionLocal()
        user = db.query(AdminUser).filter(AdminUser.username == username).first()
        db.close()

        if user and verify_password(password, user.password_hash) and user.is_superuser:
            request.session.update({"token": user.username})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request):
        return request.session.get("token") is not None
