from sqladmin import Admin, ModelView
from app.database import engine
from app.models.auth import AuthAttempt
from app.models.license import LicenseInstance
from app.models.user import AdminUser
from app.admin_auth import AdminAuth


class AuthAttemptAdmin(ModelView, model=AuthAttempt):
    column_list = [AuthAttempt.id, AuthAttempt.license_key, AuthAttempt.username, AuthAttempt.success, AuthAttempt.ip_address, AuthAttempt.attempted_at]
    can_create = True
    can_edit = True
    can_delete = True


class LicenseInstanceAdmin(ModelView, model=LicenseInstance):
    column_list = [LicenseInstance.id, LicenseInstance.license_key, LicenseInstance.company_name, LicenseInstance.odoo_url, LicenseInstance.database_name, LicenseInstance.exec_username, LicenseInstance.exec_password, LicenseInstance.is_active, LicenseInstance.created_at, LicenseInstance.expires_at]
    can_create = True
    can_edit = True
    can_delete = True


class AdminUserAdmin(ModelView, model=AdminUser):
    column_list = [AdminUser.id, AdminUser.username, AdminUser.is_superuser]
    form_excluded_columns = ["password_hash"]


def setup_admin(app):
    admin = Admin(app, engine, authentication_backend=AdminAuth(secret_key="supersecretkey"))
    admin.add_view(AuthAttemptAdmin)
    admin.add_view(LicenseInstanceAdmin)
    admin.add_view(AdminUserAdmin)
