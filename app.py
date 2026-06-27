import os
import io
import csv
from datetime import datetime, timedelta, timezone
from functools import wraps
import bcrypt
import urllib.parse
import jwt
from flask import Flask, redirect, render_template, request, session, url_for, flash, Response, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from sqlalchemy import func

from dotenv import load_dotenv

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "default-fallback-key")

raw_password = os.environ.get("SUPABASE_PASSWORD")
safe_password = urllib.parse.quote_plus(raw_password) if raw_password else ""

app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://postgres:{safe_password}@db.sdxrdppfylpiiimvcvgn.supabase.co:5432/postgres"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "fallback_jwt_secret")
app.config["JWT_EXPIRY_HOURS"] = 24

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
mail = Mail(app)


def get_ist_time():
    """Generates accurate Indian Standard Time (IST) regardless of host server location"""
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=5, minutes=30)


# --- DATABASE MODELS ---

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="staff")

    def __init__(self, email, password, name, role="staff"):
        self.name = name
        self.email = email
        self.role = role.lower()
        self.password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.password.encode("utf-8")
        )


class Supplier(db.Model):
    __tablename__ = "supplier"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact_info = db.Column(db.String(100), nullable=False)
    products = db.relationship("Product", backref="supplier", lazy=True, cascade="all, delete-orphan")


class Product(db.Model):
    __tablename__ = "product"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Float, nullable=False)
    threshold = db.Column(db.Integer, nullable=False, default=5)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id", ondelete="CASCADE"), nullable=False)
    sales = db.relationship("Sales", backref="product", lazy=True, cascade="all, delete-orphan")


class Sales(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    qty_sold = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    sale_date = db.Column(db.DateTime, nullable=False, default=get_ist_time)


# --- JWT HELPER FUNCTIONS ---

def generate_jwt_token(user):
    now_utc = datetime.now(timezone.utc)
    payload = {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.name,
        "exp": now_utc + timedelta(hours=app.config["JWT_EXPIRY_HOURS"]),
        "iat": now_utc
    }
    return jwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_jwt_token(token):
    try:
        payload = jwt.decode(token, app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Token expired. Please login again."
    except jwt.InvalidTokenError:
        return None, "Invalid token. Please login again."


def get_token_from_request():
    token = request.cookies.get("jwt_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    return None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()
        if not token:
            flash("Please login to continue.", "warning")
            return redirect("/login")
        payload, error = decode_jwt_token(token)
        if error:
            flash(error, "danger")
            response = make_response(redirect("/login"))
            response.delete_cookie("jwt_token")
            return response
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()
        if not token:
            flash("Please login to continue.", "warning")
            return redirect("/login")
        payload, error = decode_jwt_token(token)
        if error:
            flash(error, "danger")
            response = make_response(redirect("/login"))
            response.delete_cookie("jwt_token")
            return response
        if payload.get("role") != "admin":
            return "<h3>Error 403: Access Denied! Only System Admins can access this page.</h3>", 403
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated_function


def get_current_user_from_db():
    payload = getattr(request, 'current_user', None)
    if not payload:
        return None
    return db.session.get(User, payload.get("user_id"))


# --- HELPER FUNCTIONS ---

def trigger_low_stock_email(low_products):
    if not app.config['MAIL_PASSWORD'] or not low_products:
        return
    try:
        # FIX: hardcoded fake email काढला, env variable वापरतो
        admin_email = app.config['MAIL_USERNAME']
        msg = Message(
            "🚨 ALERT: Low-Stock Warehouse Notification",
            sender=admin_email,
            recipients=[admin_email]
        )
        body = "Hello System Manager,\n\nThe following items have dropped below their minimum threshold levels:\n\n"
        for item in low_products:
            body += f"- {item.name}: Only {item.quantity} left (Required Threshold: {item.threshold})\n"
        body += "\nPlease check your Inventory Dashboard to restock items."
        msg.body = body
        mail.send(msg)
    except Exception as e:
        print(f"Email failed to send: {e}")


# --- APPLICATION ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    current_user_data = get_current_user_from_db()
    if current_user_data.role.lower() != 'admin':
        flash("You do not have permission to create a new user!", "danger")
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"].lower()
        new_user = User(email=email, password=password, name=name, role=role)
        try:
            db.session.add(new_user)
            db.session.commit()
            flash(f"User {name} created successfully!", "success")
            return redirect(url_for('dashboard'))
        except Exception:
            db.session.rollback()
            return render_template("register.html", error="Email already exists!")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            # FIX: flask_login काढला, फक्त JWT वापरतो
            token = generate_jwt_token(user)
            response = make_response(redirect("/dashboard"))
            is_prod = os.environ.get("RENDER") is not None
            response.set_cookie(
                "jwt_token",
                token,
                httponly=True,
                secure=is_prod,
                samesite="Lax",
                max_age=60 * 60 * 24
            )
            return response
        else:
            return render_template("login.html", error="Invalid User or Password")
    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user_from_db()

    low_stock_products = Product.query.filter(Product.quantity <= Product.threshold).all()

    total_products_count = Product.query.count()
    total_stock_units = db.session.query(func.sum(Product.quantity)).scalar() or 0
    total_suppliers_count = Supplier.query.count()

    monthly_sales = db.session.query(
        func.to_char(Sales.sale_date, 'YYYY-MM').label('month'),
        func.sum(Sales.total_price).label('total_revenue')
    ).group_by('month').order_by('month').all()

    sales_labels = [s.month for s in monthly_sales] if monthly_sales else ['No Data']
    sales_data = [float(s.total_revenue) for s in monthly_sales] if monthly_sales else [0]

    top_products_data = db.session.query(
        Product.name,
        func.sum(Sales.qty_sold).label('total_sold')
    ).join(Sales).group_by(Product.name).order_by(func.sum(Sales.qty_sold).desc()).limit(5).all()

    chart_labels = [p[0] for p in top_products_data] if top_products_data else ["No Data"]
    chart_data = [int(p[1]) for p in top_products_data] if top_products_data else [0]

    return render_template(
        "dashboard.html",
        user=user,
        low_stock=low_stock_products,
        total_products=total_products_count,
        total_stock=total_stock_units,
        total_suppliers=total_suppliers_count,
        total_sales=Sales.query.count(),
        chart_labels=chart_labels,
        chart_data=chart_data,
        sales_labels=sales_labels,
        sales_data=sales_data
    )


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    user = get_current_user_from_db()

    if request.method == "POST":
        if user.role != 'admin':
            flash("Only admins can add new products!", "danger")
            return redirect("/products")

        name = request.form["name"]
        category = request.form["category"]
        quantity = int(request.form["quantity"])
        price = float(request.form["price"])
        threshold = int(request.form["threshold"])
        supplier_id = int(request.form["supplier_id"])

        new_product = Product(
            name=name, category=category, quantity=quantity,
            price=price, threshold=threshold, supplier_id=supplier_id,
        )
        try:
            db.session.add(new_product)
            db.session.commit()
            flash("Product added successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding product: {str(e)}", "danger")
        return redirect("/products")

    search_query = request.args.get("search", "").strip()
    category_filter = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    query = Product.query
    if search_query:
        query = query.filter(Product.name.like(f"%{search_query}%"))
    if category_filter:
        query = query.filter(Product.category == category_filter)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    all_products = pagination.items
    all_suppliers = Supplier.query.all()
    categories = [r.category for r in db.session.query(Product.category).distinct()]

    return render_template(
        "products.html",
        products=all_products,
        suppliers=all_suppliers,
        user=user,
        categories=categories,
        search=search_query,
        selected_cat=category_filter,
        pagination=pagination
    )


@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    current_user_data = getattr(request, 'current_user', None)
    user_role = current_user_data.get("role") if current_user_data else "staff"

    product = db.session.get(Product, id)
    if not product:
        flash('Product not found!', 'danger')
        return redirect(url_for('products'))

    suppliers = Supplier.query.all()

    if request.method == 'POST':
        try:
            if user_role == 'admin':
                product.name = request.form['name']
                product.category = request.form['category']
                product.price = float(request.form['price'])
                product.threshold = int(request.form['threshold'])
                product.supplier_id = int(request.form['supplier_id'])
                product.quantity = int(request.form['quantity'])
            else:
                product.quantity = int(request.form['quantity'])

            db.session.commit()
            flash('Product updated successfully!', 'success')
            return redirect(url_for('products'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating product: {str(e)}', 'danger')
            return redirect(url_for('products'))

    user = get_current_user_from_db()
    return render_template('edit_product.html', product=product, suppliers=suppliers, user=user)


@app.route('/products/delete/<int:id>')
@admin_required
def delete_product(id):
    product = db.session.get(Product, id)
    if product:
        try:
            db.session.delete(product)
            db.session.commit()
            flash('Product deleted successfully!', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting product: {str(e)}', 'danger')
    else:
        flash('Product not found!', 'danger')
    return redirect(url_for('products'))


# --- SUPPLIER ROUTES ---

@app.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    user = get_current_user_from_db()

    if request.method == "POST":
        if user.role != 'admin':
            flash("Permission denied!", "danger")
            return redirect("/suppliers")
        name = request.form["name"]
        contact_info = request.form["contact_info"]
        new_supplier = Supplier(name=name, contact_info=contact_info)
        try:
            db.session.add(new_supplier)
            db.session.commit()
            flash("New supplier added successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding supplier: {str(e)}", "danger")
        return redirect("/suppliers")

    search_query = request.args.get("search", "").strip()
    if search_query:
        all_suppliers = Supplier.query.filter(Supplier.name.like(f"%{search_query}%")).all()
    else:
        all_suppliers = Supplier.query.all()

    return render_template(
        "suppliers.html", suppliers=all_suppliers, user=user, search=search_query
    )


@app.route('/suppliers/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_supplier(id):
    supplier = db.session.get(Supplier, id)
    if not supplier:
        flash('Supplier not found!', 'danger')
        return redirect(url_for('suppliers'))

    if request.method == 'POST':
        try:
            supplier.name = request.form['name']
            supplier.contact_info = request.form['contact_info']
            db.session.commit()
            flash('Supplier updated successfully!', 'success')
            return redirect(url_for('suppliers'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating supplier: {str(e)}', 'danger')

    user = get_current_user_from_db()
    return render_template('edit_supplier.html', supplier=supplier, user=user)


@app.route('/suppliers/delete/<int:id>')
@admin_required
def delete_supplier(id):
    supplier = db.session.get(Supplier, id)
    if not supplier:
        flash('Supplier not found!', 'danger')
        return redirect(url_for('suppliers'))

    try:
        db.session.delete(supplier)
        db.session.commit()
        flash('Supplier and all their linked products deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting supplier: {str(e)}', 'danger')

    return redirect(url_for('suppliers'))


# --- SALES ROUTES ---

@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    error_msg = None

    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id"))
            qty_sold = int(request.form.get("qty_sold", 0))

            if qty_sold <= 0:
                error_msg = "Quantity must be at least 1."
            else:
                product = db.session.get(Product, product_id)

                if product:
                    if product.quantity < qty_sold:
                        error_msg = f"Insufficient stock! Only {product.quantity} items left."
                    else:
                        product.quantity -= qty_sold
                        total_price = product.price * qty_sold
                        new_sale = Sales(product_id=product_id, qty_sold=qty_sold, total_price=total_price)
                        db.session.add(new_sale)
                        db.session.commit()

                        if product.quantity <= product.threshold:
                            trigger_low_stock_email([product])

                        flash("Sale recorded successfully!", "success")
                        return redirect("/sales")
                else:
                    error_msg = "Product not found!"

        except ValueError:
            error_msg = "Invalid input! Please enter numbers for quantity."
        except Exception as e:
            db.session.rollback()
            error_msg = f"Database error: {str(e)}"

    all_sales = Sales.query.order_by(Sales.sale_date.desc()).all()
    all_products = Product.query.all()
    user = get_current_user_from_db()

    return render_template(
        "sales.html", sales=all_sales, products=all_products, error=error_msg, user=user
    )


@app.route('/sales/delete/<int:id>')
@admin_required
def delete_sale(id):
    sale = db.session.get(Sales, id)
    if not sale:
        flash('Sale record not found!', 'danger')
        return redirect(url_for('sales'))

    product = db.session.get(Product, sale.product_id)
    if product:
        product.quantity += sale.qty_sold

    try:
        db.session.delete(sale)
        db.session.commit()
        flash('Sale record deleted and stock restored successfully!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting sale log: {str(e)}', 'danger')
    return redirect(url_for('sales'))


# --- REPORTS ROUTES ---

@app.route("/reports")
@login_required
def reports():
    user = get_current_user_from_db()
    all_products = Product.query.all()

    total_valuation = sum([p.quantity * p.price for p in all_products])
    total_products_count = len(all_products)

    monthly_sales = db.session.query(
        func.to_char(Sales.sale_date, 'YYYY-MM').label('month'),
        func.sum(Sales.total_price).label('total')
    ).group_by('month').order_by('month').all()

    sales_labels = [s.month for s in monthly_sales] if monthly_sales else ['No Data']
    sales_data = [float(s.total) for s in monthly_sales] if monthly_sales else [0]

    top_products_data = db.session.query(
        Product.name,
        func.sum(Sales.qty_sold).label('total_sold')
    ).join(Sales).group_by(Product.name).order_by(func.sum(Sales.qty_sold).desc()).limit(5).all()

    chart_labels = [p[0] for p in top_products_data] if top_products_data else ["No Data"]
    chart_data = [int(p[1]) for p in top_products_data] if top_products_data else [0]

    return render_template(
        "reports.html",
        user=user,
        products=all_products,
        total_value=total_valuation,
        products_count=total_products_count,
        chart_labels=chart_labels,
        chart_data=chart_data,
        sales_labels=sales_labels,
        sales_data=sales_data
    )


@app.route("/reports/csv")
@login_required
def reports_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Product ID', 'Product Name', 'Category', 'Stock Qty', 'Price', 'Total Asset Value'])

    all_products = Product.query.all()
    for p in all_products:
        writer.writerow([p.id, p.name, p.category, p.quantity, p.price, p.quantity * p.price])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=Inventory_Valuation_Report.csv"
    return response


@app.route("/reports/pdf")
@login_required
def reports_pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>Inventory Stock Valuation Report</b>", styles['Title']))
    elements.append(Spacer(1, 15))

    data = [['ID', 'Product Name', 'Category', 'Stock Qty', 'Unit Price (INR)', 'Value (INR)']]
    total_valuation = 0

    all_products = Product.query.all()
    for p in all_products:
        val = p.quantity * p.price
        total_valuation += val
        data.append([p.id, p.name, p.category, p.quantity, f"{p.price}", f"{val}"])

    data.append(['', '', '', '', 'Grand Total:', f"{total_valuation}"])

    t = Table(data, colWidths=[40, 160, 100, 60, 70, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0b224e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f8fafc')),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#cbd5e1')),
        ('LINEABOVE', (0, -1), (-1, -1), 1.5, colors.HexColor('#0b224e')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold')
    ]))

    elements.append(t)
    doc.build(elements)
    buffer.seek(0)

    return Response(buffer.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=Inventory_Valuation_Report.pdf"})


@app.route("/invoice/<int:sale_id>")
@login_required
def generate_invoice(sale_id):
    sale = db.session.get(Sales, sale_id)
    if not sale:
        return "Sale not found", 404

    product = db.session.get(Product, sale.product_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("Inventory Management System", styles['Title']))
    elements.append(Paragraph("Sales Invoice", styles['Heading2']))
    elements.append(Paragraph("Pune, Maharashtra", styles['Normal']))
    elements.append(Paragraph("Email: support@gmail.com", styles['Normal']))
    elements.append(Spacer(1, 20))

    data = [
        ["Invoice No", f"INV-{sale.id}"],
        ["Date", sale.sale_date.strftime("%d-%m-%Y")],
        ["Product Name", product.name],
        ["Category", product.category],
        ["Quantity Sold", str(sale.qty_sold)],
        ["Unit Price", f"INR {product.price:.2f}"],
        ["Total Amount", f"INR {sale.total_price:.2f}"]
    ]

    table = Table(data, colWidths=[150, 250])
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey)
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Invoice_{sale.id}.pdf"}
    )


# --- SETTINGS ROUTES ---

@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    current_user = get_current_user_from_db()

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"].lower()

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("User with this Email already exists!", "danger")
        else:
            new_user = User(email=email, password=password, name=name, role=role)
            try:
                db.session.add(new_user)
                db.session.commit()
                flash("New user account successfully registered!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error registering user: {str(e)}", "danger")
        return redirect("/settings")

    all_users = User.query.all()
    return render_template("settings.html", user=current_user, users=all_users)


@app.route("/user/delete/<int:user_id>")
@admin_required
def delete_user(user_id):
    current_user_obj = get_current_user_from_db()
    user_to_delete = db.session.get(User, user_id)

    if user_to_delete:
        if user_to_delete.email != current_user_obj.email:
            try:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash("User account deleted successfully.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error deleting user: {str(e)}", "danger")
        else:
            flash("Cannot delete your own active session account!", "danger")
    else:
        flash("User not found!", "danger")

    return redirect("/settings")


@app.route("/logout")
def logout():
    response = make_response(redirect("/login"))
    response.delete_cookie("jwt_token")
    return response


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
