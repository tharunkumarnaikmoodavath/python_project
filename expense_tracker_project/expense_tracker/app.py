from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = "change-this-secret-key-before-real-use"

# Change these values if your MySQL settings are different.
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "aimlb2",
    "database": "Python_Project"
}

#
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# Pages below this decorator can only be opened after login.
def login_required(page_function):
    @wraps(page_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return page_function(*args, **kwargs)
    return wrapper

def get_categories():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name")
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    return rows

@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or len(password) < 6:
            flash("Enter all details. Password must be at least 6 characters.")
            return redirect(url_for("register"))

        db = get_db()
        cursor = db.cursor()
        try:
            password_hash = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, email, password_hash)
            )
            db.commit()
            flash("Registration successful. Please log in.")
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            flash("This email is already registered.")
        finally:
            cursor.close()
            db.close()

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT e.expense_id, e.expense_date, e.amount,
               e.description, e.payment_method,
               c.category_name
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        WHERE e.user_id = %s
        ORDER BY e.expense_date DESC
    """, (session["user_id"],))

    expenses = cursor.fetchall()
    cursor.close()
    db.close()

    # Get all available categories
    categories = get_categories()

    # Convert database records into a DataFrame
    df = pd.DataFrame(expenses)

    selected_category = request.args.get("category", "").strip()

    # Convert amounts into numeric values
    if not df.empty:
        df["amount"] = pd.to_numeric(df["amount"])

    # All expenses for category-wise comparison
    all_df = df.copy()

    # Filter expenses when a category is selected
    if selected_category:
        df = df[
            df["category_name"] == selected_category
        ].copy()

    # Calculate total, minimum, maximum and average
    if not df.empty:
        total = round(float(df["amount"].sum()), 2)
        minimum = round(float(df["amount"].min()), 2)
        maximum = round(float(df["amount"].max()), 2)
        average = round(float(np.mean(df["amount"].to_numpy())), 2)
    else:
        total = 0
        minimum = 0
        maximum = 0
        average = 0


    category_stats = []

    if not all_df.empty:
        grouped = all_df.groupby("category_name")["amount"]

        for name, values in grouped:
            category_stats.append({
                "category_name": name,
                "total": round(float(values.sum()), 2),
                "minimum": round(float(values.min()), 2),
                "maximum": round(float(values.max()), 2),
                "average": round(float(values.mean()), 2)
            })

    # Category-wise pie chart
    category_file = None
    monthly_file = None

    os.makedirs("static", exist_ok=True)

    if not all_df.empty:
        category_file = f"category_{session['user_id']}.png"

        category_totals = all_df.groupby(
            "category_name"
        )["amount"].sum()

        plt.figure(figsize=(6, 4))
        category_totals.plot(
            kind="pie",
            autopct="%1.1f%%"
        )
        plt.ylabel("")
        plt.title("Category-wise Expenses")
        plt.tight_layout()
        plt.savefig(os.path.join("static", category_file))
        plt.close()

    # Monthly bar chart for selected category or all expenses
    if not df.empty:
        monthly_file = f"monthly_{session['user_id']}.png"

        chart_df = df.copy()
        chart_df["month"] = pd.to_datetime(
            chart_df["expense_date"]
        ).dt.strftime("%Y-%m")

        monthly_totals = chart_df.groupby("month")["amount"].sum()

        plt.figure(figsize=(6, 4))
        monthly_totals.plot(kind="bar")
        plt.ylabel("Amount (₹)")

        if selected_category:
            plt.title(f"Monthly Spending - {selected_category}")
        else:
            plt.title("Monthly Expenses")

        plt.tight_layout()
        plt.savefig(os.path.join("static", monthly_file))
        plt.close()

    return render_template(
        "dashboard.html",
        expenses=expenses if not selected_category else [
            e for e in expenses
            if e["category_name"] == selected_category
        ],
        total=total,
        minimum=minimum,
        maximum=maximum,
        average=average,
        categories=categories,
        selected_category=selected_category,
        category_stats=category_stats,
        category_file=category_file,
        monthly_file=monthly_file
    )
@app.route("/add", methods=["GET", "POST"])
@login_required
def add_expense():
    categories = get_categories()

    if request.method == "POST":
        expense_date = request.form["expense_date"]
        category_id = request.form["category_id"]
        amount = request.form["amount"]
        description = request.form["description"].strip()
        payment_method = request.form["payment_method"].strip()

        try:
            amount = float(amount)
            if amount <= 0:
                flash("Amount must be greater than zero.")
                return redirect(url_for("add_expense"))
        except ValueError:
            flash("Please enter a valid amount.")
            return redirect(url_for("add_expense"))

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO expenses
            (expense_date, category_id, amount, description, payment_method, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (expense_date, category_id, amount, description, payment_method, session["user_id"]))
        db.commit()
        cursor.close()
        db.close()
        flash("Expense added successfully.")
        return redirect(url_for("dashboard"))

    return render_template("expense_form.html", categories=categories, expense=None)

@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    categories = get_categories()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # user_id check prevents editing another user's expense.
    cursor.execute(
        "SELECT * FROM expenses WHERE expense_id=%s AND user_id=%s",
        (expense_id, session["user_id"])
    )
    expense = cursor.fetchone()

    if expense is None:
        cursor.close()
        db.close()
        flash("Expense not found.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            amount = float(request.form["amount"])
            if amount <= 0:
                flash("Amount must be greater than zero.")
                return redirect(url_for("edit_expense", expense_id=expense_id))
        except ValueError:
            flash("Please enter a valid amount.")
            return redirect(url_for("edit_expense", expense_id=expense_id))

        cursor.execute("""
            UPDATE expenses
            SET expense_date=%s, category_id=%s, amount=%s,
                description=%s, payment_method=%s
            WHERE expense_id=%s AND user_id=%s
        """, (
            request.form["expense_date"], request.form["category_id"], amount,
            request.form["description"].strip(), request.form["payment_method"].strip(),
            expense_id, session["user_id"]
        ))
        db.commit()
        cursor.close()
        db.close()
        flash("Expense updated successfully.")
        return redirect(url_for("dashboard"))

    cursor.close()
    db.close()
    return render_template("expense_form.html", categories=categories, expense=expense)

@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    db = get_db()
    cursor = db.cursor()
    # user_id check prevents deleting another user's expense.
    cursor.execute(
        "DELETE FROM expenses WHERE expense_id=%s AND user_id=%s",
        (expense_id, session["user_id"])
    )
    db.commit()
    cursor.close()
    db.close()
    flash("Expense deleted (if it belonged to your account).")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
