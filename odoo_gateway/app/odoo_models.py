MODEL_MAP = {
    "leaves": {
        "model": "hr.leave",
        "permissions": ["create", "read", "update", "delete"]
    },
    "leaves_allocation": {
        "model": "hr.leave.allocation",
        "permissions": ["create", "read", "update", "delete"]
    },
    "leave_types": {
        "model": "hr.leave.type",
        "permissions": ["read"]
    },
    "employees": {
        "model": "hr.employee",
        "permissions": ["read"]
    },
    "attendances": {
        "model": "hr.attendance",
        "permissions": ["create", "read", "update"]
    },
    "departments": {
        "model": "hr.department",
        "permissions": ["read"]
    },
    "public_holidays": {
        "model": "resource.calendar.leaves",
        "permissions": ["read"]
    },
    "payslips": {
        "model": "hr.payslip",
        "permissions": ["read"]
    },
    "expenses": {
        "model": "hr.expense",
        "permissions": ["create", "read", "update", "delete"]
    },
    "expense_category": {
        "model": "product.product",
        "permissions": ["read"]
    }
}
