#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
        MIKROTIK-STYLE CAPTIVE PORTAL & WIFI HOTSPOT MANAGEMENT SYSTEM
                        Optimized for Termux (Android)
=============================================================================
Author: Expert Python & Networking Specialist
Framework: Flask (Single-File Architecture)
Database: Built-in SQLite3
Compatibility: Termux (Android), Linux, Windows (for local testing)
=============================================================================
"""

import os
import sys
import sqlite3
import random
import string
import subprocess
from datetime import datetime
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session, 
    render_template_string, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Application Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "mikrotik_hotspot_secret_key_2026_termux")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hotspot.db")
PORT = 8080
HOST = "0.0.0.0"

# ---------------------------------------------------------------------------
# Database Management
# ---------------------------------------------------------------------------
def get_db():
    """Connects to SQLite database with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes tables and default admin credentials if not existing."""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Admin Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Vouchers / PIN Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pin TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'active', -- active, used
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP,
            used_by_ip TEXT
        )
    """)
    
    # 3. Active Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_ip TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL,
            login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_agent TEXT
        )
    """)
    
    # Insert default admin: admin / admin
    cursor.execute("SELECT id FROM admin_users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed = generate_password_hash("admin")
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", ("admin", hashed))
        print("[*] Default admin created: Username: admin | Password: admin")
        
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Termux / Linux Network Helper Functions (IPTables Integration)
# ---------------------------------------------------------------------------
def execute_system_cmd(cmd_list):
    """Executes a system shell command safely (for Termux root/tsu environments)."""
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, check=False)
        return res.returncode == 0, res.stdout, res.stderr
    except Exception as e:
        return False, "", str(e)

def allow_client_internet(client_ip):
    """
    Grants internet access to the authenticated client IP in iptables.
    Works automatically when Termux is running as root (tsu).
    """
    if os.name != 'nt':  # Linux / Android Termux
        # Insert ACCEPT rule before captive portal REDIRECT in PREROUTING or FORWARD
        # 1. Allow forwarding for this IP
        execute_system_cmd(["iptables", "-I", "FORWARD", "-s", client_ip, "-j", "ACCEPT"])
        execute_system_cmd(["iptables", "-I", "FORWARD", "-d", client_ip, "-j", "ACCEPT"])
        # 2. Bypass captive portal redirect in NAT table
        execute_system_cmd(["iptables", "-t", "nat", "-I", "PREROUTING", "-s", client_ip, "-j", "ACCEPT"])

def revoke_client_internet(client_ip):
    """Removes iptables exception when an admin kicks or user logs out."""
    if os.name != 'nt':
        execute_system_cmd(["iptables", "-D", "FORWARD", "-s", client_ip, "-j", "ACCEPT"])
        execute_system_cmd(["iptables", "-D", "FORWARD", "-d", client_ip, "-j", "ACCEPT"])
        execute_system_cmd(["iptables", "-t", "nat", "-D", "PREROUTING", "-s", client_ip, "-j", "ACCEPT"])

def get_client_ip():
    """Accurately detect client IP, handling proxies if configured."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"

def is_ip_authenticated(client_ip):
    """Checks if client IP has an active session."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM active_sessions WHERE client_ip = ?", (client_ip,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

# ---------------------------------------------------------------------------
# Authentication Decorator
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("অনুগ্রহ করে আগে অ্যাডমিন প্যানেলে লগইন করুন।", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------------------------
# HTML & CSS Embedded Templates (MikroTik Inspired UI)
# ---------------------------------------------------------------------------
BASE_CSS = """
:root {
    --primary: #007bff;
    --primary-dark: #0056b3;
    --secondary: #17a2b8;
    --dark: #1b263b;
    --light: #f4f6f9;
    --surface: #ffffff;
    --success: #28a745;
    --danger: #dc3545;
    --warning: #ffc107;
    --border: #e2e8f0;
    --text: #2d3748;
    --text-muted: #718096;
    --radius: 12px;
    --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

body {
    background-color: var(--light);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

/* Navbar */
.navbar {
    background: var(--dark);
    color: white;
    padding: 14px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 2px 10px rgba(0,0,0,0.15);
}

.navbar .brand {
    font-size: 1.25rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #fff;
    text-decoration: none;
}

.navbar .nav-links {
    display: flex;
    align-items: center;
    gap: 15px;
}

.navbar a.nav-link {
    color: #cbd5e0;
    text-decoration: none;
    font-size: 0.9rem;
    padding: 6px 12px;
    border-radius: 6px;
    transition: 0.2s;
}

.navbar a.nav-link:hover, .navbar a.nav-link.active {
    color: white;
    background: rgba(255, 255, 255, 0.1);
}

.btn-logout {
    background: var(--danger);
    color: white;
    padding: 6px 14px;
    border-radius: 6px;
    text-decoration: none;
    font-size: 0.85rem;
    font-weight: 600;
}

/* Containers */
.container {
    max-width: 1100px;
    margin: 30px auto;
    padding: 0 20px;
    width: 100%;
}

/* Card */
.card {
    background: var(--surface);
    border-radius: var(--radius);
    padding: 24px;
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
    margin-bottom: 24px;
}

/* Form inputs & buttons */
.form-group {
    margin-bottom: 18px;
}

label {
    display: block;
    margin-bottom: 6px;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text);
}

.form-control {
    width: 100%;
    padding: 12px 16px;
    border: 1.5px solid var(--border);
    border-radius: 8px;
    font-size: 1rem;
    outline: none;
    transition: 0.2s;
}

.form-control:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.15);
}

.btn {
    display: inline-block;
    padding: 11px 20px;
    font-size: 0.95rem;
    font-weight: 600;
    border-radius: 8px;
    cursor: pointer;
    border: none;
    text-decoration: none;
    text-align: center;
    transition: 0.2s;
}

.btn-primary { background: var(--primary); color: white; }
.btn-primary:hover { background: var(--primary-dark); }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }
.btn-dark { background: var(--dark); color: white; }
.btn-sm { padding: 6px 12px; font-size: 0.8rem; }
.btn-block { width: 100%; }

/* Alerts */
.alert {
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 0.9rem;
}
.alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
.alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
.alert-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
.alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }

/* Badges */
.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
}
.badge-success { background: #28a745; color: white; }
.badge-secondary { background: #6c757d; color: white; }
.badge-primary { background: #007bff; color: white; }

/* Tables */
.table-responsive {
    overflow-x: auto;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}
th, td {
    padding: 12px 16px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.9rem;
}
th {
    background: #f8fafc;
    color: var(--text-muted);
    font-weight: 600;
}
tr:hover { background: #f8fafc; }

/* Grid stats */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 20px;
    margin-bottom: 25px;
}
.stat-box {
    background: white;
    border-radius: var(--radius);
    padding: 20px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 6px rgba(0,0,0,0.03);
    border-left: 5px solid var(--primary);
}
.stat-box.green { border-left-color: var(--success); }
.stat-box.orange { border-left-color: var(--warning); }
.stat-box.red { border-left-color: var(--danger); }
.stat-box h3 { font-size: 1.8rem; margin-bottom: 5px; color: var(--dark); }
.stat-box p { font-size: 0.85rem; color: var(--text-muted); font-weight: 500; }

/* Terminal code box */
pre.terminal {
    background: #111827;
    color: #10b981;
    padding: 16px;
    border-radius: 8px;
    font-family: monospace;
    font-size: 0.85rem;
    overflow-x: auto;
    line-height: 1.5;
    margin: 10px 0;
}

/* Voucher Cards Preview for Printing */
.voucher-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 15px;
    margin-top: 15px;
}
.voucher-card {
    border: 2px dashed #007bff;
    background: #f0f7ff;
    padding: 14px;
    border-radius: 8px;
    text-align: center;
}
.voucher-card .pin {
    font-size: 1.6rem;
    font-weight: 800;
    letter-spacing: 5px;
    color: #0056b3;
    margin: 6px 0;
}
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MikroTik Hotspot Portal</title>
    <style>
        {{ css | safe }}
        body {
            background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .portal-card {
            background: #ffffff;
            width: 100%;
            max-width: 400px;
            border-radius: 16px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            overflow: hidden;
            text-align: center;
        }
        .portal-header {
            background: #007bff;
            padding: 30px 20px;
            color: white;
        }
        .portal-header .logo-icon {
            font-size: 40px;
            margin-bottom: 8px;
        }
        .portal-header h2 {
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
        .portal-header p {
            font-size: 0.85rem;
            opacity: 0.9;
            margin-top: 4px;
        }
        .portal-body {
            padding: 28px 24px;
        }
        .pin-input {
            letter-spacing: 12px;
            font-size: 2rem;
            text-align: center;
            font-weight: 800;
            color: #0d1b2a;
            border: 2px solid #cbd5e0;
            height: 60px;
            border-radius: 10px;
        }
        .pin-input:focus {
            border-color: #007bff;
        }
        .client-info {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
        }
        .footer-note {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 20px;
        }
        .admin-link {
            display: inline-block;
            margin-top: 15px;
            font-size: 0.8rem;
            color: #64748b;
            text-decoration: none;
        }
        .admin-link:hover { text-decoration: underline; color: #007bff; }
    </style>
</head>
<body>
    <div class="portal-card">
        <div class="portal-header">
            <div class="logo-icon">📶</div>
            <h2>WIFI HOTSPOT PORTAL</h2>
            <p>MikroTik High Speed Wireless Network</p>
        </div>
        <div class="portal-body">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <div class="client-info">
                <span>🌐 Client IP: <strong>{{ client_ip }}</strong></span>
                <span>⚡ Status: <strong>লগইন প্রয়োজন</strong></span>
            </div>

            <form action="{{ url_for('login') }}" method="POST">
                <div class="form-group">
                    <label for="pin">৪-ডিজিট ভাউচার পিন দিন (Voucher PIN)</label>
                    <input 
                        type="text" 
                        name="pin" 
                        id="pin" 
                        class="form-control pin-input" 
                        placeholder="••••" 
                        maxlength="4" 
                        pattern="[0-9]{4}" 
                        inputmode="numeric" 
                        required 
                        autofocus
                    >
                </div>
                <button type="submit" class="btn btn-primary btn-block" style="padding: 14px; font-size: 1.05rem;">
                    🚀 কানেক্ট করুন (Connect Internet)
                </button>
            </form>

            <p class="footer-note">
                ভাউচার পিন পেতে অনুগ্রহ করে হটস্পট অ্যাডমিনের সাথে যোগাযোগ করুন।
            </p>
            <a href="{{ url_for('admin_login') }}" class="admin-link">⚙️ Admin Login</a>
        </div>
    </div>
</body>
</html>
"""

STATUS_HTML = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connected - WiFi Hotspot</title>
    <style>
        {{ css | safe }}
        body {
            background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .status-card {
            background: white;
            border-radius: 16px;
            max-width: 440px;
            width: 100%;
            padding: 32px 24px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            text-align: center;
        }
        .success-icon {
            font-size: 56px;
            color: #28a745;
            margin-bottom: 12px;
        }
        .info-table {
            margin: 20px 0;
            background: #f8fafc;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }
        .info-table td {
            padding: 10px 14px;
            font-size: 0.88rem;
        }
        .info-table td:first-child {
            color: var(--text-muted);
            font-weight: 500;
        }
        .info-table td:last-child {
            text-align: right;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="status-card">
        <div class="success-icon">✓</div>
        <h2 style="color: #28a745; margin-bottom: 6px;">ইন্টারনেট এক্টিভেটেড!</h2>
        <p style="color: var(--text-muted); font-size: 0.9rem;">আপনি সফলভাবে ওয়াইফাই নেটওয়ার্কে যুক্ত হয়েছেন।</p>

        <table class="info-table">
            <tr>
                <td>IP Address:</td>
                <td>{{ session_data.client_ip }}</td>
            </tr>
            <tr>
                <td>Voucher PIN:</td>
                <td>{{ session_data.pin }}</td>
            </tr>
            <tr>
                <td>Login Time:</td>
                <td>{{ session_data.login_time }}</td>
            </tr>
            <tr>
                <td>Status:</td>
                <td><span class="badge badge-success">Online</span></td>
            </tr>
        </table>

        <div style="display: flex; gap: 10px;">
            <a href="https://www.google.com" class="btn btn-primary" style="flex: 1;">🌐 গুগল ব্রাউজ করুন</a>
            <form action="{{ url_for('user_logout') }}" method="POST" style="flex: 1;">
                <button type="submit" class="btn btn-danger btn-block">ডিসকানেক্ট</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

ADMIN_BASE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - Hotspot Admin</title>
    <style>{{ css | safe }}</style>
</head>
<body>
    <nav class="navbar">
        <a href="{{ url_for('admin_dashboard') }}" class="brand">
            📡 MikroTik Hotspot Panel
        </a>
        <div class="nav-links">
            <a href="{{ url_for('admin_dashboard') }}" class="nav-link {% if active_page == 'dashboard' %}active{% endif %}">📊 ড্যাশবোর্ড</a>
            <a href="{{ url_for('admin_vouchers') }}" class="nav-link {% if active_page == 'vouchers' %}active{% endif %}">🎟️ ভাউচার পিন</a>
            <a href="{{ url_for('admin_termux_guide') }}" class="nav-link {% if active_page == 'guide' %}active{% endif %}">📱 টার্মাক্স গাইড</a>
            <a href="{{ url_for('admin_settings') }}" class="nav-link {% if active_page == 'settings' %}active{% endif %}">⚙️ সেটিংস</a>
            <a href="{{ url_for('admin_logout') }}" class="btn-logout">লগআউট</a>
        </div>
    </nav>

    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login - Hotspot Panel</title>
    <style>
        {{ css | safe }}
        body {
            background: #0f172a;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-box {
            background: white;
            border-radius: 14px;
            padding: 30px;
            width: 100%;
            max-width: 380px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
        }
        .login-box h3 {
            text-align: center;
            margin-bottom: 20px;
            color: #0f172a;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h3>🔐 অ্যাডমিন লগইন</h3>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form action="{{ url_for('admin_login') }}" method="POST">
            <div class="form-group">
                <label for="username">ইউজারনেম (Username)</label>
                <input type="text" name="username" id="username" class="form-control" placeholder="admin" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">পাসওয়ার্ড (Password)</label>
                <input type="password" name="password" id="password" class="form-control" placeholder="admin" required>
            </div>
            <button type="submit" class="btn btn-primary btn-block" style="margin-top: 10px;">লগইন করুন</button>
        </form>
        <div style="text-align: center; margin-top: 15px;">
            <a href="{{ url_for('portal_index') }}" style="font-size: 0.85rem; color: #64748b; text-decoration: none;">← ক্যাপটিভ পোর্টালে ফিরুন</a>
        </div>
    </div>
</body>
</html>
"""

ADMIN_DASHBOARD_CONTENT = """
{% extends base_template %}
{% block content %}
    <div class="stats-grid">
        <div class="stat-box">
            <h3>{{ stats.total_pins }}</h3>
            <p>মোট জেনারেটেড পিন (Total)</p>
        </div>
        <div class="stat-box green">
            <h3>{{ stats.active_pins }}</h3>
            <p>অ্যাক্টিভ পিন (Unused)</p>
        </div>
        <div class="stat-box orange">
            <h3>{{ stats.used_pins }}</h3>
            <p>ব্যবহৃত পিন (Used)</p>
        </div>
        <div class="stat-box red">
            <h3>{{ stats.active_users }}</h3>
            <p>বর্তমানে অনলাইনে কানেক্টেড ইউজার</p>
        </div>
    </div>

    <!-- Quick PIN Generator -->
    <div class="card">
        <h3 style="margin-bottom: 15px;">⚡ দ্রুত ৪-ডিজিট ভাউচার পিন তৈরি করুন</h3>
        <form action="{{ url_for('admin_generate_pin') }}" method="POST" style="display: flex; gap: 15px; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 180px;">
                <label for="count">কতগুলো পিন জেনারেট করবেন?</label>
                <select name="count" id="count" class="form-control">
                    <option value="1">১টি পিন</option>
                    <option value="5" selected>৫টি পিন (র‍্যান্ডম)</option>
                    <option value="10">১০টি পিন (র‍্যান্ডম)</option>
                    <option value="20">২০টি পিন (র‍্যান্ডম)</option>
                </select>
            </div>
            <div style="flex: 1; min-width: 180px;">
                <label for="custom_pin">কাস্টম ৪-ডিজিট পিন (ঐচ্ছিক):</label>
                <input type="text" name="custom_pin" id="custom_pin" class="form-control" placeholder="যেমন: 5566" maxlength="4" pattern="[0-9]{4}">
            </div>
            <div style="display: flex; align-items: flex-end;">
                <button type="submit" class="btn btn-success" style="height: 48px; padding: 0 24px;">+ পিন তৈরি করুন</button>
            </div>
        </form>
    </div>

    <!-- Active Connected Users -->
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3>🟢 বর্তমানে কানেক্টেড ইউজারস (Active Sessions)</h3>
            <span class="badge badge-primary">{{ active_sessions|length }} টি ডিভাইস</span>
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Client IP</th>
                        <th>ব্যবহৃত ভাউচার পিন</th>
                        <th>লগইন সময়</th>
                        <th>অ্যাকশন</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in active_sessions %}
                    <tr>
                        <td><strong>{{ user.client_ip }}</strong></td>
                        <td><span class="badge badge-success">{{ user.pin }}</span></td>
                        <td>{{ user.login_time }}</td>
                        <td>
                            <form action="{{ url_for('admin_kick_user') }}" method="POST" style="display:inline;">
                                <input type="hidden" name="client_ip" value="{{ user.client_ip }}">
                                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('এই ডিভাইসটিকে ডিসকানেক্ট করতে চান?');">Kick / Disconnect</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 20px;">
                            বর্তমানে কোনো ইউজার কানেক্টেড নেই।
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
{% endblock %}
"""

ADMIN_VOUCHERS_CONTENT = """
{% extends base_template %}
{% block content %}
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px;">
            <h3>🎟️ ভাউচার পিন ম্যানেজমেন্ট (All PINs)</h3>
            <div>
                <form action="{{ url_for('admin_clear_used_pins') }}" method="POST" style="display:inline;">
                    <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('সব ব্যবহৃত পিন ডিলিট করবেন?');">
                        🗑️ সব ব্যবহৃত পিন মুছে ফেলুন
                    </button>
                </form>
            </div>
        </div>

        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>ভাউচার পিন</th>
                        <th>স্ট্যাটাস</th>
                        <th>তৈরির তারিখ</th>
                        <th>ব্যবহারের সময়</th>
                        <th>ব্যবহারকারী IP</th>
                        <th>অ্যাকশন</th>
                    </tr>
                </thead>
                <tbody>
                    {% for p in pins %}
                    <tr>
                        <td style="font-size: 1.1rem; font-weight: 700; letter-spacing: 2px;">{{ p.pin }}</td>
                        <td>
                            {% if p.status == 'active' %}
                                <span class="badge badge-success">ACTIVE</span>
                            {% else %}
                                <span class="badge badge-secondary">USED</span>
                            {% endif %}
                        </td>
                        <td>{{ p.created_at }}</td>
                        <td>{{ p.used_at or '-' }}</td>
                        <td>{{ p.used_by_ip or '-' }}</td>
                        <td>
                            <form action="{{ url_for('admin_delete_pin', pin_id=p.id) }}" method="POST" style="display:inline;">
                                <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('এই পিনটি ডিলিট করতে চান?');">ডিলিট</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">
                            কোনো ভাউচার পিন তৈরি করা হয়নি।
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Active Vouchers Print Preview Card -->
    {% if active_pins_list %}
    <div class="card">
        <h3>🖨️ প্রিন্ট ও কাস্টমারদের জন্য রেডি ভাউচার (Active Vouchers)</h3>
        <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 4px;">নিচের ভাউচারগুলো ইউজারদের হটস্পট ব্যবহারের জন্য দিতে পারেন:</p>
        <div class="voucher-grid">
            {% for v in active_pins_list %}
            <div class="voucher-card">
                <small style="font-weight: 600; color: #007bff;">WIFI ACCESS VOUCHER</small>
                <div class="pin">{{ v.pin }}</div>
                <small style="color: #64748b;">4-Digit Login PIN</small>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}
{% endblock %}
"""

ADMIN_SETTINGS_CONTENT = """
{% extends base_template %}
{% block content %}
    <div class="card" style="max-width: 550px; margin: 0 auto;">
        <h3 style="margin-bottom: 20px;">🔐 অ্যাডমিন পাসওয়ার্ড পরিবর্তন</h3>
        <form action="{{ url_for('admin_settings') }}" method="POST">
            <div class="form-group">
                <label for="current_password">বর্তমান পাসওয়ার্ড (Current Password)</label>
                <input type="password" name="current_password" id="current_password" class="form-control" required>
            </div>
            <div class="form-group">
                <label for="new_username">নতুন ইউজারনেম (New Username)</label>
                <input type="text" name="new_username" id="new_username" class="form-control" value="{{ admin_user.username }}" required>
            </div>
            <div class="form-group">
                <label for="new_password">নতুন পাসওয়ার্ড (New Password)</label>
                <input type="password" name="new_password" id="new_password" class="form-control" placeholder="কমপক্ষে ৪ অক্ষরের পাসওয়ার্ড" required>
            </div>
            <div class="form-group">
                <label for="confirm_password">নতুন পাসওয়ার্ড নিশ্চিত করুন (Confirm)</label>
                <input type="password" name="confirm_password" id="confirm_password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary btn-block" style="padding: 12px;">পাসওয়ার্ড আপডেট করুন</button>
        </form>
    </div>
{% endblock %}
"""

ADMIN_GUIDE_CONTENT = """
{% extends base_template %}
{% block content %}
    <div class="card">
        <h3>📱 টার্মাক্স (Termux) ওয়াইফাই হটস্পট ও ক্যাপটিভ পোর্টাল সেটআপ গাইড</h3>
        <p style="color: var(--text-muted); margin-top: 6px; font-size: 0.9rem;">
            অ্যান্ড্রয়েড ফোনে ওয়াইফাই হটস্পট অন করে টার্মাক্সকে MikroTik-এর মতো ক্যাপটিভ পোর্টাল রাউটার বানানোর জন্য নিচের ধাপগুলো অনুসরণ করুন।
        </p>
        
        <hr style="margin: 20px 0; border: none; border-top: 1px solid var(--border);">

        <h4 style="margin-bottom: 8px; color: var(--dark);">১. প্রয়োজনীয় প্যাকেজ ইনস্টল করুন:</h4>
        <pre class="terminal">pkg update && pkg install -y python iptables dnsmasq tsu root-repo
pip install flask</pre>

        <h4 style="margin: 20px 0 8px; color: var(--dark);">২. রুট শেল ও আইপি ফরওয়ার্ডিং এনাবল করুন:</h4>
        <pre class="terminal"># রুট এক্সেস নিন
tsu

# কার্নেলে প্যাকেট ফরওয়ার্ডিং অন করুন
echo 1 > /proc/sys/net/ipv4/ip_forward</pre>

        <h4 style="margin: 20px 0 8px; color: var(--dark);">৩. ওয়াইফাই হটস্পট ইন্টারফেস শনাক্ত করুন:</h4>
        <pre class="terminal"># ইন্টারফেস দেখতে
ip addr show
# সচরাচর অ্যান্ড্রয়েডে হটস্পট ইন্টারফেস wlan0, wlan1 বা ap0 হয়।
# আপনার মোবাইলের হটস্পটের গেটওয়ে IP সাধারণত 192.168.43.1 হয়।</pre>

        <h4 style="margin: 20px 0 8px; color: var(--dark);">৪. iptables দিয়ে সমস্ত HTTP ট্রাফিক ফ্লাস্কে (Port 8080) রিডাইরেক্ট করুন:</h4>
        <pre class="terminal"># ক্যাপটিভ পোর্টাল রিডাইরেকশন রুল (Port 80 to 8080)
iptables -t nat -F
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j REDIRECT --to-port 8080

# ডিএনএস রিডাইরেকশন (Port 53)
iptables -t nat -A PREROUTING -i wlan0 -p udp --dport 53 -j REDIRECT --to-port 5353</pre>

        <h4 style="margin: 20px 0 8px; color: var(--dark);">৫. dnsmasq দিয়ে সব ডোমেইনকে আপনার আইপিতে পয়েন্ট করুন (DNS Spoofing):</h4>
        <pre class="terminal"># সমস্ত DNS কুয়েরিকে আপনার টার্মাক্স সার্ভারে (192.168.43.1) পাঠাতে:
dnsmasq -k -a 192.168.43.1 --address=/#/192.168.43.1 -p 5353 &</pre>

        <h4 style="margin: 20px 0 8px; color: var(--dark);">৬. ফ্লাস্ক অ্যাপটি ব্যাকগ্রাউন্ডে বা স্ক্রিনে চালু রাখুন:</h4>
        <pre class="terminal">python app.py</pre>

        <div class="alert alert-info" style="margin-top: 20px;">
            💡 <strong>টিপস:</strong> যখনই কোনো ক্লায়েন্ট মোবাইল আপনার হটস্পটে কানেক্ট করবে, অ্যান্ড্রয়েড বা আইফোনের নিজস্ব অপারেটিং সিস্টেম স্বয়ংক্রিয়ভাবে Captive Portal Detection রিকোয়েস্ট পাঠাবে এবং সাথে সাথে ভাউচার লগইন পেজ স্ক্রিনে পপআপ হয়ে উঠবে!
        </div>
    </div>
{% endblock %}
"""

# ---------------------------------------------------------------------------
# Captive Portal Detection Routes (Android, Apple, Windows, Chrome)
# ---------------------------------------------------------------------------
@app.route("/generate_204")          # Android OS captive portal check
@app.route("/gen_204")               # Android alternative
@app.route("/hotspot-detect.html")   # Apple iOS & macOS captive portal check
@app.route("/ncsi.txt")              # Windows NCSI check
@app.route("/canonical.html")        # Firefox / Chrome captive check
@app.route("/connecttest.txt")       # Windows 10/11
def captive_detect():
    """
    Standard captive portal detection endpoints.
    If authenticated, returns expected success signals.
    If unauthenticated, redirects to captive login portal.
    """
    client_ip = get_client_ip()
    if is_ip_authenticated(client_ip):
        # Respond as authorized based on endpoint
        if request.path.endswith("204"):
            return ("", 204)
        elif request.path.endswith("ncsi.txt"):
            return ("Microsoft NCSI", 200, {"Content-Type": "text/plain"})
        elif request.path.endswith("hotspot-detect.html"):
            return ("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>", 200)
        return ("Success", 200)
    
    # Not authenticated: Redirect immediately to login page to trigger OS portal popup
    return redirect(url_for("portal_index"))

# ---------------------------------------------------------------------------
# User Captive Portal Routes
# ---------------------------------------------------------------------------
@app.route("/")
def portal_index():
    client_ip = get_client_ip()
    if is_ip_authenticated(client_ip):
        return redirect(url_for("portal_status"))
    return render_template_string(LOGIN_HTML, css=BASE_CSS, client_ip=client_ip)

@app.route("/login", methods=["GET", "POST"])
def login():
    client_ip = get_client_ip()
    
    if request.method == "GET":
        if is_ip_authenticated(client_ip):
            return redirect(url_for("portal_status"))
        return render_template_string(LOGIN_HTML, css=BASE_CSS, client_ip=client_ip)

    pin = request.form.get("pin", "").strip()
    
    if not pin or len(pin) != 4 or not pin.isdigit():
        flash("❌ অনুগ্রহ করে সঠিক ৪-ডিজিটের সংখ্যা পিন দিন!", "danger")
        return redirect(url_for("portal_index"))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vouchers WHERE pin = ?", (pin,))
    voucher = cursor.fetchone()

    if not voucher:
        conn.close()
        flash("❌ অবৈধ ভাউচার পিন! পুনরায় চেষ্টা করুন।", "danger")
        return redirect(url_for("portal_index"))

    if voucher["status"] != "active":
        conn.close()
        flash("⚠️ এই পিনটি ইতোমধ্যে ব্যবহার করা হয়েছে!", "warning")
        return redirect(url_for("portal_index"))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Mark voucher as used
    cursor.execute(
        "UPDATE vouchers SET status = 'used', used_at = ?, used_by_ip = ? WHERE id = ?",
        (now_str, client_ip, voucher["id"])
    )
    # Register active session
    cursor.execute(
        "INSERT OR REPLACE INTO active_sessions (client_ip, pin, login_time, user_agent) VALUES (?, ?, ?, ?)",
        (client_ip, pin, now_str, request.headers.get("User-Agent", ""))
    )
    conn.commit()
    conn.close()

    # Trigger iptables internet allow in Termux root
    allow_client_internet(client_ip)

    flash("✅ সফলভাবে অথেনটিকেটেড! ইন্টারনেট সংযোগ চালু হয়েছে।", "success")
    return redirect(url_for("portal_status"))

@app.route("/status")
def portal_status():
    client_ip = get_client_ip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_sessions WHERE client_ip = ?", (client_ip,))
    session_data = cursor.fetchone()
    conn.close()

    if not session_data:
        return redirect(url_for("portal_index"))

    return render_template_string(STATUS_HTML, css=BASE_CSS, session_data=session_data)

@app.route("/user-logout", methods=["POST"])
def user_logout():
    client_ip = get_client_ip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_sessions WHERE client_ip = ?", (client_ip,))
    conn.commit()
    conn.close()

    # Revoke iptables rule
    revoke_client_internet(client_ip)

    flash("ℹ️ আপনি সফলভাবে ডিসকানেক্ট হয়েছেন।", "info")
    return redirect(url_for("portal_index"))

# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["admin_logged_in"] = True
            session["admin_username"] = user["username"]
            flash(f"স্বাগতম {user['username']}! অ্যাডমিন প্যানেলে সফলভাবে লগইন করেছেন।", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("❌ ভুল ইউজারনেম বা পাসওয়ার্ড!", "danger")

    return render_template_string(ADMIN_LOGIN_HTML, css=BASE_CSS)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    flash("সফলভাবে লগআউট হয়েছেন।", "info")
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM vouchers")
    total_pins = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS active FROM vouchers WHERE status = 'active'")
    active_pins = cursor.fetchone()["active"]

    cursor.execute("SELECT COUNT(*) AS used FROM vouchers WHERE status = 'used'")
    used_pins = cursor.fetchone()["used"]

    cursor.execute("SELECT * FROM active_sessions ORDER BY login_time DESC")
    active_sessions = cursor.fetchall()
    active_users = len(active_sessions)

    stats = {
        "total_pins": total_pins,
        "active_pins": active_pins,
        "used_pins": used_pins,
        "active_users": active_users
    }

    conn.close()
    return render_template_string(
        ADMIN_DASHBOARD_CONTENT,
        base_template=ADMIN_BASE,
        css=BASE_CSS,
        title="ড্যাশবোর্ড",
        active_page="dashboard",
        stats=stats,
        active_sessions=active_sessions
    )

@app.route("/admin/vouchers")
@admin_required
def admin_vouchers():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vouchers ORDER BY id DESC")
    pins = cursor.fetchall()

    cursor.execute("SELECT * FROM vouchers WHERE status = 'active' ORDER BY id DESC")
    active_pins_list = cursor.fetchall()
    conn.close()

    return render_template_string(
        ADMIN_VOUCHERS_CONTENT,
        base_template=ADMIN_BASE,
        css=BASE_CSS,
        title="ভাউচার ম্যানেজমেন্ট",
        active_page="vouchers",
        pins=pins,
        active_pins_list=active_pins_list
    )

@app.route("/admin/generate-pin", methods=["POST"])
@admin_required
def admin_generate_pin():
    custom_pin = request.form.get("custom_pin", "").strip()
    count = int(request.form.get("count", 1))

    conn = get_db()
    cursor = conn.cursor()

    generated_count = 0
    if custom_pin:
        if len(custom_pin) != 4 or not custom_pin.isdigit():
            flash("❌ কাস্টম পিন অবশ্যই ঠিক ৪ ডিজিটের সংখ্যা হতে হবে!", "danger")
            conn.close()
            return redirect(url_for("admin_dashboard"))
        
        try:
            cursor.execute("INSERT INTO vouchers (pin, status) VALUES (?, 'active')", (custom_pin,))
            conn.commit()
            flash(f"✅ কাস্টম পিন {custom_pin} সফলভাবে তৈরি হয়েছে!", "success")
        except sqlite3.IntegrityError:
            flash(f"⚠️ পিন {custom_pin} ইতোমধ্যে ডাটাবেসে বিদ্যমান!", "warning")
    else:
        # Generate random 4-digit PINs
        for _ in range(count):
            attempts = 0
            while attempts < 50:
                rand_pin = f"{random.randint(1000, 9999)}"
                try:
                    cursor.execute("INSERT INTO vouchers (pin, status) VALUES (?, 'active')", (rand_pin,))
                    conn.commit()
                    generated_count += 1
                    break
                except sqlite3.IntegrityError:
                    attempts += 1
                    continue
        flash(f"✅ মোট {generated_count}টি নতুন ৪-ডিজিটের ভাউচার পিন তৈরি হয়েছে!", "success")

    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-pin/<int:pin_id>", methods=["POST"])
@admin_required
def admin_delete_pin(pin_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vouchers WHERE id = ?", (pin_id,))
    conn.commit()
    conn.close()
    flash("🗑️ ভাউচার পিন ডিলিট করা হয়েছে।", "info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/clear-used", methods=["POST"])
@admin_required
def admin_clear_used_pins():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vouchers WHERE status = 'used'")
    count = cursor.rowcount
    conn.commit()
    conn.close()
    flash(f"🗑️ মোট {count}টি ব্যবহৃত পিন মুছে ফেলা হয়েছে।", "info")
    return redirect(url_for("admin_vouchers"))

@app.route("/admin/kick-user", methods=["POST"])
@admin_required
def admin_kick_user():
    client_ip = request.form.get("client_ip")
    if client_ip:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM active_sessions WHERE client_ip = ?", (client_ip,))
        conn.commit()
        conn.close()
        revoke_client_internet(client_ip)
        flash(f"🚫 ডিভাইস ({client_ip}) সফলভাবে নেটওয়ার্ক থেকে ডিসকানেক্ট করা হয়েছে।", "warning")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_users WHERE username = ?", (session.get("admin_username"),))
    admin_user = cursor.fetchone()

    if request.method == "POST":
        current_password = request.form.get("current_password", "").strip()
        new_username = request.form.get("new_username", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not check_password_hash(admin_user["password_hash"], current_password):
            flash("❌ বর্তমান পাসওয়ার্ড ভুল!", "danger")
        elif len(new_password) < 4:
            flash("❌ নতুন পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে!", "danger")
        elif new_password != confirm_password:
            flash("❌ নতুন পাসওয়ার্ড এবং কনফার্মেশন মিলছে না!", "danger")
        elif not new_username:
            flash("❌ ইউজারনেম খালি রাখা যাবে না!", "danger")
        else:
            new_hash = generate_password_hash(new_password)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE admin_users SET username = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                (new_username, new_hash, now_str, admin_user["id"])
            )
            conn.commit()
            session["admin_username"] = new_username
            flash("✅ ইউজারনেম ও পাসওয়ার্ড সফলভাবে আপডেট করা হয়েছে!", "success")
            conn.close()
            return redirect(url_for("admin_dashboard"))

    conn.close()
    return render_template_string(
        ADMIN_SETTINGS_CONTENT,
        base_template=ADMIN_BASE,
        css=BASE_CSS,
        title="অ্যাডমিন সেটিংস",
        active_page="settings",
        admin_user=admin_user
    )

@app.route("/admin/guide")
@admin_required
def admin_termux_guide():
    return render_template_string(
        ADMIN_GUIDE_CONTENT,
        base_template=ADMIN_BASE,
        css=BASE_CSS,
        title="টার্মাক্স গাইড",
        active_page="guide"
    )

# ---------------------------------------------------------------------------
# CLI Guide & Banner
# ---------------------------------------------------------------------------
def print_startup_banner():
    banner = f"""
=============================================================================
  __  __ _ _           _____ _ _      _    _       _                  _   
 |  \/  (_) |         |_   _(_) |    | |  | |     | |                | |  
 | \  / |_| | ___ __ ___| |  _| | __ | |__| | ___ | |_ ___ _ __   ___| |_ 
 | |\/| | | |/ / '__/ _ \ | | | |/ / |  __  |/ _ \| __/ __| '_ \ / _ \ __|
 | |  | | |   <| | | (_) || | | |   <  | |  | | (_) | |_\__ \ |_) | (_) | |_ 
 |_|  |_|_|_|\_\_|  \___/ |_| |_|_|\_\ |_|  |_|\___/ \__|___/ .__/ \___/\__|
                                                            | |              
                                                            |_|              
           MIKROTIK-STYLE CAPTIVE PORTAL & HOTSPOT SYSTEM
=============================================================================
[+] Server running at: http://{HOST}:{PORT}
[+] Captive Portal:   http://{HOST}:{PORT}/
[+] Admin Dashboard:  http://{HOST}:{PORT}/admin
[+] Default Admin:    Username: admin | Password: admin
[+] Database:         {DB_PATH}
=============================================================================
>>> TERMUX HOTSPOT REDIRECTION COMMANDS (Run as root using 'tsu'):
-----------------------------------------------------------------------------
1. Enable IP Forwarding:
   echo 1 > /proc/sys/net/ipv4/ip_forward

2. Redirect Port 80 HTTP traffic to Flask:
   iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port {PORT}

3. DNS Redirection (to catch captive portal checks):
   iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-port 5353
   dnsmasq -k -a 192.168.43.1 --address=/#/192.168.43.1 -p 5353 &
=============================================================================
"""
    print(banner)

# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print_startup_banner()
    app.run(host=HOST, port=PORT, debug=False)
