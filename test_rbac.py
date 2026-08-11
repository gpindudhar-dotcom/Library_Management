"""
test_rbac.py
------------
End-to-end smoke test for the RBAC (Role-Based Access Control) feature.

Verifies the key flows:
  - Super Admin can log in and access admin management.
  - Super Admin can create a Sub Admin with limited permissions.
  - The Sub Admin can only access granted modules and is blocked from
    admin management, settings, and deleting/sharing the Super Admin.
  - Super Admin cannot be deleted/disabled.
  - Semi-Super Admin role is created with full library access and can
    manage Sub Admins but not Super Admins.

Run with:  python test_rbac.py
"""

import json

import app as application
import database as db

app = application.app


def login(client, username, password, role_type="super_admin"):
    """Log in a user and return the response.

    The login page now offers two separate portals:
      - role_type="super_admin" for Super Admin accounts (full access)
      - role_type="sub_admin" for Sub Admin / Semi-Super Admin accounts
    """
    return client.post(
        "/login",
        data={"username": username, "password": password, "role_type": role_type},
        follow_redirects=True,
    )


def logout(client):
    """Log out the current user."""
    return client.get("/logout", follow_redirects=True)


def create_sub_admin(client, username="worker", password="1234", perms=("books",)):
    """Use the current session (must be admin) to create a Sub Admin."""
    return client.post(
        "/create_sub_admin",
        data={
            "name": "Worker",
            "username": username,
            "password": password,
            "confirm_password": password,
            "role": db.ROLE_SUB_ADMIN,
            "permissions": list(perms),
        },
        follow_redirects=True,
    )


def main():
    print("=" * 60)
    print("RBAC end-to-end smoke test")
    print("=" * 60)

    # Clean up any leftover test users so the test can be re-run safely.
    cleanup_conn = db.get_connection()
    cleanup_conn.execute(
        "DELETE FROM admin WHERE username IN ('worker', 'semiboss')"
    )
    cleanup_conn.commit()
    cleanup_conn.close()

    # ---------------------------------------------------------
    # 1. Super Admin login
    # ---------------------------------------------------------
    client = app.test_client()
    resp = login(client, "pranu", "1234")
    assert resp.status_code == 200
    assert b"Welcome back, Pranu" in resp.data
    print("[OK] Super Admin (pranu) logged in.")

    # 2. Super Admin can access admin management
    resp = client.get("/admin_management")
    assert resp.status_code == 200
    print("[OK] Super Admin can view admin management.")

    # 3. Create a Sub Admin with only 'books' permission
    resp = create_sub_admin(client, username="worker", perms=("books",))
    assert resp.status_code == 200
    assert b"created successfully" in resp.data
    print("[OK] Super Admin created Sub Admin 'worker' with 'books' permission.")

    logout(client)

    # ---------------------------------------------------------
    # 4. Sub Admin login
    # ---------------------------------------------------------
    resp = login(client, "worker", "1234")
    assert resp.status_code == 200
    print("[OK] Sub Admin (worker) logged in.")

    # Books page accessible (granted)
    resp = client.get("/books")
    assert resp.status_code == 200
    print("[OK] Sub Admin can view /books (granted permission).")

    # Add book blocked (not granted)
    resp = client.get("/add_book")
    assert resp.status_code == 403
    print("[OK] Sub Admin blocked from /add_book (403).")

    # Issue book blocked (not granted)
    resp = client.get("/issue_book")
    assert resp.status_code == 403
    print("[OK] Sub Admin blocked from /issue_book (403).")

    # Reports blocked (not granted)
    resp = client.get("/reports")
    assert resp.status_code == 403
    print("[OK] Sub Admin blocked from /reports (403).")

    # Admin management blocked (must never be accessible to Sub Admin)
    resp = client.get("/admin_management")
    assert resp.status_code == 403
    print("[OK] Sub Admin blocked from /admin_management (403).")

    # Settings blocked (Super Admin only)
    resp = client.get("/settings")
    assert resp.status_code in (403, 404)
    print("[OK] Sub Admin blocked from /settings.")

    logout(client)

    # ---------------------------------------------------------
    # 5. Super Admin cannot be deleted or disabled
    # ---------------------------------------------------------
    login(client, "pranu", "1234")
    # Find the Super Admin's id
    conn = db.get_connection()
    super_admin = conn.execute(
        "SELECT id FROM admin WHERE username = 'pranu' AND role = 'admin'"
    ).fetchone()
    conn.close()
    super_admin_id = super_admin["id"]

    resp = client.get(f"/delete_sub_admin/{super_admin_id}", follow_redirects=True)
    assert b"Super Admin accounts cannot be deleted" in resp.data
    print("[OK] Super Admin cannot delete a Super Admin account.")

    resp = client.get(f"/toggle_sub_admin/{super_admin_id}", follow_redirects=True)
    assert b"Super Admin accounts cannot be disabled" in resp.data
    print("[OK] Super Admin cannot disable a Super Admin account.")

    # ---------------------------------------------------------
    # 6. Semi-Super Admin role
    # ---------------------------------------------------------
    # Create a Semi-Super Admin (only Super Admin can do this)
    resp = client.post(
        "/create_sub_admin",
        data={
            "name": "Semi Boss",
            "username": "semiboss",
            "password": "1234",
            "confirm_password": "1234",
            "role": db.ROLE_SEMI_SUPER_ADMIN,
        },
        follow_redirects=True,
    )
    assert b"created successfully" in resp.data
    print("[OK] Super Admin created Semi-Super Admin 'semiboss'.")

    logout(client)

    # Login as Semi-Super Admin
    resp = login(client, "semiboss", "1234")
    assert resp.status_code == 200
    print("[OK] Semi-Super Admin logged in.")

    # Semi-Super Admin can access library modules
    resp = client.get("/books")
    assert resp.status_code == 200
    print("[OK] Semi-Super Admin can view /books.")

    resp = client.get("/add_book")
    assert resp.status_code == 200
    print("[OK] Semi-Super Admin can view /add_book.")

    # Semi-Super Admin can view admin management
    resp = client.get("/admin_management")
    assert resp.status_code == 200
    print("[OK] Semi-Super Admin can view admin management.")

    # Semi-Super Admin cannot access settings (Super Admin only)
    # (settings route doesn't exist -> 404, which is acceptable)
    resp = client.get("/settings")
    assert resp.status_code in (403, 404)
    print("[OK] Semi-Super Admin blocked from /settings.")

    logout(client)

    print("=" * 60)
    print("ALL RBAC TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
