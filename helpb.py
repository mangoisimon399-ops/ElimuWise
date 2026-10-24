from flask import Flask, request, session, redirect, jsonify, render_template_string
import requests, json, os, uuid, sqlite3, re
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-to-a-long-random-secret-before-deployment")

INTASEND_PUBLISHABLE_KEY = os.environ.get("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.environ.get("INTASEND_SECRET_KEY")
INTASEND_API_BASE = "https://api.intasend.com/api/v1"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_MPESA_PHONE = "254712345678" 

DB_FILE = "students.json"
AGENTS_FILE = "agents.json"
WITHDRAW_FILE = "withdrawals.json"
EARNINGS_FILE = "earnings.json"  # Permanent payment/commission ledger; do not clear when student records are reset.
PAYMENT_SETTINGS_FILE = "payment_settings.json"

def get_payment_settings():
    """Load editable prices/commission; create defaults matching the existing setup."""
    defaults = {"direct_price": 600, "agent_price": 800, "agent_commission": 240, "minimum_withdrawal": 240}
    try:
        with open(PAYMENT_SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        settings = defaults.copy()
        if isinstance(stored, dict):
            for key in defaults:
                try:
                    value = int(stored.get(key, defaults[key]))
                    if value >= 0:
                        settings[key] = value
                except (TypeError, ValueError):
                    pass
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        settings = defaults.copy()
    # Commission cannot exceed the agent-referred student price.
    settings["agent_commission"] = min(settings["agent_commission"], settings["agent_price"])
    return settings

def save_payment_settings(settings):
    with open(PAYMENT_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

# Built-in education fees API (SQLite). Fee records are only treated as exact when
# they have a source URL, are verified, and match the configured academic year.
EDUCATION_FEES_DB = os.environ.get("EDUCATION_FEES_DB", "education_fees.sqlite3")
EDUCATION_FEE_YEAR = os.environ.get("EDUCATION_FEE_YEAR", "2026/2027")
EDUCATION_API_ADMIN_TOKEN = os.environ.get("EDUCATION_API_ADMIN_TOKEN", "")

# Existing category estimates are retained only as fallbacks when no verified,
# current-year fee record exists for the exact institution + course.
COURSE_ESTIMATES = {
    "medicine": 600000,
    "engineering": 400000,
    "computer": 300000,
    "education_science": 300000,
    "education_arts": 250000,
    "law": 250000,
    "other": 250000,
}

CUE_SOURCE_URL = "https://www.cue.or.ke/index.php?Itemid=492&id=81%3Aapproved-academic-programmes-dec-2023&option=com_phocadownload&view=category"
# Seeded directory of 89 CUE-listed university institutions, based on the register
# published for 15 September 2026. Includes chartered universities, specialized
# degree-awarding institutions, constituent colleges, and Letters of Interim Authority.
# This is not a claim that every institution has current course/fee data.
SEED_INSTITUTIONS = [
    ('University of Nairobi', 'public'),
    ('Moi University', 'public'),
    ('Kenyatta University', 'public'),
    ('Egerton University', 'public'),
    ('Jomo Kenyatta University of Agriculture and Technology', 'public'),
    ('Maseno University', 'public'),
    ('Masinde Muliro University of Science and Technology', 'public'),
    ('Dedan Kimathi University of Technology', 'public'),
    ('Chuka University', 'public'),
    ('Technical University of Kenya', 'public'),
    ('Technical University of Mombasa', 'public'),
    ('Pwani University', 'public'),
    ('Kisii University', 'public'),
    ('University of Eldoret', 'public'),
    ('Maasai Mara University', 'public'),
    ('Jaramogi Oginga Odinga University of Science and Technology', 'public'),
    ('Laikipia University', 'public'),
    ('South Eastern Kenya University', 'public'),
    ('Meru University of Science and Technology', 'public'),
    ('Multimedia University of Kenya', 'public'),
    ('University of Kabianga', 'public'),
    ('Karatina University', 'public'),
    ('Kibabii University', 'public'),
    ('Rongo University', 'public'),
    ('The Co-operative University of Kenya', 'public'),
    ('Taita Taveta University', 'public'),
    ("Murang'a University of Technology", 'public'),
    ('University of Embu', 'public'),
    ('Machakos University', 'public'),
    ('Kirinyaga University', 'public'),
    ('Garissa University', 'public'),
    ('Alupe University', 'public'),
    ('Kaimosi Friends University', 'public'),
    ('Tom Mboya University', 'public'),
    ('Tharaka University', 'public'),
    ('Bomet University', 'public'),
    ('National Defence University-Kenya', 'public'),
    ('Open University of Kenya', 'public'),
    ('National Intelligence Research University', 'public'),
    ('Kenya Advanced Institute of Science and Technology', 'public'),
    ('Kenya Medical Research Institute', 'public'),
    ('Turkana University College', 'public'),
    ('Koitaleel Samoei University College', 'public'),
    ('Mama Ngina University College', 'public'),
    ('Nyandarua University College', 'public'),
    ('Kabarnet University College', 'public'),
    ('Makueni University College', 'public'),
    ('Kerio Valley University College', 'public'),
    ('University of Eastern Africa, Baraton', 'private'),
    ('Catholic University of Eastern Africa', 'private'),
    ('Daystar University', 'private'),
    ('Scott Christian University', 'private'),
    ('United States International University-Africa', 'private'),
    ('Africa Nazarene University', 'private'),
    ('Kenya Methodist University', 'private'),
    ("St. Paul's University", 'private'),
    ('Pan Africa Christian University', 'private'),
    ('Strathmore University', 'private'),
    ('Kabarak University', 'private'),
    ('Mount Kenya University', 'private'),
    ('Africa International University', 'private'),
    ('Kenya Highlands Evangelical University', 'private'),
    ('Great Lakes University of Kisumu', 'private'),
    ('KCA University', 'private'),
    ('Adventist University of Africa', 'private'),
    ('KAG EAST University', 'private'),
    ('Umma University', 'private'),
    ('Presbyterian University of East Africa', 'private'),
    ('Aga Khan University', 'private'),
    ("Kiriri Women's University of Science and Technology", 'private'),
    ('The East African University', 'private'),
    ('Zetech University', 'private'),
    ('Lukenya University', 'private'),
    ('Management University of Africa', 'private'),
    ('Tangaza University', 'private'),
    ('Islamic University of Kenya', 'private'),
    ('Riara University', 'private'),
    ('Uzima University', 'private'),
    ('Gretsa University', 'private'),
    ('Amref International University', 'private'),
    ('Hekima University College', 'private'),
    ('Marist International University College', 'private'),
    ('Pioneer International University', 'private'),
    ('International Leadership University', 'private'),
    ('Consolata International University', 'private'),
    ('Outspan Global University', 'private'),
    ('The African Talent University', 'private'),
    ('East Kenya Integrated University', 'private'),
    ('Kamagambo University', 'private'),
]


# Additional institution directory for the student form. These are selectable
# institution names, not a claim that the list covers every TVET college/campus.
SEED_COLLEGES = [
    "Nairobi National Polytechnic", "Kenya Coast National Polytechnic",
    "Kisumu National Polytechnic", "Eldoret National Polytechnic",
    "Nyeri National Polytechnic", "Meru National Polytechnic",
    "Kabete National Polytechnic", "Sigalagala National Polytechnic",
    "Rift Valley National Polytechnic", "Kiambu National Polytechnic",
    "Thika Technical Training Institute", "Kenya Technical Trainers College",
    "Kenya Institute of Highways and Building Technology",
    "Kenya Water Institute", "Kenya Institute of Social Work and Community Development",
    "Nairobi Technical Training Institute", "PC Kinyanjui Technical Training Institute",
    "Mombasa Technical Training Institute", "Coast Institute of Technology",
    "Rift Valley Institute of Science and Technology", "Michuki Technical Training Institute",
    "The Nyandarua National Polytechnic", "Bungoma National Polytechnic",
    "Kitale National Polytechnic", "Kisiwa Technical Training Institute",
    "Baringo National Polytechnic", "Kajiado West Technical and Vocational College",
    "Murang'a Technical Training Institute", "Nakuru Training Institute",
    "Kaiboi Technical Training Institute", "Kisii National Polytechnic",
    "Keroka Technical Training Institute", "Bomet Technical Training Institute",
    "Mathenge Technical Training Institute", "Shamberere Technical Training Institute",
    "Webuye West Technical and Vocational College", "Wote Technical Training Institute",
    "Kwale Technical and Vocational College", "Lamu East Technical and Vocational College",
    "Garissa Technical Training Institute", "Mandera Technical Training Institute",
    "Wajir Technical Training Institute", "Kibwezi Technical Training Institute",
    "Mukurwe-ini Technical Training Institute", "Nyandarua Institute of Science and Technology"
]

SEED_KMTC = [
    "KMTC Nairobi Campus", "KMTC Mombasa Campus", "KMTC Kisumu Campus",
    "KMTC Nakuru Campus", "KMTC Eldoret Campus", "KMTC Nyeri Campus",
    "KMTC Kakamega Campus", "KMTC Kisii Campus", "KMTC Meru Campus",
    "KMTC Thika Campus", "KMTC Machakos Campus", "KMTC Kitui Campus",
    "KMTC Embu Campus", "KMTC Garissa Campus", "KMTC Lodwar Campus",
    "KMTC Kakuma Campus", "KMTC Kabarnet Campus", "KMTC Kapkatet Campus",
    "KMTC Kericho Campus", "KMTC Bomet Campus", "KMTC Bungoma Campus",
    "KMTC Busia Campus", "KMTC Homa Bay Campus", "KMTC Migori Campus",
    "KMTC Kisumu Campus", "KMTC Siaya Campus", "KMTC Vihiga Campus",
    "KMTC Kitale Campus", "KMTC Webuye Campus", "KMTC Makueni Campus",
    "KMTC Kilifi Campus", "KMTC Msambweni Campus", "KMTC Port Reitz Campus",
    "KMTC Taveta Campus", "KMTC Murang'a Campus", "KMTC Kangema Campus",
    "KMTC Nyahururu Campus", "KMTC Mwingi Campus", "KMTC Isiolo Campus",
    "KMTC Marsabit Campus", "KMTC Molo Campus", "KMTC Bondo Campus",
    "KMTC Chuka Campus", "KMTC Karuri Campus", "KMTC Loitokitok Campus",
    "KMTC Voi Campus", "KMTC Mpeketoni Campus", "KMTC Rachuonyo Campus"
]

def db_connect():
    conn = sqlite3.connect(EDUCATION_FEES_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_education_db():
    with db_connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            ownership TEXT NOT NULL CHECK(ownership IN ('public','private')),
            institution_type TEXT NOT NULL DEFAULT 'university' CHECK(institution_type IN ('university','college','kmtc')),
            official_source_url TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
            name TEXT NOT NULL COLLATE NOCASE,
            category TEXT NOT NULL DEFAULT 'other',
            UNIQUE(institution_id, name)
        );
        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            academic_year TEXT NOT NULL,
            annual_fee INTEGER NOT NULL CHECK(annual_fee >= 0),
            student_type TEXT NOT NULL DEFAULT 'all',
            source_url TEXT NOT NULL,
            source_title TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, academic_year, student_type)
        );
        CREATE INDEX IF NOT EXISTS idx_courses_institution ON courses(institution_id);
        CREATE INDEX IF NOT EXISTS idx_fees_course_year ON fees(course_id, academic_year, verified);
        """)
        # Migrate databases created by older versions.
        institution_columns = {row[1] for row in conn.execute("PRAGMA table_info(institutions)").fetchall()}
        if "institution_type" not in institution_columns:
            conn.execute("ALTER TABLE institutions ADD COLUMN institution_type TEXT NOT NULL DEFAULT 'university'")
        for name, ownership in SEED_INSTITUTIONS:
            conn.execute("INSERT OR IGNORE INTO institutions(name, ownership, institution_type, official_source_url) VALUES(?,?,?,?)", (name, ownership, 'university', CUE_SOURCE_URL))
        for name in SEED_COLLEGES:
            conn.execute("INSERT OR IGNORE INTO institutions(name, ownership, institution_type, official_source_url) VALUES(?,?,?,?)", (name, 'public', 'college', 'https://www.tveta.go.ke/'))
        for name in set(SEED_KMTC):
            conn.execute("INSERT OR IGNORE INTO institutions(name, ownership, institution_type, official_source_url) VALUES(?,?,?,?)", (name, 'public', 'kmtc', 'https://www.kmtc.ac.ke/'))
        # Migrate a couple of names from the earlier seed without deleting course/fee data.
        legacy_names = {
            "National Intelligence and Research University": "National Intelligence Research University",
            "Bomet University College": "Bomet University",
        }
        for old_name, current_name in legacy_names.items():
            old_row = conn.execute("SELECT id FROM institutions WHERE name=? COLLATE NOCASE", (old_name,)).fetchone()
            current_row = conn.execute("SELECT id FROM institutions WHERE name=? COLLATE NOCASE", (current_name,)).fetchone()
            if old_row and not current_row:
                conn.execute("UPDATE institutions SET name=?, official_source_url=? WHERE id=?", (current_name, CUE_SOURCE_URL, old_row["id"]))
            elif old_row and current_row:
                # Retain the legacy record only if it has course data; otherwise remove the duplicate.
                has_courses = conn.execute("SELECT 1 FROM courses WHERE institution_id=? LIMIT 1", (old_row["id"],)).fetchone()
                if not has_courses:
                    conn.execute("DELETE FROM institutions WHERE id=?", (old_row["id"],))
        # Remove obsolete seeded entries only when they have no course records; preserve user data.
        current_seed_names = ({name.casefold() for name, _ in SEED_INSTITUTIONS}
                              | {name.casefold() for name in SEED_COLLEGES}
                              | {name.casefold() for name in SEED_KMTC})
        for row in conn.execute("SELECT id, name FROM institutions").fetchall():
            if row["name"].casefold() not in current_seed_names:
                has_courses = conn.execute("SELECT 1 FROM courses WHERE institution_id=? LIMIT 1", (row["id"],)).fetchone()
                if not has_courses:
                    conn.execute("DELETE FROM institutions WHERE id=?", (row["id"],))
        # Historical example data from the Open University of Kenya's official fee
        # page. It is stored as 2025/2026 and is deliberately NOT treated as current
        # for the 2026/2027 calculator unless the user requests that academic year.
        ouk = conn.execute("SELECT id FROM institutions WHERE name = ?", ("Open University of Kenya",)).fetchone()
        if ouk:
            historical = [
                ("Bachelor of Data Science", "computer", 79000),
                ("Bachelor of Science in Cyber Security and Digital Forensics", "computer", 79000),
                ("Bachelor of Technology Education", "education_science", 86000),
                ("Bachelor of Education (Arts)", "education_arts", 79000),
                ("Bachelor of Computer Science", "computer", 79000),
                ("Bachelor of Science in Nursing", "medicine", 344000),
            ]
            for course_name, category, fee in historical:
                conn.execute("INSERT OR IGNORE INTO courses(institution_id, name, category) VALUES(?,?,?)", (ouk["id"], course_name, category))
                course = conn.execute("SELECT id FROM courses WHERE institution_id=? AND name=?", (ouk["id"], course_name)).fetchone()
                conn.execute("INSERT OR IGNORE INTO fees(course_id, academic_year, annual_fee, student_type, source_url, source_title, verified) VALUES(?,?,?,?,?,?,1)", (course["id"], "2025/2026", fee, "all", "https://ouk.ac.ke/node/164", "Open University of Kenya programme fee structure (2025/2026)") )

init_education_db()

def get_education_catalog():
    """Return institutions/courses from the local catalogue for the existing form."""
    with db_connect() as conn:
        institutions = conn.execute("SELECT id, name, ownership, institution_type FROM institutions ORDER BY name").fetchall()
        result = []
        for inst in institutions:
            rows = conn.execute("""SELECT c.id, c.name, c.category,
                f.annual_fee, f.academic_year, f.source_url, f.verified
                FROM courses c LEFT JOIN fees f ON f.course_id=c.id
                AND f.academic_year=? AND f.verified=1
                WHERE c.institution_id=? ORDER BY c.name""", (EDUCATION_FEE_YEAR, inst["id"])).fetchall()
            result.append({"id": inst["id"], "name": inst["name"], "ownership": inst["ownership"], "type": inst["institution_type"], "courses": [dict(r) for r in rows]})
        return result

def find_official_course_fee(institution_name, course_name):
    """Return only a verified, sourced fee for the configured academic year."""
    if not institution_name or not course_name:
        return None
    with db_connect() as conn:
        row = conn.execute("""SELECT f.annual_fee, f.academic_year, f.source_url, f.source_title,
            f.student_type, i.name AS institution_name, c.name AS course_name
            FROM institutions i JOIN courses c ON c.institution_id=i.id
            JOIN fees f ON f.course_id=c.id
            WHERE i.name = ? COLLATE NOCASE AND c.name = ? COLLATE NOCASE
            AND f.academic_year=? AND f.student_type='all' AND f.verified=1 AND f.source_url <> ''
            ORDER BY f.checked_at DESC LIMIT 1""", (institution_name.strip(), course_name.strip(), EDUCATION_FEE_YEAR)).fetchone()
        return dict(row) if row else None

def admin_token_valid():
    supplied = request.headers.get("X-API-ADMIN-TOKEN", "")
    return bool(EDUCATION_API_ADMIN_TOKEN) and supplied == EDUCATION_API_ADMIN_TOKEN

@app.route('/api/health')
def education_api_health():
    return jsonify({"status": "ok", "api": "education-fees", "academic_year": EDUCATION_FEE_YEAR})

@app.route('/api')
def education_api_info():
    return jsonify({
        "name": "Kenya University Education Fees API",
        "version": "1.1",
        "institution_directory_count": 89,
        "institution_directory_scope": "CUE-listed university institutions: chartered universities, specialized degree-awarding institutions, constituent colleges, and institutions with Letters of Interim Authority; not 89 fully chartered universities.",
        "academic_year_default": EDUCATION_FEE_YEAR,
        "endpoints": {
            "health": "/api/health",
            "institutions": "/api/institutions?institution_type=university|college|kmtc",
            "courses": "/api/courses?institution_id=1",
            "fees": "/api/fees?institution_id=1&academic_year=2026/2027",
            "admin_add_institution": "POST /api/admin/institutions",
            "admin_add_or_update_fee": "POST /api/admin/fees"
        },
        "fee_policy": "Only fees with verified=true, a source URL, and the requested academic year are returned by /api/fees and used as exact fees."
    })

@app.route('/api/institutions')
def api_institutions():
    ownership = request.args.get("ownership", "").lower()
    institution_type = request.args.get("institution_type", "").lower()
    clauses, args = [], []
    if ownership in ("public", "private"):
        clauses.append("ownership=?"); args.append(ownership)
    if institution_type in ("university", "college", "kmtc"):
        clauses.append("institution_type=?"); args.append(institution_type)
    sql = "SELECT id, name, ownership, institution_type, official_source_url FROM institutions"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name"
    with db_connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return jsonify({"count": len(rows), "institutions": [dict(r) for r in rows]})

@app.route('/api/courses')
def api_courses():
    institution_id = request.args.get("institution_id", type=int)
    if not institution_id:
        return jsonify({"error": "institution_id is required"}), 400
    with db_connect() as conn:
        rows = conn.execute("""SELECT c.id, c.name, c.category FROM courses c
            WHERE c.institution_id=? ORDER BY c.name""", (institution_id,)).fetchall()
    return jsonify({"count": len(rows), "courses": [dict(r) for r in rows]})

@app.route('/api/fees')
def api_fees():
    institution_id = request.args.get("institution_id", type=int)
    course_id = request.args.get("course_id", type=int)
    academic_year = request.args.get("academic_year", EDUCATION_FEE_YEAR)
    with db_connect() as conn:
        sql = """SELECT i.id AS institution_id, i.name AS institution, i.ownership, i.institution_type,
            c.id AS course_id, c.name AS course, c.category, f.annual_fee,
            f.academic_year, f.student_type, f.source_url, f.source_title,
            f.verified, f.checked_at FROM fees f JOIN courses c ON c.id=f.course_id
            JOIN institutions i ON i.id=c.institution_id WHERE f.academic_year=? AND f.verified=1"""
        args = [academic_year]
        if institution_id:
            sql += " AND i.id=?"; args.append(institution_id)
        if course_id:
            sql += " AND c.id=?"; args.append(course_id)
        sql += " ORDER BY i.name, c.name"
        rows = conn.execute(sql, args).fetchall()
    return jsonify({"academic_year": academic_year, "count": len(rows), "fees": [dict(r) for r in rows]})

@app.route('/api/admin/institutions', methods=['POST'])
def api_admin_add_institution():
    if not admin_token_valid():
        return jsonify({"error": "Unauthorized. Configure EDUCATION_API_ADMIN_TOKEN and send X-API-ADMIN-TOKEN."}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    ownership = str(data.get("ownership", "")).lower().strip()
    institution_type = str(data.get("institution_type", "university")).lower().strip()
    source_url = str(data.get("official_source_url", "")).strip()
    if not name or ownership not in ("public", "private") or institution_type not in ("university", "college", "kmtc") or not source_url.startswith("https://"):
        return jsonify({"error": "name, ownership (public/private), institution_type (university/college/kmtc), and an https official_source_url are required"}), 400
    try:
        with db_connect() as conn:
            cur = conn.execute("INSERT INTO institutions(name, ownership, institution_type, official_source_url) VALUES(?,?,?,?)", (name, ownership, institution_type, source_url))
            return jsonify({"id": cur.lastrowid, "name": name, "ownership": ownership, "institution_type": institution_type}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Institution already exists"}), 409

@app.route('/api/admin/fees', methods=['POST'])
def api_admin_add_fee():
    if not admin_token_valid():
        return jsonify({"error": "Unauthorized. Configure EDUCATION_API_ADMIN_TOKEN and send X-API-ADMIN-TOKEN."}), 401
    data = request.get_json(silent=True) or {}
    institution_name = str(data.get("institution", "")).strip()
    course_name = str(data.get("course", "")).strip()
    category = str(data.get("category", "other")).strip().lower()
    academic_year = str(data.get("academic_year", "")).strip()
    student_type = str(data.get("student_type", "all")).strip().lower()
    source_url = str(data.get("source_url", "")).strip()
    source_title = str(data.get("source_title", "")).strip()
    try:
        annual_fee = int(data.get("annual_fee"))
    except (TypeError, ValueError):
        return jsonify({"error": "annual_fee must be a whole number"}), 400
    allowed_categories = set(COURSE_ESTIMATES)
    if not institution_name or not course_name or not academic_year or annual_fee < 0 or category not in allowed_categories or not source_url.startswith("https://") or not source_title:
        return jsonify({"error": "institution, course, category, academic_year, non-negative annual_fee, https source_url, and source_title are required"}), 400
    # Admin must explicitly attest that the official source was checked.
    if data.get("verified") is not True:
        return jsonify({"error": "Set verified=true only after checking the official institution fee document/page."}), 400
    with db_connect() as conn:
        inst = conn.execute("SELECT id FROM institutions WHERE name=? COLLATE NOCASE", (institution_name,)).fetchone()
        if not inst:
            return jsonify({"error": "Institution not found; add it first through /api/admin/institutions"}), 404
        conn.execute("INSERT INTO courses(institution_id, name, category) VALUES(?,?,?) ON CONFLICT(institution_id,name) DO UPDATE SET category=excluded.category", (inst["id"], course_name, category))
        course = conn.execute("SELECT id FROM courses WHERE institution_id=? AND name=? COLLATE NOCASE", (inst["id"], course_name)).fetchone()
        conn.execute("""INSERT INTO fees(course_id, academic_year, annual_fee, student_type, source_url, source_title, verified, checked_at)
            VALUES(?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
            ON CONFLICT(course_id, academic_year, student_type) DO UPDATE SET annual_fee=excluded.annual_fee,
            source_url=excluded.source_url, source_title=excluded.source_title, verified=1, checked_at=CURRENT_TIMESTAMP""",
            (course["id"], academic_year, annual_fee, student_type, source_url, source_title))
        return jsonify({"status": "saved", "institution": institution_name, "course": course_name, "annual_fee": annual_fee, "academic_year": academic_year, "source_url": source_url, "verified": True}), 201

def load_json(f, default=None):
    if default is None:
        default = []
    if not os.path.exists(f):
        with open(f, 'w') as fd:
            json.dump(default, fd)
        return default
    try:
        with open(f, 'r') as fd:
            return json.load(fd)
    except (OSError, json.JSONDecodeError):
        return default

def save_json(f,data):
    with open(f,'w') as fd: json.dump(data,fd,indent=2)

def record_paid_earning(student):
    """Store a confirmed payment once in a separate ledger that survives student-record resets."""
    if not student or not student.get('paid') or not student.get('order_ref'):
        return
    earnings = load_json(EARNINGS_FILE)
    if any(e.get('order_ref') == student.get('order_ref') for e in earnings):
        return
    earnings.append({
        "order_ref": student.get("order_ref"),
        "date": student.get("paid_date") or student.get("date"),
        "name": student.get("name"),
        "ref_code": student.get("ref_code"),
        "price": int(student.get("price", 0) or 0),
        "agent_earning": int(student.get("agent_earning", 0) or 0),
        "owner_earning": int(student.get("owner_earning", 0) or 0),
        "paid": True
    })
    save_json(EARNINGS_FILE, earnings)

def sync_earnings_from_student_records():
    """Backfill the ledger from already-paid records before any records are cleared."""
    for student in load_json(DB_FILE):
        if student.get('paid'):
            record_paid_earning(student)
    return load_json(EARNINGS_FILE)

def calculate_full(data):
    try:
        income = int(data.get('mother_income', 0) or 0) + int(data.get('father_income', 0) or 0) + int(data.get('guardian_income', 0) or 0)
    except (TypeError, ValueError):
        income = 0
    try: hs_fee=int(data.get('hs_fee',0))
    except: hs_fee=0
    try: primary_fee=int(data.get('primary_fee',0))
    except: primary_fee=0
    parent_type=data.get('parent_type','both')
    school_fee_payer = str(data.get('school_fee_payer', 'parent')).strip().lower()
    institution_type=data.get('institution_type','university')
    institution_name = str(data.get('institution_name', '')).strip()
    course_name = str(data.get('course_name', '')).strip()
    course_category = str(data.get('course_category', 'other')).strip().lower()
    exact_fee = find_official_course_fee(institution_name, course_name)
    if exact_fee:
        total_annual_fees = int(exact_fee['annual_fee'])
        fee_source = 'verified_official_source'
    else:
        total_annual_fees = COURSE_ESTIMATES.get(course_category, COURSE_ESTIMATES['other'])
        fee_source = 'category_estimate'
    
    score=100
    if parent_type=='single': score+=15
    elif parent_type=='orphan': score=90
    
    if income>50000: score-=25
    elif income>25000: score-=10
    
    if hs_fee < 20000: score+=10
    if primary_fee < 10000: score+=5

    # Band 1 is assigned only when all requested conditions are met:
    # combined monthly household support/income below KSh 3,000,
    # the student is supported by one parent or a guardian (orphan status),
    # and high-school fees were paid by a sponsor.
    band_one_eligible = (
        income < 3000
        and parent_type in ('single', 'orphan')
        and school_fee_payer == 'sponsor'
    )
    # Band 2 requires a sponsor, one-parent household, and monthly income
    # from KSh 3,000 through KSh 5,000 inclusive.
    band_two_eligible = (
        3000 <= income <= 5000
        and parent_type == 'single'
        and school_fee_payer == 'sponsor'
    )
    if band_one_eligible:
        band = "BAND 1"
    elif band_two_eligible:
        band = "BAND 2"
    elif score>=40: band="BAND 3"
    elif score>=20: band="BAND 4"
    else: band="BAND 5"

    # Exact Band Funding Allocation Logic
    if band == "BAND 1":
        scholarship_pct = 70
        loan_pct = 25
        household_pct = 5
        upkeep_year = 60000
        upkeep_sem = 30000
    elif band == "BAND 2":
        scholarship_pct = 60
        loan_pct = 30
        household_pct = 10
        upkeep_year = 55000
        upkeep_sem = 27500
    elif band == "BAND 3":
        scholarship_pct = 50
        loan_pct = 30
        household_pct = 20
        upkeep_year = 50000
        upkeep_sem = 25000
    elif band == "BAND 4":
        scholarship_pct = 40
        loan_pct = 30
        household_pct = 30
        upkeep_year = 45000
        upkeep_sem = 22500
    else: # BAND 5
        scholarship_pct = 30
        loan_pct = 30
        household_pct = 40
        upkeep_year = 40000
        upkeep_sem = 20000

    # Fallback ranges for colleges and KMTC if specified, but mapping directly to official allocations
    if institution_type != 'university':
        if institution_type == 'college':
            upkeep_year = int(upkeep_year * 0.6)
            upkeep_sem = int(upkeep_sem * 0.6)
        else: # KMTC
            upkeep_year = int(upkeep_year * 0.4)
            upkeep_sem = int(upkeep_sem * 0.4)

    scholarship_amount = int(total_annual_fees * (scholarship_pct / 100))
    loan_amount = int(total_annual_fees * (loan_pct / 100))
    household_amount = int(total_annual_fees * (household_pct / 100))

    guidance = []
    if band in ["BAND 3", "BAND 4", "BAND 5"]:
        guidance.append("To secure a better band (e.g., Band 1 or Band 2) and maximize your upkeep, ensure your family income is documented accurately as low/unstable.")
        guidance.append("Make sure your high school fees history accurately reflects financial strain or fee arrears if applicable, as low secondary and primary school fees strongly support high need scoring.")
        if parent_type == 'single':
            guidance.append("Ensure you have your **Single Parent Certificate** ready for verification, proving that only one parent is providing for you.")
        elif parent_type == 'orphan':
            guidance.append("Have your **Death Certificate(s)** and official orphan/guardian supporting letters ready.")
        else:
            guidance.append("Even with both parents, securing a Single Parent Certificate or proof of absolute financial incapacity for one parent can boost your score.")
    else:
        guidance.append("You are already in a top funding band! Ensure you keep your admission documents, ID, and bank/M-Pesa details ready for smooth HEF disbursement.")

    return {
        "score": score,
        "band": band,
        "institution": institution_type,
        "institution_name": institution_name,
        "course_name": course_name,
        "course_category": course_category,
        "school_fee_payer": school_fee_payer,
        "band_one_eligible": band_one_eligible,
        "band_two_eligible": band_two_eligible,
        "fee_source": fee_source,
        "academic_year": exact_fee.get('academic_year') if exact_fee else EDUCATION_FEE_YEAR,
        "fee_source_url": exact_fee.get('source_url') if exact_fee else None,
        "fee_source_title": exact_fee.get('source_title') if exact_fee else None,
        "total_annual_fees": total_annual_fees,
        "scholarship_pct": scholarship_pct,
        "scholarship_amount": scholarship_amount,
        "loan_pct": loan_pct,
        "loan_amount": loan_amount,
        "household_pct": household_pct,
        "household_amount": household_amount,
        "upkeep_year": upkeep_year,
        "upkeep_sem": upkeep_sem,
        "upkeep": f"Ksh {upkeep_year:,} per year (Ksh {upkeep_sem:,} per semester)",
        "guidance": guidance
    }

@app.route('/')
def home():
    return redirect('/student')

@app.route('/student')
def index():
    ref=request.args.get('ref')
    agent=None
    if ref:
        agents=load_json(AGENTS_FILE)
        agent=next((a for a in agents if a['code']==ref),None)
        if agent:
            session['ref_code']=ref
        else:
            session.pop('ref_code', None)
    else:
        # A normal student portal visit is a direct payment, not an old agent referral.
        session.pop('ref_code', None)
    
    payment_settings = get_payment_settings()
    price = payment_settings["agent_price"] if agent else payment_settings["direct_price"]
    direct_price = payment_settings["direct_price"]
    agent_price = payment_settings["agent_price"]
    
    return render_template_string("""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
    <style>body{font-family:Arial;padding:15px;max-width:600px;margin:auto;background:#f5f5f5}input,select{box-sizing:border-box;width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #ccc}label{display:block;font-weight:600;margin-top:10px}.field-help{display:block;color:#555;font-size:13px;margin:0 0 5px}.card{background:white;padding:15px;border-radius:10px}button{width:100%;padding:14px;background:green;color:white;border:none;border-radius:8px}</style></head><body>
    <h2>HEF Band Checker & Funding Allocation {% if agent %} - Agent: {{agent.name}}{% endif %}</h2>
    {% if agent %}<div style="background:#eaffea;padding:10px;border-radius:8px">Price: <b>Ksh {{agent_price}}</b> - Powered by {{agent.name}}</div>
    {% else %}<div style="background:#e7f3ff;padding:10px;border-radius:8px">Direct Price: Ksh {{direct_price}} - Standard Portal</div>{% endif %}
    
    <form action="/pay{% if agent %}?ref={{agent.code}}{% endif %}" method="POST" class="card">
    <input name="name" placeholder="Student Full Name" required>
    <label>Institution Type:</label>
    <select name="institution_type" required>
        <option value="university">University</option>
        <option value="college">College</option>
        <option value="kmtc">KMTC</option>
    </select>
    <label for="institution_name">Search Your Institution:</label>
    <input id="institution_name" name="institution_name" list="institution_options" autocomplete="off" placeholder="Start typing your institution name" required>
    <datalist id="institution_options"></datalist>
    <span class="field-help">Start typing to find your institution. If it is not listed, enter its name manually.</span>
    <label for="course_category">Course Category:</label>
    <select id="course_category" name="course_category" required>
        <option value="medicine">Medicine-related courses</option>
        <option value="engineering">Engineering courses</option>
        <option value="computer">Computer-related courses</option>
        <option value="education_science">Education Science</option>
        <option value="education_arts">Education Arts</option>
        <option value="law">Law</option>
        <option value="other">Other courses</option>
    </select>
    <label for="course_picker">Choose a Course:</label>
    <select id="course_picker" onchange="selectCatalogCourse()" >
        <option value="">Choose course placed or enter it in tab for Exact Course Name: if is not listed here</option>
    </select>
    <span class="field-help">Course suggestions are general. Confirm that your selected institution offers the course; you can also type the exact course name below.</span>
    <label for="course_name">Exact Course Name:</label>
    <input id="course_name" name="course_name" placeholder="e.g. Bachelor of Science in Computer Science" required>
    <label>Parent Status:</label>
    <select name="parent_type" id="parent_type" onchange="toggleParentOptions()" required>
        <option value="both">Both Parents Alive</option>
        <option value="single">One Parent Provides for Me</option>
        <option value="orphan">Both Parents Deceased (Guardian Supports Me)</option>
    </select>
    <div id="income_both" style="background:#f9f9f9;padding:10px;border-radius:8px;margin-top:8px">
        <label for="mother_income">Mother's Monthly Income (KSh)</label>
        <span class="field-help">Enter the mother's approximate income per month. Enter 0 if she has no income.</span>
        <input id="mother_income" name="mother_income" type="number" min="0" step="1" value="0">
        <label for="father_income">Father's Monthly Income (KSh)</label>
        <span class="field-help">Enter the father's approximate income per month. Enter 0 if he has no income.</span>
        <input id="father_income" name="father_income" type="number" min="0" step="1" value="0">
    </div>
    <div id="income_single" style="display:none;background:#f9f9f9;padding:10px;border-radius:8px;margin-top:8px">
        <label for="caring_parent">Parent Caring for You</label>
        <select name="caring_parent" id="caring_parent"><option value="mother">Mother</option><option value="father">Father</option></select>
        <label for="single_income">Caring Parent's Monthly Income (KSh)</label>
        <span class="field-help">Enter only the monthly income of the parent who supports you.</span>
        <input id="single_income" name="single_income" type="number" min="0" step="1" value="0">
        <label for="other_parent_status">Status of the Other Parent</label>
        <select name="other_parent_status" id="other_parent_status"><option value="alive_separated">Alive / separated / absent</option><option value="deceased">Deceased</option></select>
    </div>
    <div id="income_orphan" style="display:none;background:#f9f9f9;padding:10px;border-radius:8px;margin-top:8px">
        <label for="guardian_income">Guardian's Monthly Income (KSh)</label>
        <span class="field-help">Enter the monthly income of the guardian who supports you. Enter 0 if there is no regular income.</span>
        <input id="guardian_income" name="guardian_income" type="number" min="0" step="1" value="0">
    </div>

    <label for="school_fee_payer">Who paid your high-school fees?</label>
    <select id="school_fee_payer" name="school_fee_payer" required>
        <option value="parent">Parent / family paid</option>
        <option value="sponsor">Sponsor / sponsorship programme paid</option>
    </select>
    <span class="field-help">Choose Sponsor only if a sponsor or sponsorship programme paid your high-school fees. This is one of the conditions used for the Band 1 estimate.</span>

    <label for="hs_fee">Fees paid for the whole year in Form 4 (KSh)</label>
    <span class="field-help">Enter the approximate total fees paid for your Form 4 year, not the monthly amount.</span>
    <input id="hs_fee" name="hs_fee" type="number" min="0" step="1" required>

    <label for="primary_fee">Fees paid for the whole year in Class 8 (KSh)</label>
    <span class="field-help">Enter the approximate total fees paid for your Class 8 year, not the monthly amount.</span>
    <input id="primary_fee" name="primary_fee" type="number" min="0" step="1" required>
    <button type="submit" style="margin-top:12px;">Continue to Pay Ksh {{price}}</button>
    </form>
    <script>
    const educationCatalog = {{ catalog|tojson }};
    const institutionInput = document.getElementById('institution_name');
    const coursePicker = document.getElementById('course_picker');
    const courseNameInput = document.getElementById('course_name');
    const institutionTypeInput = document.querySelector('select[name="institution_type"]');
    const institutionOptions = document.getElementById('institution_options');
    const courseCategoryInput = document.getElementById('course_category');

    function updateCourseNamePlaceholder(){
        if (!courseNameInput) return;
        const selectedType = institutionTypeInput.value;
        if (selectedType === 'college' || selectedType === 'kmtc') {
            courseNameInput.placeholder = 'Start with Diploma in ... or Certificate in ...';
        } else {
            courseNameInput.placeholder = 'e.g. Bachelor of Science in Computer Science';
        }
    }

    const commonCourses = {
        university: [
            ['Bachelor of Commerce','other'], ['Bachelor of Business Administration','other'],
            ['Bachelor of Science in Computer Science','computer'], ['Bachelor of Information Technology','computer'],
            ['Bachelor of Science in Nursing','medicine'], ['Bachelor of Medicine and Bachelor of Surgery (MBChB)','medicine'],
            ['Bachelor of Engineering','engineering'], ['Bachelor of Education (Arts)','education_arts'],
            ['Bachelor of Education (Science)','education_science'], ['Bachelor of Laws (LLB)','law'],
            ['Bachelor of Science in Agriculture','other'], ['Bachelor of Arts','other'],
            ['Bachelor of Science in Economics','other'], ['Diploma in Information Technology','computer']
        ],
        college: [
            ['Diploma in Information Technology','computer'], ['Diploma in Business Management','other'],
            ['Diploma in Electrical Engineering','engineering'], ['Diploma in Mechanical Engineering','engineering'],
            ['Diploma in Civil Engineering','engineering'], ['Diploma in Education','education_arts'],
            ['Certificate in Information Technology','computer'], ['Diploma in Hospitality Management','other'],
            ['Diploma in Social Work','other'], ['Diploma in Agriculture','other']
        ],
        kmtc: [
            ['Diploma in Clinical Medicine and Surgery','medicine'], ['Diploma in Nursing','medicine'],
            ['Diploma in Medical Laboratory Sciences','medicine'], ['Diploma in Pharmacy','medicine'],
            ['Diploma in Radiography and Imaging','medicine'], ['Diploma in Community Health','medicine'],
            ['Diploma in Health Records and Information Technology','computer'],
            ['Certificate in Medical Emergency Technician','medicine'], ['Diploma in Physiotherapy','medicine']
        ]
    };

    function selectedInstitutionName(){
        return institutionInput ? institutionInput.value.trim() : '';
    }
    function updateInstitutionOptions(){
        if (!institutionOptions) return;
        const selectedType = institutionTypeInput.value;
        institutionOptions.innerHTML = '';
        educationCatalog.filter(item => item.type === selectedType).forEach(institution => {
            const option = document.createElement('option');
            option.value = institution.name;
            institutionOptions.appendChild(option);
        });
        // If the currently selected institution belongs to another type, clear it.
        const selected = educationCatalog.find(item => item.name.toLowerCase() === selectedInstitutionName().toLowerCase());
        if (selected && selected.type !== selectedType) institutionInput.value = '';
        updateCatalogCourses();
    }
    function selectCatalogCourse(){
        if (!coursePicker || !coursePicker.value) return;
        courseNameInput.value = coursePicker.value;
        const institution = educationCatalog.find(item => item.name.toLowerCase() === selectedInstitutionName().toLowerCase());
        const course = institution && (institution.courses || []).find(item => item.name === coursePicker.value);
        const category = course && course.category ? course.category : coursePicker.options[coursePicker.selectedIndex].dataset.category;
        if (category && Array.from(courseCategoryInput.options).some(option => option.value === category)) {
            courseCategoryInput.value = category;
        }
    }
    function updateCatalogCourses(){
        if (!coursePicker) return;
        coursePicker.innerHTML = '<option value="">Choose a course or enter it below</option>';
        const institution = educationCatalog.find(item => item.name.toLowerCase() === selectedInstitutionName().toLowerCase() && item.type === institutionTypeInput.value);
        let courses = institution && Array.isArray(institution.courses) ? institution.courses.filter(course => course && course.name) : [];
        // If this institution has no course records yet, show general suggestions
        // for the selected institution type without claiming every course is offered there.
        if (!courses.length) courses = commonCourses[institutionTypeInput.value].map(item => ({name:item[0], category:item[1]}));
        courses.forEach(course => {
            const option = document.createElement('option');
            option.value = course.name;
            option.textContent = course.name;
            option.dataset.category = course.category || 'other';
            coursePicker.appendChild(option);
        });
    }
    institutionTypeInput.addEventListener('change', updateInstitutionOptions);
    institutionTypeInput.addEventListener('change', updateCourseNamePlaceholder);
    institutionInput.addEventListener('input', updateCatalogCourses);
    institutionInput.addEventListener('change', updateCatalogCourses);
    coursePicker.addEventListener('change', selectCatalogCourse);
    function toggleParentOptions(){
        const pt = document.getElementById('parent_type').value;
        document.getElementById('income_both').style.display = pt === 'both' ? 'block' : 'none';
        document.getElementById('income_single').style.display = pt === 'single' ? 'block' : 'none';
        document.getElementById('income_orphan').style.display = pt === 'orphan' ? 'block' : 'none';
        document.getElementById('mother_income').disabled = pt !== 'both';
        document.getElementById('father_income').disabled = pt !== 'both';
        document.getElementById('single_income').disabled = pt !== 'single';
        document.getElementById('guardian_income').disabled = pt !== 'orphan';
    }
    updateInstitutionOptions();
    updateCourseNamePlaceholder();
    toggleParentOptions();
    </script>
    </body></html>""", agent=agent, price=price, direct_price=direct_price, agent_price=agent_price, catalog=get_education_catalog())

@app.route('/agent/register')
@app.route('/become-agent')
def become_agent():
    return """<div style="max-width:500px;margin:auto;font-family:Arial;padding:20px"><h2>Become Agent - Earn Ksh 240 per student</h2>
    <form action="/register-agent" method="POST" style="background:white;padding:15px;border-radius:10px">
    <input name="name" placeholder="Full Name" required style="width:100%;padding:10px;margin:5px 0">
    <input name="email" type="email" placeholder="Email (for login)" required style="width:100%;padding:10px;margin:5px 0">
    <input name="phone" placeholder="Your Phone 254..." required style="width:100%;padding:10px;margin:5px 0">
    <input name="mpesa_phone" placeholder="Mpesa Phone to Receive Payments 254..." required style="width:100%;padding:10px;margin:5px 0">
    <input name="mpesa_name" placeholder="Mpesa Name (e.g JOHN KAMAU)" required style="width:100%;padding:10px;margin:5px 0">
    <input name="password" type="password" placeholder="Create Password" required style="width:100%;padding:10px;margin:5px 0">
    <button style="width:100%;padding:14px;background:green;color:white;border:none;border-radius:8px">Get My Agent Link</button>
    </form></div>"""

@app.route('/register-agent', methods=['POST'])
def register_agent():
    agents=load_json(AGENTS_FILE)
    if any(a['email']==request.form['email'] for a in agents):
        return "Email already exists <a href='/agent-login'>Login</a>"
    code=str(uuid.uuid4())[:6].upper()
    agent={"code":code,"name":request.form['name'],"email":request.form['email'],"phone":request.form['phone'],"mpesa_phone":request.form['mpesa_phone'],"mpesa_name":request.form['mpesa_name'],"password_hash":generate_password_hash(request.form['password']),"date":datetime.now().strftime("%Y-%m-%d %H:%M")}
    agents.append(agent); save_json(AGENTS_FILE, agents)
    return f"""<div style="max-width:500px;margin:auto;font-family:Arial;padding:20px;text-align:center">
    <h2>✅ Registered!</h2><p>Your Link: <b>{request.host_url.rstrip('/')}/student?ref={code}</b></p>
    <p>Mpesa to receive: {agent['mpesa_phone']} ({agent['mpesa_name']})</p>
    <p>Dashboard: <a href='/agent/{code}'>/agent/{code}</a></p>
    <a href='/agent/{code}'><button style="padding:12px;background:green;color:white;border:none;width:100%">Go to Dashboard</button></a></div>"""

@app.route('/agent/login', methods=['GET','POST'])
@app.route('/agent-login', methods=['GET','POST'])
def agent_login():
    if request.method=='POST':
        email=request.form['email']; password=request.form['password']
        agents=load_json(AGENTS_FILE); agent=next((a for a in agents if a['email']==email),None)
        if agent and check_password_hash(agent['password_hash'], password):
            session['agent_code']=agent['code']; return redirect(f"/agent/{agent['code']}")
        else: return "Wrong password <a href='/agent/login'>Try again</a>"
    return """<div style="max-width:400px;margin:auto;padding:20px;font-family:Arial"><h2>Agent Login</h2>
    <form method="POST" style="background:white;padding:15px;border-radius:10px">
    <input name="email" type="email" placeholder="Email" required style="width:100%;padding:10px;margin:5px 0">
    <input name="password" type="password" placeholder="Password" required style="width:100%;padding:10px;margin:5px 0">
    <button style="width:100%;padding:12px;background:green;color:white;border:none">Login</button></form></div>"""

@app.route('/pay', methods=['POST'])
def pay():
    data=dict(request.form)
    ref_code=request.args.get('ref') or session.get('ref_code')
    # Only a real registered agent code may attribute this payment to an agent.
    agents=load_json(AGENTS_FILE)
    if not ref_code or not any(a.get('code') == ref_code for a in agents):
        ref_code=None
        session.pop('ref_code', None)
    else:
        session['ref_code']=ref_code
    session.pop('sub_ref_code', None)
    
    parent_type = data.get('parent_type', 'both')
    if parent_type == 'single':
        data['mother_income'] = data.get('single_income', '0') if data.get('caring_parent') == 'mother' else '0'
        data['father_income'] = data.get('single_income', '0') if data.get('caring_parent') == 'father' else '0'
        data['guardian_income'] = '0'
    elif parent_type == 'orphan':
        data['mother_income'] = '0'; data['father_income'] = '0'
    else:
        data['guardian_income'] = '0'
    data['income'] = str(sum(int(data.get(k, 0) or 0) for k in ('mother_income', 'father_income', 'guardian_income')))
    result=calculate_full(data)
    session['data']=data; session['result']=result
    payment_settings = get_payment_settings()
    price = payment_settings["agent_price"] if ref_code else payment_settings["direct_price"]
    
    return render_template_string("""
    <div style="max-width:500px;margin:auto;font-family:Arial;padding:20px;text-align:center">
    <h2>Lipa Ksh {{price}}</h2>
    <p>Complete payment to unlock your funding report. Your course-fee result will appear in the report after the payment step.</p>
    <input id="phone" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="10" minlength="10" pattern="(07|01)[0-9]{8}" placeholder="M-Pesa number (07XXXXXXXX or 01XXXXXXXX)" title="Enter exactly 10 digits starting with 07 or 01" style="width:100%;padding:12px" required><br>
    <input id="mpesa_name" placeholder="Mpesa Name (Name on Mpesa)" style="width:100%;padding:12px;margin-top:8px"><br><br>
    <button onclick="payNow()" id="btn" style="padding:14px;background:green;color:white;border:none;width:100%">Pay Ksh {{price}} via M-Pesa</button>
    <p id="status" role="status"></p>
    <script>
    async function payNow(){
        const phone=document.getElementById('phone').value.trim();
        const mpesa_name=document.getElementById('mpesa_name').value.trim();
        const btn=document.getElementById('btn');
        const status=document.getElementById('status');
        if(!/^(07|01)[0-9]{8}$/.test(phone)){alert('Enter exactly 10 digits starting with 07 or 01, for example 0712345678 or 0112345678.');return;}
        if(!mpesa_name){alert('Enter the name registered on M-Pesa');return;}
        btn.disabled=true; btn.innerText='Requesting M-Pesa prompt...';
        try {
            const res=await fetch('/intasend-stk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,mpesa_name})});
            const d=await res.json();
            if(!res.ok || d.status!=='success'){status.innerText=d.message || 'Could not start payment. Please try again.';btn.disabled=false;btn.innerText='Try payment again';return;}
            status.innerText='M-Pesa prompt requested. Enter your PIN on your phone, then keep this page open while we confirm payment.';
            btn.innerText='Waiting for payment...';
            for(let i=0;i<40;i++){
                await new Promise(resolve=>setTimeout(resolve,3000));
                const check=await fetch('/payment-status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_ref:d.api_ref})});
                const result=await check.json();
                if(result.status==='paid'){status.innerText='Payment confirmed. Opening your report...';window.location.href='/report';return;}
                if(result.status==='failed' || result.status==='cancelled'){
                    status.innerText=result.message || 'Payment was not completed. You can try again.';btn.disabled=false;btn.innerText='Try payment again';return;
                }
                status.innerText=result.message || 'Waiting for IntaSend to confirm your payment...';
            }
            status.innerText='Payment has not been confirmed yet. If you entered your PIN, wait a little and try checking again; do not pay again unless you confirm the first request failed.';
            btn.disabled=false;btn.innerText='Check / retry payment';
        } catch(e) {
            status.innerText='Could not contact the payment service. Check your connection and try again.';
            btn.disabled=false;btn.innerText='Try payment again';
        }
    }
    </script></div>""", result=result, price=price)

@app.route('/intasend-stk', methods=['POST'])
def intasend_stk():
    payload = request.get_json(silent=True) or {}
    phone = str(payload.get('phone', '')).strip()
    mpesa_name = str(payload.get('mpesa_name', '')).strip()
    data = session.get('data')
    result = session.get('result')
    if not phone or not mpesa_name or not data or not result:
        return jsonify({"status": "failed", "message": "Missing payment or student details. Please return to the form and try again."}), 400
    if (not INTASEND_PUBLISHABLE_KEY or not INTASEND_SECRET_KEY or
            "YOUR_KEY" in INTASEND_PUBLISHABLE_KEY or "YOUR_SECRET" in INTASEND_SECRET_KEY):
        app.logger.error('IntaSend keys are not configured in environment variables.')
        return jsonify({"status": "failed", "message": "Payments are not configured yet. Please contact the website administrator."}), 503
    # Accept only the exact local format requested: 10 digits beginning with 07 or 01.
    # Do not strip characters or accept 254-prefixed numbers; validate before converting for IntaSend.
    if not re.fullmatch(r'(?:07|01)\d{8}', phone):
        return jsonify({"status": "failed", "message": "Enter exactly 10 digits starting with 07 or 01, for example 0712345678 or 0112345678."}), 400
    phone = '254' + phone[1:]

    ref_code = session.get('ref_code')
    payment_settings = get_payment_settings()
    price = payment_settings["agent_price"] if ref_code else payment_settings["direct_price"]
    order_ref = 'EDU-' + uuid.uuid4().hex[:16].upper()
    if ref_code:
        agent_earning = min(payment_settings["agent_commission"], price)
        owner_earning = price - agent_earning
    else:
        owner_earning = price
        agent_earning = 0

    student = {
        "order_ref": order_ref,
        "invoice_id": None,
        "payment_state": "PENDING",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name": data.get('name'),
        "institution_type": data.get('institution_type'),
        "institution_name": data.get('institution_name'),
        "course_category": data.get('course_category'),
        "course_name": data.get('course_name'),
        "annual_fees": result.get('total_annual_fees'),
        "fee_source": result.get('fee_source'),
        "fee_academic_year": result.get('academic_year'),
        "fee_source_url": result.get('fee_source_url'),
        "fee_source_title": result.get('fee_source_title'),
        "phone": phone,
        "mpesa_name": mpesa_name,
        "ref_code": ref_code,
        "parent_type": data.get('parent_type'),
        "school_fee_payer": data.get('school_fee_payer', 'parent'),
        "form4_annual_fees": int(data.get('hs_fee', 0) or 0),
        "class8_annual_fees": int(data.get('primary_fee', 0) or 0),
        "band_one_eligible": result.get('band_one_eligible', False),
        "mother_monthly_income": int(data.get('mother_income', 0) or 0),
        "father_monthly_income": int(data.get('father_income', 0) or 0),
        "guardian_monthly_income": int(data.get('guardian_income', 0) or 0),
        "total_monthly_parent_income": int(data.get('income', 0) or 0),
        "price": price,
        "band": result['band'],
        "score": result['score'],
        "owner_earning": owner_earning,
        "agent_earning": agent_earning,
        "paid": False
    }
    students = load_json(DB_FILE)
    students.append(student)
    save_json(DB_FILE, students)

    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
    intasend_payload = {"amount": price, "phone_number": phone, "api_ref": order_ref, "mobile_tarrif": "BUSINESS-PAYS"}
    try:
        response = requests.post(f"{INTASEND_API_BASE}/payment/mpesa-stk-push/", json=intasend_payload, headers=headers, timeout=25)
        response.raise_for_status()
        response_data = response.json()
        invoice = response_data.get('invoice') or {}
        invoice_id = invoice.get('invoice_id') or invoice.get('id') or response_data.get('invoice_id')
        if not invoice_id:
            app.logger.error('IntaSend response did not include an invoice ID: %s', response_data)
            return jsonify({"status": "failed", "message": "IntaSend did not return a payment reference. Please try again later."}), 502
        for item in students:
            if item.get('order_ref') == order_ref:
                item['invoice_id'] = str(invoice_id)
                item['payment_state'] = invoice.get('state', 'PENDING')
                break
        save_json(DB_FILE, students)
        session['pending_order_ref'] = order_ref
        session.pop('payment_confirmed_order_ref', None)
        return jsonify({"status": "success", "message": "M-Pesa prompt sent. Enter your PIN to complete payment.", "api_ref": order_ref})
    except requests.RequestException as exc:
        app.logger.error('IntaSend STK request failed: %s', exc)
        return jsonify({"status": "failed", "message": "We could not start the M-Pesa request. Please check the number and try again."}), 502
    except (ValueError, TypeError) as exc:
        app.logger.error('Invalid IntaSend response: %s', exc)
        return jsonify({"status": "failed", "message": "We received an invalid response from the payment service. Please try again later."}), 502

@app.route('/payment-status', methods=['POST'])
def payment_status():
    payload = request.get_json(silent=True) or {}
    order_ref = str(payload.get('api_ref', '')).strip()
    if not order_ref or order_ref != session.get('pending_order_ref'):
        return jsonify({"status": "failed", "message": "Payment reference not recognised. Please restart the payment process."}), 400
    students = load_json(DB_FILE)
    student = next((item for item in students if item.get('order_ref') == order_ref), None)
    if not student:
        return jsonify({"status": "failed", "message": "Payment record not found. Please contact support."}), 404
    if student.get('paid'):
        session['payment_confirmed_order_ref'] = order_ref
        return jsonify({"status": "paid", "message": "Payment confirmed."})
    invoice_id = student.get('invoice_id')
    if not invoice_id:
        return jsonify({"status": "pending", "message": "Waiting for the payment reference from IntaSend..."})
    if not INTASEND_SECRET_KEY:
        return jsonify({"status": "failed", "message": "Payment verification is not configured."}), 503
    try:
        response = requests.post(
            f"{INTASEND_API_BASE}/payment/status/",
            json={"invoice_id": invoice_id},
            headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"},
            timeout=20
        )
        response.raise_for_status()
        status_data = response.json()
        invoice = status_data.get('invoice') or status_data
        state = str(invoice.get('state', '')).upper()
        returned_ref = invoice.get('api_ref')
        try:
            paid_value = round(float(invoice.get('value', 0)), 2)
        except (TypeError, ValueError):
            paid_value = -1
        currency = str(invoice.get('currency', 'KES')).upper()
        if returned_ref and returned_ref != order_ref:
            app.logger.error('IntaSend reference mismatch for order %s', order_ref)
            return jsonify({"status": "failed", "message": "Payment details did not match this order. Please contact support."}), 409
        if state == 'COMPLETE' and paid_value == float(student.get('price', 0)) and currency == 'KES':
            for item in students:
                if item.get('order_ref') == order_ref:
                    item['paid'] = True
                    item['payment_state'] = 'COMPLETE'
                    item['provider_ref'] = invoice.get('provider_ref') or invoice.get('mpesa_reference')
                    item['paid_date'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    break
            save_json(DB_FILE, students)
            confirmed_student = next((item for item in students if item.get('order_ref') == order_ref), None)
            record_paid_earning(confirmed_student)
            session['payment_confirmed_order_ref'] = order_ref
            return jsonify({"status": "paid", "message": "Payment confirmed. Opening your report..."})
        if state in ('FAILED', 'CANCELED'):
            for item in students:
                if item.get('order_ref') == order_ref:
                    item['payment_state'] = state
                    break
            save_json(DB_FILE, students)
            return jsonify({"status": "failed" if state == 'FAILED' else 'cancelled', "message": "IntaSend reports that this payment was not completed. You can try again."})
        return jsonify({"status": "pending", "message": "Waiting for IntaSend to confirm payment..."})
    except requests.RequestException as exc:
        app.logger.warning('IntaSend status check failed: %s', exc)
        return jsonify({"status": "pending", "message": "Could not check payment status just now. Retrying..."})
    except (ValueError, TypeError) as exc:
        app.logger.error('Invalid IntaSend status response: %s', exc)
        return jsonify({"status": "pending", "message": "Waiting for a valid payment confirmation..."})

@app.route('/report')
def report():
    result=session.get('result')
    if not result: return redirect('/')
    order_ref = session.get('payment_confirmed_order_ref')
    students = load_json(DB_FILE)
    confirmed = any(item.get('order_ref') == order_ref and item.get('paid') is True for item in students) if order_ref else False
    if not confirmed:
        return redirect('/student')
    return render_template_string("""
    <div style='max-width:750px;margin:auto;font-family:Arial;padding:15px'>
    <div style="background:#eaffea;padding:20px;border-radius:10px;text-align:center;">
        <h2>Funding Planning Guide: {{r.band}} (Score: {{r.score}})</h2>
        <p style="font-size:13px;color:#555">Use this breakdown to plan ahead for your education costs and prepare for the funding process. Your final funding band and award will be determined through the official HEF assessment.</p>
        {% if r.band == 'BAND 1' %}<p>Your details align with the Band 1 criteria used in this guide: monthly income below KSh 3,000, a one-parent/orphan household, and sponsored high-school fees.</p>{% elif r.band == 'BAND 2' and r.band_two_eligible %}<p>Your details align with the Band 2 criteria used in this guide: monthly income from KSh 3,000 to KSh 5,000, support from one parent, and sponsored high-school fees.</p>{% else %}<p>This guide checks the Band 1 criteria (monthly income below KSh 3,000, a one-parent/orphan household, and sponsored high-school fees) and the Band 2 criteria (monthly income from KSh 3,000 to KSh 5,000, support from one parent, and sponsored high-school fees). Where these conditions are not met, the calculator's existing scoring rules are used to indicate the applicable band.</p>{% endif %}
        <p>Institution Type: <b>{{r.institution|upper}}</b></p>
        <p>Institution: <b>{{r.institution_name or 'Not entered'}}</b></p>
        <p>Course: <b>{{r.course_name or 'Not entered'}}</b></p>
        <p>Total Annual Fees: <b>Ksh {{ "{:,}".format(r.total_annual_fees|int) }}</b></p>
        <p style="font-size:13px;color:#555;">Fee basis: <b>{{('Verified official fee for ' ~ (r.academic_year or 'the recorded year')) if r.fee_source == 'verified_official_source' else 'Category-based estimate — confirm with the institution'}}</b></p>
        {% if r.fee_source_url %}<p>Official fee source: <a href="{{r.fee_source_url}}" target="_blank" rel="noopener">{{r.fee_source_title or r.fee_source_url}}</a></p>{% endif %}
    </div>

    <h3>📌 BANDS FUNDING ALLOCATION BREAKDOWN</h3>
    <table border="1" cellpadding="8" style="width:100%;border-collapse:collapse;background:white;margin-bottom:15px;">
        <tr style="background:#f2f2f2">
            <th>Component</th>
            <th>Percentage</th>
            <th>Amount (Ksh)</th>
        </tr>
        <tr>
            <td><b>Government Scholarship</b></td>
            <td>{{r.scholarship_pct}}%</td>
            <td><b>Ksh {{ "{:,}".format(r.scholarship_amount|int) }}</b></td>
        </tr>
        <tr>
            <td><b>HELB Loan</b></td>
            <td>{{r.loan_pct}}%</td>
            <td><b>Ksh {{ "{:,}".format(r.loan_amount|int) }}</b></td>
        </tr>
        <tr>
            <td><b>Household (Parents)</b></td>
            <td>{{r.household_pct}}%</td>
            <td><b>Ksh {{ "{:,}".format(r.household_amount|int) }}</b></td>
        </tr>
    </table>

    <div style="background:#e7f3ff;padding:15px;border-radius:10px;margin-bottom:15px;">
        <h4 style="margin:0 0 10px 0;">+ Upkeep Loan Allocation:</h4>
        <p style="margin:5px 0;"><b>Per Academic Year:</b> Ksh {{ "{:,}".format(r.upkeep_year|int) }}</p>
        <p style="margin:5px 0;">👉 <b>Per Semester:</b> Ksh {{ "{:,}".format(r.upkeep_sem|int) }} (sent to your M-Pesa/Bank)</p>
    </div>

    <h3>🚀 Action Guide: How to Get into a Better Band & Secure Maximum Upkeep</h3>
    <ul>
    {% for g in r.guidance %}
        <li style="margin:10px 0; font-size:15px;">{{g}}</li>
    {% endfor %}
    </ul>
    
    <div style="background:#fff3cd;padding:15px;border-radius:8px;margin-top:15px;">
        <b>Important Document Checklist (Keep Ready, Do Not Upload Yet):</b>
        <ul>
            <li>Student ID / Birth Certificate</li>
            <li>Parent / Guardian National ID</li>
            <li>Single Parent Certificate (If applicable, instead of death certificate)</li>
            <li>Death Certificate(s) (Only if parent(s) are deceased)</li>
            <li>Secondary & Primary School sponsorship letters / Receipts</li>
        </ul>
    </div>
    <br>
    <button onclick='window.print()' style='width:100%;padding:14px;background:green;color:white;border:none;border-radius:8px;font-size:16px;'>Print / Save Report</button>
    </div>""", r=result)

@app.route('/agent/<code>')
def agent_dash(code):
    agents=load_json(AGENTS_FILE); agent=next((a for a in agents if a['code']==code),None)
    if not agent: return "Agent not found"
    if session.get('agent_code') != code and not session.get('is_admin'): return redirect('/agent/login')
    students=load_json(DB_FILE); withdrawals=load_json(WITHDRAW_FILE)
    earnings=sync_earnings_from_student_records()
    mystudents=[s for s in students if s.get('ref_code')==code]
    paid_students=[s for s in mystudents if s.get('paid')]
    total_earned=sum(int(e.get('agent_earning', 0) or 0) for e in earnings if e.get('ref_code')==code and e.get('paid'))
    agent_withdrawals=[w for w in withdrawals if w.get('agent_code')==code]
    # Only completed payouts count as withdrawn; pending/processing requests reserve funds.
    total_withdrawn=sum([int(w.get('amount', 0) or 0) for w in agent_withdrawals if w.get('status')=='Paid'])
    reserved_amount=sum([int(w.get('amount', 0) or 0) for w in agent_withdrawals if w.get('status') in ['Pending','Processing']])
    balance=max(0, total_earned-reserved_amount-total_withdrawn)
    payment_settings=get_payment_settings()
    minimum_withdrawal=int(payment_settings.get('minimum_withdrawal', 240))
    return render_template_string("""
    <div style="max-width:900px;margin:auto;font-family:Arial;padding:15px">
    <h2>Agent Dashboard: {{agent.name}} ({{agent.code}})</h2>
    <p>Email: {{agent.email}} | Mpesa: <b>{{agent.mpesa_phone}} ({{agent.mpesa_name}})</b></p>
    <p>Link: <b>{{request.host_url.rstrip('/')}}/student?ref={{agent.code}}</b> <button onclick="navigator.clipboard.writeText('{{request.host_url.rstrip('/')}}/student?ref={{agent.code}}')">Copy</button></p>
    <div style="background:#eaffea;padding:15px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
    <div><h3 style="margin:0">Available Balance: KSh {{balance}}</h3><small>Total Earned: KSh {{total_earned}} | Total Withdrawn: KSh {{total_withdrawn}} | Pending/Processing: KSh {{reserved_amount}}</small></div>
    <div>{% if balance>=minimum_withdrawal %}<form action="/agent/{{agent.code}}/withdraw" method="POST"><button style="background:green;color:white;padding:12px 20px;border:none;border-radius:8px">💰 Request Withdrawal (KSh {{balance}})</button></form>
    {% else %}<button disabled style="background:gray;color:white;padding:12px 20px;border:none;border-radius:8px">Minimum KSh {{minimum_withdrawal}} (Need KSh {{minimum_withdrawal-balance}} more)</button>{% endif %}</div>
    </div>
    <div style="background:#fff3cd;padding:10px;border-radius:8px;margin:10px 0"><b>Withdrawal rules:</b> Minimum KSh {{minimum_withdrawal}} | Before 7:30PM → Today 8PM | After 7:30PM → Tomorrow 8PM | Payout to: {{agent.mpesa_phone}}</div>
    <h3>Withdrawal History</h3>
    <table border="1" cellpadding="6" style="width:100%;border-collapse:collapse"><tr style="background:orange"><th>Date</th><th>Amount</th><th>Status</th><th>Payout Time</th></tr>
    {% for w in withdrawals|reverse %}<tr><td>{{w.request_date}}</td><td>Ksh {{w.amount}}</td><td>{% if w.status=='Pending' %}<span style="background:orange;color:white;padding:3px 8px;border-radius:12px">⏳ Waiting Processing</span>{% elif w.status=='Processing' %}🔄 Processing{% else %}<span style="background:green;color:white;padding:3px 8px;border-radius:12px">✅ Paid {{w.paid_date}}</span>{% endif %}</td><td>{{w.payout_time}}</td></tr>{% endfor %}
    </table>
    <h3>Your Students ({{mystudents|length}} total, {{paid_students|length}} paid)</h3>
    <table border="1" cellpadding="6" style="width:100%;border-collapse:collapse"><tr><th>Date</th><th>Student Name</th><th>Mpesa Phone</th><th>Mpesa Name</th><th>Band</th><th>Your Earn</th><th>Paid</th></tr>
    {% for s in mystudents %}<tr><td>{{s.date}}</td><td>{{s.name}}</td><td><b>{{s.phone}}</b></td><td>{{s.mpesa_name}}</td><td>{{s.band}}</td><td>Ksh {{s.agent_earning}}</td><td>{{'✅' if s.paid else '❌'}}</td></tr>{% endfor %}
    </table>
    <script>setTimeout(()=>location.reload(),15000);</script>
    </div>
    """, agent=agent, mystudents=mystudents, paid_students=paid_students, withdrawals=agent_withdrawals, total_earned=total_earned, total_withdrawn=total_withdrawn, reserved_amount=reserved_amount, balance=balance, minimum_withdrawal=minimum_withdrawal)

@app.route('/agent/<code>/withdraw', methods=['POST'])
def withdraw(code):
    agents=load_json(AGENTS_FILE); agent=next((a for a in agents if a['code']==code),None)
    if session.get('agent_code')!=code: return redirect('/agent-login')
    withdrawals=load_json(WITHDRAW_FILE)
    earnings=sync_earnings_from_student_records()
    if not agent: return "Agent not found", 404
    total=sum(int(e.get('agent_earning', 0) or 0) for e in earnings if e.get('ref_code')==code and e.get('paid'))
    agent_withdrawals=[w for w in withdrawals if w.get('agent_code')==code]
    total_w=sum([int(w.get('amount', 0) or 0) for w in agent_withdrawals if w.get('status') in ['Paid','Pending','Processing']])
    balance=max(0, total-total_w)
    minimum_withdrawal=int(get_payment_settings().get('minimum_withdrawal', 240))
    if balance<minimum_withdrawal: return f"Minimum withdrawal is KSh {minimum_withdrawal}; available balance is KSh {balance}. <a href='/agent/{code}'>Back</a>"
    now=datetime.now(); cutoff=now.replace(hour=19,minute=30,second=0)
    if now<=cutoff: payout=now.replace(hour=20,minute=0).strftime("%Y-%m-%d 8:00 PM TODAY")
    else: payout=(now+timedelta(days=1)).replace(hour=20,minute=0).strftime("%Y-%m-%d 8:00 PM TOMORROW")
    entry={"id":str(uuid.uuid4())[:8],"agent_code":code,"agent_name":agent['name'],"agent_email":agent['email'],"mpesa_phone":agent['mpesa_phone'],"mpesa_name":agent['mpesa_name'],"amount":balance,"request_date":now.strftime("%Y-%m-%d %H:%M"),"payout_time":payout,"status":"Pending"}
    withdrawals.append(entry); save_json(WITHDRAW_FILE, withdrawals)
    return f"<div style='max-width:500px;margin:auto;font-family:Arial;padding:20px;text-align:center'><h2>✅ Requested Ksh {balance}</h2><p>Status: ⏳ Waiting Processing</p><p>Payout: {payout}</p><p>To: {agent['mpesa_phone']}</p><a href='/agent/{code}'><button style='padding:12px;background:green;color:white;border:none;width:100%'>Back</button></a></div>"

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password', '') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect('/admin')
        return "<p>Incorrect password.</p><a href='/admin/login'>Try again</a>", 401
    return """<div style='max-width:400px;margin:50px auto;font-family:Arial'><h2>Admin Login</h2><form method='POST'><label>Admin Password</label><input name='password' type='password' required style='box-sizing:border-box;width:100%;padding:12px;margin:10px 0'><button style='padding:12px;width:100%'>Login</button></form></div>"""

@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect('/admin/login')
    pwd = ''
    payment_settings = get_payment_settings()
    students=load_json(DB_FILE); agents=load_json(AGENTS_FILE); withdrawals=load_json(WITHDRAW_FILE)
    earnings=sync_earnings_from_student_records()
    for a in agents:
        ms=[s for s in students if s.get('ref_code')==a['code'] and s.get('paid')]
        ledger_agent=[e for e in earnings if e.get('ref_code')==a['code'] and e.get('paid')]
        a['total_students']=len(ms)
        a['total_sales']=sum(int(e.get('price', 0) or 0) for e in ledger_agent)
        a['agent_total']=sum(int(e.get('agent_earning', 0) or 0) for e in ledger_agent)
        a['owner_total']=sum(int(e.get('owner_earning', 0) or 0) for e in ledger_agent)
        a['students_list']=ms
    direct=[s for s in students if not s.get('ref_code') and s.get('paid')]
    # Financial totals are cumulative and come from the ledger, so they survive student-record resets.
    direct_earnings=[e for e in earnings if not e.get('ref_code') and e.get('paid')]
    direct_funds=sum(int(e.get('price', 0) or 0) for e in direct_earnings)
    paid_agent_earnings=[e for e in earnings if e.get('ref_code') and e.get('paid')]
    agent_admin_share=sum(int(e.get('owner_earning', max(0, int(e.get('price', 0) or 0) - int(e.get('agent_earning', 0) or 0))) or 0) for e in paid_agent_earnings)
    admin_total_funds=direct_funds + agent_admin_share
    pending=[w for w in withdrawals if w['status']=='Pending']
    return render_template_string("""
    <div style="max-width:1400px;margin:auto;font-family:Arial;font-size:12px;padding:10px">
    <h2>SUPER ADMIN - Verification + Automated M-Pesa STK Payout</h2>
    <h3 style="background:#e7f3ff;padding:10px">ADMIN FUNDS SUMMARY</h3>
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 18px">
      <div style="flex:1;min-width:180px;background:#eaffea;border:1px solid #b8dfb8;border-radius:8px;padding:14px"><b>Direct student payments</b><h2 style="margin:8px 0">KSh {{ "{:,}".format(direct_funds) }}</h2><small>Confirmed payments from students without an agent referral</small></div>
      <div style="flex:1;min-width:180px;background:#e7f3ff;border:1px solid #b7cde0;border-radius:8px;padding:14px"><b>Admin share from agents</b><h2 style="margin:8px 0">KSh {{ "{:,}".format(agent_admin_share) }}</h2><small>Confirmed agent-referred payments after agent commission</small></div>
      <div style="flex:1;min-width:180px;background:#f3e8ff;border:1px solid #d8bdf5;border-radius:8px;padding:14px"><b>Total admin funds</b><h2 style="margin:8px 0">KSh {{ "{:,}".format(admin_total_funds) }}</h2><small>Direct payments plus admin share from agents; excludes agent commissions</small></div>
    </div>
    <h3 style="background:#fff3cd;padding:10px">STUDENT RECORD CLEANUP</h3>
    <p>This removes confirmed/paid student details from the student records file only. Permanent earnings, agent balances, withdrawal history, agent accounts, payment settings, and fee catalogue are kept. Pending/unpaid records are retained so an in-progress payment is not broken.</p>
    <form action="/admin/reset-student-records" method="POST" onsubmit="return confirm('Remove all confirmed student records? Earnings and withdrawals will be preserved. This cannot be undone unless you have a backup.');" style="padding:12px;border:1px solid #e0b35a;border-radius:8px;margin-bottom:15px">
      <button type="submit" style="padding:12px;background:#b42318;color:white;border:0;border-radius:5px">Clear Confirmed Student Records Only</button>
    </form>
    <h3 style="background:#e7f3ff;padding:10px">PAYMENT SETTINGS</h3>
    <form action="/admin/settings" method="POST" style="border:1px solid #b7cde0;padding:15px;border-radius:8px;margin-bottom:15px;background:#f8fbff">
      <label>Direct student price (KSh)</label><input type="number" name="direct_price" min="1" step="1" required value="{{payment_settings.direct_price}}" style="box-sizing:border-box;width:100%;padding:10px;margin:5px 0 12px">
      <label>Student price through an agent (KSh)</label><input type="number" name="agent_price" min="1" step="1" required value="{{payment_settings.agent_price}}" style="box-sizing:border-box;width:100%;padding:10px;margin:5px 0 12px">
      <label>Agent commission per confirmed referred payment (KSh)</label><input type="number" name="agent_commission" min="0" step="1" required value="{{payment_settings.agent_commission}}" style="box-sizing:border-box;width:100%;padding:10px;margin:5px 0 12px">
      <label>Minimum agent withdrawal amount (KSh)</label><input type="number" name="minimum_withdrawal" min="1" step="1" required value="{{payment_settings.minimum_withdrawal}}" style="box-sizing:border-box;width:100%;padding:10px;margin:5px 0 12px">
      <p style="color:#555">The admin receives the remaining amount from an agent-referred payment. Direct payments go to the admin share before payment-processing costs. Changes apply to new payment attempts; past payments keep their recorded amounts.</p>
      <button type="submit" style="padding:12px;background:green;color:white;border:0;border-radius:5px">Save Payment Settings</button>
    </form>
    <h3 style="background:orange;padding:10px">💰 PENDING WITHDRAWALS ({{pending|length}})</h3>
    {% for w in pending %}
    <div style="border:2px solid orange;padding:10px;margin:10px 0;background:#fff3cd;border-radius:8px">
        <b>Agent/Partner:</b> {{w.agent_name}} ({{w.agent_code}}) | <b>To Pay:</b> {{w.mpesa_phone}} ({{w.mpesa_name}}) | <b>Amount:</b> Ksh {{w.amount}} | <b>Payout:</b> {{w.payout_time}}
        <br><br>
        <button onclick="payAgent('{{w.id}}')" id="btn-{{w.id}}" style="background:green;color:white;border:none;padding:10px 15px;border-radius:5px">💸 Pay Ksh {{w.amount}} Now (STK to {{ADMIN_PHONE}})</button>
        <span id="status-{{w.id}}"></span>
        <a href="/admin/mark-paid/{{w.id}}"><button style="background:blue;color:white;border:none;padding:10px 15px;border-radius:5px;margin-left:10px">Mark Paid Manually</button></a>
    </div>
    {% endfor %}
    <script>
    async function payAgent(id){
        let btn=document.getElementById('btn-'+id); let status=document.getElementById('status-'+id);
        btn.innerText='Sending STK to {{ADMIN_PHONE}}...'; btn.disabled=true;
        let res=await fetch('/admin/pay-agent/'+id,{method:'POST'}); let data=await res.json(); status.innerText=data.message;
        if(data.status=='success'){
            alert('Enter PIN on YOUR phone '+data.admin_phone);
            let interval=setInterval(async ()=>{
                let check=await fetch('/admin/check-status/'+id); let cdata=await check.json();
                if(cdata.status=='Paid'){ status.innerHTML='<b style="color:green">✅ Paid!</b>'; clearInterval(interval); location.reload();}
            },5000);
        } else { btn.innerText='Failed - Try Again'; btn.disabled=false; }
    }
    </script>
    <h3 style="background:green;color:white;padding:10px">DIRECT STUDENTS - Current price Ksh {{payment_settings.direct_price}} (100% Yours before costs) - {{direct|length}} Students</h3>
    <table border="1" cellpadding="5" style="border-collapse:collapse;width:100%"><tr style="background:green;color:white"><th>Date</th><th>Student Name</th><th>Mpesa Phone</th><th>Band</th><th>Amount</th></tr>
    {% for s in direct|reverse %}<tr><td>{{s.date}}</td><td>{{s.name}}</td><td><b>{{s.phone}}</b></td><td>{{s.band}}</td><td>Ksh {{s.price}}</td></tr>{% endfor %}
    </table>
    <h3 style="background:purple;color:white;padding:10px">AGENTS & THEIR STUDENTS</h3>
    {% for a in agents %}<div style="border:1px solid #ccc;padding:10px;margin:10px 0"><b>Agent:</b> {{a.name}} | Code: {{a.code}} | Mpesa: <b>{{a.mpesa_phone}} ({{a.mpesa_name}})</b> | Students: {{a.total_students}} | Admin share: <b>Ksh {{a.owner_total}}</b> | Agent commission: Ksh {{a.agent_total}} <a href="/agent/{{a.code}}">View Dashboard</a></div>{% endfor %}
    </div>
    """, agents=agents, direct=direct, pending=pending, withdrawals=withdrawals, pwd=pwd, ADMIN_PHONE=ADMIN_MPESA_PHONE, payment_settings=payment_settings, direct_funds=direct_funds, agent_admin_share=agent_admin_share, admin_total_funds=admin_total_funds)

@app.route('/admin/reset-student-records', methods=['POST'])
def admin_reset_student_records():
    if not session.get('is_admin'):
        return "Unauthorized", 401
    # First preserve any older paid records in the permanent ledger, then remove only paid student details.
    sync_earnings_from_student_records()
    students = load_json(DB_FILE)
    remaining = [student for student in students if not student.get('paid')]
    removed_count = len(students) - len(remaining)
    save_json(DB_FILE, remaining)
    return f"""<div style='max-width:600px;margin:40px auto;font-family:Arial;padding:20px'>
      <h2>Student record cleanup complete</h2>
      <p>Removed {removed_count} confirmed student record(s).</p>
      <p>Permanent earnings, agent balances, withdrawal history, agent accounts, payment settings, and fee catalogue were preserved. Pending/unpaid records were kept.</p>
      <a href='/admin'>Return to Admin Dashboard</a>
    </div>"""

@app.route('/admin/settings', methods=['POST'])
def admin_save_payment_settings():
    if not session.get('is_admin'):
        return "Unauthorized", 401
    try:
        direct_price = int(request.form.get('direct_price', ''))
        agent_price = int(request.form.get('agent_price', ''))
        agent_commission = int(request.form.get('agent_commission', ''))
        minimum_withdrawal = int(request.form.get('minimum_withdrawal', ''))
        if direct_price < 1 or agent_price < 1 or agent_commission < 0 or minimum_withdrawal < 1:
            raise ValueError
        if agent_commission > agent_price:
            return ("Agent commission cannot be greater than the agent student price. "
                    "<a href='/admin'>Return to admin dashboard</a>"), 400
    except (TypeError, ValueError):
        return ("Enter valid whole-number KSh amounts. Prices must be at least KSh 1 and commission cannot be negative. "
                "<a href='/admin'>Return to admin dashboard</a>"), 400
    save_payment_settings({
        "direct_price": direct_price,
        "agent_price": agent_price,
        "agent_commission": agent_commission,
        "minimum_withdrawal": minimum_withdrawal
    })
    return redirect('/admin')

@app.route('/admin/pay-agent/<wid>', methods=['POST'])
def pay_agent(wid):
    if not session.get('is_admin'): return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    withdrawals=load_json(WITHDRAW_FILE)
    w=next((x for x in withdrawals if x['id']==wid),None)
    if not w: return jsonify({"status":"failed","message":"Not found"})
    if "YOUR_KEY" in INTASEND_PUBLISHABLE_KEY:
        w['status']='Paid'; w['paid_date']=datetime.now().strftime("%Y-%m-%d %H:%M"); save_json(WITHDRAW_FILE, withdrawals)
        return jsonify({"status":"success","message":"DEMO: Marked Paid (Add real keys for real Mpesa)","admin_phone":ADMIN_MPESA_PHONE})
    url="https://payment.intasend.com/api/v1/send-money/initiate/"
    headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}","Content-Type":"application/json"}
    payload={"provider":"M-PESA","currency":"KES","transactions":[{"name":w['mpesa_name'],"account":w['mpesa_phone'],"amount":str(w['amount']),"narrative":f"Payout {w['agent_code']}"}]}
    try:
        resp=requests.post(url,json=payload,headers=headers)
        if resp.status_code in [200,201]:
            w['status']='Processing'; save_json(WITHDRAW_FILE, withdrawals)
            return jsonify({"status":"success","message":f"STK sent to {ADMIN_MPESA_PHONE}. Enter PIN","admin_phone":ADMIN_MPESA_PHONE})
        else: return jsonify({"status":"failed","message":resp.text})
    except Exception as e: return jsonify({"status":"failed","message":str(e)})

@app.route('/admin/check-status/<wid>')
def check_status(wid):
    if not session.get('is_admin'): return jsonify({"status": "Unauthorized"}), 401
    withdrawals=load_json(WITHDRAW_FILE)
    w=next((x for x in withdrawals if x['id']==wid),None)
    return jsonify({"status":w['status'] if w else "NotFound"})

@app.route('/admin/mark-paid/<wid>')
def mark_paid(wid):
    if not session.get('is_admin'): return "Unauthorized", 401
    withdrawals=load_json(WITHDRAW_FILE)
    for w in withdrawals:
        if w['id']==wid: w['status']='Paid'; w['paid_date']=datetime.now().strftime("%Y-%m-%d %H:%M")
    save_json(WITHDRAW_FILE, withdrawals)
    return redirect('/admin')

if __name__=='__main__':
    app.run(debug=True)