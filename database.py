"""
database.py
------------
SQLite database helpers for the Library Book Management System.

This module centralises all database operations (connection, schema creation,
and sample data seeding) so the Flask app stays clean and modular.
It also defines the RBAC (Role-Based Access Control) roles and module
permissions used to restrict what a Sub Admin can access.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

DATE_FORMAT = "%Y-%m-%d"
FINE_RATE = 10  # fine in currency units per overdue day

# ----------------------------------------------------------------------
# RBAC constants
# ----------------------------------------------------------------------
# Roles supported by the system
ROLE_SUPER_ADMIN = "admin"
ROLE_SEMI_SUPER_ADMIN = "semi_admin"
ROLE_SUB_ADMIN = "sub_admin"

# Default permission set for each built-in role.
#  - Super Admin:      full access to everything (library + settings + admins)
#  - Semi-Super Admin: full library access + can manage Sub Admins and other
#                      Semi-Super Admins, but NOT Super Admins or settings.
#  - Sub Admin:        only the modules explicitly granted by an admin.
RULES = {
    ROLE_SUPER_ADMIN: [
        "books", "add_book", "edit_book", "delete_book", "issue",
        "return", "search", "reports", "settings", "manage_admins",
    ],
    ROLE_SEMI_SUPER_ADMIN: [
        "books", "add_book", "edit_book", "delete_book", "issue",
        "return", "search", "reports", "manage_admins",
    ],
    ROLE_SUB_ADMIN: [],
}

# Modules that a Semi-Super Admin can never access (reserved for Super Admin).
SUPER_ADMIN_ONLY_MODULES = ["settings"]

# The normal library modules (excluding the special admin/settings modules).
MODULES = [
    "books",
    "add_book",
    "edit_book",
    "delete_book",
    "issue",
    "return",
    "search",
    "reports",
]

# Human-friendly labels for the permission modules (used in the UI).
MODULE_LABELS = {
    "books": "View Books",
    "add_book": "Add Books",
    "edit_book": "Edit Books",
    "delete_book": "Delete Books",
    "issue": "Issue Books",
    "return": "Return Books",
    "search": "Search Books",
    "reports": "Reports",
    "settings": "System Settings",
    "manage_admins": "Manage Admins",
}


def get_connection():
    """
    Open (and return) a connection to the SQLite database.
    row_factory is set so column values can be accessed by name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema():
    """
    Create the books, issued_books, admin, and contact_messages tables if they
    do not already exist. Uses proper primary / foreign keys. Also runs a
    lightweight migration for existing databases and creates performance
    indexes for faster lookups.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            book_id          TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            author           TEXT NOT NULL,
            category         TEXT NOT NULL,
            publisher        TEXT NOT NULL,
            year             INTEGER NOT NULL,
            isbn             TEXT NOT NULL UNIQUE,
            quantity         INTEGER NOT NULL,
            available_copies INTEGER NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS issued_books (
            record_id      TEXT PRIMARY KEY,
            student_name   TEXT NOT NULL,
            student_id     TEXT NOT NULL,
            book_id        TEXT NOT NULL,
            issue_date     TEXT NOT NULL,
            due_date       TEXT NOT NULL,
            return_date    TEXT,
            overdue_days   INTEGER NOT NULL DEFAULT 0,
            fine           INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (book_id) REFERENCES books (book_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL UNIQUE,
            password    TEXT NOT NULL,
            name        TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'admin',
            permissions TEXT NOT NULL DEFAULT '[]',
            is_active   INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            subject     TEXT NOT NULL,
            message     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
    )

    # --- Migration: add RBAC columns to an existing admin table ---
    # If the admin table was created before RBAC was introduced, the new
    # columns (role, permissions, is_active) will be missing. Add them here.
    admin_cols = [
        col[1] for col in cursor.execute("PRAGMA table_info(admin)").fetchall()
    ]
    if "role" not in admin_cols:
        cursor.execute("ALTER TABLE admin ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if "permissions" not in admin_cols:
        cursor.execute(
            "ALTER TABLE admin ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]'"
        )
    if "is_active" not in admin_cols:
        cursor.execute(
            "ALTER TABLE admin ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
        )

    # Ensure existing Super Admins have full permissions after migration.
    cursor.execute(
        """
        UPDATE admin
        SET permissions = ?,
            is_active = 1
        WHERE role = ? AND (permissions IS NULL OR permissions = '[]')
        """,
        (json.dumps(RULES[ROLE_SUPER_ADMIN]), ROLE_SUPER_ADMIN),
    )

    # Ensure existing Semi-Super Admins get the correct default permission set.
    cursor.execute(
        """
        UPDATE admin
        SET permissions = ?
        WHERE role = ? AND (permissions IS NULL OR permissions = '[]')
        """,
        (json.dumps(RULES[ROLE_SEMI_SUPER_ADMIN]), ROLE_SEMI_SUPER_ADMIN),
    )

    # --- Performance indexes for faster lookups / report queries ---
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_issued_book ON issued_books (book_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_issued_return ON issued_books (return_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_books_isbn ON books (isbn)"
    )

    conn.commit()
    conn.close()


def seed_sample_data():
    """
    Insert sample books and issued-book records into the database
    only when the books table is empty (so existing data is preserved).
    """
    conn = get_connection()
    cursor = conn.cursor()

    count = cursor.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    if count > 0:
        conn.close()
        return

    sample_books = [
        ("B001", "Python Basics", "John Doe", "Programming", "Tech Press", 2021, "9780140449136", 10, 7),
        ("B002", "Data Science 101", "Jane Smith", "Data Science", "DataPress", 2020, "9780140449143", 8, 4),
        ("B003", "Modern Algorithms", "Alan Turing", "Computer Science", "AlgoPub", 2019, "9780140449150", 5, 5),
        ("B004", "Networking Essentials", "Emily Clark", "Networking", "NetPress", 2022, "9780140449167", 6, 2),
        ("B005", "Database Systems", "Robert King", "Databases", "DBBooks", 2018, "9780140449174", 7, 3),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO books
        (book_id, title, author, category, publisher, year, isbn, quantity, available_copies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        sample_books,
    )

    # Sample issued records (one already returned late, one still out)
    today = datetime.now().strftime(DATE_FORMAT)
    due_date = (datetime.now() + timedelta(days=14)).strftime(DATE_FORMAT)
    sample_issued = [
        ("R001", "Anita Sharma", "S123", "B001", "2026-07-10", "2026-07-24", "2026-07-25", 1, 10),
        ("R002", "Raj Patel", "S124", "B002", today, due_date, None, 0, 0),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO issued_books
        (record_id, student_name, student_id, book_id, issue_date, due_date,
         return_date, overdue_days, fine)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        sample_issued,
    )

    conn.commit()
    conn.close()


def seed_admin():
    """
    Insert the default Super Admin user (pranu / 1234) if the admin table is
    empty. The password is stored as a Werkzeug hash (never plaintext).
    The Super Admin is granted full permissions on all modules.
    """
    conn = get_connection()
    cursor = conn.cursor()

    count = cursor.execute("SELECT COUNT(*) FROM admin").fetchone()[0]
    if count == 0:
        cursor.execute(
            """
            INSERT INTO admin (username, password, name, role, permissions, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                "pranu",
                generate_password_hash("1234"),
                "Pranu",
                ROLE_SUPER_ADMIN,
                json.dumps(RULES[ROLE_SUPER_ADMIN]),
            ),
        )
        conn.commit()

    conn.close()


def init_db():
    """Create the schema and load sample data (called once at startup)."""
    create_schema()
    seed_admin()
    seed_sample_data()


if __name__ == "__main__":
    init_db()
    print("Database initialised at:", DB_PATH)
