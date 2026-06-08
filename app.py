from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import os

app = Flask(__name__)

app.config['SECRET_KEY'] = 'edulibrary-secret-key-2026'
_db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'edulibrary.db')
os.makedirs(os.path.dirname(_db_path), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{_db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Iltimos, tizimga kiring!'

FINE_PER_DAY = 1000  # so'm per overdue day

# ───────────────────────────── MODELS ─────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='librarian')  # admin / librarian
    full_name = db.Column(db.String(150))
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        try:
            return self.full_name or self.username
        except Exception:
            return self.username


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    student_id = db.Column(db.String(30), unique=True, nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(10))           # erkak / ayol
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    date_of_birth = db.Column(db.Date)
    address = db.Column(db.String(250))
    parent_name = db.Column(db.String(150))
    parent_phone = db.Column(db.String(20))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    borrows = db.relationship('Borrow', backref='student', lazy=True, cascade='all, delete-orphan')

    @property
    def active_borrows(self):
        return [b for b in self.borrows if b.status == 'borrowed']

    @property
    def overdue_borrows(self):
        return [b for b in self.borrows if b.is_overdue]

    @property
    def total_fines(self):
        return sum(f.amount for b in self.borrows for f in b.fines if not f.paid)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    isbn = db.Column(db.String(30), unique=True)
    category = db.Column(db.String(80))
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    description = db.Column(db.Text)
    publisher = db.Column(db.String(150))
    year = db.Column(db.Integer)
    language = db.Column(db.String(50), default="O'zbek")
    shelf_location = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    borrows = db.relationship('Borrow', backref='book', lazy=True)

    @property
    def borrow_count(self):
        return len(self.borrows)


class Borrow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    borrow_date = db.Column(db.Date, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='borrowed')  # borrowed / returned / overdue
    notes = db.Column(db.String(250))
    fines = db.relationship('Fine', backref='borrow', lazy=True, cascade='all, delete-orphan')

    @property
    def is_overdue(self):
        return self.status == 'borrowed' and self.due_date < date.today()

    @property
    def days_overdue(self):
        if self.is_overdue:
            return (date.today() - self.due_date).days
        return 0

    @property
    def fine_amount(self):
        return self.days_overdue * FINE_PER_DAY


class Fine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    borrow_id = db.Column(db.Integer, db.ForeignKey('borrow.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    paid = db.Column(db.Boolean, default=False)
    paid_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ───────────────────────────── DECORATORS ─────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Bu sahifaga faqat admin kirishi mumkin!', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ───────────────────────────── LOGIN ─────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # is_active may be NULL on migrated rows — treat NULL as active
            if getattr(user, 'is_active', True) is False:
                flash("Hisobingiz bloklangan!", 'danger')
            else:
                try:
                    user.last_login = datetime.utcnow()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                login_user(user)
                return redirect(url_for('dashboard'))
        else:
            flash("Login yoki parol noto'g'ri!", 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ───────────────────────────── PROFILE ─────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_info':
            current_user.full_name = request.form.get('full_name', '').strip() or None
            current_user.email = request.form.get('email', '').strip() or None
            current_user.phone = request.form.get('phone', '').strip() or None
            db.session.commit()
            flash('Profil yangilandi!', 'success')
        elif action == 'change_password':
            old_pw = request.form.get('old_password', '')
            new_pw = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')
            if not current_user.check_password(old_pw):
                flash('Eski parol noto\'g\'ri!', 'danger')
            elif new_pw != confirm_pw:
                flash('Yangi parollar mos kelmadi!', 'danger')
            elif len(new_pw) < 6:
                flash('Parol kamida 6 ta belgidan iborat bo\'lishi kerak!', 'danger')
            else:
                current_user.set_password(new_pw)
                db.session.commit()
                flash('Parol muvaffaqiyatli o\'zgartirildi!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')


# ───────────────────────────── DASHBOARD ─────────────────────────────

@app.route('/')
@login_required
def dashboard():
    total_books = Book.query.count()
    total_students = Student.query.count()
    active_borrows = Borrow.query.filter_by(status='borrowed').count()
    all_active = Borrow.query.filter_by(status='borrowed').all()
    overdue_list = [b for b in all_active if b.is_overdue]
    total_copies = db.session.query(db.func.sum(Book.total_copies)).scalar() or 0
    available_copies = db.session.query(db.func.sum(Book.available_copies)).scalar() or 0
    returned_today = Borrow.query.filter_by(status='returned', return_date=date.today()).count()
    unpaid_fines = Fine.query.filter_by(paid=False).count()
    recent_borrows = Borrow.query.order_by(Borrow.id.desc()).limit(10).all()
    # category distribution
    from sqlalchemy import func
    cat_stats = db.session.query(Book.category, func.count(Book.id)).group_by(Book.category).all()
    return render_template('dashboard.html',
        total_books=total_books,
        total_students=total_students,
        active_borrows=active_borrows,
        overdue_count=len(overdue_list),
        total_copies=total_copies,
        available_copies=available_copies,
        returned_today=returned_today,
        unpaid_fines=unpaid_fines,
        recent_borrows=recent_borrows,
        cat_stats=cat_stats,
    )


# ───────────────────────────── BOOKS ─────────────────────────────

CATEGORIES = ['Adabiyot', 'Matematika', 'Fizika', 'Kimyo', 'Biologiya',
              'Tarix', 'Geografiya', 'Til', 'Texnologiya', 'Boshqa']
LANGUAGES = ["O'zbek", 'Rus', 'Ingliz', 'Boshqa']


@app.route('/books')
@login_required
def books():
    q = request.args.get('q', '')
    cat = request.args.get('cat', '')
    query = Book.query
    if q:
        query = query.filter(
            (Book.title.ilike(f'%{q}%')) | (Book.author.ilike(f'%{q}%')) | (Book.isbn.ilike(f'%{q}%'))
        )
    if cat:
        query = query.filter_by(category=cat)
    book_list = query.order_by(Book.title).all()
    return render_template('books.html', books=book_list, q=q, cat=cat, categories=CATEGORIES)


@app.route('/books/<int:id>')
@login_required
def book_detail(id):
    book = Book.query.get_or_404(id)
    history = Borrow.query.filter_by(book_id=id).order_by(Borrow.id.desc()).all()
    return render_template('book_detail.html', book=book, history=history)


@app.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    if request.method == 'POST':
        copies = int(request.form.get('total_copies', 1))
        book = Book(
            title=request.form['title'].strip(),
            author=request.form['author'].strip(),
            isbn=request.form.get('isbn', '').strip() or None,
            category=request.form.get('category'),
            total_copies=copies,
            available_copies=copies,
            description=request.form.get('description', '').strip() or None,
            publisher=request.form.get('publisher', '').strip() or None,
            year=int(request.form['year']) if request.form.get('year') else None,
            language=request.form.get('language') or "O'zbek",
            shelf_location=request.form.get('shelf_location', '').strip() or None,
        )
        db.session.add(book)
        db.session.commit()
        flash("Kitob muvaffaqiyatli qo'shildi!", 'success')
        return redirect(url_for('books'))
    return render_template('book_form.html', book=None, categories=CATEGORIES, languages=LANGUAGES)


@app.route('/books/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.title = request.form['title'].strip()
        book.author = request.form['author'].strip()
        book.isbn = request.form.get('isbn', '').strip() or None
        book.category = request.form.get('category')
        book.description = request.form.get('description', '').strip() or None
        book.publisher = request.form.get('publisher', '').strip() or None
        book.year = int(request.form['year']) if request.form.get('year') else None
        book.language = request.form.get('language') or "O'zbek"
        book.shelf_location = request.form.get('shelf_location', '').strip() or None
        # adjust available copies if total changed
        new_total = int(request.form.get('total_copies', book.total_copies))
        diff = new_total - book.total_copies
        book.total_copies = new_total
        book.available_copies = max(0, book.available_copies + diff)
        db.session.commit()
        flash('Kitob yangilandi!', 'success')
        return redirect(url_for('book_detail', id=book.id))
    return render_template('book_form.html', book=book, categories=CATEGORIES, languages=LANGUAGES)


@app.route('/books/delete/<int:id>', methods=['POST'])
@login_required
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    flash("Kitob o'chirildi!", 'info')
    return redirect(url_for('books'))


# ───────────────────────────── STUDENTS ─────────────────────────────

GRADES = [f'{g}-{s}' for g in range(1, 12) for s in ['A', 'B', 'C']]


@app.route('/students')
@login_required
def students():
    q = request.args.get('q', '')
    grade_filter = request.args.get('grade', '')
    query = Student.query
    if q:
        query = query.filter(
            (Student.full_name.ilike(f'%{q}%')) |
            (Student.student_id.ilike(f'%{q}%')) |
            (Student.phone.ilike(f'%{q}%'))
        )
    if grade_filter:
        query = query.filter_by(grade=grade_filter)
    student_list = query.order_by(Student.full_name).all()
    all_grades = sorted(set(s.grade for s in Student.query.all()))
    return render_template('students.html', students=student_list, q=q,
                           grade_filter=grade_filter, all_grades=all_grades)


@app.route('/students/<int:id>')
@login_required
def student_detail(id):
    student = Student.query.get_or_404(id)
    history = Borrow.query.filter_by(student_id=id).order_by(Borrow.id.desc()).all()
    return render_template('student_detail.html', student=student, history=history)


@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        dob_str = request.form.get('date_of_birth', '').strip()
        dob = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        student = Student(
            full_name=request.form['full_name'].strip(),
            student_id=request.form['student_id'].strip(),
            grade=request.form['grade'],
            gender=request.form.get('gender') or None,
            phone=request.form.get('phone', '').strip() or None,
            email=request.form.get('email', '').strip() or None,
            date_of_birth=dob,
            address=request.form.get('address', '').strip() or None,
            parent_name=request.form.get('parent_name', '').strip() or None,
            parent_phone=request.form.get('parent_phone', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
        )
        db.session.add(student)
        db.session.commit()
        flash("O'quvchi qo'shildi!", 'success')
        return redirect(url_for('students'))
    return render_template('student_form.html', student=None, grades=GRADES)


@app.route('/students/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    student = Student.query.get_or_404(id)
    if request.method == 'POST':
        dob_str = request.form.get('date_of_birth', '').strip()
        student.full_name = request.form['full_name'].strip()
        student.student_id = request.form['student_id'].strip()
        student.grade = request.form['grade']
        student.gender = request.form.get('gender') or None
        student.phone = request.form.get('phone', '').strip() or None
        student.email = request.form.get('email', '').strip() or None
        student.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        student.address = request.form.get('address', '').strip() or None
        student.parent_name = request.form.get('parent_name', '').strip() or None
        student.parent_phone = request.form.get('parent_phone', '').strip() or None
        student.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash("O'quvchi yangilandi!", 'success')
        return redirect(url_for('student_detail', id=student.id))
    return render_template('student_form.html', student=student, grades=GRADES)


@app.route('/students/delete/<int:id>', methods=['POST'])
@login_required
def delete_student(id):
    student = Student.query.get_or_404(id)
    db.session.delete(student)
    db.session.commit()
    flash("O'quvchi o'chirildi!", 'info')
    return redirect(url_for('students'))


# ───────────────────────────── BORROWS ─────────────────────────────

@app.route('/borrows')
@login_required
def borrows():
    status_filter = request.args.get('status', 'all')
    q = request.args.get('q', '')
    query = Borrow.query
    if q:
        query = query.join(Student).filter(Student.full_name.ilike(f'%{q}%'))
    if status_filter == 'borrowed':
        query = query.filter(Borrow.status == 'borrowed')
    elif status_filter == 'returned':
        query = query.filter(Borrow.status == 'returned')
    borrow_list = query.order_by(Borrow.id.desc()).all()
    if status_filter == 'overdue':
        borrow_list = [b for b in Borrow.query.filter_by(status='borrowed').all() if b.is_overdue]
    return render_template('borrows.html', borrows=borrow_list, status_filter=status_filter, q=q)


@app.route('/borrows/add', methods=['GET', 'POST'])
@login_required
def add_borrow():
    if request.method == 'POST':
        book = db.session.get(Book, int(request.form['book_id']))
        if not book or book.available_copies < 1:
            flash('Bu kitobning nusxasi mavjud emas!', 'danger')
            return redirect(url_for('add_borrow'))
        due = date.today() + timedelta(days=int(request.form.get('days', 14)))
        borrow = Borrow(
            student_id=int(request.form['student_id']),
            book_id=book.id,
            due_date=due,
            notes=request.form.get('notes', '').strip() or None,
        )
        book.available_copies -= 1
        db.session.add(borrow)
        db.session.commit()
        flash('Kitob berildi!', 'success')
        return redirect(url_for('borrows'))
    students_list = Student.query.order_by(Student.full_name).all()
    books_list = Book.query.filter(Book.available_copies > 0).order_by(Book.title).all()
    return render_template('borrow_form.html', students=students_list, books=books_list)


@app.route('/borrows/return/<int:id>', methods=['POST'])
@login_required
def return_book(id):
    borrow = Borrow.query.get_or_404(id)
    borrow.return_date = date.today()
    borrow.status = 'returned'
    borrow.book.available_copies += 1
    # create fine if overdue
    if borrow.due_date < date.today():
        days = (date.today() - borrow.due_date).days
        fine = Fine(borrow_id=borrow.id, amount=days * FINE_PER_DAY)
        db.session.add(fine)
        flash(f"Kitob qaytarildi! Kechikish: {days} kun. Jarima: {days * FINE_PER_DAY:,} so'm", 'warning')
    else:
        flash('Kitob qaytarildi!', 'success')
    db.session.commit()
    return redirect(url_for('borrows'))


# ───────────────────────────── FINES ─────────────────────────────

@app.route('/fines')
@login_required
def fines():
    paid_filter = request.args.get('paid', 'unpaid')
    if paid_filter == 'paid':
        fine_list = Fine.query.filter_by(paid=True).order_by(Fine.id.desc()).all()
    else:
        fine_list = Fine.query.filter_by(paid=False).order_by(Fine.id.desc()).all()
    total_unpaid = db.session.query(db.func.sum(Fine.amount)).filter_by(paid=False).scalar() or 0
    return render_template('fines.html', fines=fine_list, paid_filter=paid_filter, total_unpaid=total_unpaid)


@app.route('/fines/pay/<int:id>', methods=['POST'])
@login_required
def pay_fine(id):
    fine = Fine.query.get_or_404(id)
    fine.paid = True
    fine.paid_date = date.today()
    db.session.commit()
    flash('Jarima to\'landi!', 'success')
    return redirect(url_for('fines'))


@app.route('/fines/pay-all', methods=['POST'])
@login_required
def pay_all_fines():
    student_id = request.form.get('student_id', type=int)
    query = Fine.query.filter_by(paid=False)
    if student_id:
        query = query.join(Borrow).filter(Borrow.student_id == student_id)
    for fine in query.all():
        fine.paid = True
        fine.paid_date = date.today()
    db.session.commit()
    flash("Barcha jarimalar to'landi!", 'success')
    return redirect(url_for('fines'))


# ───────────────────────────── REPORTS ─────────────────────────────

@app.route('/reports')
@login_required
def reports():
    top_books = db.session.query(Book, db.func.count(Borrow.id).label('cnt'))\
        .join(Borrow).group_by(Book.id).order_by(db.text('cnt DESC')).limit(10).all()
    top_students = db.session.query(Student, db.func.count(Borrow.id).label('cnt'))\
        .join(Borrow).group_by(Student.id).order_by(db.text('cnt DESC')).limit(10).all()
    overdue_borrows = [b for b in Borrow.query.filter_by(status='borrowed').all() if b.is_overdue]
    # monthly borrow stats (last 6 months)
    monthly = []
    for i in range(5, -1, -1):
        d = date.today().replace(day=1) - timedelta(days=i * 30)
        cnt = Borrow.query.filter(
            db.func.strftime('%Y-%m', Borrow.borrow_date) == d.strftime('%Y-%m')
        ).count()
        monthly.append({'month': d.strftime('%b %Y'), 'count': cnt})
    # category stats
    cat_stats = db.session.query(Book.category, db.func.count(Book.id))\
        .group_by(Book.category).all()
    return render_template('reports.html',
        top_books=top_books,
        top_students=top_students,
        overdue_borrows=overdue_borrows,
        monthly=monthly,
        cat_stats=cat_stats,
    )


# ───────────────────────────── USERS (admin) ─────────────────────────────

@app.route('/users')
@login_required
@admin_required
def users():
    user_list = User.query.order_by(User.id).all()
    return render_template('users.html', users=user_list)


@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username'].strip()
        if User.query.filter_by(username=username).first():
            flash('Bu username allaqachon mavjud!', 'danger')
            return redirect(url_for('add_user'))
        user = User(
            username=username,
            role=request.form.get('role', 'librarian'),
            full_name=request.form.get('full_name', '').strip() or None,
            email=request.form.get('email', '').strip() or None,
            phone=request.form.get('phone', '').strip() or None,
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        flash('Foydalanuvchi qo\'shildi!', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=None)


@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.full_name = request.form.get('full_name', '').strip() or None
        user.email = request.form.get('email', '').strip() or None
        user.phone = request.form.get('phone', '').strip() or None
        user.role = request.form.get('role', 'librarian')
        user.is_active = 'is_active' in request.form
        new_pw = request.form.get('new_password', '').strip()
        if new_pw:
            user.set_password(new_pw)
        db.session.commit()
        flash('Foydalanuvchi yangilandi!', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=user)


@app.route('/users/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    if id == current_user.id:
        flash('O\'zingizni o\'chira olmaysiz!', 'danger')
        return redirect(url_for('users'))
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Foydalanuvchi o\'chirildi!', 'info')
    return redirect(url_for('users'))


# ───────────────────────────── EXPORT ─────────────────────────────

@app.route('/export/borrows')
@login_required
def export_borrows():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', "O'quvchi", 'Sinf', 'Kitob', 'Muallif', 'Berilgan sana',
                     'Qaytarish muddati', 'Qaytarilgan sana', 'Holat', 'Kechikish (kun)', 'Jarima (so\'m)'])
    for b in Borrow.query.order_by(Borrow.id.desc()).all():
        writer.writerow([
            b.id, b.student.full_name, b.student.grade,
            b.book.title, b.book.author,
            b.borrow_date, b.due_date,
            b.return_date or '',
            'Qaytarildi' if b.status == 'returned' else ("Muddati o'tdi" if b.is_overdue else 'Berilgan'),
            b.days_overdue,
            b.fine_amount,
        ])
    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=borrows_{date.today()}.csv'}
    )


@app.route('/export/students')
@login_required
def export_students():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'F.I.Sh.', 'ID raqam', 'Sinf', 'Jinsi', 'Telefon', 'Email',
                     "Tug'ilgan sana", 'Manzil', 'Ota-ona', 'Ota-ona telefon',
                     'Faol kitoblar', "Jami berilgan", "Ro'yxatga olingan"])
    for s in Student.query.order_by(Student.full_name).all():
        writer.writerow([
            s.id, s.full_name, s.student_id, s.grade, s.gender or '',
            s.phone or '', s.email or '', s.date_of_birth or '', s.address or '',
            s.parent_name or '', s.parent_phone or '',
            len(s.active_borrows), len(s.borrows),
            s.created_at.strftime('%Y-%m-%d'),
        ])
    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=students_{date.today()}.csv'}
    )


@app.route('/export/books')
@login_required
def export_books():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Nomi', 'Muallif', 'ISBN', 'Kategoriya', 'Nashriyot',
                     'Yil', 'Til', 'Javon', 'Jami nusxa', 'Mavjud nusxa', 'Berilgan marta'])
    for b in Book.query.order_by(Book.title).all():
        writer.writerow([
            b.id, b.title, b.author, b.isbn or '', b.category or '',
            b.publisher or '', b.year or '', b.language or '',
            b.shelf_location or '', b.total_copies, b.available_copies, b.borrow_count,
        ])
    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=books_{date.today()}.csv'}
    )


# ───────────────────────────── INIT DB (single context, no nesting) ─────────────────────────────

def init_db():
    """Create tables, migrate missing columns, seed initial data.
    Called once at module level — safe under both `python app.py` and gunicorn.
    """
    from sqlalchemy import inspect, text

    with app.app_context():
        # 1. Create any brand-new tables
        db.create_all()

        # 2. Add missing columns to EXISTING tables (for already-deployed databases)
        insp = inspect(db.engine)
        existing_tables = insp.get_table_names()

        def _add(table, col, col_type):
            """ALTER TABLE … ADD COLUMN if the column is absent."""
            if table not in existing_tables:
                return
            present = [c['name'] for c in insp.get_columns(table)]
            if col not in present:
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text(
                            f'ALTER TABLE "{table}" ADD COLUMN {col} {col_type}'
                        ))
                        conn.commit()
                except Exception:
                    pass  # column already added by a concurrent worker, ignore

        # student
        _add('student', 'gender',        'VARCHAR(10)')
        _add('student', 'email',         'VARCHAR(120)')
        _add('student', 'date_of_birth', 'DATE')
        _add('student', 'address',       'VARCHAR(250)')
        _add('student', 'parent_name',   'VARCHAR(150)')
        _add('student', 'parent_phone',  'VARCHAR(20)')
        _add('student', 'notes',         'TEXT')
        # user
        _add('user', 'full_name',  'VARCHAR(150)')
        _add('user', 'email',      'VARCHAR(120)')
        _add('user', 'phone',      'VARCHAR(20)')
        _add('user', 'is_active',  'BOOLEAN DEFAULT 1')
        _add('user', 'last_login', 'DATETIME')
        _add('user', 'created_at', 'DATETIME')
        # book
        _add('book', 'description',    'TEXT')
        _add('book', 'publisher',      'VARCHAR(150)')
        _add('book', 'year',           'INTEGER')
        _add('book', 'language',       'VARCHAR(50)')
        _add('book', 'shelf_location', 'VARCHAR(50)')
        # borrow
        _add('borrow', 'notes', 'VARCHAR(250)')

        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='admin', full_name='Bosh Administrator',
                         email='admin@edulibrary.uz', phone='+998901000001')
            admin.set_password('admin123')
            db.session.add(admin)

        if not User.query.filter_by(username='librarian').first():
            lib = User(username='librarian', role='librarian', full_name='Kutubxonachi Hamida',
                       email='hamida@edulibrary.uz', phone='+998901000002')
            lib.set_password('lib123')
            db.session.add(lib)

        if Book.query.count() == 0:
            sample_books = [
                Book(title="O'tkan kunlar", author='Abdulla Qodiriy', category='Adabiyot',
                     isbn='978-9943-01-001-1', total_copies=5, available_copies=5,
                     publisher='Sharq', year=2010, language="O'zbek", shelf_location='A-1',
                     description="O'zbek klassik romanlaridan biri. Muhabbat va milliy ozodlik mavzusi."),
                Book(title='Matematika 9-sinf', author='T. Mirzaahmedov', category='Matematika',
                     isbn='978-9943-01-002-2', total_copies=8, available_copies=8,
                     publisher="O'zbekiston", year=2022, language="O'zbek", shelf_location='B-1',
                     description='9-sinf matematika darsligi.'),
                Book(title='Fizika 10-sinf', author='S. Bozorov', category='Fizika',
                     isbn='978-9943-01-003-3', total_copies=6, available_copies=6,
                     publisher='TDPU', year=2021, language="O'zbek", shelf_location='B-2',
                     description='Mexanika, termodinamika va optika bo\'limlari.'),
                Book(title='Ingliz tili 8-sinf', author='B. Mengliyev', category='Til',
                     isbn='978-9943-01-004-4', total_copies=10, available_copies=10,
                     publisher='Nihol', year=2023, language="O'zbek", shelf_location='C-1',
                     description="O'rta maktab ingliz tili darsligi."),
                Book(title='Tarix 8-sinf', author='M. Sodiqov', category='Tarix',
                     isbn='978-9943-01-005-5', total_copies=4, available_copies=4,
                     publisher='Yangi nashr', year=2020, language="O'zbek", shelf_location='D-1',
                     description="O'zbekiston tarixi 8-sinf uchun."),
                Book(title='Kimyo 9-sinf', author='N. Nurullayev', category='Kimyo',
                     isbn='978-9943-01-006-6', total_copies=5, available_copies=5,
                     publisher='Fan', year=2021, language="O'zbek", shelf_location='B-3'),
                Book(title='Biologiya 10-sinf', author='A. Xolmatov', category='Biologiya',
                     isbn='978-9943-01-007-7', total_copies=4, available_copies=4,
                     publisher='Fan', year=2022, language="O'zbek", shelf_location='B-4'),
                Book(title='Geografiya 7-sinf', author='H. Hasanov', category='Geografiya',
                     isbn='978-9943-01-008-8', total_copies=6, available_copies=6,
                     publisher='Sharq', year=2019, language="O'zbek", shelf_location='D-2'),
                Book(title='Informatika 9-sinf', author='T. Rajabov', category='Texnologiya',
                     isbn='978-9943-01-009-9', total_copies=3, available_copies=3,
                     publisher='Fan va texnologiya', year=2023, language="O'zbek", shelf_location='E-1'),
                Book(title='Sherlar va qo\'shiqlar', author='Alisher Navoiy', category='Adabiyot',
                     isbn='978-9943-01-010-0', total_copies=7, available_copies=7,
                     publisher='Sharq', year=2015, language="O'zbek", shelf_location='A-2',
                     description="Buyuk shoir Alisher Navoiyning asarlari to'plami."),
            ]
            db.session.add_all(sample_books)

        if Student.query.count() == 0:
            sample_students = [
                Student(full_name='Aliyev Bobur Mansurovich', student_id='S001', grade='9-A',
                        gender='erkak', phone='+998901234567', email='bobur@example.com',
                        date_of_birth=date(2009, 3, 15), address='Toshkent sh., Yunusobod t.',
                        parent_name='Aliyev Mansur', parent_phone='+998901234560'),
                Student(full_name='Karimova Malika Saidovna', student_id='S002', grade='10-B',
                        gender='ayol', phone='+998907654321', email='malika@example.com',
                        date_of_birth=date(2008, 7, 22), address='Toshkent sh., Chilonzor t.',
                        parent_name='Karimov Said', parent_phone='+998907654320'),
                Student(full_name='Toshmatov Jasur Aliyevich', student_id='S003', grade='8-A',
                        gender='erkak', phone='+998991112233', email='jasur@example.com',
                        date_of_birth=date(2010, 1, 5), address='Toshkent sh., Shayxontohur t.',
                        parent_name='Toshmatov Ali', parent_phone='+998991112230'),
                Student(full_name='Nazarova Zulfiya Baxtiyorovna', student_id='S004', grade='7-B',
                        gender='ayol', phone='+998933334455', email='zulfiya@example.com',
                        date_of_birth=date(2011, 9, 10), address='Toshkent sh., Mirzo Ulugbek t.',
                        parent_name='Nazarov Baxtiyor', parent_phone='+998933334450'),
                Student(full_name='Umarov Sherzod Qodirovitch', student_id='S005', grade='11-A',
                        gender='erkak', phone='+998945556677', email='sherzod@example.com',
                        date_of_birth=date(2007, 12, 3), address='Toshkent sh., Sergeli t.',
                        parent_name='Umarov Qodir', parent_phone='+998945556670'),
                Student(full_name='Xoliqova Nargiza Ilhomovna', student_id='S006', grade='10-A',
                        gender='ayol', phone='+998956667788', email='nargiza@example.com',
                        date_of_birth=date(2008, 4, 18), address='Toshkent sh., Yakkasaroy t.',
                        parent_name='Xoliqov Ilhom', parent_phone='+998956667780'),
                Student(full_name='Mirzayev Sardor Ulugbek o\'g\'li', student_id='S007', grade='9-B',
                        gender='erkak', phone='+998967778899', email='sardor@example.com',
                        date_of_birth=date(2009, 8, 25), address='Toshkent sh., Bektemir t.',
                        parent_name='Mirzayev Ulugbek', parent_phone='+998967778890'),
                Student(full_name='Rашидова Камола Бахромовна', student_id='S008', grade='8-B',
                        gender='ayol', phone='+998978889900', email='kamola@example.com',
                        date_of_birth=date(2010, 6, 30), address='Toshkent sh., Olmazar t.',
                        parent_name='Rashidov Baxrom', parent_phone='+998978889900'),
                Student(full_name='Yusupov Asilbek Hamidovich', student_id='S009', grade='11-B',
                        gender='erkak', phone='+998989990011', email='asilbek@example.com',
                        date_of_birth=date(2007, 2, 14), address='Toshkent sh., Uchtepa t.',
                        parent_name='Yusupov Hamid', parent_phone='+998989990010'),
                Student(full_name='Abdullayeva Dilnoza Ravshan qizi', student_id='S010', grade='7-A',
                        gender='ayol', phone='+998990001122', email='dilnoza@example.com',
                        date_of_birth=date(2011, 11, 8), address='Toshkent sh., Zangiota t.',
                        parent_name='Abdullayev Ravshan', parent_phone='+998990001120'),
            ]
            db.session.add_all(sample_students)
            db.session.flush()  # get IDs

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


# ── Run migrations + seed data on every startup (works under gunicorn too) ──
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
