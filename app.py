"""
D-SCAE Flask Backend  |  app.py
Install: pip install flask cx_Oracle flask-session
Run:     python app.py
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import oracledb as cx_Oracle
import hashlib
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ── Oracle connection ──────────────────────────────────────────────────────────
DB_DSN  = cx_Oracle.makedsn("localhost", 1521, service_name="XE")   # adjust as needed
DB_USER = "dscae"   # your Oracle username
DB_PASS = "dscae123" # your Oracle password

def get_conn():
    return cx_Oracle.connect(user=DB_USER, password=DB_PASS, dsn=DB_DSN)

def query(sql, params=None, fetchall=True):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or {})
        cols = [d[0].lower() for d in cur.description]
        rows = cur.fetchall() if fetchall else cur.fetchone()
        if fetchall:
            return [dict(zip(cols, r)) for r in rows]
        return dict(zip(cols, rows)) if rows else None

def execute(sql, params=None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or {})
        conn.commit()

# ── Auth helpers ───────────────────────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def seed_users_if_requested():
    """
    Optional one-time seeding helper.
    Controlled via env var: DSCAE_SEED_USERS=1
    Inserts users only if username doesn't already exist.
    """
    if os.getenv("DSCAE_SEED_USERS") != "1":
        return

    # Seed admin
    admin = query("SELECT user_id FROM USERS WHERE username=:u", {'u': 'admin1'}, fetchall=False)
    if not admin:
        execute(
            """INSERT INTO USERS VALUES (SEQ_USER.NEXTVAL,:un,:em,:pw,:br,:cg,:sem,'admin',SYSDATE)""",
            {
                'un': 'admin1',
                'em': 'admin1@example.com',
                'pw': hash_pw('Admin@123'),
                'br': 'ADMIN',
                'cg': 10.0,
                'sem': 'NA'
            }
        )

    # Seed a demo student
    student = query("SELECT user_id FROM USERS WHERE username=:u", {'u': 'student1'}, fetchall=False)
    if not student:
        execute(
            """INSERT INTO USERS VALUES (SEQ_USER.NEXTVAL,:un,:em,:pw,:br,:cg,:sem,'student',SYSDATE)""",
            {
                'un': 'student1',
                'em': 'student1@example.com',
                'pw': hash_pw('Student@123'),
                'br': 'CSE',
                'cg': 8.5,
                'sem': '6'
            }
        )

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Admin access required.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = query(
            "SELECT * FROM USERS WHERE username=:u AND password_hash=:p",
            {'u': request.form['username'], 'p': hash_pw(request.form['password'])},
            fetchall=False
        )
        if user:
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role']     = user['role']
            return redirect(url_for('dashboard'))
        flash("Invalid credentials.", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        execute(
            """INSERT INTO USERS VALUES (SEQ_USER.NEXTVAL,:un,:em,:pw,:br,:cg,:sem,'student',SYSDATE)""",
            {
                'un':  request.form['username'],
                'em':  request.form['email'],
                'pw':  hash_pw(request.form['password']),
                'br':  request.form['branch'],
                'cg':  float(request.form['cgpa']),
                'sem': request.form['semester']
            }
        )
        flash("Account created! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if session['role'] == 'admin':
        forms = query("SELECT * FROM FORMS ORDER BY form_id DESC")
    else:
        # Only show open forms the student is eligible for
        forms = query("""
            SELECT f.*, fn_is_eligible(:uid, f.form_id) AS eligible
            FROM   FORMS f
            WHERE  f.status = 'open' AND f.end_date >= SYSDATE
        """, {'uid': session['user_id']})
    return render_template('dashboard.html', forms=forms)

# ── Forms (admin only) ─────────────────────────────────────────────────────────

@app.route('/forms/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_form():
    if request.method == 'POST':
        execute("""
            INSERT INTO FORMS (form_id,created_by,title,description,status,start_date,end_date)
            VALUES (SEQ_FORM.NEXTVAL,:cb,:t,:d,'open',TO_DATE(:sd,'YYYY-MM-DD'),TO_DATE(:ed,'YYYY-MM-DD'))
        """, {
            'cb': session['user_id'],
            't':  request.form['title'],
            'd':  request.form['description'],
            'sd': request.form['start_date'],
            'ed': request.form['end_date']
        })
        form = query("SELECT MAX(form_id) AS fid FROM FORMS", fetchall=False)
        return redirect(url_for('edit_form_fields', form_id=form['fid']))
    return render_template('form_create.html')

@app.route('/forms/<int:form_id>/fields', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_form_fields(form_id):
    if request.method == 'POST':
        execute("""
            INSERT INTO FORM_FIELDS (field_id,form_id,field_name,field_type,is_required,validation_rule,display_order)
            VALUES (SEQ_FIELD.NEXTVAL,:fid,:fn,:ft,:req,:vr,:ord)
        """, {
            'fid': form_id, 'fn': request.form['field_name'],
            'ft':  request.form['field_type'],
            'req': 1 if request.form.get('is_required') else 0,
            'vr':  request.form.get('validation_rule') or None,
            'ord': request.form.get('display_order', 1)
        })
    fields = query("SELECT * FROM FORM_FIELDS WHERE form_id=:fid ORDER BY display_order", {'fid': form_id})
    return render_template('form_fields.html', form_id=form_id, fields=fields)

@app.route('/forms/<int:form_id>/rules', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_form_rules(form_id):
    if request.method == 'POST':
        execute("""
            INSERT INTO ACCESS_RULES (rule_id,form_id,attribute_name,operator,attribute_value)
            VALUES (SEQ_RULE.NEXTVAL,:fid,:an,:op,:av)
        """, {
            'fid': form_id,
            'an':  request.form['attribute_name'],
            'op':  request.form['operator'],
            'av':  request.form['attribute_value']
        })
    rules = query("SELECT * FROM ACCESS_RULES WHERE form_id=:fid", {'fid': form_id})
    return render_template('form_rules.html', form_id=form_id, rules=rules)

# ── Submissions (students) ─────────────────────────────────────────────────────

@app.route('/forms/<int:form_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_form(form_id):
    eligible = query(
        "SELECT fn_is_eligible(:uid,:fid) AS e FROM DUAL",
        {'uid': session['user_id'], 'fid': form_id},
        fetchall=False
    )
    if not eligible or eligible['e'] != 'ELIGIBLE':
        flash("You are not eligible for this form.", "danger")
        return redirect(url_for('dashboard'))

    fields = query("SELECT * FROM FORM_FIELDS WHERE form_id=:fid ORDER BY display_order", {'fid': form_id})
    form = query("SELECT * FROM FORMS WHERE form_id=:fid", {'fid': form_id}, fetchall=False)

    if request.method == 'POST':
        with get_conn() as conn:
            cur = conn.cursor()
            sub_id_var = cur.var(cx_Oracle.NUMBER)
            field_ids = cx_Oracle.Array(cx_Oracle.NUMBER, [f['field_id'] for f in fields])
            values    = cx_Oracle.Array(cx_Oracle.STRING, [request.form.get(f'field_{f["field_id"]}','') for f in fields])
            try:
                cur.callproc('sp_submit_form', [form_id, session['user_id'], field_ids, values, sub_id_var])
                conn.commit()
                flash(f"Submitted successfully! (ID: {int(sub_id_var.getvalue())})", "success")
                return redirect(url_for('dashboard'))
            except cx_Oracle.DatabaseError as e:
                flash(str(e), "danger")

    return render_template('form_submit.html', form_id=form_id, form=form, fields=fields)

# ── Analytics ─────────────────────────────────────────────────────────────────

@app.route('/analytics/<int:form_id>')
@login_required
@admin_required
def analytics(form_id):
    form = query("SELECT * FROM FORMS WHERE form_id=:fid", {'fid': form_id}, fetchall=False)
    stats = query("""
        SELECT ff.field_name, ff.field_type,
               COUNT(r.response_id) AS total,
               ROUND(AVG(CASE WHEN ff.field_type='NUMERIC' THEN TO_NUMBER(r.response_value) END),2) AS avg_val,
               SUM(CASE WHEN UPPER(r.response_value)='YES' THEN 1 ELSE 0 END) AS yes_count,
               SUM(CASE WHEN UPPER(r.response_value)='NO'  THEN 1 ELSE 0 END) AS no_count
        FROM   FORM_FIELDS ff
        LEFT   JOIN RESPONSES r   ON r.field_id = ff.field_id
        LEFT   JOIN SUBMISSIONS s ON s.submission_id = r.submission_id
        WHERE  ff.form_id = :fid
        GROUP  BY ff.field_id, ff.field_name, ff.field_type
    """, {'fid': form_id})
    participation = query("""
        SELECT COUNT(DISTINCT s.user_id) AS submitted,
               (SELECT COUNT(*) FROM USERS WHERE role='student') AS total
        FROM   SUBMISSIONS s WHERE s.form_id=:fid
    """, {'fid': form_id}, fetchall=False)
    return render_template('analytics.html', form=form, stats=stats, participation=participation)

# ── API endpoint for dashboard refresh ────────────────────────────────────────
@app.route('/api/forms')
@login_required
def api_forms():
    forms = query("SELECT form_id, title, status, end_date FROM FORMS WHERE status='open'")
    return jsonify(forms)

if __name__ == '__main__':
    seed_users_if_requested()
    app.run(debug=True, port=5000)
