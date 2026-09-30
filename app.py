#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  MikroTik-Style Captive Portal — Full Payment & Hotspot Management System
  Features: Package Plans · bKash/Nagad · Auto-Voucher · Timer · Messaging
=============================================================================
"""

import os, sqlite3, random, string, subprocess
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, request, redirect, url_for, session,
                   render_template_string, flash, Response, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hotspot_secret_2026_xK9mQ")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "hotspot.db")
HOST, PORT = "0.0.0.0", 8080

# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS admin_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS site_settings(
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS vouchers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pin TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'active',
        source TEXT DEFAULT 'manual',
        order_id TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        used_at TEXT, used_by_ip TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS active_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_ip TEXT UNIQUE NOT NULL,
        pin TEXT NOT NULL,
        package_id INTEGER,
        login_time TEXT DEFAULT (datetime('now','localtime')),
        expires_at TEXT,
        user_agent TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS packages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, price REAL NOT NULL,
        duration_minutes INTEGER NOT NULL,
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS payment_methods(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        method TEXT NOT NULL,
        number TEXT NOT NULL,
        account_name TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1)""")

    c.execute("""CREATE TABLE IF NOT EXISTS payment_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE NOT NULL,
        client_ip TEXT NOT NULL,
        client_name TEXT DEFAULT '',
        package_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_method TEXT NOT NULL,
        transaction_id TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        voucher_pin TEXT,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        verified_at TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_ip TEXT NOT NULL,
        sender_name TEXT DEFAULT 'ইউজার',
        message TEXT NOT NULL,
        reply TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        replied_at TEXT,
        is_read INTEGER DEFAULT 0)""")

    # Auto-migration for existing tables with older schemas
    def add_column_if_missing(table, col, col_type):
        try:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    add_column_if_missing("active_sessions", "package_id", "INTEGER")
    add_column_if_missing("active_sessions", "expires_at", "TEXT")
    add_column_if_missing("vouchers", "source", "TEXT DEFAULT 'manual'")
    add_column_if_missing("vouchers", "order_id", "TEXT")

    # Default admin
    if not c.execute("SELECT id FROM admin_users WHERE username='admin'").fetchone():
        c.execute("INSERT INTO admin_users(username,password_hash) VALUES(?,?)",
                  ("admin", generate_password_hash("admin")))
        print("[*] Default admin -> username: admin | password: admin")

    # Default settings
    for k, v in {
        "site_name": "WiFi Hotspot Portal",
        "site_subtitle": "High Speed Wireless Network",
        "welcome_text": "একটি প্ল্যান বেছে নিন এবং ইন্টারনেট উপভোগ করুন।",
        "footer_text": "সমস্যায় অ্যাডমিনের সাথে যোগাযোগ করুন।",
        "hotspot_name": "MikroTik HotSpot",
        "primary_color": "#007bff",
        "gateway_ip": "192.168.43.1",
        "contact_whatsapp": "",
        "auto_approve": "0",
    }.items():
        c.execute("INSERT OR IGNORE INTO site_settings(key,value) VALUES(?,?)", (k, v))

    # Default packages
    if not c.execute("SELECT COUNT(*) FROM packages").fetchone()[0]:
        for nm, pr, dur, desc, srt in [
            ("বেসিক — ১ টাকা",  1.0,  10,  "১০ মিনিটের ইন্টারনেট প্যাকেজ", 1),
            ("স্ট্যান্ডার্ড — ২ টাকা", 2.0, 30, "৩০ মিনিটের ইন্টারনেট প্যাকেজ", 2),
            ("প্রিমিয়াম — ৫ টাকা", 5.0, 60,  "১ ঘণ্টার আনলিমিটেড প্যাকেজ",   3),
        ]:
            c.execute("INSERT INTO packages(name,price,duration_minutes,description,sort_order) VALUES(?,?,?,?,?)",
                      (nm, pr, dur, desc, srt))

    # Default payment methods
    if not c.execute("SELECT COUNT(*) FROM payment_methods").fetchone()[0]:
        c.execute("INSERT INTO payment_methods(method,number,account_name) VALUES(?,?,?)",
                  ("bkash",  "01XXXXXXXXX", "অ্যাডমিন"))
        c.execute("INSERT INTO payment_methods(method,number,account_name) VALUES(?,?,?)",
                  ("nagad",  "01XXXXXXXXX", "অ্যাডমিন"))

    conn.commit(); conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM site_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def client_ip():
    xff = request.headers.get("X-Forwarded-For")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "127.0.0.1")

def is_authenticated(ip):
    conn = get_db()
    row = conn.execute("SELECT id,expires_at FROM active_sessions WHERE client_ip=?", (ip,)).fetchone()
    conn.close()
    if not row:
        return False
    if row["expires_at"]:
        try:
            if datetime.now() > datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S"):
                conn2 = get_db()
                conn2.execute("DELETE FROM active_sessions WHERE client_ip=?", (ip,))
                conn2.commit(); conn2.close()
                _revoke(ip)
                return False
        except Exception:
            pass
    return True

def _allow(ip):
    if os.name != "nt":
        for cmd in [
            ["iptables", "-I", "FORWARD", "-s", ip, "-j", "ACCEPT"],
            ["iptables", "-I", "FORWARD", "-d", ip, "-j", "ACCEPT"],
            ["iptables", "-t","nat","-I","PREROUTING","-s",ip,"-j","ACCEPT"],
        ]:
            subprocess.run(cmd, capture_output=True)

def _revoke(ip):
    if os.name != "nt":
        for cmd in [
            ["iptables", "-D", "FORWARD", "-s", ip, "-j", "ACCEPT"],
            ["iptables", "-D", "FORWARD", "-d", ip, "-j", "ACCEPT"],
            ["iptables", "-t","nat","-D","PREROUTING","-s",ip,"-j","ACCEPT"],
        ]:
            subprocess.run(cmd, capture_output=True)

def gen_order_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def make_voucher(conn, order_id):
    for _ in range(200):
        pin = str(random.randint(1000, 9999))
        try:
            conn.execute("INSERT INTO vouchers(pin,source,order_id) VALUES(?,?,?)",
                         (pin, "payment", order_id))
            conn.commit()
            return pin
        except sqlite3.IntegrityError:
            continue
    return None

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("admin_logged_in"):
            flash("অনুগ্রহ করে লগইন করুন।", "danger")
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return w

def pending_counts():
    conn = get_db()
    pm = conn.execute("SELECT COUNT(*) FROM payment_orders WHERE status='pending'").fetchone()[0]
    um = conn.execute("SELECT COUNT(*) FROM messages WHERE is_read=0").fetchone()[0]
    conn.close()
    return pm, um

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
def base_css(primary="#007bff"):
    return f"""
:root{{--p:{primary};--dark:#1b263b;--surface:#fff;--success:#28a745;
--danger:#dc3545;--warning:#ffc107;--border:#e2e8f0;--text:#2d3748;
--muted:#718096;--r:12px;--sh:0 8px 24px -4px rgba(0,0,0,.12)}}
*{{margin:0;padding:0;box-sizing:border-box;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}
body{{background:#f4f6f9;color:var(--text);min-height:100vh}}
a{{color:var(--p);text-decoration:none}}
.navbar{{background:var(--dark);color:#fff;padding:12px 22px;
  display:flex;justify-content:space-between;align-items:center;
  box-shadow:0 2px 8px rgba(0,0,0,.2);flex-wrap:wrap;gap:8px}}
.brand{{font-size:1.1rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:7px}}
.nav-links{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.nav-link{{color:#cbd5e0;font-size:.83rem;padding:5px 10px;border-radius:6px;transition:.2s;position:relative}}
.nav-link:hover,.nav-link.active{{color:#fff;background:rgba(255,255,255,.12)}}
.nav-badge{{background:var(--danger);color:#fff;font-size:.65rem;font-weight:700;
  padding:2px 5px;border-radius:10px;position:absolute;top:-4px;right:-4px}}
.btn-logout{{background:var(--danger);color:#fff;padding:5px 12px;
  border-radius:6px;font-size:.82rem;font-weight:600}}
.container{{max-width:1100px;margin:26px auto;padding:0 16px;width:100%}}
.card{{background:#fff;border-radius:var(--r);padding:22px;
  box-shadow:var(--sh);border:1px solid var(--border);margin-bottom:20px}}
.card h3{{margin-bottom:13px;font-size:1rem;color:var(--dark)}}
.form-group{{margin-bottom:15px}}
label{{display:block;margin-bottom:5px;font-size:.86rem;font-weight:600}}
.form-control{{width:100%;padding:10px 14px;border:1.5px solid var(--border);
  border-radius:8px;font-size:.95rem;outline:none;transition:.2s;background:#fff}}
.form-control:focus{{border-color:var(--p);box-shadow:0 0 0 3px rgba(0,123,255,.15)}}
.btn{{display:inline-block;padding:10px 18px;font-size:.9rem;font-weight:600;
  border-radius:8px;cursor:pointer;border:none;text-align:center;transition:.2s;line-height:1.4}}
.btn-primary{{background:var(--p);color:#fff}}.btn-primary:hover{{opacity:.9}}
.btn-success{{background:var(--success);color:#fff}}.btn-success:hover{{opacity:.9}}
.btn-danger{{background:var(--danger);color:#fff}}.btn-danger:hover{{opacity:.9}}
.btn-warning{{background:var(--warning);color:#333}}
.btn-secondary{{background:#6c757d;color:#fff}}
.btn-info{{background:#17a2b8;color:#fff}}
.btn-block{{width:100%}}.btn-sm{{padding:5px 10px;font-size:.78rem}}
.alert{{padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:.87rem}}
.alert-success{{background:#d4edda;color:#155724;border:1px solid #c3e6cb}}
.alert-danger{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}}
.alert-warning{{background:#fff3cd;color:#856404;border:1px solid #ffeeba}}
.alert-info{{background:#d1ecf1;color:#0c5460;border:1px solid #bee5eb}}
.badge{{display:inline-block;padding:3px 9px;border-radius:20px;
  font-size:.7rem;font-weight:700;text-transform:uppercase}}
.badge-success{{background:var(--success);color:#fff}}
.badge-danger{{background:var(--danger);color:#fff}}
.badge-warning{{background:var(--warning);color:#333}}
.badge-secondary{{background:#6c757d;color:#fff}}
.badge-primary{{background:var(--p);color:#fff}}
.badge-info{{background:#17a2b8;color:#fff}}
.table-responsive{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px 13px;text-align:left;border-bottom:1px solid var(--border);font-size:.86rem}}
th{{background:#f8fafc;color:var(--muted);font-weight:600}}
tr:hover td{{background:#f8fafc}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:20px}}
.stat-box{{background:#fff;border-radius:var(--r);padding:16px;
  border:1px solid var(--border);box-shadow:0 2px 6px rgba(0,0,0,.04);border-left:5px solid var(--p)}}
.stat-box.green{{border-left-color:var(--success)}}.stat-box.orange{{border-left-color:var(--warning)}}
.stat-box.red{{border-left-color:var(--danger)}}.stat-box.purple{{border-left-color:#6f42c1}}
.stat-box h3{{font-size:1.65rem;margin-bottom:3px;color:var(--dark)}}
.stat-box p{{font-size:.79rem;color:var(--muted);font-weight:500}}
.voucher-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:11px;margin-top:12px}}
.voucher-card{{border:2px dashed var(--p);background:#f0f7ff;padding:12px;border-radius:8px;text-align:center}}
.voucher-card .pin{{font-size:1.5rem;font-weight:800;letter-spacing:5px;color:var(--dark);margin:5px 0}}
pre.terminal{{background:#0d1117;color:#3fb950;padding:13px;border-radius:8px;
  font-family:monospace;font-size:.82rem;overflow-x:auto;line-height:1.6;margin:7px 0}}
.pkg-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin:18px 0}}
.pkg-card{{background:#fff;border:2px solid var(--border);border-radius:14px;
  padding:22px 18px;text-align:center;cursor:pointer;transition:.25s;position:relative}}
.pkg-card:hover{{border-color:var(--p);transform:translateY(-3px);box-shadow:0 12px 28px rgba(0,0,0,.12)}}
.pkg-card.popular{{border-color:var(--p)}}
.pkg-price{{font-size:2rem;font-weight:800;color:var(--p);margin:10px 0 5px}}
.pkg-dur{{font-size:.88rem;color:var(--muted);margin-bottom:12px}}
.pkg-badge{{position:absolute;top:-10px;right:14px;background:var(--p);
  color:#fff;padding:3px 10px;border-radius:20px;font-size:.72rem;font-weight:700}}
.pay-method-btn{{display:flex;align-items:center;gap:12px;padding:14px 16px;
  border:2px solid var(--border);border-radius:10px;cursor:pointer;margin-bottom:10px;
  transition:.2s;background:#fff}}
.pay-method-btn:hover,.pay-method-btn.selected{{border-color:var(--p);background:#f0f7ff}}
.pay-method-btn .icon{{font-size:1.6rem}}
.pay-method-btn .info{{text-align:left}}
.pay-method-btn .info strong{{display:block;font-size:.95rem}}
.pay-method-btn .info small{{color:var(--muted);font-size:.8rem}}
.order-status-box{{text-align:center;padding:30px 20px}}
.order-status-box .status-icon{{font-size:52px;margin-bottom:12px}}
.timer-box{{background:linear-gradient(135deg,#0d1b2a,#1b263b);color:#fff;
  border-radius:12px;padding:16px;text-align:center;margin:16px 0}}
.timer-box .time{{font-size:2rem;font-weight:800;color:#4ade80;font-family:monospace}}
.msg-bubble{{background:#f0f7ff;border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;margin-bottom:10px;font-size:.88rem}}
.msg-bubble.reply{{background:#f0fff4;border-color:#c3e6cb;margin-left:20px}}
@media(max-width:600px){{
  .navbar{{flex-direction:column;text-align:center}}
  .pkg-cards{{grid-template-columns:1fr}}
}}"""

# ─────────────────────────────────────────────────────────────────────────────
# Admin Base & Renderer
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_BASE = """<!DOCTYPE html>
<html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} — Hotspot Admin</title>
<style>{{ css|safe }}</style></head><body>
<nav class="navbar">
  <a href="{{ url_for('admin_dashboard') }}" class="brand">📡 {{ s.hotspot_name }}</a>
  <div class="nav-links">
    <a href="{{ url_for('admin_dashboard') }}"       class="nav-link {{'active' if ap=='dash'}}">📊 ড্যাশবোর্ড</a>
    <a href="{{ url_for('admin_orders') }}"          class="nav-link {{'active' if ap=='orders'}}">
      💳 অর্ডার{% if po %}<span class="nav-badge">{{po}}</span>{% endif %}</a>
    <a href="{{ url_for('admin_packages') }}"        class="nav-link {{'active' if ap=='pkgs'}}">📦 প্যাকেজ</a>
    <a href="{{ url_for('admin_payment_methods') }}" class="nav-link {{'active' if ap=='pay'}}">💰 পেমেন্ট</a>
    <a href="{{ url_for('admin_vouchers') }}"        class="nav-link {{'active' if ap=='vchr'}}">🎟️ ভাউচার</a>
    <a href="{{ url_for('admin_messages') }}"        class="nav-link {{'active' if ap=='msg'}}">
      💬 বার্তা{% if um %}<span class="nav-badge">{{um}}</span>{% endif %}</a>
    <a href="{{ url_for('admin_site_settings') }}"   class="nav-link {{'active' if ap=='site'}}">🎨 সাইট</a>
    <a href="{{ url_for('admin_settings') }}"        class="nav-link {{'active' if ap=='cfg'}}">⚙️ সেটিং</a>
    <a href="{{ url_for('admin_guide') }}"           class="nav-link {{'active' if ap=='guide'}}">📱 গাইড</a>
    <a href="{{ url_for('admin_logout') }}" class="btn-logout">লগআউট</a>
  </div>
</nav>
<div class="container">
  {% with msgs=get_flashed_messages(with_categories=true) %}
    {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
  {% endwith %}
  {{ page_content|safe }}
</div></body></html>"""

def render_admin(title, ap, html):
    s = get_settings()
    po, um = pending_counts()
    return render_template_string(ADMIN_BASE,
        title=title, ap=ap, s=s, css=base_css(s.get("primary_color","#007bff")),
        page_content=html, po=po, um=um)

# ─────────────────────────────────────────────────────────────────────────────
# ══  USER TEMPLATES  ══
# ─────────────────────────────────────────────────────────────────────────────
PACKAGES_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{{ s.site_name }}</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;align-items:flex-start;
  justify-content:center;padding:24px 16px;min-height:100vh}
.portal-wrap{width:100%;max-width:520px}
.portal-head{background:{{ s.primary_color }};border-radius:16px 16px 0 0;
  padding:26px 20px;color:#fff;text-align:center}
.portal-head .icon{font-size:40px;margin-bottom:7px}
.portal-head h2{font-size:1.3rem;font-weight:700}
.portal-head p{font-size:.82rem;opacity:.9;margin-top:3px}
.portal-body{background:#fff;border-radius:0 0 16px 16px;padding:22px 18px}
.section-title{font-size:.9rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;margin-bottom:12px}
.voucher-link{display:block;text-align:center;margin-top:16px;padding:12px;
  background:#f8fafc;border:1.5px dashed var(--border);border-radius:8px;
  font-size:.85rem;color:var(--muted);transition:.2s}
.voucher-link:hover{border-color:var(--p);color:var(--p);background:#f0f7ff}
.contact-link{display:flex;align-items:center;justify-content:center;gap:8px;
  margin-top:10px;padding:10px;background:#fff3cd;border:1px solid #ffeeba;
  border-radius:8px;font-size:.83rem;color:#856404;text-decoration:none}
</style></head><body>
<div class="portal-wrap">
  <div class="portal-head">
    <div class="icon">📶</div>
    <h2>{{ s.site_name }}</h2>
    <p>{{ s.site_subtitle }}</p>
  </div>
  <div class="portal-body">
    {% with msgs=get_flashed_messages(with_categories=true) %}
      {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
    {% endwith %}
    <div class="section-title">একটি প্যাকেজ বেছে নিন</div>
    <div class="pkg-cards">
      {% for pkg in packages %}
      <a href="{{ url_for('order_page', pkg_id=pkg.id) }}" style="text-decoration:none">
        <div class="pkg-card {% if loop.index==2 %}popular{% endif %}">
          {% if loop.index==2 %}<div class="pkg-badge">জনপ্রিয়</div>{% endif %}
          <div style="font-size:1.05rem;font-weight:700;color:var(--dark)">{{ pkg.name }}</div>
          <div class="pkg-price">৳{{ "%.0f"|format(pkg.price) }}</div>
          <div class="pkg-dur">⏱ {{ pkg.duration_minutes }} মিনিট</div>
          <div style="font-size:.8rem;color:var(--muted);margin-bottom:14px">{{ pkg.description }}</div>
          <button class="btn btn-primary btn-block" style="background:{{ s.primary_color }}">
            এই প্ল্যান নিন →
          </button>
        </div>
      </a>
      {% else %}
      <div class="alert alert-warning">কোনো প্যাকেজ পাওয়া যায়নি।</div>
      {% endfor %}
    </div>
    <a href="{{ url_for('voucher_page') }}" class="voucher-link">
      🎟️ আমার কাছে ভাউচার কোড আছে — সরাসরি কানেক্ট করুন
    </a>
    <a href="{{ url_for('contact_page') }}" class="contact-link">
      💬 অ্যাডমিনের সাথে যোগাযোগ করুন
    </a>
    <p style="text-align:center;font-size:.75rem;color:var(--muted);margin-top:14px">{{ s.footer_text }}</p>
  </div>
</div></body></html>"""

PAYMENT_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>পেমেন্ট — {{ s.site_name }}</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;
  align-items:flex-start;justify-content:center;padding:24px 16px;min-height:100vh}
.wrap{width:100%;max-width:480px;background:#fff;border-radius:16px;
  box-shadow:0 20px 40px rgba(0,0,0,.3);overflow:hidden}
.pay-head{background:{{ s.primary_color }};padding:18px 20px;color:#fff}
.pay-head h3{font-size:1.1rem;font-weight:700}
.pay-head .pkg-summary{background:rgba(255,255,255,.2);border-radius:8px;
  padding:10px 14px;margin-top:12px;display:flex;justify-content:space-between}
.pay-body{padding:20px 18px}
.method-label{font-size:.86rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.pay-num-box{background:#f8fafc;border:1.5px solid var(--border);
  border-radius:10px;padding:14px;margin-bottom:14px;font-size:1.5rem;
  font-weight:800;letter-spacing:3px;text-align:center;color:var(--dark)}
.step-box{background:#fff8e1;border:1px solid #ffd54f;border-radius:8px;
  padding:12px;font-size:.83rem;line-height:1.7;margin-bottom:14px}
</style></head><body>
<div class="wrap">
  <div class="pay-head">
    <a href="{{ url_for('portal_index') }}" style="color:rgba(255,255,255,.8);font-size:.82rem">← পিছনে যান</a>
    <h3 style="margin-top:6px">💳 পেমেন্ট করুন</h3>
    <div class="pkg-summary">
      <span>{{ pkg.name }}</span>
      <strong>৳{{ "%.0f"|format(pkg.price) }} / {{ pkg.duration_minutes }}মিনিট</strong>
    </div>
  </div>
  <div class="pay-body">
    {% with msgs=get_flashed_messages(with_categories=true) %}
      {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
    {% endwith %}

    {% for m in methods %}
    <div class="method-label">
      {% if m.method=='bkash' %}🔴 বিকাশ নম্বর{% elif m.method=='nagad' %}🟠 নগদ নম্বর{% else %}💳 {{ m.method }}{% endif %}
    </div>
    <div class="pay-num-box">{{ m.number }}</div>
    <p style="font-size:.8rem;color:var(--muted);margin-bottom:14px">অ্যাকাউন্ট: <strong>{{ m.account_name }}</strong></p>
    {% endfor %}

    <div class="step-box">
      📋 <strong>পেমেন্টের ধাপ:</strong><br>
      ১. উপরের নম্বরে <strong>৳{{ "%.0f"|format(pkg.price) }}</strong> Send Money করুন<br>
      ২. পেমেন্ট সফল হলে Transaction ID পাবেন<br>
      ৩. নিচের ফর্মে Transaction ID টি দিন<br>
      ৪. অ্যাডমিন ভেরিফাই করলে আপনার ভাউচার কোড দেওয়া হবে
    </div>

    <form method="POST" action="{{ url_for('submit_order') }}">
      <input type="hidden" name="package_id" value="{{ pkg.id }}">
      <div class="form-group">
        <label>আপনার নাম (ঐচ্ছিক)</label>
        <input name="client_name" class="form-control" placeholder="আপনার নাম লিখুন">
      </div>
      <div class="form-group">
        <label>পেমেন্ট পদ্ধতি</label>
        <select name="payment_method" class="form-control" required>
          {% for m in methods %}
          <option value="{{ m.method }}">
            {% if m.method=='bkash' %}🔴 বিকাশ{% elif m.method=='nagad' %}🟠 নগদ{% else %}{{ m.method }}{% endif %}
            — {{ m.number }}
          </option>
          {% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label>ট্রানজেকশন আইডি (TxnID / Reference)</label>
        <input name="transaction_id" class="form-control"
               placeholder="যেমন: 8H4XJ2P9LM" required>
        <small style="color:var(--muted);font-size:.78rem">
          বিকাশ/নগদ SMS-এ পাওয়া Transaction ID বা Reference নম্বর
        </small>
      </div>
      <button type="submit" class="btn btn-success btn-block" style="padding:13px;font-size:1rem">
        ✅ পেমেন্ট সাবমিট করুন
      </button>
    </form>
  </div>
</div></body></html>"""

ORDER_STATUS_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>অর্ডার স্ট্যাটাস</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;
  align-items:center;justify-content:center;padding:24px 16px;min-height:100vh}
.card{max-width:440px;width:100%;text-align:center}
.order-id-box{background:#f8fafc;border:1.5px dashed var(--border);
  border-radius:8px;padding:10px;font-family:monospace;font-size:1.1rem;
  font-weight:700;letter-spacing:3px;color:var(--dark);margin:14px 0}
.pin-big{font-size:2.5rem;font-weight:900;letter-spacing:8px;
  color:var(--success);background:#d4edda;padding:14px 20px;
  border-radius:12px;border:2px solid #c3e6cb;display:inline-block;
  margin:14px 0}
.info-row{display:flex;justify-content:space-between;align-items:center;
  padding:9px 0;border-bottom:1px solid var(--border);font-size:.85rem}
.info-row:last-child{border:none}
.spinner{width:40px;height:40px;border:4px solid #e2e8f0;
  border-top-color:var(--p);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head><body>
<div class="card">
  <div class="order-status-box">
    {% if order.status == 'pending' %}
      <div class="spinner"></div>
      <h2 style="color:var(--warning)">⏳ পেমেন্ট যাচাই হচ্ছে…</h2>
      <p style="color:var(--muted);font-size:.88rem;margin-top:8px">
        অ্যাডমিন আপনার পেমেন্ট ভেরিফাই করছেন। কিছুক্ষণ অপেক্ষা করুন।
      </p>
    {% elif order.status == 'verified' %}
      <div style="font-size:52px">🎉</div>
      <h2 style="color:var(--success);margin-top:8px">পেমেন্ট অনুমোদিত!</h2>
      <p style="color:var(--muted);font-size:.88rem;margin:6px 0 4px">আপনার ভাউচার কোড:</p>
      <div class="pin-big">{{ order.voucher_pin }}</div>
      <p style="font-size:.82rem;color:var(--muted);margin-bottom:14px">
        এই কোডটি সেভ করুন — পরেও ব্যবহার করতে পারবেন।
      </p>
      <form method="POST" action="{{ url_for('login') }}">
        <input type="hidden" name="pin" value="{{ order.voucher_pin }}">
        <button type="submit" class="btn btn-success btn-block" style="padding:13px;font-size:1.05rem">
          🚀 এখনই কানেক্ট করুন
        </button>
      </form>
    {% elif order.status == 'rejected' %}
      <div style="font-size:52px">❌</div>
      <h2 style="color:var(--danger);margin-top:8px">পেমেন্ট প্রত্যাখ্যাত</h2>
      {% if order.notes %}
      <div class="alert alert-danger" style="margin-top:12px;text-align:left">
        কারণ: {{ order.notes }}
      </div>
      {% endif %}
      <a href="{{ url_for('portal_index') }}" class="btn btn-primary btn-block" style="margin-top:14px">
        পুনরায় চেষ্টা করুন
      </a>
    {% endif %}

    <div style="margin-top:20px;border-top:1px solid var(--border);padding-top:14px">
      <div class="info-row"><span>অর্ডার আইডি</span><strong>{{ order.order_id }}</strong></div>
      <div class="info-row"><span>প্যাকেজ</span><span>{{ order.pkg_name }}</span></div>
      <div class="info-row"><span>পরিমাণ</span><span>৳{{ "%.0f"|format(order.amount) }}</span></div>
      <div class="info-row"><span>পেমেন্ট</span><span>{{ order.payment_method }}</span></div>
      <div class="info-row"><span>TxnID</span><span style="font-family:monospace">{{ order.transaction_id }}</span></div>
    </div>
  </div>
  <div style="margin-top:10px;display:flex;gap:10px">
    <a href="{{ url_for('portal_index') }}" class="btn btn-secondary btn-sm" style="flex:1">← পিছনে</a>
    <a href="{{ url_for('contact_page') }}" class="btn btn-warning btn-sm" style="flex:1">💬 সাহায্য</a>
  </div>
</div>
<script>
  {% if order.status == 'pending' %}
  setTimeout(()=>location.reload(), 6000);
  {% endif %}
</script>
</body></html>"""

VOUCHER_PAGE_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ভাউচার কোড — {{ s.site_name }}</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;
  align-items:center;justify-content:center;padding:24px 16px;min-height:100vh}
.card{max-width:400px;width:100%;text-align:center}
.pin-input{letter-spacing:12px;font-size:1.9rem;text-align:center;
  font-weight:800;height:60px;border:2px solid var(--border);
  border-radius:10px;color:var(--dark)}
.pin-input:focus{border-color:var(--p)}
</style></head><body>
<div class="card">
  <div style="font-size:44px;margin-bottom:12px">🎟️</div>
  <h2 style="color:#fff;margin-bottom:6px">ভাউচার কোড দিন</h2>
  <p style="color:#94a3b8;font-size:.86rem;margin-bottom:18px">
    অ্যাডমিনের দেওয়া বা পেমেন্টের মাধ্যমে পাওয়া ৪-ডিজিট কোড
  </p>
  {% with msgs=get_flashed_messages(with_categories=true) %}
    {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
  {% endwith %}
  <form method="POST" action="{{ url_for('login') }}">
    <div class="form-group">
      <input name="pin" class="form-control pin-input"
             placeholder="••••" maxlength="4" inputmode="numeric"
             pattern="[0-9]{4}" required autofocus>
    </div>
    <button type="submit" class="btn btn-primary btn-block" style="padding:13px;font-size:1.05rem;background:{{ s.primary_color }}">
      🚀 কানেক্ট করুন
    </button>
  </form>
  <a href="{{ url_for('portal_index') }}" style="display:block;margin-top:14px;color:#94a3b8;font-size:.82rem">
    ← প্যাকেজ তালিকায় ফিরুন
  </a>
</div></body></html>"""

STATUS_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>কানেক্টেড — {{ s.site_name }}</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;
  align-items:center;justify-content:center;padding:24px 16px;min-height:100vh}
.card{max-width:440px;width:100%;text-align:center}
.check{font-size:52px;color:var(--success);margin-bottom:10px}
.info-tbl{margin:16px 0;background:#f8fafc;border-radius:8px;border:1px solid var(--border)}
.info-tbl td{padding:9px 13px;font-size:.85rem}
.info-tbl td:first-child{color:var(--muted);font-weight:500}
.info-tbl td:last-child{text-align:right;font-weight:600}
.expired-banner{background:var(--danger);color:#fff;padding:10px;border-radius:8px;margin-top:10px}
</style></head><body>
<div class="card">
  <div class="check">✓</div>
  <h2 style="color:var(--success);margin-bottom:5px">ইন্টারনেট চালু!</h2>
  <p style="color:#94a3b8;font-size:.88rem">আপনি সফলভাবে কানেক্টেড।</p>

  {% if sess.expires_at %}
  <div class="timer-box">
    <div style="font-size:.82rem;opacity:.8;margin-bottom:4px">⏱ সময় বাকি</div>
    <div class="time" id="timer">লোড হচ্ছে…</div>
  </div>
  {% endif %}

  <table class="info-tbl">
    <tr><td>IP Address</td><td>{{ sess.client_ip }}</td></tr>
    <tr><td>Voucher PIN</td><td>{{ sess.pin }}</td></tr>
    <tr><td>লগইন সময়</td><td>{{ sess.login_time }}</td></tr>
    {% if sess.expires_at %}
    <tr><td>মেয়াদ শেষ</td><td id="exp-text">{{ sess.expires_at }}</td></tr>
    {% else %}
    <tr><td>মেয়াদ</td><td><span class="badge badge-success">আনলিমিটেড</span></td></tr>
    {% endif %}
    <tr><td>স্ট্যাটাস</td><td><span class="badge badge-success">ONLINE</span></td></tr>
  </table>

  <div style="display:flex;gap:10px">
    <a href="https://www.google.com" class="btn btn-primary" style="flex:1">🌐 Browse</a>
    <form method="POST" action="{{ url_for('user_logout') }}" style="flex:1">
      <button class="btn btn-danger btn-block">ডিসকানেক্ট</button>
    </form>
  </div>
</div>
<script>
const expiresAt = "{{ sess.expires_at or '' }}";
if(expiresAt){
  function tick(){
    const diff=new Date(expiresAt.replace(' ','T'))-new Date();
    if(diff<=0){
      document.getElementById('timer').innerHTML='<span style="color:#f87171">মেয়াদ শেষ!</span>';
      setTimeout(()=>location.href='/',3000); return;
    }
    const h=Math.floor(diff/3600000),m=Math.floor(diff%3600000/60000),s=Math.floor(diff%60000/1000);
    document.getElementById('timer').textContent=(h?h+'ঘ ':'')+m+'মি '+s+'সে';
    setTimeout(tick,1000);
  }
  tick();
}
</script></body></html>"""

CONTACT_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>যোগাযোগ — {{ s.site_name }}</title><style>{{ css|safe }}
body{background:linear-gradient(135deg,#0d1b2a,#1b263b);display:flex;
  align-items:flex-start;justify-content:center;padding:24px 16px;min-height:100vh}
.card{max-width:480px;width:100%}
</style></head><body>
<div class="card">
  <div style="text-align:center;margin-bottom:16px">
    <div style="font-size:40px">💬</div>
    <h2 style="color:#fff;margin-top:8px">অ্যাডমিনের সাথে যোগাযোগ</h2>
    <p style="color:#94a3b8;font-size:.83rem">আপনার সমস্যা লিখুন, অ্যাডমিন উত্তর দেবেন।</p>
  </div>
  {% with msgs=get_flashed_messages(with_categories=true) %}
    {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
  {% endwith %}

  {% for msg in prev_msgs %}
  <div class="msg-bubble">
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px">
      👤 <strong>{{ msg.sender_name }}</strong> — {{ msg.created_at }}
    </div>
    <div>{{ msg.message }}</div>
  </div>
  {% if msg.reply %}
  <div class="msg-bubble reply">
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px">
      🔧 <strong>অ্যাডমিন</strong> — {{ msg.replied_at or '' }}
    </div>
    <div>{{ msg.reply }}</div>
  </div>
  {% endif %}
  {% endfor %}

  <div class="card" style="margin-top:10px">
    <h3>নতুন বার্তা পাঠান</h3>
    <form method="POST">
      <div class="form-group">
        <label>আপনার নাম</label>
        <input name="sender_name" class="form-control" placeholder="নাম লিখুন" required>
      </div>
      <div class="form-group">
        <label>সমস্যা বা বার্তা</label>
        <textarea name="message" class="form-control" rows="4"
                  placeholder="আপনার সমস্যা বা প্রশ্ন লিখুন..." required></textarea>
      </div>
      <button type="submit" class="btn btn-primary btn-block">📤 বার্তা পাঠান</button>
    </form>
  </div>
  <a href="{{ url_for('portal_index') }}" style="display:block;text-align:center;
     margin-top:12px;color:#94a3b8;font-size:.82rem">← পিছনে যান</a>
</div></body></html>"""

ADMIN_LOGIN_TMPL = """<!DOCTYPE html><html lang="bn"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title><style>{{ css|safe }}
body{background:#0f172a;display:flex;align-items:center;justify-content:center;padding:20px}
.box{background:#fff;border-radius:14px;padding:28px;width:100%;max-width:370px;
  box-shadow:0 12px 30px rgba(0,0,0,.3)}
.box h3{text-align:center;margin-bottom:18px;color:#0f172a}
</style></head><body>
<div class="box">
  <h3>🔐 অ্যাডমিন লগইন</h3>
  {% with msgs=get_flashed_messages(with_categories=true) %}
    {% for cat,msg in msgs %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
  {% endwith %}
  <form method="POST">
    <div class="form-group">
      <label>ইউজারনেম</label>
      <input name="username" class="form-control" placeholder="admin" required autofocus>
    </div>
    <div class="form-group">
      <label>পাসওয়ার্ড</label>
      <input type="password" name="password" class="form-control" placeholder="admin" required>
    </div>
    <button type="submit" class="btn btn-primary btn-block" style="margin-top:8px">লগইন করুন</button>
  </form>
  <div style="text-align:center;margin-top:13px">
    <a href="{{ url_for('portal_index') }}" style="font-size:.82rem;color:#64748b">← পোর্টালে ফিরুন</a>
  </div>
</div></body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# ══  ADMIN CONTENT TEMPLATES  ══
# ─────────────────────────────────────────────────────────────────────────────
DASH_CONTENT = """
<div class="stats-grid">
  <div class="stat-box"><h3>{{ st.total_pins }}</h3><p>মোট ভাউচার পিন</p></div>
  <div class="stat-box green"><h3>{{ st.active_pins }}</h3><p>অ্যাক্টিভ পিন</p></div>
  <div class="stat-box orange"><h3>{{ st.pending_orders }}</h3><p>পেন্ডিং পেমেন্ট</p></div>
  <div class="stat-box red"><h3>{{ st.online }}</h3><p>এখন অনলাইন</p></div>
  <div class="stat-box purple"><h3>{{ st.total_orders }}</h3><p>মোট পেমেন্ট অর্ডার</p></div>
</div>

<div class="card">
  <h3>⚡ ম্যানুয়াল ভাউচার পিন তৈরি করুন</h3>
  <form method="POST" action="{{ url_for('admin_generate_pin') }}"
        style="display:flex;gap:13px;flex-wrap:wrap;align-items:flex-end">
    <div style="flex:1;min-width:150px">
      <label>পিন সংখ্যা</label>
      <select name="count" class="form-control">
        <option value="1">১টি</option><option value="5" selected>৫টি</option>
        <option value="10">১০টি</option><option value="20">২০টি</option>
      </select>
    </div>
    <div style="flex:1;min-width:150px">
      <label>কাস্টম পিন (ঐচ্ছিক)</label>
      <input name="custom_pin" class="form-control" placeholder="যেমন: 5566" maxlength="4" pattern="[0-9]{4}">
    </div>
    <div><button type="submit" class="btn btn-success" style="height:44px;padding:0 20px">+ তৈরি করুন</button></div>
  </form>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:13px">
    <h3>🟢 এখন কানেক্টেড ডিভাইস</h3>
    <span class="badge badge-primary">{{ sessions|length }} টি</span>
  </div>
  <div class="table-responsive"><table>
    <thead><tr><th>IP</th><th>পিন</th><th>প্যাকেজ</th><th>মেয়াদ শেষ</th><th>Action</th></tr></thead>
    <tbody>
    {% for u in sessions %}
    <tr>
      <td><strong>{{ u.client_ip }}</strong></td>
      <td><span class="badge badge-success">{{ u.pin }}</span></td>
      <td>{{ u.pkg_name or 'ম্যানুয়াল' }}</td>
      <td>
        {% if u.expires_at %}
          {% if u.expires_at < now %}
            <span class="badge badge-danger">EXPIRED</span>
          {% else %}
            {{ u.expires_at }}
          {% endif %}
        {% else %}<span class="badge badge-info">আনলিমিটেড</span>{% endif %}
      </td>
      <td>
        <form method="POST" action="{{ url_for('admin_kick_user') }}" style="display:inline">
          <input type="hidden" name="client_ip" value="{{ u.client_ip }}">
          <button class="btn btn-danger btn-sm" onclick="return confirm('Kick?')">Kick</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5" style="text-align:center;color:var(--muted);padding:18px">কোনো সেশন নেই।</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>"""

ORDERS_CONTENT = """
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;flex-wrap:wrap;gap:8px">
    <h3>💳 পেমেন্ট অর্ডার ম্যানেজমেন্ট</h3>
    <div style="display:flex;gap:8px">
      <a href="?status=pending" class="btn btn-warning btn-sm">পেন্ডিং</a>
      <a href="?status=verified" class="btn btn-success btn-sm">অনুমোদিত</a>
      <a href="?status=rejected" class="btn btn-danger btn-sm">প্রত্যাখ্যাত</a>
      <a href="?" class="btn btn-secondary btn-sm">সব</a>
    </div>
  </div>
  <div class="table-responsive"><table>
    <thead><tr><th>অর্ডার ID</th><th>নাম/IP</th><th>প্যাকেজ</th><th>পরিমাণ</th>
      <th>পেমেন্ট</th><th>TxnID</th><th>স্ট্যাটাস</th><th>সময়</th><th>Action</th></tr></thead>
    <tbody>
    {% for o in orders %}
    <tr>
      <td><code>{{ o.order_id }}</code></td>
      <td><small>{{ o.client_name or '—' }}<br><span style="color:var(--muted)">{{ o.client_ip }}</span></small></td>
      <td style="font-size:.82rem">{{ o.pkg_name }}</td>
      <td>৳{{ "%.0f"|format(o.amount) }}</td>
      <td>
        {% if o.payment_method=='bkash' %}🔴{% elif o.payment_method=='nagad' %}🟠{% endif %}
        {{ o.payment_method }}
      </td>
      <td><code style="font-size:.78rem">{{ o.transaction_id }}</code></td>
      <td>
        {% if o.status=='pending' %}<span class="badge badge-warning">PENDING</span>
        {% elif o.status=='verified' %}<span class="badge badge-success">OK</span>
        {% elif o.status=='rejected' %}<span class="badge badge-danger">REJECTED</span>
        {% endif %}
        {% if o.voucher_pin %}<br><strong>PIN: {{ o.voucher_pin }}</strong>{% endif %}
      </td>
      <td style="font-size:.78rem">{{ o.created_at }}</td>
      <td>
        {% if o.status=='pending' %}
        <form method="POST" action="{{ url_for('admin_approve_order', order_id=o.order_id) }}" style="display:inline;margin-bottom:4px">
          <button class="btn btn-success btn-sm">✓ অনুমোদন</button>
        </form>
        <form method="POST" action="{{ url_for('admin_reject_order', order_id=o.order_id) }}" style="display:inline">
          <input type="hidden" name="notes" value="পেমেন্ট যাচাই করা যায়নি।">
          <button class="btn btn-danger btn-sm" onclick="return confirm('প্রত্যাখ্যান করবেন?')">✗ প্রত্যাখ্যান</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="9" style="text-align:center;color:var(--muted);padding:18px">কোনো অর্ডার নেই।</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>"""

PACKAGES_CONTENT = """
<div class="card">
  <h3>➕ নতুন প্যাকেজ যোগ করুন</h3>
  <form method="POST" action="{{ url_for('admin_add_package') }}"
        style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
    <div style="flex:2;min-width:160px">
      <label>প্যাকেজ নাম</label>
      <input name="name" class="form-control" placeholder="যেমন: ১ টাকা - ১০ মিনিট" required>
    </div>
    <div style="flex:1;min-width:100px">
      <label>মূল্য (টাকা)</label>
      <input name="price" type="number" step="0.01" class="form-control" placeholder="1.00" required>
    </div>
    <div style="flex:1;min-width:100px">
      <label>সময় (মিনিট)</label>
      <input name="duration_minutes" type="number" class="form-control" placeholder="10" required>
    </div>
    <div style="flex:2;min-width:180px">
      <label>বিবরণ</label>
      <input name="description" class="form-control" placeholder="সংক্ষিপ্ত বিবরণ">
    </div>
    <div><button type="submit" class="btn btn-success" style="height:44px;padding:0 18px">+ যোগ করুন</button></div>
  </form>
</div>
<div class="card">
  <h3>📦 সব প্যাকেজ</h3>
  <div class="table-responsive"><table>
    <thead><tr><th>নাম</th><th>মূল্য</th><th>সময়</th><th>বিবরণ</th><th>স্ট্যাটাস</th><th>Action</th></tr></thead>
    <tbody>
    {% for p in packages %}
    <tr>
      <td><strong>{{ p.name }}</strong></td>
      <td>৳{{ "%.2f"|format(p.price) }}</td>
      <td>{{ p.duration_minutes }} মিনিট</td>
      <td style="font-size:.82rem">{{ p.description }}</td>
      <td>
        {% if p.is_active %}<span class="badge badge-success">ACTIVE</span>
        {% else %}<span class="badge badge-secondary">INACTIVE</span>{% endif %}
      </td>
      <td style="white-space:nowrap">
        <form method="POST" action="{{ url_for('admin_toggle_package', pkg_id=p.id) }}" style="display:inline">
          <button class="btn btn-warning btn-sm">
            {% if p.is_active %}বন্ধ করুন{% else %}চালু করুন{% endif %}
          </button>
        </form>
        <form method="POST" action="{{ url_for('admin_delete_package', pkg_id=p.id) }}" style="display:inline;margin-left:4px">
          <button class="btn btn-danger btn-sm" onclick="return confirm('ডিলিট করবেন?')">ডিলিট</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="text-align:center;color:var(--muted);padding:18px">কোনো প্যাকেজ নেই।</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>"""

PAYMENT_METHODS_CONTENT = """
<div class="card">
  <h3>➕ নতুন পেমেন্ট পদ্ধতি যোগ করুন</h3>
  <form method="POST" action="{{ url_for('admin_add_payment_method') }}"
        style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
    <div style="flex:1;min-width:130px">
      <label>পেমেন্ট পদ্ধতি</label>
      <select name="method" class="form-control">
        <option value="bkash">🔴 বিকাশ (bKash)</option>
        <option value="nagad">🟠 নগদ (Nagad)</option>
        <option value="rocket">🟣 রকেট (Rocket)</option>
      </select>
    </div>
    <div style="flex:1;min-width:160px">
      <label>নম্বর</label>
      <input name="number" class="form-control" placeholder="01XXXXXXXXX" required>
    </div>
    <div style="flex:1;min-width:150px">
      <label>অ্যাকাউন্টের নাম</label>
      <input name="account_name" class="form-control" placeholder="আপনার নাম">
    </div>
    <div><button type="submit" class="btn btn-success" style="height:44px;padding:0 18px">+ যোগ করুন</button></div>
  </form>
</div>
<div class="card">
  <h3>💰 সব পেমেন্ট পদ্ধতি</h3>
  <div class="alert alert-info">
    ⚙️ <strong>অটো-অ্যাপ্রুভ:</strong>
    {% if auto_approve=='1' %}
      <span class="badge badge-success">চালু আছে</span> — ট্রানজেকশন ID দিলেই স্বয়ংক্রিয় অনুমোদন হবে।
    {% else %}
      <span class="badge badge-secondary">বন্ধ আছে</span> — ম্যানুয়ালি অর্ডার অনুমোদন করতে হবে।
    {% endif %}
    <form method="POST" action="{{ url_for('admin_toggle_auto_approve') }}" style="display:inline;margin-left:10px">
      <button class="btn btn-warning btn-sm">
        {% if auto_approve=='1' %}বন্ধ করুন{% else %}চালু করুন{% endif %}
      </button>
    </form>
  </div>
  <div class="table-responsive"><table>
    <thead><tr><th>পদ্ধতি</th><th>নম্বর</th><th>নাম</th><th>স্ট্যাটাস</th><th>Action</th></tr></thead>
    <tbody>
    {% for m in methods %}
    <tr>
      <td>
        {% if m.method=='bkash' %}🔴 বিকাশ
        {% elif m.method=='nagad' %}🟠 নগদ
        {% elif m.method=='rocket' %}🟣 রকেট
        {% else %}{{ m.method }}{% endif %}
      </td>
      <td><strong>{{ m.number }}</strong></td>
      <td>{{ m.account_name }}</td>
      <td>{% if m.is_active %}<span class="badge badge-success">ACTIVE</span>
          {% else %}<span class="badge badge-secondary">INACTIVE</span>{% endif %}</td>
      <td>
        <form method="POST" action="{{ url_for('admin_delete_payment_method', mid=m.id) }}" style="display:inline">
          <button class="btn btn-danger btn-sm" onclick="return confirm('ডিলিট করবেন?')">ডিলিট</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5" style="text-align:center;color:var(--muted);padding:18px">কোনো পেমেন্ট পদ্ধতি নেই।</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>"""

VOUCHER_CONTENT = """
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:13px;flex-wrap:wrap;gap:8px">
    <h3>🎟️ সব ভাউচার পিন</h3>
    <form method="POST" action="{{ url_for('admin_clear_used_pins') }}" style="display:inline">
      <button class="btn btn-danger btn-sm" onclick="return confirm('ব্যবহৃত পিন মুছবেন?')">🗑️ ব্যবহৃত পিন মুছুন</button>
    </form>
  </div>
  <div class="table-responsive"><table>
    <thead><tr><th>PIN</th><th>উৎস</th><th>স্ট্যাটাস</th><th>তৈরি</th><th>ব্যবহার</th><th>IP</th><th>Action</th></tr></thead>
    <tbody>
    {% for p in pins %}
    <tr>
      <td style="font-size:1.05rem;font-weight:700;letter-spacing:3px">{{ p.pin }}</td>
      <td>{% if p.source=='payment' %}<span class="badge badge-info">পেমেন্ট</span>
          {% else %}<span class="badge badge-secondary">ম্যানুয়াল</span>{% endif %}</td>
      <td>{% if p.status=='active' %}<span class="badge badge-success">ACTIVE</span>
          {% else %}<span class="badge badge-secondary">USED</span>{% endif %}</td>
      <td style="font-size:.8rem">{{ p.created_at }}</td>
      <td style="font-size:.8rem">{{ p.used_at or '—' }}</td>
      <td style="font-size:.8rem">{{ p.used_by_ip or '—' }}</td>
      <td>
        <form method="POST" action="{{ url_for('admin_delete_pin', pin_id=p.id) }}" style="display:inline">
          <button class="btn btn-danger btn-sm" onclick="return confirm('ডিলিট?')">ডিলিট</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7" style="text-align:center;color:var(--muted);padding:18px">কোনো পিন নেই।</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div>
{% if active_pins %}
<div class="card">
  <h3>🖨️ প্রিন্টযোগ্য অ্যাক্টিভ ভাউচার</h3>
  <div class="voucher-grid">
    {% for v in active_pins %}
    <div class="voucher-card">
      <small style="font-weight:600;color:var(--p)">WIFI VOUCHER</small>
      <div class="pin">{{ v.pin }}</div>
      <small style="color:var(--muted)">4-Digit PIN</small>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}"""

MESSAGES_CONTENT = """
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:13px">
    <h3>💬 ইউজার বার্তাসমূহ</h3>
    <form method="POST" action="{{ url_for('admin_mark_messages_read') }}">
      <button class="btn btn-secondary btn-sm">✓ সব পঠিত চিহ্নিত করুন</button>
    </form>
  </div>
  {% for msg in messages %}
  <div class="msg-bubble" style="{% if not msg.is_read %}border-left:3px solid var(--p){% endif %}">
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:5px;display:flex;justify-content:space-between">
      <span>👤 <strong>{{ msg.sender_name }}</strong> ({{ msg.client_ip }})</span>
      <span>{{ msg.created_at }}{% if not msg.is_read %} <span class="badge badge-primary">নতুন</span>{% endif %}</span>
    </div>
    <div style="margin-bottom:10px">{{ msg.message }}</div>
    {% if msg.reply %}
    <div class="msg-bubble reply" style="margin:0">
      <small style="color:var(--muted)">🔧 আপনার উত্তর — {{ msg.replied_at }}</small><br>
      {{ msg.reply }}
    </div>
    {% else %}
    <form method="POST" action="{{ url_for('admin_reply_message', msg_id=msg.id) }}"
          style="display:flex;gap:8px;margin-top:8px">
      <input name="reply" class="form-control" placeholder="উত্তর লিখুন..." required>
      <button type="submit" class="btn btn-primary btn-sm" style="white-space:nowrap">পাঠান</button>
    </form>
    {% endif %}
  </div>
  {% else %}
  <div style="text-align:center;color:var(--muted);padding:20px">কোনো বার্তা নেই।</div>
  {% endfor %}
</div>"""

SITE_SETTINGS_CONTENT = """
<div class="card" style="max-width:600px;margin:0 auto">
  <h3>🎨 সাইট কাস্টমাইজেশন</h3>
  <form method="POST">
    <div class="form-group"><label>হটস্পট নাম (Navbar)</label>
      <input name="hotspot_name" class="form-control" value="{{ s.hotspot_name }}" required></div>
    <div class="form-group"><label>পোর্টাল টাইটেল</label>
      <input name="site_name" class="form-control" value="{{ s.site_name }}" required></div>
    <div class="form-group"><label>সাবটাইটেল</label>
      <input name="site_subtitle" class="form-control" value="{{ s.site_subtitle }}"></div>
    <div class="form-group"><label>ওয়েলকাম টেক্সট</label>
      <input name="welcome_text" class="form-control" value="{{ s.welcome_text }}"></div>
    <div class="form-group"><label>ফুটার নোট</label>
      <input name="footer_text" class="form-control" value="{{ s.footer_text }}"></div>
    <div class="form-group"><label>প্রাইমারি রঙ</label>
      <input type="color" name="primary_color" class="form-control"
             value="{{ s.primary_color }}" style="height:46px;cursor:pointer"></div>
    <div class="form-group"><label>গেটওয়ে IP</label>
      <input name="gateway_ip" class="form-control" value="{{ s.gateway_ip }}">
      <small style="color:var(--muted)">Termux: <code>ip addr show wlan0</code> দিয়ে বের করুন</small></div>
    <button type="submit" class="btn btn-primary btn-block" style="padding:12px">💾 সেভ করুন</button>
  </form>
</div>"""

ADMIN_SETTINGS_CONTENT = """
<div class="card" style="max-width:500px;margin:0 auto">
  <h3>🔐 অ্যাডমিন ক্রেডেনশিয়াল পরিবর্তন</h3>
  <form method="POST">
    <div class="form-group"><label>বর্তমান পাসওয়ার্ড</label>
      <input type="password" name="current_password" class="form-control" required></div>
    <div class="form-group"><label>নতুন ইউজারনেম</label>
      <input name="new_username" class="form-control" value="{{ admin.username }}" required></div>
    <div class="form-group"><label>নতুন পাসওয়ার্ড</label>
      <input type="password" name="new_password" class="form-control" placeholder="কমপক্ষে ৪ অক্ষর" required></div>
    <div class="form-group"><label>পাসওয়ার্ড নিশ্চিত করুন</label>
      <input type="password" name="confirm_password" class="form-control" required></div>
    <button type="submit" class="btn btn-primary btn-block" style="padding:12px">আপডেট করুন</button>
  </form>
</div>"""

GUIDE_CONTENT = """
<div class="card">
  <h3>📱 Termux সেটআপ গাইড</h3>
  <h4 style="margin:16px 0 7px">১. প্রথমবার ইনস্টল</h4>
  <pre class="terminal">pkg update -y && pkg upgrade -y
pkg install -y python git root-repo iptables dnsmasq tsu
pip install -r requirements.txt</pre>
  <h4 style="margin:16px 0 7px">২. হটস্পট চালু করে IP বের করুন</h4>
  <pre class="terminal">ip addr show wlan0 | grep inet</pre>
  <h4 style="margin:16px 0 7px">৩. Root শেল + iptables (একবারই)</h4>
  <pre class="terminal">tsu
echo 1 > /proc/sys/net/ipv4/ip_forward
iptables -t nat -F
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80  -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 443 -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p udp --dport 53  -j REDIRECT --to-port 5353</pre>
  <h4 style="margin:16px 0 7px">৪. DNS Spoofing (নতুন সেশনে)</h4>
  <pre class="terminal">dnsmasq -k -a {{ s.gateway_ip }} --address=/#/{{ s.gateway_ip }} -p 5353 --no-resolv --no-poll &</pre>
  <h4 style="margin:16px 0 7px">৫. সার্ভার চালু (নতুন সেশনে)</h4>
  <pre class="terminal">python app.py</pre>
  <div class="alert alert-info" style="margin-top:14px">
    💡 কানেক্টেড ডিভাইস → OS captive portal check → Flask redirect → পোর্টাল পপআপ → প্যাকেজ নির্বাচন → পেমেন্ট → ভাউচার কোড → ইন্টারনেট ✅
  </div>
  <div class="alert alert-warning">
    ⚠️ iptables ছাড়া ম্যানুয়ালি <strong>http://{{ s.gateway_ip }}:8080</strong> দিয়ে এক্সেস করতে হবে।
  </div>
</div>"""

# ─────────────────────────────────────────────────────────────────────────────
# Captive Portal Detection (all OS/browser checks)
# ─────────────────────────────────────────────────────────────────────────────
BYPASS = {"/", "/login", "/status", "/user-logout", "/order",
          "/voucher", "/contact",
          "/generate_204", "/gen_204", "/hotspot-detect.html",
          "/ncsi.txt", "/canonical.html", "/connecttest.txt", "/favicon.ico"}

@app.before_request
def captive_redirect():
    p = request.path
    if p.startswith("/admin") or p.startswith("/static") or p.startswith("/order/"):
        return None
    if p in BYPASS:
        return None
    ip = client_ip()
    if not is_authenticated(ip):
        return redirect(url_for("portal_index"), 302)

@app.route("/generate_204")
@app.route("/gen_204")
@app.route("/hotspot-detect.html")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
@app.route("/canonical.html")
def captive_detect():
    ip = client_ip()
    if is_authenticated(ip):
        p = request.path
        if "204" in p: return Response(status=204)
        if "ncsi" in p or "connect" in p: return Response("Microsoft NCSI", 200, content_type="text/plain")
        return Response("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>", 200)
    return redirect(url_for("portal_index"), 302)

# ─────────────────────────────────────────────────────────────────────────────
# ══  USER ROUTES  ══
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def portal_index():
    ip = client_ip()
    if is_authenticated(ip):
        return redirect(url_for("portal_status"))
    # Check pending/verified order
    conn = get_db()
    order = conn.execute(
        "SELECT * FROM payment_orders WHERE client_ip=? AND status IN ('pending','verified') ORDER BY id DESC LIMIT 1",
        (ip,)).fetchone()
    pkgs = conn.execute("SELECT * FROM packages WHERE is_active=1 ORDER BY sort_order,price").fetchall()
    conn.close()
    if order:
        return redirect(url_for("order_status", order_id=order["order_id"]))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(PACKAGES_TMPL, s=s, css=css, ip=ip, packages=pkgs)

@app.route("/order/<pkg_id>")
def order_page(pkg_id):
    ip = client_ip()
    if is_authenticated(ip): return redirect(url_for("portal_status"))
    conn = get_db()
    pkg     = conn.execute("SELECT * FROM packages WHERE id=? AND is_active=1", (pkg_id,)).fetchone()
    methods = conn.execute("SELECT * FROM payment_methods WHERE is_active=1").fetchall()
    conn.close()
    if not pkg: return redirect(url_for("portal_index"))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(PAYMENT_TMPL, s=s, css=css, pkg=pkg, methods=methods, ip=ip)

@app.route("/order", methods=["POST"])
def submit_order():
    ip = client_ip()
    pkg_id         = request.form.get("package_id","")
    client_name    = request.form.get("client_name","").strip()
    payment_method = request.form.get("payment_method","").strip()
    txn_id         = request.form.get("transaction_id","").strip()

    if not all([pkg_id, payment_method, txn_id]):
        flash("সব তথ্য পূরণ করুন!", "danger")
        return redirect(url_for("order_page", pkg_id=pkg_id))

    conn = get_db()
    pkg = conn.execute("SELECT * FROM packages WHERE id=? AND is_active=1", (pkg_id,)).fetchone()
    if not pkg:
        conn.close(); return redirect(url_for("portal_index"))

    # Duplicate txn check
    if conn.execute("SELECT id FROM payment_orders WHERE transaction_id=?", (txn_id,)).fetchone():
        conn.close()
        flash("⚠️ এই ট্রানজেকশন আইডি আগেই ব্যবহৃত হয়েছে!", "warning")
        return redirect(url_for("order_page", pkg_id=pkg_id))

    order_id = gen_order_id()
    auto = get_settings().get("auto_approve","0") == "1"
    vpin = None; v_at = None; status = "pending"

    if auto:
        vpin   = make_voucher(conn, order_id)
        status = "verified"
        v_at   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""INSERT INTO payment_orders
        (order_id,client_ip,client_name,package_id,amount,payment_method,transaction_id,status,voucher_pin,verified_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (order_id, ip, client_name, pkg["id"], pkg["price"], payment_method, txn_id, status, vpin, v_at))
    conn.commit(); conn.close()
    return redirect(url_for("order_status", order_id=order_id))

@app.route("/order/status/<order_id>")
def order_status(order_id):
    ip = client_ip()
    if is_authenticated(ip): return redirect(url_for("portal_status"))
    conn = get_db()
    order = conn.execute(
        "SELECT o.*,p.name as pkg_name,p.duration_minutes FROM payment_orders o "
        "JOIN packages p ON o.package_id=p.id WHERE o.order_id=?", (order_id,)).fetchone()
    conn.close()
    if not order:
        flash("অর্ডার পাওয়া যায়নি।","danger")
        return redirect(url_for("portal_index"))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(ORDER_STATUS_TMPL, s=s, css=css, order=order, ip=ip)

@app.route("/voucher")
def voucher_page():
    ip = client_ip()
    if is_authenticated(ip): return redirect(url_for("portal_status"))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(VOUCHER_PAGE_TMPL, s=s, css=css, ip=ip)

@app.route("/login", methods=["POST"])
def login():
    ip  = client_ip()
    pin = request.form.get("pin","").strip()
    if not pin or len(pin)!=4 or not pin.isdigit():
        flash("❌ সঠিক ৪-ডিজিট কোড দিন!","danger")
        return redirect(url_for("voucher_page"))

    conn    = get_db()
    voucher = conn.execute("SELECT * FROM vouchers WHERE pin=?", (pin,)).fetchone()
    if not voucher:
        conn.close(); flash("❌ কোডটি বৈধ নয়!","danger")
        return redirect(url_for("voucher_page"))
    if voucher["status"] != "active":
        conn.close(); flash("⚠️ এই কোডটি আগেই ব্যবহৃত হয়েছে!","warning")
        return redirect(url_for("voucher_page"))

    # Get duration from order/package
    now = datetime.now(); now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = None; pkg_id = None
    if voucher["order_id"]:
        o = conn.execute(
            "SELECT o.package_id,p.duration_minutes FROM payment_orders o "
            "JOIN packages p ON o.package_id=p.id WHERE o.order_id=?",
            (voucher["order_id"],)).fetchone()
        if o:
            pkg_id = o["package_id"]
            expires_at = (now + timedelta(minutes=o["duration_minutes"])).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("UPDATE vouchers SET status='used',used_at=?,used_by_ip=? WHERE id=?",
                 (now_str, ip, voucher["id"]))
    conn.execute("INSERT OR REPLACE INTO active_sessions(client_ip,pin,package_id,login_time,expires_at,user_agent) VALUES(?,?,?,?,?,?)",
                 (ip, pin, pkg_id, now_str, expires_at, request.headers.get("User-Agent","")))
    conn.commit(); conn.close()
    _allow(ip)
    flash("✅ ইন্টারনেট চালু হয়েছে!","success")
    return redirect(url_for("portal_status"))

@app.route("/status")
def portal_status():
    ip   = client_ip()
    conn = get_db()
    sess = conn.execute(
        "SELECT s.*,p.name as pkg_name FROM active_sessions s "
        "LEFT JOIN packages p ON s.package_id=p.id WHERE s.client_ip=?", (ip,)).fetchone()
    conn.close()
    if not sess: return redirect(url_for("portal_index"))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(STATUS_TMPL, s=s, css=css, sess=sess)

@app.route("/user-logout", methods=["POST"])
def user_logout():
    ip = client_ip()
    conn = get_db()
    conn.execute("DELETE FROM active_sessions WHERE client_ip=?", (ip,))
    conn.commit(); conn.close()
    _revoke(ip)
    flash("ডিসকানেক্ট হয়েছেন।","info")
    return redirect(url_for("portal_index"))

@app.route("/contact", methods=["GET","POST"])
def contact_page():
    ip = client_ip()
    s  = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("sender_name","ইউজার").strip()
        msg  = request.form.get("message","").strip()
        if msg:
            conn.execute("INSERT INTO messages(client_ip,sender_name,message) VALUES(?,?,?)",
                         (ip, name, msg))
            conn.commit()
            flash("✅ আপনার বার্তা পাঠানো হয়েছে! অ্যাডমিন শীঘ্রই উত্তর দেবেন।","success")
    prev = conn.execute("SELECT * FROM messages WHERE client_ip=? ORDER BY id DESC LIMIT 10", (ip,)).fetchall()
    conn.close()
    return render_template_string(CONTACT_TMPL, s=s, css=css, prev_msgs=prev)

# ─────────────────────────────────────────────────────────────────────────────
# ══  ADMIN ROUTES  ══
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if session.get("admin_logged_in"): return redirect(url_for("admin_dashboard"))
    s = get_settings(); css = base_css(s.get("primary_color","#007bff"))
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM admin_users WHERE username=?", (u,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], p):
            session["admin_logged_in"] = True
            session["admin_username"]  = user["username"]
            session.permanent = True
            flash(f"স্বাগতম {user['username']}!","success")
            return redirect(url_for("admin_dashboard"))
        flash("❌ ভুল ইউজারনেম বা পাসওয়ার্ড!","danger")
    return render_template_string(ADMIN_LOGIN_TMPL, css=css)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("লগআউট হয়েছেন।","info")
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    total_pins    = conn.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
    active_pins   = conn.execute("SELECT COUNT(*) FROM vouchers WHERE status='active'").fetchone()[0]
    pending_orders= conn.execute("SELECT COUNT(*) FROM payment_orders WHERE status='pending'").fetchone()[0]
    total_orders  = conn.execute("SELECT COUNT(*) FROM payment_orders").fetchone()[0]
    sessions = conn.execute(
        "SELECT s.*,p.name as pkg_name FROM active_sessions s LEFT JOIN packages p ON s.package_id=p.id "
        "ORDER BY s.login_time DESC").fetchall()
    conn.close()
    st = dict(total_pins=total_pins, active_pins=active_pins,
              pending_orders=pending_orders, online=len(sessions), total_orders=total_orders)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = render_template_string(DASH_CONTENT, st=st, sessions=sessions, now=now, url_for=url_for)
    return render_admin("ড্যাশবোর্ড", "dash", html)

@app.route("/admin/orders")
@admin_required
def admin_orders():
    flt = request.args.get("status","")
    conn = get_db()
    q = "SELECT o.*,p.name as pkg_name FROM payment_orders o JOIN packages p ON o.package_id=p.id"
    q += (" WHERE o.status=?" if flt else "") + " ORDER BY o.id DESC"
    orders = conn.execute(q, (flt,) if flt else ()).fetchall()
    conn.close()
    html = render_template_string(ORDERS_CONTENT, orders=orders, url_for=url_for)
    return render_admin("পেমেন্ট অর্ডার", "orders", html)

@app.route("/admin/orders/<order_id>/approve", methods=["POST"])
@admin_required
def admin_approve_order(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM payment_orders WHERE order_id=?", (order_id,)).fetchone()
    if order and order["status"] == "pending":
        pin = make_voucher(conn, order_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE payment_orders SET status='verified',voucher_pin=?,verified_at=? WHERE order_id=?",
                     (pin, now, order_id))
        conn.commit()
        flash(f"✅ অর্ডার {order_id} অনুমোদিত। পিন: {pin}","success")
    conn.close()
    return redirect(url_for("admin_orders"))

@app.route("/admin/orders/<order_id>/reject", methods=["POST"])
@admin_required
def admin_reject_order(order_id):
    notes = request.form.get("notes","পেমেন্ট যাচাই করা যায়নি।")
    conn  = get_db()
    conn.execute("UPDATE payment_orders SET status='rejected',notes=? WHERE order_id=?", (notes, order_id))
    conn.commit(); conn.close()
    flash(f"অর্ডার {order_id} প্রত্যাখ্যাত করা হয়েছে।","warning")
    return redirect(url_for("admin_orders"))

@app.route("/admin/packages")
@admin_required
def admin_packages():
    conn = get_db()
    pkgs = conn.execute("SELECT * FROM packages ORDER BY sort_order,price").fetchall()
    conn.close()
    html = render_template_string(PACKAGES_CONTENT, packages=pkgs, url_for=url_for)
    return render_admin("প্যাকেজ ম্যানেজমেন্ট", "pkgs", html)

@app.route("/admin/packages/add", methods=["POST"])
@admin_required
def admin_add_package():
    name     = request.form.get("name","").strip()
    price    = float(request.form.get("price", 0))
    dur      = int(request.form.get("duration_minutes", 10))
    desc     = request.form.get("description","").strip()
    conn = get_db()
    conn.execute("INSERT INTO packages(name,price,duration_minutes,description) VALUES(?,?,?,?)",
                 (name, price, dur, desc))
    conn.commit(); conn.close()
    flash(f"✅ প্যাকেজ '{name}' যোগ করা হয়েছে!","success")
    return redirect(url_for("admin_packages"))

@app.route("/admin/packages/<int:pkg_id>/delete", methods=["POST"])
@admin_required
def admin_delete_package(pkg_id):
    conn = get_db()
    conn.execute("DELETE FROM packages WHERE id=?", (pkg_id,))
    conn.commit(); conn.close()
    flash("প্যাকেজ ডিলিট হয়েছে।","info")
    return redirect(url_for("admin_packages"))

@app.route("/admin/packages/<int:pkg_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_package(pkg_id):
    conn = get_db()
    conn.execute("UPDATE packages SET is_active = 1 - is_active WHERE id=?", (pkg_id,))
    conn.commit(); conn.close()
    flash("প্যাকেজ স্ট্যাটাস আপডেট হয়েছে।","info")
    return redirect(url_for("admin_packages"))

@app.route("/admin/payment-methods")
@admin_required
def admin_payment_methods():
    conn = get_db()
    methods = conn.execute("SELECT * FROM payment_methods ORDER BY id").fetchall()
    conn.close()
    s = get_settings()
    auto = s.get("auto_approve","0")
    html = render_template_string(PAYMENT_METHODS_CONTENT, methods=methods, auto_approve=auto, url_for=url_for)
    return render_admin("পেমেন্ট পদ্ধতি", "pay", html)

@app.route("/admin/payment-methods/add", methods=["POST"])
@admin_required
def admin_add_payment_method():
    method = request.form.get("method","").strip()
    number = request.form.get("number","").strip()
    name   = request.form.get("account_name","").strip()
    conn   = get_db()
    conn.execute("INSERT INTO payment_methods(method,number,account_name) VALUES(?,?,?)", (method, number, name))
    conn.commit(); conn.close()
    flash("✅ পেমেন্ট পদ্ধতি যোগ হয়েছে!","success")
    return redirect(url_for("admin_payment_methods"))

@app.route("/admin/payment-methods/<int:mid>/delete", methods=["POST"])
@admin_required
def admin_delete_payment_method(mid):
    conn = get_db()
    conn.execute("DELETE FROM payment_methods WHERE id=?", (mid,))
    conn.commit(); conn.close()
    flash("পেমেন্ট পদ্ধতি ডিলিট হয়েছে।","info")
    return redirect(url_for("admin_payment_methods"))

@app.route("/admin/payment-methods/toggle-auto", methods=["POST"])
@admin_required
def admin_toggle_auto_approve():
    conn = get_db()
    cur = conn.execute("SELECT value FROM site_settings WHERE key='auto_approve'").fetchone()
    new = "0" if (cur and cur["value"]=="1") else "1"
    conn.execute("INSERT OR REPLACE INTO site_settings(key,value) VALUES('auto_approve',?)", (new,))
    conn.commit(); conn.close()
    flash(f"অটো-অ্যাপ্রুভ {'চালু' if new=='1' else 'বন্ধ'} করা হয়েছে।","info")
    return redirect(url_for("admin_payment_methods"))

@app.route("/admin/vouchers")
@admin_required
def admin_vouchers():
    conn = get_db()
    pins       = conn.execute("SELECT * FROM vouchers ORDER BY id DESC").fetchall()
    active_pins= conn.execute("SELECT * FROM vouchers WHERE status='active' ORDER BY id DESC").fetchall()
    conn.close()
    html = render_template_string(VOUCHER_CONTENT, pins=pins, active_pins=active_pins, url_for=url_for)
    return render_admin("ভাউচার পিন","vchr", html)

@app.route("/admin/generate-pin", methods=["POST"])
@admin_required
def admin_generate_pin():
    custom = request.form.get("custom_pin","").strip()
    count  = int(request.form.get("count",1))
    conn   = get_db(); ok = 0
    if custom:
        if len(custom)!=4 or not custom.isdigit():
            flash("❌ কাস্টম পিন ৪ সংখ্যার হতে হবে!","danger")
        else:
            try:
                conn.execute("INSERT INTO vouchers(pin,source) VALUES(?,?)",(custom,"manual"))
                conn.commit(); flash(f"✅ পিন {custom} তৈরি হয়েছে!","success")
            except sqlite3.IntegrityError:
                flash(f"⚠️ পিন {custom} ইতোমধ্যে আছে!","warning")
    else:
        for _ in range(count):
            for __ in range(100):
                p = str(random.randint(1000,9999))
                try:
                    conn.execute("INSERT INTO vouchers(pin,source) VALUES(?,?)",(p,"manual"))
                    conn.commit(); ok+=1; break
                except sqlite3.IntegrityError:
                    continue
        flash(f"✅ {ok}টি পিন তৈরি হয়েছে!","success")
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-pin/<int:pin_id>", methods=["POST"])
@admin_required
def admin_delete_pin(pin_id):
    conn = get_db()
    conn.execute("DELETE FROM vouchers WHERE id=?", (pin_id,))
    conn.commit(); conn.close()
    flash("পিন ডিলিট হয়েছে।","info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/clear-used", methods=["POST"])
@admin_required
def admin_clear_used_pins():
    conn = get_db()
    n = conn.execute("DELETE FROM vouchers WHERE status='used'").rowcount
    conn.commit(); conn.close()
    flash(f"🗑️ {n}টি ব্যবহৃত পিন মুছে ফেলা হয়েছে।","info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/kick-user", methods=["POST"])
@admin_required
def admin_kick_user():
    ip = request.form.get("client_ip","")
    if ip:
        conn = get_db()
        conn.execute("DELETE FROM active_sessions WHERE client_ip=?", (ip,))
        conn.commit(); conn.close()
        _revoke(ip)
        flash(f"🚫 {ip} ডিসকানেক্ট করা হয়েছে।","warning")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/messages")
@admin_required
def admin_messages():
    conn = get_db()
    msgs = conn.execute("SELECT * FROM messages ORDER BY id DESC").fetchall()
    conn.close()
    html = render_template_string(MESSAGES_CONTENT, messages=msgs, url_for=url_for)
    return render_admin("ইউজার বার্তা","msg", html)

@app.route("/admin/messages/<int:msg_id>/reply", methods=["POST"])
@admin_required
def admin_reply_message(msg_id):
    reply = request.form.get("reply","").strip()
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn  = get_db()
    conn.execute("UPDATE messages SET reply=?,replied_at=?,is_read=1 WHERE id=?", (reply, now, msg_id))
    conn.commit(); conn.close()
    flash("উত্তর পাঠানো হয়েছে।","success")
    return redirect(url_for("admin_messages"))

@app.route("/admin/messages/mark-read", methods=["POST"])
@admin_required
def admin_mark_messages_read():
    conn = get_db()
    conn.execute("UPDATE messages SET is_read=1")
    conn.commit(); conn.close()
    flash("সব বার্তা পঠিত চিহ্নিত করা হয়েছে।","info")
    return redirect(url_for("admin_messages"))

@app.route("/admin/site-settings", methods=["GET","POST"])
@admin_required
def admin_site_settings():
    if request.method == "POST":
        conn = get_db()
        for k in ["site_name","site_subtitle","welcome_text","footer_text",
                  "hotspot_name","primary_color","gateway_ip"]:
            v = request.form.get(k,"").strip()
            if v:
                conn.execute("INSERT OR REPLACE INTO site_settings(key,value) VALUES(?,?)", (k,v))
        conn.commit(); conn.close()
        flash("✅ সেটিংস সেভ হয়েছে!","success")
        return redirect(url_for("admin_site_settings"))
    s    = get_settings()
    html = render_template_string(SITE_SETTINGS_CONTENT, s=s, url_for=url_for)
    return render_admin("সাইট সেটিংস","site", html)

@app.route("/admin/settings", methods=["GET","POST"])
@admin_required
def admin_settings():
    conn  = get_db()
    admin = conn.execute("SELECT * FROM admin_users WHERE username=?",
                         (session["admin_username"],)).fetchone()
    if request.method == "POST":
        cur = request.form.get("current_password","")
        nu  = request.form.get("new_username","").strip()
        np_ = request.form.get("new_password","")
        cnf = request.form.get("confirm_password","")
        if not check_password_hash(admin["password_hash"], cur):
            flash("❌ বর্তমান পাসওয়ার্ড ভুল!","danger")
        elif len(np_) < 4:
            flash("❌ পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে!","danger")
        elif np_ != cnf:
            flash("❌ পাসওয়ার্ড মিলছে না!","danger")
        elif not nu:
            flash("❌ ইউজারনেম খালি রাখা যাবে না!","danger")
        else:
            conn.execute("UPDATE admin_users SET username=?,password_hash=? WHERE id=?",
                         (nu, generate_password_hash(np_), admin["id"]))
            conn.commit(); session["admin_username"] = nu
            flash("✅ আপডেট হয়েছে!","success")
            conn.close()
            return redirect(url_for("admin_dashboard"))
    conn.close()
    html = render_template_string(ADMIN_SETTINGS_CONTENT, admin=admin, url_for=url_for)
    return render_admin("অ্যাডমিন সেটিং","cfg", html)

@app.route("/admin/guide")
@admin_required
def admin_guide():
    s    = get_settings()
    html = render_template_string(GUIDE_CONTENT, s=s, url_for=url_for)
    return render_admin("Termux গাইড","guide", html)

# ─────────────────────────────────────────────────────────────────────────────
# Global Error Handler (Prevents blank Internal Server Error)
# ─────────────────────────────────────────────────────────────────────────────
@app.errorhandler(500)
@app.errorhandler(Exception)
def handle_error(e):
    import traceback
    err_trace = traceback.format_exc()
    print("[ERROR]", err_trace)
    # Attempt DB self-healing
    try:
        init_db()
    except Exception:
        pass
    return f"""
    <!DOCTYPE html><html><head><meta charset='utf-8'><title>System Notice</title>
    <style>body{{font-family:sans-serif;padding:24px;background:#f8fafc;color:#1e293b}}
    .box{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;max-width:500px;margin:30px auto;box-shadow:0 4px 12px rgba(0,0,0,0.05)}}
    .btn{{display:inline-block;padding:10px 16px;background:#007bff;color:#fff;border-radius:6px;text-decoration:none;margin-top:12px}}</style>
    </head><body><div class='box'>
    <h3>⚠️ সিস্টেমে সাময়িক সমস্যা হয়েছে</h3>
    <p>ডাটাবেস স্বয়ংক্রিয়ভাবে রিকভার করা হয়েছে। অনুগ্রহ করে পেজটি রিফ্রেশ করুন।</p>
    <a href='/' class='btn'>🔄 পেজ রিফ্রেশ করুন</a>
    </div></body></html>
    """, 500

# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────
def banner():
    print("=" * 60)
    print("  MikroTik Captive Portal - Full Payment & Hotspot System")
    print("=" * 60)
    print("  Portal : http://0.0.0.0:8080/")
    print("  Admin  : http://0.0.0.0:8080/admin")
    print("  Login  : admin / admin")
    print("=" * 60)

# Always initialize on start
init_db()

if __name__ == "__main__":
    banner()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
