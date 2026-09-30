#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
        MIKROTIK-STYLE CAPTIVE PORTAL & WIFI HOTSPOT MANAGEMENT SYSTEM
                        Optimized for Termux (Android)
=============================================================================
"""

import os
import sqlite3
import random
import subprocess
from datetime import datetime
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, flash, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────────────────────────────────────
# App Config
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hotspot_secret_mikrotik_2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "hotspot.db")
HOST     = "0.0.0.0"
PORT     = 8080

# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS vouchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pin TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        used_at TEXT,
        used_by_ip TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS active_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_ip TEXT UNIQUE NOT NULL,
        pin TEXT NOT NULL,
        login_time TEXT DEFAULT (datetime('now','localtime')),
        user_agent TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")

    # Default admin
    c.execute("SELECT id FROM admin_users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admin_users (username,password_hash) VALUES (?,?)",
                  ("admin", generate_password_hash("admin")))
        print("[*] Default admin created → username: admin | password: admin")

    # Default site settings
    defaults = {
        "site_name":       "WiFi Hotspot Portal",
        "site_subtitle":   "High Speed Wireless Network",
        "welcome_text":    "ইন্টারনেট ব্যবহার করতে আপনার ভাউচার পিন দিন।",
        "hotspot_name":    "MikroTik HotSpot",
        "footer_text":     "পিনের জন্য অ্যাডমিনের সাথে যোগাযোগ করুন।",
        "primary_color":   "#007bff",
        "gateway_ip":      "192.168.43.1",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO site_settings (key,value) VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()

def get_settings():
    """Returns site_settings as a plain dict."""
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM site_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def client_ip():
    xff = request.headers.get("X-Forwarded-For")
    return xff.split(",")[0].strip() if xff else (request.remote_addr or "127.0.0.1")

def is_authenticated(ip):
    conn = get_db()
    row = conn.execute("SELECT id FROM active_sessions WHERE client_ip=?", (ip,)).fetchone()
    conn.close()
    return row is not None

def allow_ip(ip):
    if os.name != "nt":
        for cmd in [
            ["iptables", "-I", "FORWARD", "-s", ip, "-j", "ACCEPT"],
            ["iptables", "-I", "FORWARD", "-d", ip, "-j", "ACCEPT"],
            ["iptables", "-t", "nat", "-I", "PREROUTING", "-s", ip, "-j", "ACCEPT"],
        ]:
            subprocess.run(cmd, capture_output=True)

def revoke_ip(ip):
    if os.name != "nt":
        for cmd in [
            ["iptables", "-D", "FORWARD", "-s", ip, "-j", "ACCEPT"],
            ["iptables", "-D", "FORWARD", "-d", ip, "-j", "ACCEPT"],
            ["iptables", "-t", "nat", "-D", "PREROUTING", "-s", ip, "-j", "ACCEPT"],
        ]:
            subprocess.run(cmd, capture_output=True)

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("অনুগ্রহ করে আগে লগইন করুন।", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

# ─────────────────────────────────────────────────────────────────────────────
# Captive Portal Middleware
# ─────────────────────────────────────────────────────────────────────────────
BYPASS_PATHS = {"/", "/login", "/status", "/user-logout",
                "/generate_204", "/gen_204", "/hotspot-detect.html",
                "/ncsi.txt", "/canonical.html", "/connecttest.txt",
                "/favicon.ico"}

@app.before_request
def captive_redirect():
    """Redirect unauthenticated clients to login page for every request."""
    path = request.path
    # Always allow admin routes and bypass paths
    if path.startswith("/admin") or path.startswith("/static"):
        return None
    if path in BYPASS_PATHS:
        return None
    ip = client_ip()
    if not is_authenticated(ip):
        return redirect(url_for("portal_index"), 302)

# ─────────────────────────────────────────────────────────────────────────────
# CSS (shared)
# ─────────────────────────────────────────────────────────────────────────────
def base_css(primary="#007bff"):
    return f"""
:root {{
    --primary: {primary};
    --primary-d: color-mix(in srgb, {primary} 80%, black);
    --dark: #1b263b;
    --light: #f4f6f9;
    --surface: #ffffff;
    --success: #28a745;
    --danger: #dc3545;
    --warning: #ffc107;
    --border: #e2e8f0;
    --text: #2d3748;
    --muted: #718096;
    --radius: 12px;
    --shadow: 0 10px 25px -5px rgba(0,0,0,.12);
}}
*{{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}
body{{background:var(--light);color:var(--text);min-height:100vh}}
a{{color:var(--primary);text-decoration:none}}

/* Navbar */
.navbar{{background:var(--dark);color:#fff;padding:13px 22px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,.2)}}
.navbar .brand{{font-size:1.15rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:8px}}
.nav-links{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.nav-link{{color:#cbd5e0;font-size:.88rem;padding:6px 11px;border-radius:6px;transition:.2s}}
.nav-link:hover,.nav-link.active{{color:#fff;background:rgba(255,255,255,.12)}}
.btn-logout{{background:var(--danger);color:#fff;padding:6px 13px;border-radius:6px;font-size:.83rem;font-weight:600}}

/* Container */
.container{{max-width:1100px;margin:28px auto;padding:0 18px;width:100%}}

/* Card */
.card{{background:#fff;border-radius:var(--radius);padding:22px;box-shadow:var(--shadow);border:1px solid var(--border);margin-bottom:22px}}
.card h3{{margin-bottom:14px;font-size:1.05rem;color:var(--dark)}}

/* Form */
.form-group{{margin-bottom:16px}}
label{{display:block;margin-bottom:5px;font-size:.88rem;font-weight:600}}
.form-control{{width:100%;padding:11px 15px;border:1.5px solid var(--border);border-radius:8px;font-size:.97rem;outline:none;transition:.2s;background:#fff}}
.form-control:focus{{border-color:var(--primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--primary) 20%,transparent)}}

/* Buttons */
.btn{{display:inline-block;padding:10px 18px;font-size:.92rem;font-weight:600;border-radius:8px;cursor:pointer;border:none;text-align:center;transition:.2s;line-height:1.4}}
.btn-primary{{background:var(--primary);color:#fff}}
.btn-primary:hover{{background:var(--primary-d)}}
.btn-success{{background:var(--success);color:#fff}}
.btn-success:hover{{background:#1e7e34}}
.btn-danger{{background:var(--danger);color:#fff}}
.btn-danger:hover{{background:#bd2130}}
.btn-warning{{background:var(--warning);color:#333}}
.btn-secondary{{background:#6c757d;color:#fff}}
.btn-block{{width:100%}}
.btn-sm{{padding:5px 11px;font-size:.8rem}}

/* Alerts */
.alert{{padding:11px 15px;border-radius:8px;margin-bottom:18px;font-size:.88rem}}
.alert-success{{background:#d4edda;color:#155724;border:1px solid #c3e6cb}}
.alert-danger{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}}
.alert-warning{{background:#fff3cd;color:#856404;border:1px solid #ffeeba}}
.alert-info{{background:#d1ecf1;color:#0c5460;border:1px solid #bee5eb}}

/* Badge */
.badge{{display:inline-block;padding:3px 9px;border-radius:20px;font-size:.72rem;font-weight:700;text-transform:uppercase}}
.badge-success{{background:var(--success);color:#fff}}
.badge-secondary{{background:#6c757d;color:#fff}}
.badge-primary{{background:var(--primary);color:#fff}}
.badge-warning{{background:var(--warning);color:#333}}

/* Table */
.table-responsive{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:11px 14px;text-align:left;border-bottom:1px solid var(--border);font-size:.88rem}}
th{{background:#f8fafc;color:var(--muted);font-weight:600}}
tr:hover td{{background:#f8fafc}}

/* Stats grid */
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:18px;margin-bottom:22px}}
.stat-box{{background:#fff;border-radius:var(--radius);padding:18px;border:1px solid var(--border);box-shadow:0 2px 6px rgba(0,0,0,.04);border-left:5px solid var(--primary)}}
.stat-box.green{{border-left-color:var(--success)}}
.stat-box.orange{{border-left-color:var(--warning)}}
.stat-box.red{{border-left-color:var(--danger)}}
.stat-box h3{{font-size:1.75rem;margin-bottom:4px;color:var(--dark)}}
.stat-box p{{font-size:.82rem;color:var(--muted);font-weight:500}}

/* Voucher cards */
.voucher-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-top:14px}}
.voucher-card{{border:2px dashed var(--primary);background:#f0f7ff;padding:13px;border-radius:8px;text-align:center}}
.voucher-card .pin{{font-size:1.55rem;font-weight:800;letter-spacing:5px;color:var(--primary-d);margin:5px 0}}

/* Terminal block */
pre.terminal{{background:#0d1117;color:#3fb950;padding:14px;border-radius:8px;font-family:monospace;font-size:.83rem;overflow-x:auto;line-height:1.6;margin:8px 0}}

/* Color swatch */
.color-preview{{width:36px;height:36px;border-radius:6px;border:1px solid var(--border);display:inline-block;vertical-align:middle;margin-left:8px}}

@media(max-width:600px){{
    .navbar{{flex-direction:column;gap:10px;text-align:center}}
    .nav-links{{justify-content:center}}
}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Admin base renderer  (no Jinja2 extends — avoids the template-variable bug)
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_BASE_TMPL = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} — Hotspot Admin</title>
<style>{{ css | safe }}</style>
</head>
<body>
<nav class="navbar">
  <a href="{{ url_for('admin_dashboard') }}" class="brand">📡 {{ s.hotspot_name }}</a>
  <div class="nav-links">
    <a href="{{ url_for('admin_dashboard') }}"   class="nav-link {{ 'active' if ap=='dashboard' }}">📊 ড্যাশবোর্ড</a>
    <a href="{{ url_for('admin_vouchers') }}"    class="nav-link {{ 'active' if ap=='vouchers'  }}">🎟️ ভাউচার</a>
    <a href="{{ url_for('admin_site_settings') }}" class="nav-link {{ 'active' if ap=='site'   }}">🎨 সাইট সেটিংস</a>
    <a href="{{ url_for('admin_settings') }}"    class="nav-link {{ 'active' if ap=='settings' }}">⚙️ অ্যাডমিন</a>
    <a href="{{ url_for('admin_termux_guide') }}" class="nav-link {{ 'active' if ap=='guide'   }}">📱 গাইড</a>
    <a href="{{ url_for('admin_logout') }}" class="btn-logout">লগআউট</a>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}{% for cat,msg in messages %}
      <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}{% endif %}
  {% endwith %}
  {{ page_content | safe }}
</div>
</body>
</html>"""

def render_admin(title, ap, content_html):
    s = get_settings()
    css = base_css(s.get("primary_color", "#007bff"))
    return render_template_string(
        ADMIN_BASE_TMPL,
        title=title, ap=ap, s=s, css=css,
        page_content=content_html
    )

# ─────────────────────────────────────────────────────────────────────────────
# ══  USER-FACING TEMPLATES  ══
# ─────────────────────────────────────────────────────────────────────────────
PORTAL_LOGIN_TMPL = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{{ s.site_name }}</title>
<style>
{{ css | safe }}
body{
  background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 100%);
  display:flex; align-items:center; justify-content:center; padding:20px;
}
.portal-card{
  background:#fff; width:100%; max-width:400px;
  border-radius:18px; box-shadow:0 24px 48px rgba(0,0,0,.35); overflow:hidden;
}
.portal-head{
  background: var(--primary); padding:28px 20px; color:#fff; text-align:center;
}
.portal-head .icon{ font-size:44px; margin-bottom:8px; }
.portal-head h2{ font-size:1.35rem; font-weight:700; letter-spacing:.4px; }
.portal-head p{ font-size:.85rem; opacity:.9; margin-top:3px; }
.portal-body{ padding:26px 22px; }
.pin-input{
  letter-spacing:14px; font-size:2rem; text-align:center;
  font-weight:800; height:62px; border:2px solid var(--border);
  border-radius:10px; color:var(--dark);
}
.pin-input:focus{ border-color:var(--primary); }
.client-info{
  background:#f8fafc; border:1px solid var(--border);
  padding:9px 13px; border-radius:8px; font-size:.78rem;
  color:var(--muted); margin-bottom:18px;
  display:flex; justify-content:space-between;
}
.footer-note{ font-size:.75rem; color:var(--muted); margin-top:18px; text-align:center; }
.admin-link{ display:block; text-align:center; margin-top:14px; font-size:.78rem; color:#64748b; }
.admin-link:hover{ color:var(--primary); }
</style>
</head>
<body>
<div class="portal-card">
  <div class="portal-head" style="background:{{ s.primary_color }}">
    <div class="icon">📶</div>
    <h2>{{ s.site_name }}</h2>
    <p>{{ s.site_subtitle }}</p>
  </div>
  <div class="portal-body">
    {% with msgs = get_flashed_messages(with_categories=true) %}
      {% for cat,msg in msgs %}
        <div class="alert alert-{{ cat }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}

    <div class="client-info">
      <span>🌐 IP: <strong>{{ ip }}</strong></span>
      <span>⚡ লগইন প্রয়োজন</span>
    </div>

    <form method="POST" action="{{ url_for('login') }}">
      <div class="form-group">
        <label>{{ s.welcome_text }}</label>
        <input name="pin" class="form-control pin-input"
               placeholder="••••" maxlength="4"
               inputmode="numeric" pattern="[0-9]{4}"
               required autofocus>
      </div>
      <button type="submit" class="btn btn-primary btn-block"
              style="padding:14px;font-size:1.05rem;background:{{ s.primary_color }}">
        🚀 ইন্টারনেট চালু করুন
      </button>
    </form>

    <p class="footer-note">{{ s.footer_text }}</p>
    <a href="{{ url_for('admin_login') }}" class="admin-link">⚙️ Admin Panel</a>
  </div>
</div>
</body>
</html>"""

STATUS_TMPL = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connected — {{ s.site_name }}</title>
<style>
{{ css | safe }}
body{
  background:linear-gradient(135deg,#0d1b2a 0%,#1b263b 100%);
  display:flex; align-items:center; justify-content:center; padding:20px;
}
.status-card{
  background:#fff; border-radius:18px; max-width:440px; width:100%;
  padding:32px 24px; box-shadow:0 24px 48px rgba(0,0,0,.35); text-align:center;
}
.check{ font-size:56px; color:var(--success); margin-bottom:10px; }
.info-tbl{ margin:18px 0; background:#f8fafc; border-radius:8px; border:1px solid var(--border); }
.info-tbl td{ padding:10px 14px; font-size:.87rem; }
.info-tbl td:first-child{ color:var(--muted); font-weight:500; }
.info-tbl td:last-child{ text-align:right; font-weight:600; }
.actions{ display:flex; gap:10px; margin-top:4px; }
.actions a,.actions button{ flex:1; }
</style>
</head>
<body>
<div class="status-card">
  <div class="check">✓</div>
  <h2 style="color:var(--success);margin-bottom:6px">ইন্টারনেট চালু!</h2>
  <p style="color:var(--muted);font-size:.9rem">আপনি সফলভাবে কানেক্টেড।</p>

  <table class="info-tbl">
    <tr><td>IP Address</td><td>{{ sess.client_ip }}</td></tr>
    <tr><td>Voucher PIN</td><td>{{ sess.pin }}</td></tr>
    <tr><td>Login Time</td><td>{{ sess.login_time }}</td></tr>
    <tr><td>Status</td><td><span class="badge badge-success">ONLINE</span></td></tr>
  </table>

  <div class="actions">
    <a href="https://www.google.com" class="btn btn-primary">🌐 Browse</a>
    <form method="POST" action="{{ url_for('user_logout') }}" style="flex:1">
      <button type="submit" class="btn btn-danger btn-block">ডিসকানেক্ট</button>
    </form>
  </div>
</div>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────────────
# ══  ADMIN CONTENT TEMPLATES  ══
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_LOGIN_TMPL = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title>
<style>
{{ css | safe }}
body{ background:#0f172a; display:flex; align-items:center; justify-content:center; padding:20px; }
.box{ background:#fff; border-radius:14px; padding:30px; width:100%; max-width:380px; box-shadow:0 12px 30px rgba(0,0,0,.3); }
.box h3{ text-align:center; margin-bottom:20px; color:#0f172a; }
</style>
</head>
<body>
<div class="box">
  <h3>🔐 অ্যাডমিন লগইন</h3>
  {% with msgs = get_flashed_messages(with_categories=true) %}
    {% for cat,msg in msgs %}<div class="alert alert-{{ cat }}">{{ msg }}</div>{% endfor %}
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
  <div style="text-align:center;margin-top:14px">
    <a href="{{ url_for('portal_index') }}" style="font-size:.82rem;color:#64748b">← পোর্টালে ফিরুন</a>
  </div>
</div>
</body>
</html>"""

# ─── Dashboard ───
DASH_CONTENT = """
<div class="stats-grid">
  <div class="stat-box"><h3>{{ st.total }}</h3><p>মোট পিন</p></div>
  <div class="stat-box green"><h3>{{ st.active }}</h3><p>অ্যাক্টিভ পিন</p></div>
  <div class="stat-box orange"><h3>{{ st.used }}</h3><p>ব্যবহৃত পিন</p></div>
  <div class="stat-box red"><h3>{{ st.online }}</h3><p>এখন অনলাইন</p></div>
</div>

<!-- PIN Generator -->
<div class="card">
  <h3>⚡ ভাউচার পিন তৈরি করুন</h3>
  <form method="POST" action="{{ url_for('admin_generate_pin') }}"
        style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end">
    <div style="flex:1;min-width:160px">
      <label>কতগুলো পিন?</label>
      <select name="count" class="form-control">
        <option value="1">১টি</option>
        <option value="5" selected>৫টি</option>
        <option value="10">১০টি</option>
        <option value="20">২০টি</option>
        <option value="50">৫০টি</option>
      </select>
    </div>
    <div style="flex:1;min-width:160px">
      <label>কাস্টম পিন (ঐচ্ছিক)</label>
      <input name="custom_pin" class="form-control" placeholder="যেমন: 5566" maxlength="4" pattern="[0-9]{4}">
    </div>
    <div><button type="submit" class="btn btn-success" style="height:46px;padding:0 22px">+ তৈরি করুন</button></div>
  </form>
</div>

<!-- Active Sessions -->
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
    <h3>🟢 এখন কানেক্টেড ডিভাইস</h3>
    <span class="badge badge-primary">{{ sessions|length }} টি</span>
  </div>
  <div class="table-responsive">
    <table>
      <thead><tr><th>Client IP</th><th>পিন</th><th>লগইন সময়</th><th>Action</th></tr></thead>
      <tbody>
      {% for u in sessions %}
      <tr>
        <td><strong>{{ u.client_ip }}</strong></td>
        <td><span class="badge badge-success">{{ u.pin }}</span></td>
        <td>{{ u.login_time }}</td>
        <td>
          <form method="POST" action="{{ url_for('admin_kick_user') }}" style="display:inline">
            <input type="hidden" name="client_ip" value="{{ u.client_ip }}">
            <button class="btn btn-danger btn-sm"
                    onclick="return confirm('ডিসকানেক্ট করবেন?')">Kick</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="4" style="text-align:center;color:var(--muted);padding:20px">কোনো ডিভাইস নেই।</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>"""

# ─── Vouchers ───
VOUCHER_CONTENT = """
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:10px">
    <h3>🎟️ সব ভাউচার পিন</h3>
    <form method="POST" action="{{ url_for('admin_clear_used_pins') }}" style="display:inline">
      <button class="btn btn-danger btn-sm"
              onclick="return confirm('সব ব্যবহৃত পিন মুছবেন?')">🗑️ ব্যবহৃত পিন মুছুন</button>
    </form>
  </div>
  <div class="table-responsive">
    <table>
      <thead><tr><th>PIN</th><th>স্ট্যাটাস</th><th>তৈরি</th><th>ব্যবহার</th><th>IP</th><th>Action</th></tr></thead>
      <tbody>
      {% for p in pins %}
      <tr>
        <td style="font-size:1.1rem;font-weight:700;letter-spacing:3px">{{ p.pin }}</td>
        <td>
          {% if p.status=='active' %}<span class="badge badge-success">ACTIVE</span>
          {% else %}<span class="badge badge-secondary">USED</span>{% endif %}
        </td>
        <td>{{ p.created_at }}</td>
        <td>{{ p.used_at or '—' }}</td>
        <td>{{ p.used_by_ip or '—' }}</td>
        <td>
          <form method="POST" action="{{ url_for('admin_delete_pin', pin_id=p.id) }}" style="display:inline">
            <button class="btn btn-danger btn-sm"
                    onclick="return confirm('পিনটি ডিলিট করবেন?')">ডিলিট</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">কোনো পিন নেই।</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>

{% if active_pins %}
<div class="card">
  <h3>🖨️ প্রিন্টযোগ্য ভাউচার কার্ড</h3>
  <p style="color:var(--muted);font-size:.83rem;margin-bottom:10px">কাস্টমারদের দেওয়ার জন্য:</p>
  <div class="voucher-grid">
    {% for v in active_pins %}
    <div class="voucher-card">
      <small style="font-weight:600;color:var(--primary)">WIFI VOUCHER</small>
      <div class="pin">{{ v.pin }}</div>
      <small style="color:var(--muted)">4-Digit PIN</small>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}"""

# ─── Site Settings ───
SITE_SETTINGS_CONTENT = """
<div class="card" style="max-width:620px;margin:0 auto">
  <h3>🎨 সাইট কাস্টমাইজেশন</h3>
  <p style="color:var(--muted);font-size:.85rem;margin-bottom:18px">
    ক্যাপটিভ পোর্টালের নাম, রঙ ও টেক্সট পরিবর্তন করুন।
  </p>
  <form method="POST">
    <div class="form-group">
      <label>হটস্পট নাম (Navbar-এ দেখাবে)</label>
      <input name="hotspot_name" class="form-control" value="{{ s.hotspot_name }}" required>
    </div>
    <div class="form-group">
      <label>পোর্টাল টাইটেল (বড় শিরোনাম)</label>
      <input name="site_name" class="form-control" value="{{ s.site_name }}" required>
    </div>
    <div class="form-group">
      <label>সাবটাইটেল</label>
      <input name="site_subtitle" class="form-control" value="{{ s.site_subtitle }}">
    </div>
    <div class="form-group">
      <label>পিন বক্সের উপরের নির্দেশনা</label>
      <input name="welcome_text" class="form-control" value="{{ s.welcome_text }}" required>
    </div>
    <div class="form-group">
      <label>ফুটার নোট</label>
      <input name="footer_text" class="form-control" value="{{ s.footer_text }}">
    </div>
    <div class="form-group">
      <label>
        প্রাইমারি রঙ (Header ও বাটনের রঙ)
        <span class="color-preview" id="clrPreview" style="background:{{ s.primary_color }}"></span>
      </label>
      <input type="color" name="primary_color" id="clrPicker"
             class="form-control" value="{{ s.primary_color }}"
             style="height:46px;padding:4px 8px;cursor:pointer"
             oninput="document.getElementById('clrPreview').style.background=this.value">
    </div>
    <div class="form-group">
      <label>গেটওয়ে IP (আপনার হটস্পটের IP)</label>
      <input name="gateway_ip" class="form-control" value="{{ s.gateway_ip }}"
             placeholder="192.168.43.1">
      <small style="color:var(--muted)">Termux-এ <code>ip addr show wlan0</code> দিয়ে বের করুন।</small>
    </div>
    <button type="submit" class="btn btn-primary btn-block" style="padding:12px">
      💾 সেটিংস সেভ করুন
    </button>
  </form>
</div>

<div class="card" style="max-width:620px;margin:22px auto 0">
  <h3>👁️ পোর্টালের প্রিভিউ লিংক</h3>
  <p style="color:var(--muted);font-size:.85rem;margin-bottom:10px">
    সেটিংস সেভ করার পর পোর্টাল এভাবে দেখাবে:
  </p>
  <a href="{{ url_for('portal_index') }}" target="_blank"
     class="btn btn-secondary btn-sm">↗️ পোর্টাল দেখুন (নতুন ট্যাবে)</a>
</div>"""

# ─── Admin Settings ───
ADMIN_SETTINGS_CONTENT = """
<div class="card" style="max-width:520px;margin:0 auto">
  <h3>🔐 অ্যাডমিন পাসওয়ার্ড পরিবর্তন</h3>
  <form method="POST">
    <div class="form-group">
      <label>বর্তমান পাসওয়ার্ড</label>
      <input type="password" name="current_password" class="form-control" required>
    </div>
    <div class="form-group">
      <label>নতুন ইউজারনেম</label>
      <input name="new_username" class="form-control" value="{{ admin.username }}" required>
    </div>
    <div class="form-group">
      <label>নতুন পাসওয়ার্ড</label>
      <input type="password" name="new_password" class="form-control"
             placeholder="কমপক্ষে ৪ অক্ষর" required>
    </div>
    <div class="form-group">
      <label>নতুন পাসওয়ার্ড নিশ্চিত করুন</label>
      <input type="password" name="confirm_password" class="form-control" required>
    </div>
    <button type="submit" class="btn btn-primary btn-block" style="padding:12px">
      আপডেট করুন
    </button>
  </form>
</div>"""

# ─── Termux Guide ───
GUIDE_CONTENT = """
<div class="card">
  <h3>📱 Termux ক্যাপটিভ পোর্টাল সেটআপ গাইড</h3>
  <p style="color:var(--muted);font-size:.88rem;margin-top:5px">
    Android হটস্পটে কানেক্ট হওয়া মাত্র পোর্টাল পপআপ করার জন্য <strong>Root + iptables</strong> প্রয়োজন।
  </p>

  <hr style="border:none;border-top:1px solid var(--border);margin:18px 0">

  <h4 style="margin-bottom:8px">১. ইনস্টল করুন (একবারই)</h4>
  <pre class="terminal">pkg update -y && pkg upgrade -y
pkg install -y python git root-repo
pkg install -y iptables dnsmasq tsu
pip install -r requirements.txt</pre>

  <h4 style="margin:18px 0 8px">২. হটস্পট ইন্টারফেস বের করুন</h4>
  <pre class="terminal">ip addr show
# সচরাচর: wlan0, ap0, wlan1</pre>

  <h4 style="margin:18px 0 8px">৩. Root শেল নিন</h4>
  <pre class="terminal">tsu</pre>

  <h4 style="margin:18px 0 8px">৪. IP Forwarding চালু করুন</h4>
  <pre class="terminal">echo 1 > /proc/sys/net/ipv4/ip_forward</pre>

  <h4 style="margin:18px 0 8px">৫. iptables — Port 80/443 → Flask (8080)</h4>
  <pre class="terminal">iptables -t nat -F
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80  -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 443 -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p udp --dport 53  -j REDIRECT --to-port 5353</pre>

  <h4 style="margin:18px 0 8px">৬. DNS Spoofing — সব ডোমেইন নিজের IP-এ</h4>
  <pre class="terminal">dnsmasq -k -a {{ s.gateway_ip }} --address=/#/{{ s.gateway_ip }} -p 5353 --no-resolv --no-poll &</pre>

  <h4 style="margin:18px 0 8px">৭. Flask সার্ভার চালু করুন (নতুন Termux সেশনে)</h4>
  <pre class="terminal">python app.py</pre>

  <div class="alert alert-info" style="margin-top:18px">
    💡 <strong>কিভাবে কাজ করে:</strong> কানেক্টেড ডিভাইস Google/Apple-এর captive portal check URL-এ request করে →
    dnsmasq সেই domain-কে আপনার IP-এ পয়েন্ট করে → Flask 302 redirect করে → 
    OS স্বয়ংক্রিয়ভাবে <strong>"Sign in to Network"</strong> পপআপ দেখায়।
  </div>
  <div class="alert alert-warning" style="margin-top:10px">
    ⚠️ iptables ছাড়া কাজ করবে না। ম্যানুয়ালি <strong>http://{{ s.gateway_ip }}:8080</strong> দিয়ে এক্সেস করতে হবে।
  </div>
</div>"""

# ─────────────────────────────────────────────────────────────────────────────
# ══  CAPTIVE PORTAL DETECTION ROUTES  ══
# ─────────────────────────────────────────────────────────────────────────────
DETECT_PATHS = [
    "/generate_204", "/gen_204",
    "/hotspot-detect.html",
    "/ncsi.txt", "/connecttest.txt",
    "/canonical.html",
]

@app.route("/generate_204")
@app.route("/gen_204")
@app.route("/hotspot-detect.html")
@app.route("/ncsi.txt")
@app.route("/connecttest.txt")
@app.route("/canonical.html")
def captive_detect():
    ip = client_ip()
    if is_authenticated(ip):
        # Return the "success" signal each OS expects
        p = request.path
        if "204" in p:
            return Response(status=204)
        if "ncsi" in p or "connecttest" in p:
            return Response("Microsoft NCSI", 200, content_type="text/plain")
        if "hotspot" in p:
            return Response("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>", 200)
        return Response("Success", 200)
    # Not authenticated → redirect to portal (triggers OS popup)
    return redirect(url_for("portal_index"), 302)

# ─────────────────────────────────────────────────────────────────────────────
# ══  USER ROUTES  ══
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def portal_index():
    ip = client_ip()
    if is_authenticated(ip):
        return redirect(url_for("portal_status"))
    s   = get_settings()
    css = base_css(s.get("primary_color", "#007bff"))
    return render_template_string(PORTAL_LOGIN_TMPL, s=s, css=css, ip=ip)

@app.route("/login", methods=["GET","POST"])
def login():
    ip = client_ip()
    if request.method == "GET":
        return redirect(url_for("portal_index"))

    pin = request.form.get("pin","").strip()
    if not pin or len(pin) != 4 or not pin.isdigit():
        flash("❌ সঠিক ৪-ডিজিট পিন দিন!", "danger")
        return redirect(url_for("portal_index"))

    conn = get_db()
    voucher = conn.execute("SELECT * FROM vouchers WHERE pin=?", (pin,)).fetchone()

    if not voucher:
        conn.close()
        flash("❌ পিনটি বৈধ নয়!", "danger")
        return redirect(url_for("portal_index"))

    if voucher["status"] != "active":
        conn.close()
        flash("⚠️ এই পিনটি আগেই ব্যবহৃত হয়েছে!", "warning")
        return redirect(url_for("portal_index"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE vouchers SET status='used', used_at=?, used_by_ip=? WHERE id=?",
                 (now, ip, voucher["id"]))
    conn.execute("INSERT OR REPLACE INTO active_sessions (client_ip,pin,login_time,user_agent) VALUES (?,?,?,?)",
                 (ip, pin, now, request.headers.get("User-Agent","")))
    conn.commit()
    conn.close()

    allow_ip(ip)
    flash("✅ সফলভাবে কানেক্টেড! ইন্টারনেট চালু হয়েছে।", "success")
    return redirect(url_for("portal_status"))

@app.route("/status")
def portal_status():
    ip   = client_ip()
    conn = get_db()
    sess = conn.execute("SELECT * FROM active_sessions WHERE client_ip=?", (ip,)).fetchone()
    conn.close()
    if not sess:
        return redirect(url_for("portal_index"))
    s   = get_settings()
    css = base_css(s.get("primary_color","#007bff"))
    return render_template_string(STATUS_TMPL, s=s, css=css, sess=sess)

@app.route("/user-logout", methods=["POST"])
def user_logout():
    ip = client_ip()
    conn = get_db()
    conn.execute("DELETE FROM active_sessions WHERE client_ip=?", (ip,))
    conn.commit()
    conn.close()
    revoke_ip(ip)
    flash("ডিসকানেক্ট হয়েছেন।", "info")
    return redirect(url_for("portal_index"))

# ─────────────────────────────────────────────────────────────────────────────
# ══  ADMIN ROUTES  ══
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    s   = get_settings()
    css = base_css(s.get("primary_color","#007bff"))

    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["admin_logged_in"] = True
            session["admin_username"]  = user["username"]
            session.permanent = True
            flash(f"স্বাগতম {user['username']}!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("❌ ভুল ইউজারনেম বা পাসওয়ার্ড!", "danger")

    return render_template_string(ADMIN_LOGIN_TMPL, css=css)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("লগআউট হয়েছেন।", "info")
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    total  = conn.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM vouchers WHERE status='active'").fetchone()[0]
    used   = conn.execute("SELECT COUNT(*) FROM vouchers WHERE status='used'").fetchone()[0]
    sessions = conn.execute("SELECT * FROM active_sessions ORDER BY login_time DESC").fetchall()
    conn.close()
    st = dict(total=total, active=active, used=used, online=len(sessions))
    html = render_template_string(DASH_CONTENT, st=st, sessions=sessions,
                                  url_for=url_for)
    return render_admin("ড্যাশবোর্ড", "dashboard", html)

@app.route("/admin/vouchers")
@admin_required
def admin_vouchers():
    conn = get_db()
    pins       = conn.execute("SELECT * FROM vouchers ORDER BY id DESC").fetchall()
    active_pins = conn.execute("SELECT * FROM vouchers WHERE status='active' ORDER BY id DESC").fetchall()
    conn.close()
    html = render_template_string(VOUCHER_CONTENT, pins=pins, active_pins=active_pins,
                                  url_for=url_for)
    return render_admin("ভাউচার ম্যানেজমেন্ট", "vouchers", html)

@app.route("/admin/generate-pin", methods=["POST"])
@admin_required
def admin_generate_pin():
    custom = request.form.get("custom_pin","").strip()
    count  = int(request.form.get("count", 1))
    conn   = get_db()
    ok = 0
    if custom:
        if len(custom) != 4 or not custom.isdigit():
            flash("❌ কাস্টম পিন অবশ্যই ৪ সংখ্যার হতে হবে!", "danger")
        else:
            try:
                conn.execute("INSERT INTO vouchers (pin) VALUES (?)", (custom,))
                conn.commit()
                flash(f"✅ পিন {custom} তৈরি হয়েছে!", "success")
            except sqlite3.IntegrityError:
                flash(f"⚠️ পিন {custom} ইতোমধ্যে আছে!", "warning")
    else:
        for _ in range(count):
            for __ in range(100):
                p = str(random.randint(1000,9999))
                try:
                    conn.execute("INSERT INTO vouchers (pin) VALUES (?)", (p,))
                    conn.commit(); ok += 1; break
                except sqlite3.IntegrityError:
                    continue
        flash(f"✅ {ok}টি নতুন পিন তৈরি হয়েছে!", "success")
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-pin/<int:pin_id>", methods=["POST"])
@admin_required
def admin_delete_pin(pin_id):
    conn = get_db()
    conn.execute("DELETE FROM vouchers WHERE id=?", (pin_id,))
    conn.commit(); conn.close()
    flash("🗑️ পিন ডিলিট হয়েছে।", "info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/clear-used", methods=["POST"])
@admin_required
def admin_clear_used_pins():
    conn = get_db()
    n = conn.execute("DELETE FROM vouchers WHERE status='used'").rowcount
    conn.commit(); conn.close()
    flash(f"🗑️ {n}টি ব্যবহৃত পিন মুছে ফেলা হয়েছে।", "info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/kick-user", methods=["POST"])
@admin_required
def admin_kick_user():
    ip = request.form.get("client_ip","")
    if ip:
        conn = get_db()
        conn.execute("DELETE FROM active_sessions WHERE client_ip=?", (ip,))
        conn.commit(); conn.close()
        revoke_ip(ip)
        flash(f"🚫 {ip} ডিসকানেক্ট করা হয়েছে।", "warning")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/site-settings", methods=["GET","POST"])
@admin_required
def admin_site_settings():
    if request.method == "POST":
        fields = ["site_name","site_subtitle","welcome_text",
                  "footer_text","hotspot_name","primary_color","gateway_ip"]
        conn = get_db()
        for f in fields:
            v = request.form.get(f,"").strip()
            if v:
                conn.execute("INSERT OR REPLACE INTO site_settings (key,value) VALUES (?,?)", (f,v))
        conn.commit(); conn.close()
        flash("✅ সাইট সেটিংস সেভ হয়েছে!", "success")
        return redirect(url_for("admin_site_settings"))

    s    = get_settings()
    html = render_template_string(SITE_SETTINGS_CONTENT, s=s, url_for=url_for)
    return render_admin("সাইট সেটিংস", "site", html)

@app.route("/admin/settings", methods=["GET","POST"])
@admin_required
def admin_settings():
    conn  = get_db()
    admin = conn.execute("SELECT * FROM admin_users WHERE username=?",
                         (session["admin_username"],)).fetchone()

    if request.method == "POST":
        cur  = request.form.get("current_password","")
        nu   = request.form.get("new_username","").strip()
        np_  = request.form.get("new_password","")
        cnf  = request.form.get("confirm_password","")

        if not check_password_hash(admin["password_hash"], cur):
            flash("❌ বর্তমান পাসওয়ার্ড ভুল!", "danger")
        elif len(np_) < 4:
            flash("❌ পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে!", "danger")
        elif np_ != cnf:
            flash("❌ নতুন পাসওয়ার্ড মিলছে না!", "danger")
        elif not nu:
            flash("❌ ইউজারনেম খালি রাখা যাবে না!", "danger")
        else:
            conn.execute("UPDATE admin_users SET username=?, password_hash=? WHERE id=?",
                         (nu, generate_password_hash(np_), admin["id"]))
            conn.commit()
            session["admin_username"] = nu
            flash("✅ ক্রেডেনশিয়াল আপডেট হয়েছে!", "success")
            conn.close()
            return redirect(url_for("admin_dashboard"))

    conn.close()
    html = render_template_string(ADMIN_SETTINGS_CONTENT, admin=admin, url_for=url_for)
    return render_admin("অ্যাডমিন সেটিংস", "settings", html)

@app.route("/admin/guide")
@admin_required
def admin_termux_guide():
    s    = get_settings()
    html = render_template_string(GUIDE_CONTENT, s=s, url_for=url_for)
    return render_admin("Termux গাইড", "guide", html)

# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────
def banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║     MikroTik-Style Captive Portal — Hotspot System      ║
╠══════════════════════════════════════════════════════════╣
║  Portal  →  http://0.0.0.0:8080/                        ║
║  Admin   →  http://0.0.0.0:8080/admin                   ║
║  Login   →  admin / admin                               ║
╠══════════════════════════════════════════════════════════╣
║  TERMUX iptables redirect (run as root with tsu):       ║
║  echo 1 > /proc/sys/net/ipv4/ip_forward                 ║
║  iptables -t nat -A PREROUTING -i wlan0 -p tcp          ║
║           --dport 80 -j REDIRECT --to-port 8080         ║
║  iptables -t nat -A PREROUTING -i wlan0 -p udp          ║
║           --dport 53 -j REDIRECT --to-port 5353         ║
║  dnsmasq -k -a 192.168.43.1 --address=/#/192.168.43.1  ║
║          -p 5353 --no-resolv --no-poll &                ║
╚══════════════════════════════════════════════════════════╝
""")

if __name__ == "__main__":
    init_db()
    banner()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
