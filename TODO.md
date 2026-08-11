# TODO - Sub Admin RBAC + Performance Optimization

## Sub Admin Role-Based Access Control (RBAC) ✅

### Database (database.py) ✅
1. ✅ Add `role`, `permissions`, `is_active` columns to `admin` table
2. ✅ Define RBAC constants: ROLE_SUPER_ADMIN, ROLE_SEMI_SUPER_ADMIN, ROLE_SUB_ADMIN
3. ✅ Define RULES (default permission sets), MODULES, SUPER_ADMIN_ONLY_MODULES, MODULE_LABELS
4. ✅ Seed default Super Admin (`pranu`) with full permissions
5. ✅ Add migration logic for existing databases (adds missing columns)
6. ✅ Add performance indexes (books isbn, issued_books book_id/return_date)

### Backend (app.py) ✅
7. ✅ Add `get_user_permissions()`, `has_permission()`, `role_rank()`, `can_manage()`
8. ✅ Add `role_required(module)` decorator enforcing RBAC on routes
9. ✅ Store role + permissions in session on login
10. ✅ Reject disabled accounts at login
11. ✅ Add context processor exposing `has_perm`, `can_manage`, `current_role_label`, `current_role`
12. ✅ Protect library routes with module permission checks (books, add_book, edit_book, delete_book, issue, return, search, reports)
13. ✅ Add Super Admin / Semi-Super Admin management routes:
    - `/admin_management` (list all accounts)
    - `/create_sub_admin` (create Sub Admin / Semi-Super Admin with permissions)
    - `/edit_sub_admin/<id>` (edit permissions)
    - `/toggle_sub_admin/<id>` (enable/disable)
    - `/delete_sub_admin/<id>` (delete, cannot delete Super Admin)
14. ✅ Prevent privilege escalation (filter super-admin-only modules)
15. ✅ Register creates Sub Admins with no permissions by default

### Frontend (templates) ✅
16. ✅ Update `base.html` nav (show only permitted modules via `has_perm`, admin link only for admins with manage_admins)
17. ✅ Create `admin_management.html` (list accounts, role badges, actions)
18. ✅ Create `create_sub_admin.html` (role selection + permission checkboxes + JS for Semi-Super)
19. ✅ Create `edit_sub_admin.html` (edit permissions; Semi-Super shows fixed-access notice)
20. ✅ Update `profile.html` role badge (Super / Semi-Super / Sub Admin)
21. ✅ Update `dashboard.html` (role label + permission-gated quick actions)

### Performance ("make web faster") ✅
22. ✅ Add DB indexes for faster lookups
23. ✅ Dimension-consistent queries

### Testing ✅
24. ✅ `test_rbac.py` end-to-end smoke test (all checks pass)
25. ✅ Verified app imports (26 routes), login page, dashboard, admin management all render
26. ✅ Verified Super Admin cannot delete/disable Super Admin accounts
27. ✅ Verified Sub Admin blocked from unauthorized modules (403)
28. ✅ Verified Semi-Super Admin has library access + can manage admins but not settings
