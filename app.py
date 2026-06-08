from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'edulibrary-secret-key-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///edulibrary.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Iltimos, tizimga kiring!'

# ───────────────────────────── MODELS ─────────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='librarian')  # admin / librarian

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    student_id = db.Column(db.String(30), unique=True, nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    borrows = db.relationship('Borrow', backref='student', lazy=True)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    isbn = db.Column(db.String(30), unique=True)
    category = db.Column(db.String(80))
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    borrows = db.relationship('Borrow', backref='book', lazy=True)


class Borrow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    borrow_date = db.Column(db.Date, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='borrowed')  # borrowed / returned / overdue

    @property
    def is_overdue(self):
        if self.status == 'borrowed' and self.due_date < date.today():
            return True
        return False


# ───────────────────────────── LOGIN ─────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Login yoki parol noto\'g\'ri!', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ───────────────────────────── DASHBOARD ─────────────────────────────

@app.route('/')
@login_required
def dashboard():
    total_books = Book.query.count()
    total_students = Student.query.count()
    active_borrows = Borrow.query.filter_by(status='borrowed').count()
    overdue_list = [b for b in Borrow.query.filter_by(status='borrowed').all() if b.is_overdue]
    recent_borrows = Borrow.query.order_by(Borrow.id.desc()).limit(8).all()
    return render_template('dashboard.html',
        total_books=total_books,
        total_students=total_students,
        active_borrows=active_borrows,
        overdue_count=len(overdue_list),
        recent_borrows=recent_borrows
    )


# ───────────────────────────── BOOKS ─────────────────────────────

@app.route('/books')
@login_required
def books():
    q = request.args.get('q', '')
    if q:
        book_list = Book.query.filter(
            (Book.title.ilike(f'%{q}%')) | (Book.author.ilike(f'%{q}%'))
        ).all()
    else:
        book_list = Book.query.order_by(Book.id.desc()).all()
    return render_template('books.html', books=book_list, q=q)


@app.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    if request.method == 'POST':
        book = Book(
            title=request.form['title'],
            author=request.form['author'],
            isbn=request.form.get('isbn') or None,
            category=request.form.get('category'),
            total_copies=int(request.form.get('total_copies', 1)),
            available_copies=int(request.form.get('total_copies', 1))
        )
        db.session.add(book)
        db.session.commit()
        flash('Kitob muvaffaqiyatli qo\'shildi!', 'success')
        return redirect(url_for('books'))
    return render_template('book_form.html', book=None)


@app.route('/books/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.title = request.form['title']
        book.author = request.form['author']
        book.isbn = request.form.get('isbn') or None
        book.category = request.form.get('category')
        db.session.commit()
        flash('Kitob yangilandi!', 'success')
        return redirect(url_for('books'))
    return render_template('book_form.html', book=book)


@app.route('/books/delete/<int:id>', methods=['POST'])
@login_required
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    flash('Kitob o\'chirildi!', 'info')
    return redirect(url_for('books'))


# ───────────────────────────── STUDENTS ─────────────────────────────

@app.route('/students')
@login_required
def students():
    q = request.args.get('q', '')
    if q:
        student_list = Student.query.filter(
            (Student.full_name.ilike(f'%{q}%')) | (Student.student_id.ilike(f'%{q}%'))
        ).all()
    else:
        student_list = Student.query.order_by(Student.id.desc()).all()
    return render_template('students.html', students=student_list, q=q)


@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        student = Student(
            full_name=request.form['full_name'],
            student_id=request.form['student_id'],
            grade=request.form['grade'],
            phone=request.form.get('phone')
        )
        db.session.add(student)
        db.session.commit()
        flash('O\'quvchi qo\'shildi!', 'success')
        return redirect(url_for('students'))
    return render_template('student_form.html', student=None)


@app.route('/students/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    student = Student.query.get_or_404(id)
    if request.method == 'POST':
        student.full_name = request.form['full_name']
        student.student_id = request.form['student_id']
        student.grade = request.form['grade']
        student.phone = request.form.get('phone')
        db.session.commit()
        flash('O\'quvchi yangilandi!', 'success')
        return redirect(url_for('students'))
    return render_template('student_form.html', student=student)


@app.route('/students/delete/<int:id>', methods=['POST'])
@login_required
def delete_student(id):
    student = Student.query.get_or_404(id)
    db.session.delete(student)
    db.session.commit()
    flash('O\'quvchi o\'chirildi!', 'info')
    return redirect(url_for('students'))


# ───────────────────────────── BORROWS ─────────────────────────────

@app.route('/borrows')
@login_required
def borrows():
    status_filter = request.args.get('status', 'all')
    if status_filter == 'borrowed':
        borrow_list = Borrow.query.filter_by(status='borrowed').all()
    elif status_filter == 'returned':
        borrow_list = Borrow.query.filter_by(status='returned').all()
    elif status_filter == 'overdue':
        borrow_list = [b for b in Borrow.query.filter_by(status='borrowed').all() if b.is_overdue]
    else:
        borrow_list = Borrow.query.order_by(Borrow.id.desc()).all()
    return render_template('borrows.html', borrows=borrow_list, status_filter=status_filter)


@app.route('/borrows/add', methods=['GET', 'POST'])
@login_required
def add_borrow():
    if request.method == 'POST':
        book = Book.query.get(int(request.form['book_id']))
        if book.available_copies < 1:
            flash('Bu kitobning nusxasi mavjud emas!', 'danger')
            return redirect(url_for('add_borrow'))
        from datetime import timedelta
        due = date.today() + timedelta(days=int(request.form.get('days', 14)))
        borrow = Borrow(
            student_id=int(request.form['student_id']),
            book_id=book.id,
            due_date=due
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
    db.session.commit()
    flash('Kitob qaytarildi!', 'success')
    return redirect(url_for('borrows'))


# ───────────────────────────── REPORTS ─────────────────────────────

@app.route('/reports')
@login_required
def reports():
    top_books = db.session.query(Book, db.func.count(Borrow.id).label('cnt'))\
        .join(Borrow).group_by(Book.id).order_by(db.text('cnt DESC')).limit(5).all()
    top_students = db.session.query(Student, db.func.count(Borrow.id).label('cnt'))\
        .join(Borrow).group_by(Student.id).order_by(db.text('cnt DESC')).limit(5).all()
    overdue_borrows = [b for b in Borrow.query.filter_by(status='borrowed').all() if b.is_overdue]
    return render_template('reports.html',
        top_books=top_books,
        top_students=top_students,
        overdue_borrows=overdue_borrows
    )


# ───────────────────────────── INIT DB ─────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)

        # Sample data
        if Book.query.count() == 0:
            sample_books = [
                Book(title='Ona tili va adabiyot', author='Abdulla Qodiriy', category='Adabiyot', total_copies=5, available_copies=5),
                Book(title='Matematika 9-sinf', author='T. Mirzaahmedov', category='Matematika', total_copies=3, available_copies=3),
                Book(title='Fizika 10-sinf', author='S. Bozorov', category='Fizika', total_copies=4, available_copies=4),
                Book(title='Ingliz tili', author='B. Mengliyev', category='Til', total_copies=6, available_copies=6),
                Book(title='Tarix 8-sinf', author='M. Sodiqov', category='Tarix', total_copies=3, available_copies=3),
            ]
            db.session.add_all(sample_books)

        if Student.query.count() == 0:
            sample_students = [
                Student(full_name='Aliyev Bobur Mansurovich', student_id='S001', grade='9-A', phone='+998901234567'),
                Student(full_name='Karimova Malika Saidovna', student_id='S002', grade='10-B', phone='+998907654321'),
                Student(full_name='Toshmatov Jasur Aliyevich', student_id='S003', grade='8-A', phone='+998991112233'),
            ]
            db.session.add_all(sample_students)

        db.session.commit()


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
