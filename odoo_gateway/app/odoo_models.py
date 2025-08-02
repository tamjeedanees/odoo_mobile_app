# app/odoo_models.py

leaves = 'hr.leave'
leave_types = 'hr.leave.type'
employees = 'hr.employee'
attendances = 'hr.attendance'
timeoffs = 'hr.leave.allocation'
departments = 'hr.department'
public_holidays = 'resource.calendar.leaves'

# Create a dictionary for fast lookup
MODEL_MAP = {
    "leaves": leaves,
    "leave_type": leave_types,
    "employees": employees,
    "attendances": attendances,
    "timeoffs": timeoffs,
    "departments": departments,
    "public_holidays": public_holidays
}
