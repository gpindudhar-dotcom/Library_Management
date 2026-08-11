"""
Library Book Management System - Flask Web Application
=======================================================
A web-based library management system built with Flask, SQLite,
Bootstrap 5, Jinja2, Pandas, and Chart.js.

Features:
    - Secure login (SQLite admin table, hashed passwords)
    - Role-Based Access Control
        (Super Admin / Semi-Super Admin / Sub Admin)
    - Dashboard with live statistics and Chart.js charts
    - Book registration (add / edit / delete / search)
    - Issue / return books (auto-updates available copies + fines)
    - Pandas-based reports with CSV export and print
    - Profile (view username + change password)
    - Contact page (saves messages to SQLite)
"""

import json
import os
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

app = Flask(__name__)
app.secret_key = "supersecretkey123"
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DATE_FORMAT = "%Y-%m-%d"
FINE_RATE = 10  # fine amount per overdue day

# Ensure the reports folder exists
os.makedirs(REPORTS_DIR, exist_ok=True)

# Create DB schema, apply migration, and seed sample data on startup
db.init_db()


# ------------------------------------------------------------
# RBAC (Role-Based Access Control) helpers
# ------------------------------------------------------------

def get_user_permissions():
    """Return the permission list for the current user from the session.

    Super Admins and Semi-Super Admins have a fixed permission set defined in
    db.RULES; Sub Admins only have the modules explicitly granted to them.
    """
    role = session.get("role")
    if role in db.RULES and role != db.ROLE_SUB_ADMIN:
        return db.RULES[role]
    perms = session.get("permissions", [])
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except (ValueError, TypeError):
            perms = []
    return perms or []


def has_permission(module):
    """Return True if the current user may access the given module."""
    # The super admin-only modules (settings) can never be granted to a
    # Semi-Super Admin or a Sub Admin.
    if module in db.SUPER_ADMIN_ONLY_MODULES:
        return session.get("role") == db.ROLE_SUPER_ADMIN
    return module in get_user_permissions()


def role_rank(role):
    """Return a numeric rank for a role (higher = more powerful)."""
    rank = {
        db.ROLE_SUPER_ADMIN: 3,
        db.ROLE_SEMI_SUPER_ADMIN: 2,
        db.ROLE_SUB_ADMIN: 1,
    }
    return rank.get(role, 0)


def can_manage(actor_role, target_role):
    """Return True if 'actor_role' may manage a user with 'target_role'.

    - Super Admin can manage everyone.
    - Semi-Super Admin can manage Sub Admins and other Semi-Super Admins,
      but NOT Super Admins.
    - Sub Admin cannot manage anyone.
    """
    if actor_role == db.ROLE_SUPER_ADMIN:
        return True
    if actor_role == db.ROLE_SEMI_SUPER_ADMIN:
        return target_role in (db.ROLE_SUB_ADMIN, db.ROLE_SEMI_SUPER_ADMIN)
    return False


def role_required(module):
    """Decorator that enforces RBAC on a Flask route.

    Checks that the user is logged in AND has the required permission.
    Returns a 403 page if the user is not authorised.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "logged_in" not in session:
                return redirect(url_for("login"))
            if not has_permission(module):
                abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_now():
    """Make the current year available to all templates (used in the footer)."""
    return {"now": datetime.now().year}


@app.context_processor
def inject_rbac_globals():
    """Expose RBAC helpers to all templates.

    - current_role_label: the role label shown in the UI
    - has_perm(module): template helper to conditionally render nav links
    - can_manage(role): template helper to control admin management actions
    - current_role: the raw role string for the logged-in user
    """
    role = session.get("role", db.ROLE_SUPER_ADMIN)
    role_labels = {
        db.ROLE_SUPER_ADMIN: "Super Admin",
        db.ROLE_SEMI_SUPER_ADMIN: "Semi-Super Admin",
        db.ROLE_SUB_ADMIN: "Sub Admin",
    }
    role_label = role_labels.get(role, "Admin")
    return {
        "current_role_label": role_label,
        "has_perm": has_permission,
        "can_manage": can_manage,
        "current_role": role,
    }


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def calc_due_date(issue_date_str):
    """Return the due date (issue date + 14 days)."""
    issue_date = datetime.strptime(issue_date_str, DATE_FORMAT)
    return (issue_date + timedelta(days=14)).strftime(DATE_FORMAT)


def calc_overdue(due, returned):
    """Compute overdue days and fine for a returned book."""
    if not returned:
        return 0, 0
    due_date = datetime.strptime(due, DATE_FORMAT)
    return_date = datetime.strptime(returned, DATE_FORMAT)
    overdue_days = max((return_date - due_date).days, 0)
    return overdue_days, overdue_days * FINE_RATE


def login_required(func):
    """Redirect unauthenticated users to the login page."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def count_registered_students():
    """Return the number of distinct students recorded in issued_books."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT COUNT(DISTINCT student_id) AS c FROM issued_books"
    ).fetchone()
    conn.close()
    return int(row["c"]) if row else 0


# ------------------------------------------------------------
# Public pages
# ------------------------------------------------------------

@app.route("/")
def home():
    """Render the public home / landing page (login-gated)."""
    if "logged_in" not in session:
        return redirect(url_for("login"))

    conn = db.get_connection()
    books_df = pd.read_sql_query("SELECT * FROM books", conn)
    issued_df = pd.read_sql_query("SELECT * FROM issued_books", conn)
    conn.close()

    total_books = int(books_df["quantity"].sum()) if not books_df.empty else 0
    available_books = int(books_df["available_copies"].sum()) if not books_df.empty else 0
    total_issued = len(issued_df) if not issued_df.empty else 0
    returned_books = (
        int(issued_df["return_date"].notna().sum()) if not issued_df.empty else 0
    )
    return render_template(
        "index.html",
        total_books=total_books,
        available_books=available_books,
        total_issued=total_issued,
        returned_books=returned_books,
        registered_students=count_registered_students(),
    )


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """Render the contact page and handle message submissions."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if not all([name, email, subject, message]):
            flash("Please fill in all fields.", "warning")
            return render_template("contact.html")

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO contact_messages (name, email, subject, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, email, subject, message, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        flash("Your message has been sent successfully!", "success")

    return render_template("contact.html")


# ------------------------------------------------------------
# Authentication
# ------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login against the SQLite admin table (hashed passwords).

    The login page offers two separate login options:
      - Super Admin login: only accounts with the 'admin' role can sign in.
      - Sub Admin login:   only accounts with the 'sub_admin' or 'semi_admin'
        role can sign in. Sub Admins have limited, permission-based access.
    The chosen role type is validated against the user's actual role so that
    a Sub Admin cannot log in through the Super Admin portal and vice-versa.
    """
    # Default to "super_admin" so the first card is the primary one.
    role_type = request.form.get("role_type", "super_admin")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        remember = request.form.get("remember")  # "on" if checked

        conn = db.get_connection()
        user = conn.execute(
            "SELECT * FROM admin WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        # Reject disabled accounts
        if user and not user["is_active"]:
            flash("This account has been disabled. Contact the Super Admin.", "danger")
            return render_template("login.html", role_type=role_type)

        # Validate the credentials first.
        if not (user and check_password_hash(user["password"], password)):
            flash("Invalid username or password.", "danger")
            return render_template("login.html", role_type=role_type)

        # Enforce the role type chosen on the login page.
        # 'super_admin' login only accepts Super Admin accounts (full access).
        if role_type == "super_admin" and user["role"] != db.ROLE_SUPER_ADMIN:
            flash(
                "This portal is for Super Admins only. Please use the Sub Admin login.",
                "danger",
            )
            return render_template("login.html", role_type=role_type)

        # 'sub_admin' login only accepts Sub Admin / Semi-Super Admin accounts.
        if role_type == "sub_admin" and user["role"] not in (
            db.ROLE_SUB_ADMIN,
            db.ROLE_SEMI_SUPER_ADMIN,
        ):
            flash(
                "This portal is for Sub Admins only. Please use the Super Admin login.",
                "danger",
            )
            return render_template("login.html", role_type=role_type)

        # Successful login: store role + permissions in the session.
        session["logged_in"] = True
        session["username"] = username
        session["user_name"] = user["name"]
        session["role"] = user["role"]
        session["permissions"] = user["permissions"]

        # When "remember me" is checked, keep the session for 30 days.
        if remember == "on":
            session.permanent = True
            app.permanent_session_lifetime = timedelta(days=30)
        else:
            session.permanent = False
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html", role_type=role_type)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register a new admin account (stored in the SQLite admin table).

    New accounts are created as Sub Admins with no permissions by default.
    An admin (Super/Semi-Super) must grant permissions afterwards.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        name = request.form.get("name", "").strip()

        if not all([username, password, confirm_password]):
            flash("Please fill in all required fields.", "warning")
            return render_template("register.html")

        if len(password) < 4:
            flash("Password must be at least 4 characters long.", "warning")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        conn = db.get_connection()
        existing = conn.execute(
            "SELECT 1 FROM admin WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            conn.close()
            flash("That username is already taken.", "danger")
            return render_template("register.html")

        # New accounts are Sub Admins with no permissions until granted.
        conn.execute(
            """
            INSERT INTO admin (username, password, name, role, permissions, is_active)
            VALUES (?, ?, ?, ?, '[]', 1)
            """,
            (username, generate_password_hash(password), name or username,
             db.ROLE_SUB_ADMIN),
        )
        conn.commit()
        conn.close()

        flash("Account created successfully! Contact an admin for permissions.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    """Log the current user out and destroy the session."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ------------------------------------------------------------
# Profile
# ------------------------------------------------------------

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Show the logged-in user's profile and allow changing the password."""
    conn = db.get_connection()
    admin = conn.execute(
        "SELECT * FROM admin WHERE username = ?", (session["username"],)
    ).fetchone()

    if request.method == "POST":
        current_password = request.form.get("current_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not all([current_password, new_password, confirm_password]):
            conn.close()
            flash("All fields are required.", "warning")
            return render_template("profile.html", admin=admin)

        if not check_password_hash(admin["password"], current_password):
            conn.close()
            flash("Current password is incorrect.", "danger")
            return render_template("profile.html", admin=admin)

        if len(new_password) < 4:
            conn.close()
            flash("New password must be at least 4 characters long.", "warning")
            return render_template("profile.html", admin=admin)

        if new_password != confirm_password:
            conn.close()
            flash("New passwords do not match.", "danger")
            return render_template("profile.html", admin=admin)

        conn.execute(
            "UPDATE admin SET password = ? WHERE username = ?",
            (generate_password_hash(new_password), session["username"]),
        )
        conn.commit()
        conn.close()

        flash("Password changed successfully.", "success")
        return redirect(url_for("profile"))

    conn.close()
    return render_template("profile.html", admin=admin)


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    """Show summary statistics and charts on the dashboard."""
    conn = db.get_connection()
    books_df = pd.read_sql_query("SELECT * FROM books", conn)
    issued_df = pd.read_sql_query("SELECT * FROM issued_books", conn)
    conn.close()

    total_books = int(books_df["quantity"].sum()) if not books_df.empty else 0
    available_books = int(books_df["available_copies"].sum()) if not books_df.empty else 0
    total_issued = len(issued_df) if not issued_df.empty else 0
    returned_books = (
        int(issued_df["return_date"].notna().sum()) if not issued_df.empty else 0
    )

    # Most borrowed books (top 5)
    top_books = []
    if not issued_df.empty:
        counts = (
            issued_df["book_id"].value_counts().reset_index()
            .rename(columns={issued_df["book_id"].name: "book_id", "count": "Times Issued"})
        )
        counts = counts.merge(
            books_df[["book_id", "title"]], on="book_id", how="left"
        )
        counts.rename(columns={"title": "Title"}, inplace=True)
        top_books = counts.head(5).to_dict(orient="records")

    # Category distribution
    categories = (
        books_df["category"].value_counts().reset_index()
        .rename(columns={books_df["category"].name: "Category", "count": "Count"})
        .to_dict(orient="records")
        if not books_df.empty
        else []
    )

    return render_template(
        "dashboard.html",
        total_books=total_books,
        available_books=available_books,
        total_issued=total_issued,
        returned_books=returned_books,
        registered_students=count_registered_students(),
        top_books=top_books,
        categories=categories,
    )


# ------------------------------------------------------------
# Book registration
# ------------------------------------------------------------

@app.route("/add_book", methods=["GET", "POST"])
@role_required("add_book")
def add_book():
    """Register a new book with validated fields."""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        category = request.form.get("category", "").strip()
        publisher = request.form.get("publisher", "").strip()
        year = request.form.get("year", "").strip()
        isbn = request.form.get("isbn", "").strip()
        quantity = request.form.get("quantity", "").strip()

        # Basic validation
        if not all([title, author, category, publisher, year, isbn, quantity]):
            flash("Please fill in every field.", "warning")
            return render_template("add_book.html")

        if not year.isdigit() or len(year) != 4:
            flash("Year must be a valid 4-digit number.", "warning")
            return render_template("add_book.html")

        if not quantity.isdigit() or int(quantity) < 1:
            flash("Quantity must be a positive integer.", "warning")
            return render_template("add_book.html")

        conn = db.get_connection()
        cursor = conn.cursor()

        # Enforce ISBN uniqueness
        existing = cursor.execute(
            "SELECT 1 FROM books WHERE isbn = ?", (isbn,)
        ).fetchone()
        if existing:
            conn.close()
            flash("A book with the same ISBN already exists.", "danger")
            return render_template("add_book.html")

        # Generate next Book ID (B001, B002, ...)
        row = cursor.execute(
            "SELECT book_id FROM books ORDER BY book_id DESC LIMIT 1"
        ).fetchone()
        if row and row["book_id"].startswith("B") and row["book_id"][1:].isdigit():
            next_id = f"B{int(row['book_id'][1:]) + 1:03d}"
        else:
            next_id = "B001"

        cursor.execute(
            """
            INSERT INTO books
            (book_id, title, author, category, publisher, year, isbn,
             quantity, available_copies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (next_id, title, author, category, publisher, int(year), isbn,
             int(quantity), int(quantity)),
        )
        conn.commit()
        conn.close()

        flash(f"Book '{title}' added successfully (ID: {next_id}).", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_book.html")


# ------------------------------------------------------------
# Record management (view all books)
# ------------------------------------------------------------

@app.route("/books")
@role_required("books")
def books():
    """View / manage all book records (Record Management)."""
    conn = db.get_connection()
    df = pd.read_sql_query("SELECT * FROM books", conn)
    conn.close()
    return render_template("books.html", books=df.to_dict(orient="records"))


@app.route("/search", methods=["GET", "POST"])
@role_required("search")
def search():
    """Search books by ID, title, author, or category."""
    results = []
    query = ""
    search_type = "title"
    if request.method == "POST":
        search_type = request.form.get("search_type", "title")
        query = request.form.get("query", "").strip().lower()

        conn = db.get_connection()
        if search_type == "book_id":
            df = pd.read_sql_query(
                "SELECT * FROM books WHERE LOWER(book_id) = ?", conn, params=[query]
            )
        elif search_type == "title":
            df = pd.read_sql_query(
                "SELECT * FROM books WHERE LOWER(title) LIKE ?",
                conn, params=[f"%{query}%"],
            )
        elif search_type == "author":
            df = pd.read_sql_query(
                "SELECT * FROM books WHERE LOWER(author) LIKE ?",
                conn, params=[f"%{query}%"],
            )
        elif search_type == "category":
            df = pd.read_sql_query(
                "SELECT * FROM books WHERE LOWER(category) LIKE ?",
                conn, params=[f"%{query}%"],
            )
        else:
            df = pd.DataFrame()
        conn.close()

        results = df.to_dict(orient="records") if not df.empty else []
        if not results:
            flash("No matching books found.", "info")

    return render_template(
        "search.html", books=results, query=query, search_type=search_type
    )


@app.route("/edit_book/<book_id>", methods=["GET", "POST"])
@role_required("edit_book")
def edit_book(book_id):
    """Edit the details of an existing book."""
    conn = db.get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        category = request.form.get("category", "").strip()
        publisher = request.form.get("publisher", "").strip()
        year = request.form.get("year", "").strip()
        isbn = request.form.get("isbn", "").strip()
        quantity = request.form.get("quantity", "").strip()

        if not all([title, author, category, publisher, year, isbn, quantity]):
            flash("Please fill in every field.", "warning")
            return redirect(url_for("edit_book", book_id=book_id))

        if not year.isdigit() or len(year) != 4:
            flash("Year must be a valid 4-digit number.", "warning")
            return redirect(url_for("edit_book", book_id=book_id))

        if not quantity.isdigit() or int(quantity) < 1:
            flash("Quantity must be a positive integer.", "warning")
            return redirect(url_for("edit_book", book_id=book_id))

        # Check ISBN uniqueness (excluding the current book)
        dup = cursor.execute(
            "SELECT 1 FROM books WHERE isbn = ? AND book_id != ?", (isbn, book_id)
        ).fetchone()
        if dup:
            conn.close()
            flash("This ISBN is already assigned to another book.", "danger")
            return redirect(url_for("edit_book", book_id=book_id))

        # Adjust available copies based on the quantity change
        current = cursor.execute(
            "SELECT quantity, available_copies FROM books WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        if not current:
            conn.close()
            flash("Book not found.", "danger")
            return redirect(url_for("search"))

        quantity_int = int(quantity)
        diff = quantity_int - int(current["quantity"])
        new_available = int(current["available_copies"]) + diff
        if new_available < 0:
            conn.close()
            flash(
                "Cannot reduce quantity below the number of currently issued copies.",
                "danger",
            )
            return redirect(url_for("edit_book", book_id=book_id))

        cursor.execute(
            """
            UPDATE books SET title=?, author=?, category=?, publisher=?,
                year=?, isbn=?, quantity=?, available_copies=?
            WHERE book_id=?
            """,
            (title, author, category, publisher, int(year), isbn,
             quantity_int, new_available, book_id),
        )
        conn.commit()
        conn.close()

        flash("Book details updated successfully.", "success")
        return redirect(url_for("search"))

    # GET: fetch the current book for pre-filling the form
    row = cursor.execute(
        "SELECT * FROM books WHERE book_id = ?", (book_id,)
    ).fetchone()
    conn.close()

    if not row:
        flash("Book not found.", "danger")
        return redirect(url_for("search"))

    return render_template("edit_book.html", book=dict(row))


@app.route("/delete_book/<book_id>")
@role_required("delete_book")
def delete_book(book_id):
    """Delete a book only if it is not currently issued."""
    conn = db.get_connection()
    cursor = conn.cursor()

    # Prevent deletion while the book is still out on loan
    active = cursor.execute(
        "SELECT 1 FROM issued_books WHERE book_id = ? AND return_date IS NULL",
        (book_id,),
    ).fetchone()
    if active:
        conn.close()
        flash("Cannot delete a book while it is still issued to a student.", "danger")
        return redirect(url_for("search"))

    # Remove any historical issue records for this book first (FK constraint),
    # then delete the book itself.
    cursor.execute("DELETE FROM issued_books WHERE book_id = ?", (book_id,))
    cursor.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
    conn.commit()
    conn.close()

    flash(f"Book {book_id} deleted successfully.", "success")
    return redirect(url_for("search"))


# ------------------------------------------------------------
# Issue book
# ------------------------------------------------------------

@app.route("/issue_book", methods=["GET", "POST"])
@role_required("issue")
def issue_book():
    """Issue an available book to a student."""
    conn = db.get_connection()
    cursor = conn.cursor()

    # Load books that still have available copies for the dropdown
    available_books = cursor.execute(
        "SELECT book_id, title, available_copies FROM books WHERE available_copies > 0"
    ).fetchall()

    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        book_id = request.form.get("book_id", "").strip()
        issue_date = request.form.get("issue_date", "").strip()

        if not all([student_name, student_id, book_id, issue_date]):
            conn.close()
            flash("Please fill in all fields.", "warning")
            return render_template("issue_book.html", books=available_books)

        # Validate the chosen book
        book = cursor.execute(
            "SELECT * FROM books WHERE book_id = ?", (book_id,)
        ).fetchone()
        if not book:
            conn.close()
            flash("Book ID not found.", "danger")
            return render_template("issue_book.html", books=available_books)

        if int(book["available_copies"]) <= 0:
            conn.close()
            flash("This book is currently unavailable.", "danger")
            return render_template("issue_book.html", books=available_books)

        # Validate the issue date
        try:
            datetime.strptime(issue_date, DATE_FORMAT)
        except ValueError:
            conn.close()
            flash("Issue date must use the format YYYY-MM-DD.", "warning")
            return render_template("issue_book.html", books=available_books)

        due_date = calc_due_date(issue_date)

        # Generate next record ID (R001, R002, ...)
        last = cursor.execute(
            "SELECT record_id FROM issued_books ORDER BY record_id DESC LIMIT 1"
        ).fetchone()
        if last and last["record_id"].startswith("R") and last["record_id"][1:].isdigit():
            record_id = f"R{int(last['record_id'][1:]) + 1:03d}"
        else:
            record_id = "R001"

        cursor.execute(
            """
            INSERT INTO issued_books
            (record_id, student_name, student_id, book_id, issue_date,
             due_date, return_date, overdue_days, fine)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (record_id, student_name, student_id, book_id, issue_date, due_date, None),
        )

        # Reduce available copies
        cursor.execute(
            "UPDATE books SET available_copies = available_copies - 1 WHERE book_id = ?",
            (book_id,),
        )
        conn.commit()
        conn.close()

        flash(f"Book issued successfully (Record ID: {record_id}).", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("issue_book.html", books=available_books)


# ------------------------------------------------------------
# Return book
# ------------------------------------------------------------

@app.route("/return_book", methods=["GET", "POST"])
@role_required("return")
def return_book():
    """Process a return, compute fines, and restore available copies."""
    conn = db.get_connection()
    cursor = conn.cursor()

    # Load open (not yet returned) records for the dropdown
    open_records = cursor.execute(
        """
        SELECT i.record_id, i.student_name, i.book_id, i.due_date, b.title
        FROM issued_books i
        LEFT JOIN books b ON i.book_id = b.book_id
        WHERE i.return_date IS NULL
        """
    ).fetchall()

    if request.method == "POST":
        record_id = request.form.get("record_id", "").strip()
        return_date = request.form.get("return_date", "").strip()

        if not all([record_id, return_date]):
            conn.close()
            flash("Please choose a record and enter the return date.", "warning")
            return render_template("return_book.html", records=open_records)

        try:
            datetime.strptime(return_date, DATE_FORMAT)
        except ValueError:
            conn.close()
            flash("Return date must use the format YYYY-MM-DD.", "warning")
            return render_template("return_book.html", records=open_records)

        record = cursor.execute(
            "SELECT * FROM issued_books WHERE record_id = ?", (record_id,)
        ).fetchone()
        if not record or record["return_date"] is not None:
            conn.close()
            flash("Record not found or already returned.", "danger")
            return render_template("return_book.html", records=open_records)

        overdue_days, fine = calc_overdue(record["due_date"], return_date)

        cursor.execute(
            """
            UPDATE issued_books SET return_date=?, overdue_days=?, fine=?
            WHERE record_id=?
            """,
            (return_date, overdue_days, fine, record_id),
        )

        # Restore available copy
        cursor.execute(
            "UPDATE books SET available_copies = available_copies + 1 WHERE book_id = ?",
            (record["book_id"],),
        )
        conn.commit()
        conn.close()

        flash(f"Book returned. Overdue: {overdue_days} days, Fine: {fine}.", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("return_book.html", records=open_records)


# ------------------------------------------------------------
# Reports
# ------------------------------------------------------------

@app.route("/reports")
@role_required("reports")
def reports():
    """Primary reports page with summary, charts, and generated tables."""
    conn = db.get_connection()
    books_df = pd.read_sql_query("SELECT * FROM books", conn)
    issued_df = pd.read_sql_query("SELECT * FROM issued_books", conn)
    conn.close()

    summary = {
        "Total Books": int(books_df["quantity"].sum()) if not books_df.empty else 0,
        "Available Books": int(books_df["available_copies"].sum()) if not books_df.empty else 0,
        "Issued Books": len(issued_df) if not issued_df.empty else 0,
        "Returned Books": int(issued_df["return_date"].notna().sum()) if not issued_df.empty else 0,
    }

    # Most borrowed
    top_books = []
    if not issued_df.empty:
        counts = (
            issued_df["book_id"].value_counts().reset_index()
            .rename(columns={issued_df["book_id"].name: "book_id", "count": "Times Issued"})
        )
        counts = counts.merge(books_df[["book_id", "title"]], on="book_id", how="left")
        counts.rename(columns={"title": "Title"}, inplace=True)
        top_books = counts.to_dict(orient="records")

    # Category counts
    categories = (
        books_df["category"].value_counts().reset_index()
        .rename(columns={books_df["category"].name: "Category", "count": "Count"})
        .to_dict(orient="records")
        if not books_df.empty
        else []
    )

    # Export summary to CSV using Pandas (as required)
    report_df = pd.DataFrame([summary])
    report_path = os.path.join(REPORTS_DIR, "library_summary_report.csv")
    report_df.to_csv(report_path, index=False)

    return render_template(
        "reports.html",
        summary=summary,
        top_books=top_books,
        categories=categories,
    )


@app.route("/export_report/<report_type>")
@role_required("reports")
def export_report(report_type):
    """Export a report as a downloadable CSV using Pandas."""
    conn = db.get_connection()

    if report_type == "books":
        df = pd.read_sql_query("SELECT * FROM books", conn)
        filename = "books_report.csv"
    elif report_type == "issued":
        df = pd.read_sql_query("SELECT * FROM issued_books", conn)
        filename = "issued_books_report.csv"
    elif report_type == "summary":
        books_df = pd.read_sql_query("SELECT * FROM books", conn)
        issued_df = pd.read_sql_query("SELECT * FROM issued_books", conn)
        df = pd.DataFrame([{
            "Total Books": int(books_df["quantity"].sum()) if not books_df.empty else 0,
            "Available Books": int(books_df["available_copies"].sum()) if not books_df.empty else 0,
            "Issued Books": len(issued_df) if not issued_df.empty else 0,
            "Returned Books": int(issued_df["return_date"].notna().sum()) if not issued_df.empty else 0,
        }])
        filename = "summary_report.csv"
    else:
        conn.close()
        flash("Invalid report type.", "danger")
        return redirect(url_for("reports"))

    conn.close()

    csv_data = df.to_csv(index=False)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/view_books")
@role_required("reports")
def view_books():
    """View all book records."""
    conn = db.get_connection()
    df = pd.read_sql_query("SELECT * FROM books", conn)
    conn.close()
    return render_template(
        "reports.html", books=df.to_dict(orient="records"), report_type="books"
    )


@app.route("/view_issued")
@role_required("reports")
def view_issued():
    """View all issued-book records."""
    conn = db.get_connection()
    df = pd.read_sql_query("SELECT * FROM issued_books", conn)
    conn.close()
    return render_template(
        "reports.html", issued=df.to_dict(orient="records"), report_type="issued"
    )


@app.route("/view_overdue")
@role_required("reports")
def view_overdue():
    """View overdue books (not returned past the due date)."""
    conn = db.get_connection()
    df = pd.read_sql_query("SELECT * FROM issued_books", conn)
    conn.close()

    overdue = []
    if not df.empty:
        for _, row in df.iterrows():
            if row["return_date"] is None or pd.isna(row["return_date"]):
                due = datetime.strptime(row["due_date"], DATE_FORMAT)
                if datetime.now() > due:
                    overdue.append(dict(row))

    return render_template(
        "reports.html", overdue=overdue, report_type="overdue"
    )


# ------------------------------------------------------------
# Admin management (Super Admin & Semi-Super Admin)
# ------------------------------------------------------------

@app.route("/admin_management")
@role_required("manage_admins")
def admin_management():
    """List all admin accounts (Super / Semi-Super / Sub Admins)."""
    conn = db.get_connection()
    admins = conn.execute(
        "SELECT id, username, name, role, permissions, is_active FROM admin"
    ).fetchall()
    conn.close()

    # Decode permissions for display
    admin_list = []
    for a in admins:
        try:
            perms = json.loads(a["permissions"]) if a["permissions"] else []
        except (ValueError, TypeError):
            perms = []
        admin_list.append(dict(a, permissions_list=perms))

    return render_template("admin_management.html", admins=admin_list)


@app.route("/create_sub_admin", methods=["GET", "POST"])
@role_required("manage_admins")
def create_sub_admin():
    """Create a new Sub Admin or Semi-Super Admin account.

    The actor's role determines which roles they may create:
    - Super Admin may create Sub Admins and Semi-Super Admins.
    - Semi-Super Admin may create Sub Admins (and other Semi-Super Admins).
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        name = request.form.get("name", "").strip()
        role = request.form.get("role", db.ROLE_SUB_ADMIN)
        # Only grant modules that are actually permitted for a Sub Admin.
        selected = request.form.getlist("permissions")

        if not all([username, password, confirm_password, name]):
            flash("Please fill in all fields.", "warning")
            return render_template("create_sub_admin.html")

        if len(password) < 4:
            flash("Password must be at least 4 characters long.", "warning")
            return render_template("create_sub_admin.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("create_sub_admin.html")

        actor_role = session.get("role")
        # Validate the requested role is allowed for the actor.
        if role == db.ROLE_SUPER_ADMIN:
            # Cannot create Super Admin accounts.
            flash("You cannot create Super Admin accounts.", "danger")
            return render_template("create_sub_admin.html")
        if role == db.ROLE_SEMI_SUPER_ADMIN and actor_role != db.ROLE_SUPER_ADMIN:
            # Only Super Admin can create Semi-Super Admins.
            flash("Only the Super Admin can create Semi-Super Admin accounts.", "danger")
            return render_template("create_sub_admin.html")

        # Filter out any super-admin-only modules to prevent privilege escalation.
        valid_perms = [p for p in selected
                       if p in db.MODULES and p not in db.SUPER_ADMIN_ONLY_MODULES]

        # Semi-Super Admins always get the full fixed permission set.
        if role == db.ROLE_SEMI_SUPER_ADMIN:
            valid_perms = db.RULES[db.ROLE_SEMI_SUPER_ADMIN]

        conn = db.get_connection()
        existing = conn.execute(
            "SELECT 1 FROM admin WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            conn.close()
            flash("That username is already taken.", "danger")
            return render_template("create_sub_admin.html")

        conn.execute(
            """
            INSERT INTO admin (username, password, name, role, permissions, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (username, generate_password_hash(password), name,
             role, json.dumps(valid_perms)),
        )
        conn.commit()
        conn.close()

        role_name = (
            "Semi-Super Admin" if role == db.ROLE_SEMI_SUPER_ADMIN else "Sub Admin"
        )
        flash(f"{role_name} '{username}' created successfully.", "success")
        return redirect(url_for("admin_management"))

    return render_template("create_sub_admin.html")


@app.route("/edit_sub_admin/<int:admin_id>", methods=["GET", "POST"])
@role_required("manage_admins")
def edit_sub_admin(admin_id):
    """Edit a Sub Admin / Semi-Super Admin's details and permissions."""
    conn = db.get_connection()
    target = conn.execute(
        "SELECT * FROM admin WHERE id = ?", (admin_id,)
    ).fetchone()

    if not target:
        conn.close()
        flash("Admin account not found.", "danger")
        return redirect(url_for("admin_management"))

    # The actor may only manage targets they are allowed to manage.
    actor_role = session.get("role")
    if not can_manage(actor_role, target["role"]):
        conn.close()
        flash("You are not allowed to manage this account.", "danger")
        return redirect(url_for("admin_management"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        selected = request.form.getlist("permissions")

        if not name:
            conn.close()
            flash("Name cannot be empty.", "warning")
            return render_template("edit_sub_admin.html", target=target)

        if target["role"] == db.ROLE_SUPER_ADMIN:
            conn.close()
            flash("Super Admin accounts cannot be edited here.", "danger")
            return redirect(url_for("admin_management"))

        valid_perms = [p for p in selected
                       if p in db.MODULES and p not in db.SUPER_ADMIN_ONLY_MODULES]

        # Semi-Super Admins always keep the full fixed permission set.
        if target["role"] == db.ROLE_SEMI_SUPER_ADMIN:
            valid_perms = db.RULES[db.ROLE_SEMI_SUPER_ADMIN]

        conn.execute(
            "UPDATE admin SET name = ?, permissions = ? WHERE id = ?",
            (name, json.dumps(valid_perms), admin_id),
        )
        conn.commit()
        conn.close()

        flash(f"Admin '{target['username']}' updated successfully.", "success")
        return redirect(url_for("admin_management"))

    conn.close()
    try:
        perms = json.loads(target["permissions"]) if target["permissions"] else []
    except (ValueError, TypeError):
        perms = []
    return render_template("edit_sub_admin.html", target=dict(target), perms=perms)


@app.route("/toggle_sub_admin/<int:admin_id>")
@role_required("manage_admins")
def toggle_sub_admin(admin_id):
    """Enable or disable a Sub Admin / Semi-Super Admin account."""
    conn = db.get_connection()
    target = conn.execute(
        "SELECT * FROM admin WHERE id = ?", (admin_id,)
    ).fetchone()

    if not target:
        conn.close()
        flash("Admin account not found.", "danger")
        return redirect(url_for("admin_management"))

    # The actor may only manage targets they are allowed to manage.
    actor_role = session.get("role")
    if not can_manage(actor_role, target["role"]):
        conn.close()
        flash("You are not allowed to manage this account.", "danger")
        return redirect(url_for("admin_management"))

    # Super Admin accounts cannot be disabled.
    if target["role"] == db.ROLE_SUPER_ADMIN:
        conn.close()
        flash("Super Admin accounts cannot be disabled.", "danger")
        return redirect(url_for("admin_management"))

    new_status = 0 if target["is_active"] else 1
    conn.execute(
        "UPDATE admin SET is_active = ? WHERE id = ?", (new_status, admin_id)
    )
    conn.commit()
    conn.close()

    action = "enabled" if new_status else "disabled"
    flash(f"Admin '{target['username']}' {action}.", "success")
    return redirect(url_for("admin_management"))


@app.route("/delete_sub_admin/<int:admin_id>")
@role_required("manage_admins")
def delete_sub_admin(admin_id):
    """Delete a Sub Admin / Semi-Super Admin account.

    Super Admin accounts can never be deleted.
    """
    conn = db.get_connection()
    target = conn.execute(
        "SELECT * FROM admin WHERE id = ?", (admin_id,)
    ).fetchone()

    if not target:
        conn.close()
        flash("Admin account not found.", "danger")
        return redirect(url_for("admin_management"))

    # The actor may only manage targets they are allowed to manage.
    actor_role = session.get("role")
    if not can_manage(actor_role, target["role"]):
        conn.close()
        flash("You are not allowed to manage this account.", "danger")
        return redirect(url_for("admin_management"))

    # Prevent deleting a Super Admin account.
    if target["role"] == db.ROLE_SUPER_ADMIN:
        conn.close()
        flash("Super Admin accounts cannot be deleted.", "danger")
        return redirect(url_for("admin_management"))

    # Prevent deleting yourself.
    if target["username"] == session.get("username"):
        conn.close()
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_management"))

    conn.execute("DELETE FROM admin WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()

    flash(f"Admin '{target['username']}' deleted successfully.", "success")
    return redirect(url_for("admin_management"))


# ------------------------------------------------------------
# Compatibility route (kept for backward routing)
# ------------------------------------------------------------

@app.route("/generate_reports")
@role_required("reports")
def generate_reports():
    """Compatibility route that redirects to the reports page."""
    return redirect(url_for("reports"))


if __name__ == "__main__":
    app.run(debug=True)

