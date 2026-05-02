from flask import Flask, render_template, request, redirect, session, flash, jsonify, send_file
import sqlite3
import os
import base64
import uuid
import io
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from werkzeug.utils import secure_filename
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "secretkey"

# =========================
# EMAIL CONFIG
# =========================
MAIL_SENDER  = "kervytabigue69@gmail.com"
MAIL_PASSWORD = "ckbxjfryrbruejqn"

def send_email_async(to_email, subject, html_body):
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = MAIL_SENDER
            msg["To"]      = to_email
            msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(MAIL_SENDER, MAIL_PASSWORD)
                server.sendmail(MAIL_SENDER, to_email, msg.as_string())
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send to {to_email}: {e}")
    threading.Thread(target=_send, daemon=True).start()

def notify_reservation(student_email, student_name, action, res):
    if not student_email:
        return
    approved = (action == "accept")
    color    = "#28a745" if approved else "#dc3545"
    status   = "APPROVED ✅" if approved else "DECLINED ❌"
    subject  = f"CCS Sit-in: Your reservation has been {status}"
    admin_note_html = (
        f"<p><strong>Admin Note:</strong> {res['admin_note']}</p>"
        if res.get("admin_note") else ""
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
      <div style="background:{color};padding:20px;text-align:center;">
        <h2 style="color:white;margin:0;">Reservation {status}</h2>
      </div>
      <div style="padding:30px;">
        <p>Hi <strong>{student_name}</strong>,</p>
        <p>Your sit-in reservation has been <strong style="color:{color};">{status}</strong>.</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
          <tr style="background:#f8f9fa;">
            <td style="padding:8px 12px;font-weight:bold;width:40%;">Lab</td>
            <td style="padding:8px 12px;">Lab {res['lab']}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;font-weight:bold;">PC Number</td>
            <td style="padding:8px 12px;">PC {res['pc_number']}</td>
          </tr>
          <tr style="background:#f8f9fa;">
            <td style="padding:8px 12px;font-weight:bold;">Date</td>
            <td style="padding:8px 12px;">{res['date']}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;font-weight:bold;">Time Slot</td>
            <td style="padding:8px 12px;">{res['time_slot']}</td>
          </tr>
          <tr style="background:#f8f9fa;">
            <td style="padding:8px 12px;font-weight:bold;">Purpose</td>
            <td style="padding:8px 12px;">{res['purpose']}</td>
          </tr>
        </table>
        {admin_note_html}
        {"<p>Please proceed to the lab at your scheduled time. Make sure to bring your student ID.</p>" if approved else "<p>You may submit a new reservation request if needed.</p>"}
        <p style="margin-top:24px;font-size:13px;color:#888;">— CCS Sit-in Monitoring System, University of Cebu</p>
      </div>
    </div>
    """
    send_email_async(student_email, subject, html)

# =========================
# PROFILE PIC CONFIG
# =========================
UPLOAD_FOLDER = os.path.join("static", "uploads")
SOFTWARE_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, "software")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_SOFTWARE_EXTENSIONS = {
    "exe", "msi", "zip", "rar", "7z", "iso",
    "pdf", "txt", "doc", "docx",
}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SOFTWARE_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_software_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_SOFTWARE_EXTENSIONS

# =========================
# DATABASE CONNECTION
# =========================
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# INITIALIZE DATABASE
# =========================
def init_db():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE,
        first_name TEXT,
        last_name TEXT,
        middle_name TEXT,
        course TEXT,
        course_level TEXT,
        email TEXT,
        address TEXT,
        password TEXT,
        remaining_session INTEGER DEFAULT 30,
        is_admin INTEGER DEFAULT 0,
        profile_pic TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS rooms(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT UNIQUE,
        capacity INTEGER,
        is_occupied INTEGER DEFAULT 0,
        current_user_id INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sitin_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        name TEXT,
        purpose TEXT,
        lab TEXT,
        pc_number INTEGER,
        session INTEGER DEFAULT 30,
        time_in DATETIME DEFAULT CURRENT_TIMESTAMP,
        time_out DATETIME,
        status TEXT DEFAULT 'IN'
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS announcements(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS lab_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        must_rules TEXT,
        must_not_rules TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS reservations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        name TEXT,
        purpose TEXT,
        lab TEXT,
        pc_number INTEGER,
        date TEXT,
        time_slot TEXT,
        status TEXT DEFAULT 'PENDING',
        admin_note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS pc_availability(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT,
        date TEXT,
        time_start TEXT,
        time_end TEXT,
        available_pcs TEXT,
        UNIQUE(room_number, date, time_start, time_end)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sitin_id INTEGER UNIQUE,
        student_id TEXT,
        name TEXT,
        lab TEXT,
        purpose TEXT,
        rating INTEGER,
        feedback_text TEXT,
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS software_uploads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        file_name TEXT NOT NULL,
        stored_name TEXT NOT NULL UNIQUE,
        file_size_bytes INTEGER DEFAULT 0,
        uploaded_by INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    rooms = [
        ('524', 50), ('525', 50), ('526', 50), ('527', 50), ('528', 50),
        ('529', 50), ('530', 50), ('530A', 50), ('530B', 50), ('530C', 50)
    ]
    for r in rooms:
        conn.execute("INSERT OR IGNORE INTO rooms (room_number, capacity) VALUES (?, ?)", r)
    conn.execute("UPDATE rooms SET capacity=50 WHERE capacity < 50")

    admin = conn.execute("SELECT * FROM users WHERE student_id='admin'").fetchone()
    if not admin:
        conn.execute("""
        INSERT INTO users (student_id, first_name, last_name, password, is_admin)
        VALUES ('admin','Admin','User','admin123',1)
        """)

    migrations = [
        "ALTER TABLE users ADD COLUMN remaining_session INTEGER DEFAULT 30",
        "ALTER TABLE sitin_records ADD COLUMN session INTEGER DEFAULT 30",
        "ALTER TABLE sitin_records ADD COLUMN pc_number INTEGER",
        "ALTER TABLE users ADD COLUMN profile_pic TEXT",
        "ALTER TABLE reservations ADD COLUMN admin_note TEXT",
        "ALTER TABLE reservations ADD COLUMN pc_number INTEGER",
        "ALTER TABLE pc_availability ADD COLUMN time_start TEXT",
        "ALTER TABLE pc_availability ADD COLUMN time_end TEXT",
        "ALTER TABLE reservations ADD COLUMN seen_by_student INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN reservation_enabled INTEGER DEFAULT 1",
        "ALTER TABLE users ADD COLUMN preferred_pc INTEGER",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass

    conn.commit()
    conn.close()

init_db()

# =========================
# HELPER: Save profile picture
# =========================
def save_profile_pic(file=None, base64_data=None, old_pic=None):
    if old_pic:
        old_path = os.path.join(UPLOAD_FOLDER, old_pic)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    filename = None

    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(UPLOAD_FOLDER, filename))

    elif base64_data and base64_data.startswith("data:image"):
        try:
            header, encoded = base64_data.split(",", 1)
            ext = header.split("/")[1].split(";")[0]
            if ext not in ALLOWED_EXTENSIONS:
                ext = "jpg"
            filename = f"{uuid.uuid4().hex}.{ext}"
            img_bytes = base64.b64decode(encoded)
            with open(os.path.join(UPLOAD_FOLDER, filename), "wb") as f:
                f.write(img_bytes)
        except Exception:
            filename = None

    return filename

# =========================
# HELPER: sit-in session duration for student dashboard
# =========================
def _parse_sitin_timestamp(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    # Strip sub-second and timezone tails for ISO parse (len(fmt) is NOT input length — was a bug)
    iso = s.replace("Z", "+00:00")
    if "." in iso and ("T" in iso or (len(iso) > 10 and iso[10] == " ")):
        iso = iso.split(".")[0]
    if " " in iso and "T" not in iso[:11]:
        iso = iso.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def _format_sitin_duration(total_seconds, ongoing=False):
    if total_seconds < 0:
        total_seconds = 0
    secs = int(total_seconds)
    if secs < 60 and secs > 0:
        text = f"{secs}s"
    else:
        hours, rem = divmod(secs, 3600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        text = " ".join(parts)
    if ongoing:
        return f"{text} (ongoing)"
    return text


def _build_sitin_summary(student_id, conn):
    """Aggregate sit-in stats for the student dashboard (all records, not only recent)."""
    rows = conn.execute(
        """
        SELECT time_in, time_out, status
        FROM sitin_records
        WHERE student_id=?
        """,
        (student_id,),
    ).fetchall()

    now = datetime.now()
    durations = []
    for r in rows:
        tin = _parse_sitin_timestamp(r["time_in"])
        if not tin:
            durations.append(0.0)
            continue
        tout = _parse_sitin_timestamp(r["time_out"])
        if tout:
            sec = (tout - tin).total_seconds()
        elif (r["status"] or "").upper() == "IN":
            sec = (now - tin).total_seconds()
        else:
            sec = 0.0
        durations.append(max(0.0, sec))

    n = len(durations)
    if n == 0:
        return {
            "session_count": 0,
            "total_hours_display": "—",
            "avg_duration_display": "—",
            "longest_duration_display": "—",
        }

    total_sec = sum(durations)
    longest_sec = max(durations)
    avg_sec = total_sec / n

    return {
        "session_count": n,
        "total_hours_display": f"{total_sec / 3600:.1f} hrs",
        "avg_duration_display": _format_sitin_duration(avg_sec, ongoing=False),
        "longest_duration_display": _format_sitin_duration(longest_sec, ongoing=False),
    }


# =========================
# HELPER: parse and format PC availability selections
# =========================
def parse_pc_selection(text):
    """Convert a string like '1-7, 10, 15-20' into a sorted list of ints."""
    if not text:
        return []
    pcs = set()
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            bounds = part.split('-')
            if len(bounds) == 2 and bounds[0].strip().isdigit() and bounds[1].strip().isdigit():
                start = int(bounds[0].strip())
                end   = int(bounds[1].strip())
                if start <= end:
                    for n in range(max(1, start), min(50, end) + 1):
                        pcs.add(n)
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= 50:
                pcs.add(n)
    return sorted(pcs)


def format_pc_selection(pcs):
    if not pcs:
        return ""
    values = sorted({int(x) for x in pcs if str(x).strip().isdigit()})
    ranges = []
    start = prev = values[0]
    for n in values[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = n
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def normalize_time(t):
    """
    Normalise a time string to 24-h 'HH:MM' so we can compare
    time_start / time_end (stored as 'HH:MM') with the student's
    time_slot (stored as e.g. '9:00 AM - 10:00 AM').

    Accepts:
      '09:00'            → '09:00'
      '9:00'             → '09:00'
      '9:00 AM'          → '09:00'
      '1:00 PM'          → '13:00'
      '12:00 PM'         → '12:00'
      '12:00 AM'         → '00:00'
    """
    if not t:
        return ""
    t = t.strip()
    try:
        # Try 24-h first ("HH:MM" or "H:MM")
        if "AM" not in t.upper() and "PM" not in t.upper():
            parts = t.split(":")
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        # 12-h with AM/PM
        upper = t.upper()
        pm = "PM" in upper
        time_part = upper.replace("AM", "").replace("PM", "").strip()
        parts = time_part.split(":")
        h = int(parts[0]); m = int(parts[1])
        if pm and h != 12:
            h += 12
        if not pm and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    except Exception:
        return t  # return as-is if we can't parse


def slot_within_window(time_slot, time_start, time_end):
    """
    Return True ONLY when the student's time_slot falls fully within
    (or exactly matches) the admin-configured [time_start, time_end] window.

    If the student picks ANY time outside the window → returns False,
    which causes get_available_pcs_for_slot to fall back to all 50 PCs.

    time_slot  : e.g. "9:00 AM - 10:00 AM"  OR just "09:00"
    time_start : e.g. "08:30"  (24-h, stored by admin)
    time_end   : e.g. "09:30"
    """
    if not time_start or not time_end:
        # No restriction configured — always matches (all-day row)
        return True

    ts_norm = normalize_time(time_start)
    te_norm = normalize_time(time_end)

    # Split "H:MM AM - H:MM PM" style slot string
    if " - " in time_slot:
        parts = time_slot.split(" - ", 1)
        slot_start = normalize_time(parts[0].strip())
        slot_end   = normalize_time(parts[1].strip())
    else:
        slot_start = slot_end = normalize_time(time_slot.strip())

    if not slot_start or not slot_end:
        return False

    # Student slot must start >= window start AND end <= window end
    return slot_start >= ts_norm and slot_end <= te_norm


def get_available_pcs_for_slot(conn, room, date, time_slot):
    """
    Return the list of PC numbers available for a given room/date/time_slot.
    Applies admin-configured availability first, then removes already-booked PCs.
    """
    rows = conn.execute(
        "SELECT * FROM pc_availability WHERE room_number=? AND date=?",
        (room, date)
    ).fetchall()

    matched_row = None

    if time_slot and rows:
        # Find the row whose time window FULLY CONTAINS the requested slot
        for row in rows:
            if slot_within_window(time_slot, row["time_start"], row["time_end"]):
                matched_row = row
                break
        if not matched_row:
            # No configured window contains this slot → fall back to all-day row
            for row in rows:
                if not row["time_start"] and not row["time_end"]:
                    matched_row = row
                    break
        # If still no match → matched_row stays None → all 50 PCs returned below
    elif rows:
        matched_row = rows[0]

    if matched_row and matched_row["available_pcs"]:
        available = parse_pc_selection(matched_row["available_pcs"])
    else:
        # No config for this date → all 50 PCs available
        available = list(range(1, 51))

    # Remove PCs already reserved for this slot
    if time_slot:
        blocked_rows = conn.execute(
            """
            SELECT pc_number FROM reservations
            WHERE lab=? AND date=? AND time_slot=? AND status IN ('PENDING','APPROVED')
            """,
            (room, date, time_slot)
        ).fetchall()
        blocked_pcs = {r["pc_number"] for r in blocked_rows if r["pc_number"] is not None}
        available = [n for n in available if n not in blocked_pcs]

    return available


def build_admin_analytics(conn):
    """Summary metrics + chart series for the admin analytics page."""
    avg_sess_row = conn.execute("""
        SELECT AVG(CAST((strftime('%s', time_out) - strftime('%s', time_in)) AS REAL) / 60.0)
        FROM sitin_records
        WHERE time_out IS NOT NULL AND time_in IS NOT NULL
    """).fetchone()
    avg_session_minutes = round(float(avg_sess_row[0] or 0), 1)

    top_lab_row = conn.execute("""
        SELECT lab, COUNT(*) AS c FROM sitin_records
        GROUP BY lab ORDER BY c DESC LIMIT 1
    """).fetchone()
    top_lab_name = top_lab_row["lab"] if top_lab_row else None
    top_lab_count = int(top_lab_row["c"]) if top_lab_row else 0

    sitins_30d = int(
        conn.execute("""
            SELECT COUNT(*) FROM sitin_records
            WHERE datetime(time_in) >= datetime('now', '-30 days')
        """).fetchone()[0]
    )

    res_stat_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM reservations GROUP BY status"
    ).fetchall()
    reservation_counts = {r["status"]: int(r["n"]) for r in res_stat_rows}
    _ap = reservation_counts.get("APPROVED", 0)
    _de = reservation_counts.get("DECLINED", 0)
    reservation_approval_pct = (
        round(100.0 * _ap / (_ap + _de), 1) if (_ap + _de) > 0 else None
    )

    avg_rating = conn.execute(
        "SELECT ROUND(AVG(rating), 2) FROM feedback"
    ).fetchone()[0] or 0
    feedback_n = int(conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0])

    lab_dist = conn.execute("""
        SELECT lab, COUNT(*) AS c FROM sitin_records
        GROUP BY lab ORDER BY c DESC LIMIT 12
    """).fetchall()
    lab_chart_labels = [f"Lab {r['lab']}" for r in lab_dist]
    lab_chart_counts = [int(r["c"]) for r in lab_dist]

    return {
        "avg_session_minutes": avg_session_minutes,
        "top_lab_name": top_lab_name,
        "top_lab_count": top_lab_count,
        "sitins_last_30_days": sitins_30d,
        "reservation_approval_pct": reservation_approval_pct,
        "reservation_counts": reservation_counts,
        "feedback_submissions": feedback_n,
        "avg_rating_display": float(avg_rating) if avg_rating else 0.0,
        "lab_chart_labels": lab_chart_labels,
        "lab_chart_counts": lab_chart_counts,
    }


# =========================
# HELPER: load admin dashboard data
# =========================
def get_admin_data(search=None):
    conn = get_db()

    total_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]

    if search:
        students = conn.execute("""
            SELECT * FROM users
            WHERE is_admin=0 AND (
                student_id LIKE ? OR
                first_name LIKE ? OR
                last_name LIKE ? OR
                middle_name LIKE ?
            )
        """, (f"%{search}%",) * 4).fetchall()
    else:
        students = conn.execute("SELECT * FROM users WHERE is_admin=0").fetchall()

    sitin_records = conn.execute("""
        SELECT student_id, name, purpose, lab, session, time_in, time_out, status
        FROM sitin_records
        ORDER BY time_in DESC
    """).fetchall()

    current_sitin_count = conn.execute(
        "SELECT COUNT(*) FROM sitin_records WHERE status='IN'"
    ).fetchone()[0]

    total_sitin_count = conn.execute(
        "SELECT COUNT(*) FROM sitin_records"
    ).fetchone()[0]

    announcements = conn.execute(
        "SELECT * FROM announcements ORDER BY id DESC"
    ).fetchall()
    current_lab_rules = conn.execute(
        "SELECT * FROM lab_rules ORDER BY id DESC LIMIT 1"
    ).fetchone()

    rooms = conn.execute("SELECT * FROM rooms ORDER BY room_number").fetchall()

    purpose_rows = conn.execute("""
        SELECT purpose, COUNT(*) as count
        FROM sitin_records
        GROUP BY purpose
    """).fetchall()
    purpose_map = {row["purpose"]: row["count"] for row in purpose_rows}
    purposes = ["C Programming", "Java", "C#", "PHP"]
    purpose_counts = [purpose_map.get(p, 0) for p in purposes]

    reservations = conn.execute("""
        SELECT * FROM reservations ORDER BY created_at DESC
    """).fetchall()

    pending_reservations_count = conn.execute(
        "SELECT COUNT(*) FROM reservations WHERE status='PENDING'"
    ).fetchone()[0]

    feedback_reports = conn.execute("""
        SELECT f.*, s.time_in, s.time_out
        FROM feedback f
        LEFT JOIN sitin_records s ON s.id = f.sitin_id
        ORDER BY f.submitted_at DESC
    """).fetchall()

    software_uploads = conn.execute("""
        SELECT su.*, u.first_name, u.last_name
        FROM software_uploads su
        LEFT JOIN users u ON u.id = su.uploaded_by
        ORDER BY su.created_at DESC
        LIMIT 30
    """).fetchall()

    pc_availabilities = conn.execute(
        "SELECT * FROM pc_availability ORDER BY date DESC, room_number"
    ).fetchall()

    # ── Leaderboard: top 3 students by total sit-in count + accumulated time ──
    leaderboard_rows = conn.execute("""
        SELECT
            u.student_id,
            u.first_name || ' ' || u.last_name AS full_name,
            u.course,
            u.course_level,
            COUNT(s.id)                          AS total_sitins,
            SUM(
                CASE
                    WHEN s.time_out IS NOT NULL
                    THEN CAST(
                        (strftime('%s', s.time_out) - strftime('%s', s.time_in))
                        AS INTEGER)
                    ELSE 0
                END
            )                                    AS total_seconds
        FROM sitin_records s
        JOIN users u ON u.student_id = s.student_id
        WHERE u.is_admin = 0
        GROUP BY s.student_id
        ORDER BY total_sitins DESC, total_seconds DESC
        LIMIT 3
    """).fetchall()

    # Convert seconds to "Xh Ym" string
    def fmt_duration(secs):
        if not secs or secs <= 0:
            return "0m"
        h = secs // 3600
        m = (secs % 3600) // 60
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    leaderboard = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, row in enumerate(leaderboard_rows):
        leaderboard.append({
            "rank":         idx + 1,
            "medal":        medals[idx],
            "student_id":   row["student_id"],
            "full_name":    row["full_name"],
            "course":       row["course"],
            "course_level": row["course_level"],
            "total_sitins": row["total_sitins"],
            "total_time":   fmt_duration(row["total_seconds"]),
        })

    avg_rating = conn.execute(
        "SELECT ROUND(AVG(rating), 2) FROM feedback"
    ).fetchone()[0] or 0

    conn.close()

    return dict(
        total_users=total_users,
        students=students,
        sitin_records=sitin_records,
        current_sitin_count=current_sitin_count,
        total_sitin_count=total_sitin_count,
        announcements=announcements,
        current_lab_rules=current_lab_rules,
        rooms=rooms,
        purposes=purposes,
        purpose_counts=purpose_counts,
        search=search or "",
        reservations=reservations,
        pending_reservations_count=pending_reservations_count,
        feedback_reports=feedback_reports,
        avg_rating=avg_rating,
        pc_availabilities=pc_availabilities,
        leaderboard=leaderboard,
        software_uploads=software_uploads,
    )


# =========================
# API: Available PCs for a slot
# =========================
@app.route("/available_pcs")
def available_pcs():
    room      = request.args.get("room", "").strip()
    date      = request.args.get("date", "").strip()
    time_slot = request.args.get("time_slot", "").strip()

    if not room or not date:
        return jsonify({"pcs": [], "configured": False})

    conn = get_db()
    # Check if admin has configured anything for this room+date
    config_exists = conn.execute(
        "SELECT 1 FROM pc_availability WHERE room_number=? AND date=?", (room, date)
    ).fetchone()
    available = get_available_pcs_for_slot(conn, room, date, time_slot)
    conn.close()
    return jsonify({"pcs": available, "configured": config_exists is not None})


# =========================
# API: All time slots configured for a room+date
# (used by student reservation form to show dropdown)
# =========================
@app.route("/available_slots")
def available_slots():
    room = request.args.get("room", "").strip()
    date = request.args.get("date", "").strip()

    if not room or not date:
        return jsonify({"slots": []})

    conn = get_db()
    rows = conn.execute(
        "SELECT time_start, time_end FROM pc_availability WHERE room_number=? AND date=? ORDER BY time_start",
        (room, date)
    ).fetchall()
    conn.close()

    slots = []
    for row in rows:
        if row["time_start"] and row["time_end"]:
            slots.append(f"{row['time_start']} - {row['time_end']}")
    return jsonify({"slots": slots})


# =========================
# PC AVAILABILITY PAGE (admin)
# =========================
@app.route('/pc_availability')
def pc_availability():
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    rooms = conn.execute("SELECT * FROM rooms ORDER BY room_number").fetchall()
    pc_availabilities = conn.execute(
        "SELECT * FROM pc_availability ORDER BY date DESC, room_number"
    ).fetchall()
    conn.close()
    return render_template('pc_availability.html', rooms=rooms, pc_availabilities=pc_availabilities)


@app.route('/save_pc_availability', methods=["POST"])
def save_pc_availability():
    """Admin saves a PC availability schedule for a lab/date/time window."""
    if not session.get("is_admin"):
        return redirect("/")

    room_number       = request.form.get("room_number", "").strip()
    availability_date = request.form.get("availability_date", "").strip()
    # Strip seconds if browser sends HH:MM:SS — store only HH:MM
    def strip_seconds(t):
        if not t: return None
        t = t.strip()
        if not t: return None
        parts = t.split(":")
        if len(parts) >= 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return t

    time_start = strip_seconds(request.form.get("time_start", ""))
    time_end   = strip_seconds(request.form.get("time_end", ""))
    available_pcs_raw = request.form.get("available_pcs", "").strip()

    if not room_number or not availability_date:
        flash("Lab and date are required.", "warning")
        return redirect("/pc_availability")

    # Validate time window
    if (time_start and not time_end) or (time_end and not time_start):
        flash("Please provide both Time Start and Time End, or leave both blank.", "warning")
        return redirect("/pc_availability")

    if not available_pcs_raw:
        flash("Please select at least one available PC.", "warning")
        return redirect("/pc_availability")

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO pc_availability (room_number, date, time_start, time_end, available_pcs)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(room_number, date, time_start, time_end)
            DO UPDATE SET available_pcs=excluded.available_pcs
        """, (room_number, availability_date, time_start, time_end, available_pcs_raw))
        conn.commit()
        flash(f"PC availability saved for Lab {room_number} on {availability_date}!", "success")
    except Exception as e:
        flash(f"Error saving availability: {e}", "error")
    finally:
        conn.close()

    return redirect("/pc_availability")


@app.route('/delete_pc_availability/<int:avail_id>', methods=["POST"])
def delete_pc_availability(avail_id):
    """Admin deletes a PC availability schedule."""
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    conn.execute("DELETE FROM pc_availability WHERE id=?", (avail_id,))
    conn.commit()
    conn.close()
    flash("Availability schedule deleted.", "info")
    return redirect("/pc_availability")


# =========================
# ADMIN ANALYTICS PAGE (separate window, like PC Availability)
# =========================
@app.route("/admin_analytics")
def admin_analytics_page():
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    admin_analytics = build_admin_analytics(conn)
    conn.close()
    return render_template("admin_analytics.html", admin_analytics=admin_analytics)


# =========================
# LOGIN
# =========================
@app.route("/")
def login():
    return render_template("login.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/login", methods=["POST"])
def login_user():
    student_id = request.form["student_id"]
    password   = request.form["password"]

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE student_id=? AND password=?",
        (student_id, password)
    ).fetchone()
    conn.close()

    if user:
        session["user_id"] = user["id"]
        session["is_admin"] = user["is_admin"]
        return redirect("/dashboard")

    return "<script>alert('Invalid login');window.location='/'</script>"

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()

    if session.get("is_admin"):
        data = get_admin_data()
        return render_template("admin_dashboard.html", user=user, open_search=False, **data)

    # STUDENT VIEW
    conn = get_db()

    active_sitin = conn.execute(
        "SELECT * FROM sitin_records WHERE student_id=? AND status='IN'",
        (user["student_id"],)
    ).fetchone()

    lab_counts = conn.execute(
        "SELECT lab, COUNT(*) as count FROM sitin_records WHERE status='IN' GROUP BY lab"
    ).fetchall()
    lab_count_map = {row["lab"]: row["count"] for row in lab_counts}

    all_rooms = conn.execute("SELECT * FROM rooms ORDER BY room_number").fetchall()
    labs = [
        {"name": r["room_number"], "capacity": r["capacity"], "current": lab_count_map.get(r["room_number"], 0)}
        for r in all_rooms
    ]

    announcements = conn.execute(
        "SELECT * FROM announcements ORDER BY id DESC"
    ).fetchall()
    current_lab_rules = conn.execute(
        "SELECT * FROM lab_rules ORDER BY id DESC LIMIT 1"
    ).fetchone()

    student_data = conn.execute(
        "SELECT remaining_session FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()
    remaining_session = student_data["remaining_session"] if student_data else 30

    my_reservations = conn.execute("""
        SELECT * FROM reservations
        WHERE student_id=?
        ORDER BY created_at DESC
    """, (user["student_id"],)).fetchall()

    pending_reservation = conn.execute("""
        SELECT * FROM reservations
        WHERE student_id=? AND status='PENDING'
        LIMIT 1
    """, (user["student_id"],)).fetchone()

    # In-app notification: newly approved/declined reservations
    unseen = conn.execute("""
        SELECT * FROM reservations
        WHERE student_id=? AND status IN ('APPROVED','DECLINED') AND seen_by_student=0
        ORDER BY created_at DESC
    """, (user["student_id"],)).fetchall()

    for res in unseen:
        if res["status"] == "APPROVED":
            flash(f"✅ Your reservation for Lab {res['lab']} PC {res['pc_number']} on {res['date']} at {res['time_slot']} has been APPROVED!", "success")
        else:
            note = f" Reason: {res['admin_note']}" if res["admin_note"] else ""
            flash(f"❌ Your reservation for Lab {res['lab']} PC {res['pc_number']} on {res['date']} has been DECLINED.{note}", "error")

    if unseen:
        conn.execute("""
            UPDATE reservations SET seen_by_student=1
            WHERE student_id=? AND status IN ('APPROVED','DECLINED') AND seen_by_student=0
        """, (user["student_id"],))
        conn.commit()

    # Recent sit-in sessions — exclude sessions that already have feedback submitted
    # (once feedback is given, the row disappears from the list)
    recent_rows_raw = conn.execute("""
        SELECT s.*,
               0 AS has_feedback
        FROM sitin_records s
        LEFT JOIN feedback f ON f.sitin_id = s.id
        WHERE s.student_id=?
          AND f.id IS NULL
        ORDER BY s.time_in DESC
        LIMIT 20
    """, (user["student_id"],)).fetchall()

    # Convert to dicts; add human-readable duration
    recent_sessions = []
    for r in recent_rows_raw:
        d = dict(r)
        tin = _parse_sitin_timestamp(d.get("time_in"))
        tout = _parse_sitin_timestamp(d.get("time_out"))
        if tin:
            end = tout if tout else datetime.now()
            ongoing = tout is None and (d.get("status") or "").upper() == "IN"
            d["duration_display"] = _format_sitin_duration(
                (end - tin).total_seconds(), ongoing=ongoing
            )
        else:
            d["duration_display"] = "—"
        recent_sessions.append(d)

    sitin_summary = _build_sitin_summary(user["student_id"], conn)

    conn.close()

    return render_template("dashboard.html",
                           user=user,
                           active_sitin=active_sitin,
                           labs=labs,
                           announcements=announcements,
                           current_lab_rules=current_lab_rules,
                           remaining_session=remaining_session,
                           my_reservations=my_reservations,
                           pending_reservation=pending_reservation,
                           recent_sessions=recent_sessions,
                           sitin_summary=sitin_summary)

# =========================
# SEARCH STUDENT
# =========================
@app.route("/search_student")
def search_student():
    if "user_id" not in session or not session.get("is_admin"):
        return redirect("/")

    search = request.args.get("search", "").strip()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()

    data = get_admin_data(search=search)
    return render_template("admin_dashboard.html", user=user, open_search=True, **data)

# =========================
# GET STUDENT INFO (sit-in modal autocomplete)
# =========================
@app.route("/get_student_info")
def get_student_info():
    id_number = request.args.get("id")
    conn = get_db()
    student = conn.execute("""
        SELECT first_name, last_name, remaining_session
        FROM users WHERE student_id=? AND is_admin=0
    """, (id_number,)).fetchone()
    conn.close()

    if student:
        return jsonify({
            "success": True,
            "name": f"{student['first_name']} {student['last_name']}",
            "remaining_session": student['remaining_session'] or 30
        })
    return jsonify({"success": False})

# =========================
# SIT-IN (admin)
# =========================
@app.route("/sitin", methods=["POST"])
def sitin():
    id_number = request.form["id_number"]
    name      = request.form["student_name"]
    purpose   = request.form["purpose"]
    lab       = request.form["lab"]

    conn = get_db()

    existing = conn.execute("""
        SELECT * FROM sitin_records WHERE student_id=? AND status='IN'
    """, (id_number,)).fetchone()

    if existing:
        flash("Student is already sitting in!", "error")
        conn.close()
        return redirect("/dashboard")

    student = conn.execute(
        "SELECT remaining_session FROM users WHERE student_id=?", (id_number,)
    ).fetchone()
    remaining = student['remaining_session'] if student else 30

    conn.execute("""
        INSERT INTO sitin_records (student_id, name, purpose, lab, session)
        VALUES (?, ?, ?, ?, ?)
    """, (id_number, name, purpose, lab, remaining))
    conn.commit()
    conn.close()
    flash("Sit-in recorded successfully!", "success")
    return redirect("/dashboard")

# =========================
# TIME OUT (admin)
# =========================
@app.route("/timeout/<int:id>", methods=["POST"])
def timeout(id):
    conn = get_db()
    conn.execute("""
        UPDATE sitin_records SET status='OUT', time_out=CURRENT_TIMESTAMP WHERE id=?
    """, (id,))
    conn.commit()
    conn.close()
    flash("Student timed out successfully!", "success")
    return redirect("/dashboard")

# =========================
# REGISTER
# =========================
@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/register_user", methods=["POST"])
def register_user():
    data = (
        request.form["student_id"],
        request.form["first_name"],
        request.form["last_name"],
        request.form.get("middle_name", ""),
        request.form["course"],
        request.form["course_level"],
        request.form.get("email", ""),
        request.form.get("address", ""),
        request.form["password"]
    )

    is_admin = session.get("is_admin", False)
    redirect_on_error   = "/dashboard" if is_admin else "/register"
    redirect_on_success = "/dashboard" if is_admin else "/"

    conn = get_db()
    existing = conn.execute("SELECT * FROM users WHERE student_id=?", (data[0],)).fetchone()
    if existing:
        conn.close()
        flash("Student ID already exists.", "error")
        return redirect(redirect_on_error)

    conn.execute("""
        INSERT INTO users
        (student_id, first_name, last_name, middle_name, course, course_level, email, address, password)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    conn.commit()
    conn.close()
    flash("Student registered successfully!", "success")
    return redirect(redirect_on_success)

# =========================
# EDIT STUDENT
# =========================
@app.route("/edit_student", methods=["POST"])
def edit_student():
    if not session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    pref_raw = request.form.get("preferred_pc", "").strip()
    preferred_pc = None
    if pref_raw:
        try:
            n = int(pref_raw)
            if 1 <= n <= 50:
                preferred_pc = n
        except ValueError:
            pass

    conn.execute("""
        UPDATE users SET first_name=?, last_name=?, course=?, course_level=?, email=?,
        preferred_pc=?
        WHERE student_id=?
    """, (
        request.form["first_name"],
        request.form["last_name"],
        request.form["course"],
        request.form["course_level"],
        request.form.get("email", ""),
        preferred_pc,
        request.form["student_id"]
    ))
    conn.commit()
    conn.close()
    flash("Student updated successfully!", "success")
    return redirect("/dashboard")

# =========================
# DELETE STUDENT
# =========================
@app.route("/delete_student/<student_id>", methods=["POST"])
def delete_student(student_id):
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    conn.execute("DELETE FROM users WHERE student_id=? AND is_admin=0", (student_id,))
    conn.commit()
    conn.close()
    flash("Student deleted successfully!", "success")
    return redirect("/dashboard")


@app.route("/admin_toggle_student_reservations/<student_id>", methods=["POST"])
def admin_toggle_student_reservations(student_id):
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    row = conn.execute(
        "SELECT is_admin, reservation_enabled FROM users WHERE student_id=?",
        (student_id,),
    ).fetchone()
    if not row or row["is_admin"]:
        conn.close()
        flash("Student not found.", "error")
        return redirect("/dashboard")
    cur = row["reservation_enabled"]
    if cur is None:
        cur = 1
    new_val = 0 if cur else 1
    conn.execute(
        "UPDATE users SET reservation_enabled=? WHERE student_id=? AND is_admin=0",
        (new_val, student_id),
    )
    conn.commit()
    conn.close()
    if new_val:
        flash(f"Reservations enabled for student {student_id}.", "success")
    else:
        flash(f"Reservations disabled for student {student_id}.", "warning")
    return redirect("/dashboard")


# =========================
# RESET ALL SESSIONS
# =========================
@app.route("/reset_all_sessions", methods=["POST"])
def reset_all_sessions():
    if not session.get("is_admin"):
        return redirect("/")
    conn = get_db()
    conn.execute("UPDATE users SET remaining_session=30 WHERE is_admin=0")
    conn.commit()
    conn.close()
    flash("All sessions have been reset!", "success")
    return redirect("/dashboard")

# =========================
# POST ANNOUNCEMENT
# =========================
@app.route("/post_announcement", methods=["POST"])
def post_announcement():
    if not session.get("is_admin"):
        return redirect("/")
    text = request.form["announcement"]
    conn = get_db()
    conn.execute("INSERT INTO announcements (text) VALUES (?)", (text,))
    conn.commit()
    conn.close()
    flash("Announcement posted successfully!", "success")
    return redirect("/dashboard")

# =========================
# POST LAB RULES
# =========================
@app.route("/post_lab_rules", methods=["POST"])
def post_lab_rules():
    if not session.get("is_admin"):
        return redirect("/")

    must_rules = request.form.get("must_rules", "").strip()
    must_not_rules = request.form.get("must_not_rules", "").strip()

    conn = get_db()
    conn.execute(
        "INSERT INTO lab_rules (must_rules, must_not_rules) VALUES (?, ?)",
        (must_rules, must_not_rules)
    )
    conn.commit()
    conn.close()

    flash("Lab rules updated successfully!", "success")
    return redirect("/dashboard")


# =========================
# ADMIN: SOFTWARE / APP UPLOAD
# =========================
@app.route("/upload_software", methods=["POST"])
def upload_software():
    if not session.get("is_admin"):
        return redirect("/")

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    file = request.files.get("software_file")

    if not title:
        flash("Software title is required.", "warning")
        return redirect("/dashboard")
    if not file or not file.filename:
        flash("Please choose a file to upload.", "warning")
        return redirect("/dashboard")
    if not allowed_software_file(file.filename):
        flash("Unsupported file type. Allowed: exe, msi, zip, rar, 7z, iso, pdf, txt, doc, docx.", "warning")
        return redirect("/dashboard")

    safe_original = secure_filename(file.filename)
    ext = safe_original.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(SOFTWARE_UPLOAD_FOLDER, stored_name)

    try:
        file.save(save_path)
        file_size = os.path.getsize(save_path)
    except Exception as e:
        flash(f"Upload failed: {e}", "error")
        return redirect("/dashboard")

    conn = get_db()
    conn.execute("""
        INSERT INTO software_uploads
        (title, description, file_name, stored_name, file_size_bytes, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        title,
        description,
        safe_original,
        stored_name,
        file_size,
        session.get("user_id"),
    ))
    conn.commit()
    conn.close()

    flash("Software file uploaded successfully.", "success")
    return redirect("/dashboard")

# =========================
# STUDENT SELF SIT-IN
# =========================
@app.route("/student_sitin", methods=["POST"])
def student_sitin():
    if "user_id" not in session or session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    existing = conn.execute("""
        SELECT * FROM sitin_records WHERE student_id=? AND status='IN'
    """, (user["student_id"],)).fetchone()

    if existing:
        conn.close()
        return redirect("/dashboard")

    if user["remaining_session"] <= 0:
        conn.close()
        return redirect("/dashboard")

    lab     = request.form["lab"]
    purpose = request.form["purpose"]
    name    = f"{user['first_name']} {user['last_name']}"

    conn.execute("""
        INSERT INTO sitin_records (student_id, name, purpose, lab, session)
        VALUES (?, ?, ?, ?, ?)
    """, (user["student_id"], name, purpose, lab, user["remaining_session"]))

    conn.execute("""
        UPDATE users SET remaining_session = remaining_session - 1 WHERE id=?
    """, (session["user_id"],))

    conn.commit()
    conn.close()
    flash("Sit-in recorded successfully!", "success")
    return redirect("/dashboard")

# =========================
# STUDENT SELF TIME OUT
# =========================
@app.route("/student_timeout/<int:id>", methods=["POST"])
def student_timeout(id):
    if "user_id" not in session or session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    conn.execute("""
        UPDATE sitin_records SET status='OUT', time_out=CURRENT_TIMESTAMP WHERE id=?
    """, (id,))
    conn.commit()
    conn.close()
    flash("Timed out successfully!", "success")
    return redirect("/dashboard")

# =========================
# UPDATE PROFILE
# =========================
@app.route("/update_profile", methods=["POST"])
def update_profile():
    if "user_id" not in session:
        return redirect("/")

    first_name    = request.form["first_name"]
    last_name     = request.form["last_name"]
    email         = request.form["email"]
    address       = request.form["address"]
    remove_pic    = request.form.get("remove_pic", "0") == "1"
    captured_data = request.form.get("captured_photo", "").strip()
    uploaded_file = request.files.get("profile_pic")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    old_pic = user["profile_pic"] if user else None

    new_pic = old_pic

    if remove_pic:
        if old_pic:
            old_path = os.path.join(UPLOAD_FOLDER, old_pic)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        new_pic = None
    elif captured_data:
        new_pic = save_profile_pic(base64_data=captured_data, old_pic=old_pic)
    elif uploaded_file and uploaded_file.filename:
        new_pic = save_profile_pic(file=uploaded_file, old_pic=old_pic)

    conn.execute("""
        UPDATE users
        SET first_name=?, last_name=?, email=?, address=?, profile_pic=?
        WHERE id=?
    """, (first_name, last_name, email, address, new_pic, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Profile updated successfully!", "success")
    return redirect("/dashboard")

# =========================
# RESERVATIONS
# =========================
@app.route("/reserve_sitin", methods=["POST"])
def reserve_sitin():
    if "user_id" not in session or session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    if user["reservation_enabled"] == 0:
        flash(
            "Your ability to submit new reservations has been disabled by an administrator. "
            "Contact the lab office if you need help.",
            "error",
        )
        conn.close()
        return redirect("/dashboard")

    existing_pending = conn.execute("""
        SELECT * FROM reservations WHERE student_id=? AND status='PENDING'
    """, (user["student_id"],)).fetchone()

    if existing_pending:
        flash("You already have a pending reservation. Please wait for admin approval.", "warning")
        conn.close()
        return redirect("/dashboard")

    active_sitin = conn.execute("""
        SELECT * FROM sitin_records WHERE student_id=? AND status='IN'
    """, (user["student_id"],)).fetchone()

    if active_sitin:
        flash("You are currently sitting in. Time out first before making a reservation.", "warning")
        conn.close()
        return redirect("/dashboard")

    if user["remaining_session"] <= 0:
        flash("You have no remaining sessions.", "error")
        conn.close()
        return redirect("/dashboard")

    lab       = request.form["lab"]
    pc_number = request.form.get("pc_number", "").strip()
    purpose   = request.form["purpose"]
    date      = request.form["date"]
    time_slot = request.form["time_slot"]
    name      = f"{user['first_name']} {user['last_name']}"

    if not pc_number.isdigit():
        flash("Please select a valid PC number.", "warning")
        conn.close()
        return redirect("/dashboard")

    pc_number = int(pc_number)
    if pc_number < 1 or pc_number > 50:
        flash("PC number must be between 1 and 50.", "warning")
        conn.close()
        return redirect("/dashboard")

    available = get_available_pcs_for_slot(conn, lab, date, time_slot)
    if pc_number not in available:
        flash("That PC is not available for the selected lab/date/time.", "warning")
        conn.close()
        return redirect("/dashboard")

    duplicate = conn.execute("""
        SELECT 1 FROM reservations
        WHERE lab=? AND date=? AND time_slot=? AND pc_number=? AND status IN ('PENDING','APPROVED')
    """, (lab, date, time_slot, pc_number)).fetchone()
    if duplicate:
        flash("That PC is already reserved for the selected slot.", "warning")
        conn.close()
        return redirect("/dashboard")

    conn.execute("""
        INSERT INTO reservations (student_id, name, purpose, lab, pc_number, date, time_slot)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user["student_id"], name, purpose, lab, pc_number, date, time_slot))
    conn.commit()
    conn.close()
    flash("Reservation submitted! Please wait for admin approval.", "success")
    return redirect("/dashboard")


@app.route("/cancel_reservation/<int:res_id>", methods=["POST"])
def cancel_reservation(res_id):
    if "user_id" not in session or session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.execute("""
        UPDATE reservations SET status='CANCELLED'
        WHERE id=? AND student_id=? AND status='PENDING'
    """, (res_id, user["student_id"]))
    conn.commit()
    conn.close()
    flash("Reservation cancelled.", "info")
    return redirect("/dashboard")


@app.route("/admin_reservation_action/<int:res_id>/<action>", methods=["POST"])
def admin_reservation_action(res_id, action):
    if not session.get("is_admin"):
        return redirect("/")
    if action not in ("accept", "decline"):
        return redirect("/dashboard")

    admin_note = request.form.get("admin_note", "").strip()
    new_status = "APPROVED" if action == "accept" else "DECLINED"

    conn = get_db()

    if action == "accept":
        res = conn.execute("SELECT * FROM reservations WHERE id=?", (res_id,)).fetchone()
        if res and res["status"] == "PENDING":
            student = conn.execute(
                "SELECT * FROM users WHERE student_id=?", (res["student_id"],)
            ).fetchone()

            existing = conn.execute("""
                SELECT * FROM sitin_records WHERE student_id=? AND status='IN'
            """, (res["student_id"],)).fetchone()

            if existing:
                flash("Student is already sitting in — cannot approve reservation.", "error")
                conn.close()
                return redirect("/dashboard")

            remaining = student["remaining_session"] if student else 30

            conn.execute("""
                INSERT INTO sitin_records (student_id, name, purpose, lab, pc_number, session)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (res["student_id"], res["name"], res["purpose"], res["lab"], res["pc_number"], remaining))

            conn.execute("""
                UPDATE users SET remaining_session = remaining_session - 1
                WHERE student_id=?
            """, (res["student_id"],))

    conn.execute("""
        UPDATE reservations SET status=?, admin_note=? WHERE id=?
    """, (new_status, admin_note, res_id))
    conn.commit()

    try:
        res_row = conn.execute("SELECT * FROM reservations WHERE id=?", (res_id,)).fetchone()
        if res_row:
            student = conn.execute(
                "SELECT email, first_name, last_name FROM users WHERE student_id=?",
                (res_row["student_id"],)
            ).fetchone()
            if student and student["email"]:
                res_data = dict(res_row)
                res_data["admin_note"] = admin_note
                notify_reservation(
                    student["email"],
                    f"{student['first_name']} {student['last_name']}",
                    action,
                    res_data
                )
    except Exception as e:
        print(f"[EMAIL NOTIFY ERROR] {e}")

    conn.close()

    msg = "Reservation approved — sit-in created!" if action == "accept" else "Reservation declined."
    flash(msg, "success" if action == "accept" else "warning")
    return redirect("/dashboard")


# =========================
# SUBMIT FEEDBACK
# =========================
@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    if "user_id" not in session or session.get("is_admin"):
        return redirect("/")

    sitin_id      = request.form.get("sitin_id", "").strip()
    rating        = request.form.get("rating", "").strip()
    feedback_text = request.form.get("feedback_text", "").strip()

    if not sitin_id or not rating:
        flash("Please provide a star rating before submitting.", "warning")
        return redirect("/dashboard")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    record = conn.execute("""
        SELECT * FROM sitin_records
        WHERE id=? AND student_id=? AND status='OUT'
    """, (sitin_id, user["student_id"])).fetchone()

    if not record:
        flash("Cannot submit feedback for this session.", "error")
        conn.close()
        return redirect("/dashboard")

    existing = conn.execute(
        "SELECT id FROM feedback WHERE sitin_id=?", (sitin_id,)
    ).fetchone()

    if existing:
        flash("Feedback already submitted for this session.", "warning")
        conn.close()
        return redirect("/dashboard")

    name = f"{user['first_name']} {user['last_name']}"
    conn.execute("""
        INSERT INTO feedback (sitin_id, student_id, name, lab, purpose, rating, feedback_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (sitin_id, user["student_id"], name, record["lab"], record["purpose"],
          int(rating), feedback_text))
    conn.commit()
    conn.close()
    flash("Thank you for your feedback!", "success")
    return redirect("/dashboard")


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# EXPORT PDF
# =========================
@app.route("/export_sitin_report")
def export_sitin_report():
    if not session.get("is_admin"):
        return redirect("/")

    conn = get_db()
    sitin_records = conn.execute(
        "SELECT * FROM sitin_records ORDER BY time_in DESC"
    ).fetchall()
    conn.close()

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    uc_logo_path = os.path.join(app.root_path, "static", "images", "uclogo.png")
    ccs_logo_path = os.path.join(app.root_path, "static", "images", "logo.png")

    if os.path.exists(uc_logo_path):
        pdf.image(uc_logo_path, x=10, y=8, w=22)
    if os.path.exists(ccs_logo_path):
        pdf.image(ccs_logo_path, x=265, y=8, w=22)

    pdf.set_y(8)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 8, "University Of Cebu", ln=1, align="C")
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 8, "CCS Sit-In Report", ln=1, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 8, datetime.now().strftime("Generated: %B %d, %Y %I:%M %p"), ln=1, align="C")
    pdf.ln(4)

    headers    = ["#", "Student ID", "Name", "Purpose", "Lab", "Session", "Time In", "Time Out", "Duration", "Status"]
    col_widths = [12, 28, 48, 30, 24, 20, 38, 38, 28, 24]
    line_height = 8

    pdf.set_fill_color(94, 58, 140)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 9)
    for idx, header in enumerate(headers):
        pdf.cell(col_widths[idx], line_height, header, border=1, align="C", fill=True)
    pdf.ln(line_height)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 8)

    for index, record in enumerate(sitin_records, start=1):
        student_id    = record["student_id"]
        name          = record["name"] or ""
        purpose       = record["purpose"] or ""
        lab           = record["lab"] or ""
        session_count = str(record["session"]) if record["session"] is not None else ""
        time_in       = record["time_in"] or ""
        time_out      = record["time_out"] or ""
        raw_status    = (record["status"] or "").upper()
        status        = "Done" if raw_status == "OUT" else ("In Progress" if raw_status == "IN" else raw_status.title())

        duration = ""
        if time_in and time_out:
            try:
                dt_in  = datetime.fromisoformat(str(time_in))
                dt_out = datetime.fromisoformat(str(time_out))
                duration = str(dt_out - dt_in).split(".")[0]
            except Exception:
                duration = ""

        row_values = [
            str(index), student_id, name, purpose, lab,
            session_count, time_in, time_out, duration, status
        ]

        for idx, value in enumerate(row_values):
            text = str(value)
            if len(text) > 30:
                text = text[:27] + "..."
            pdf.cell(col_widths[idx], line_height, text, border=1)
        pdf.ln(line_height)

    pdf_bytes = bytes(pdf.output(dest='S'))
    output = io.BytesIO(pdf_bytes)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="university_of_cebu_sit_in_report.pdf"
    )

# =========================
# RUN APP
# =========================
if __name__ == "__main__":
    app.run(debug=True)
