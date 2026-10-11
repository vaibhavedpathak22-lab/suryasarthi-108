#!/usr/bin/env python3
"""
Suryasarthi 108 - Multi-User SQLite Server & Privacy-First Web API
==================================================================
Serves the web application and persists all yoga practice records,
configurations, hydration logs, and statistics into an isolated SQLite database
with strict per-user privacy, authentication, and Admin portal management.

Features:
- Dedicated Port 8088 (avoids collisions with standard 8000/8080 ports).
- Isolated SQLite database (suryasarthi_users.db).
- Multi-user authentication (Registration, Login, Session Tokens).
- Strict user data isolation: Users can NEVER access each other's data.
- Admin Portal: Only the admin can inspect all users' records and system metrics.
- Offline-friendly: Gracefully syncs when connected, allows local offline practice.
- Zero external pip dependencies (Pure Python 3.12 standard library).
"""

import http.server
import socketserver
import sqlite3
import json
import os
import sys
import hashlib
import secrets
import socket
from datetime import datetime
from urllib.parse import urlparse, parse_qs

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Configuration
PORT = int(os.environ.get("PORT", 8088))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "suryasarthi_users.db")


def hash_password(password: str, salt: str = None) -> str:
    """Hash password with SHA-256 and salt."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored salt$hash."""
    try:
        salt, hashed = stored_hash.split("$")
        check = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return secrets.compare_digest(hashed, check)
    except Exception:
        return False


def get_local_ip():
    """Retrieve the primary local LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def init_db():
    """Initialize the SQLite database schema with multi-user isolation."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # 1. Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. User Sessions Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 3. User Config Table (scoped to user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_configs (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 4. User Stats Table (scoped to user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 5. User Workout History Table (scoped to user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_workouts (
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                sets INTEGER DEFAULT 0,
                time_ms INTEGER DEFAULT 0,
                goal INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, date),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 6. User Water Logs Table (scoped to user_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_water_logs (
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                glasses INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, date),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 7. User Snapshots Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Seed default Admin account if not present
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            admin_hash = hash_password("admin108")
            cursor.execute("""
                INSERT INTO users (username, password_hash, name, role)
                VALUES ('admin', ?, 'Suryasarthi Admin', 'admin')
            """, (admin_hash,))

        conn.commit()


def get_user_by_token(token: str):
    """Retrieve user dictionary given a session token."""
    if not token:
        return None
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.username, u.name, u.role, u.created_at
            FROM users u
            JOIN user_sessions s ON u.id = s.user_id
            WHERE s.token = ?
        """, (token,))
        row = cursor.fetchone()
        return dict(row) if row else None


def load_user_data_from_db(user_id: int):
    """Extract and reconstruct { cfg, data } payload for a specific user."""
    cfg = {}
    data = {
        "history": {},
        "totalAllTime": 0,
        "totalTimeMs": 0,
        "programDay": 1,
        "lastDate": "",
        "baseGoal": 0,
        "goalDate": "",
        "lastGoal": 0,
        "lastCompletedGoal": 0,
        "lastRecoveryAt": 0,
        "waterLogs": {},
        "reels": {}
    }

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Load User Config
        cursor.execute("SELECT key, value FROM user_configs WHERE user_id = ?", (user_id,))
        for row in cursor.fetchall():
            k, v = row["key"], row["value"]
            try:
                cfg[k] = json.loads(v)
            except Exception:
                cfg[k] = v

        # Load User Stats
        cursor.execute("SELECT key, value FROM user_stats WHERE user_id = ?", (user_id,))
        for row in cursor.fetchall():
            k, v = row["key"], row["value"]
            try:
                parsed_val = json.loads(v)
                data[k] = parsed_val
            except Exception:
                data[k] = v

        # Load Workout History
        cursor.execute("""
            SELECT date, sets, time_ms, goal
            FROM user_workouts
            WHERE user_id = ?
            ORDER BY date ASC
        """, (user_id,))
        for row in cursor.fetchall():
            data["history"][row["date"]] = {
                "sets": row["sets"] or 0,
                "timeMs": row["time_ms"] or 0,
                "goal": row["goal"] or 0
            }

        # Load Water Logs
        cursor.execute("""
            SELECT date, glasses
            FROM user_water_logs
            WHERE user_id = ?
            ORDER BY date ASC
        """, (user_id,))
        for row in cursor.fetchall():
            data["waterLogs"][row["date"]] = row["glasses"] or 0

    return {"cfg": cfg, "data": data}


def save_user_data_to_db(user_id: int, payload: dict, create_snapshot: bool = False):
    """Upsert { cfg, data } for a specific user within an ACID transaction."""
    cfg = payload.get("cfg", {})
    data = payload.get("data", {})

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Upsert Config
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                cursor.execute("""
                    INSERT INTO user_configs (user_id, key, value, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, k, json.dumps(v)))

        # Upsert User Stats (excluding collections like history & waterLogs)
        if isinstance(data, dict):
            for k, v in data.items():
                if k in ("history", "waterLogs", "reels"):
                    continue
                cursor.execute("""
                    INSERT INTO user_stats (user_id, key, value, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, k, json.dumps(v)))

            # Upsert Workout History
            history = data.get("history", {})
            if isinstance(history, dict):
                for date_key, rec in history.items():
                    if isinstance(rec, (int, float)):
                        sets = int(rec)
                        time_ms = 0
                        goal = 0
                    elif isinstance(rec, dict):
                        sets = int(rec.get("sets") or 0)
                        time_ms = int(rec.get("timeMs") or 0)
                        goal = int(rec.get("goal") or 0)
                    else:
                        continue

                    cursor.execute("""
                        INSERT INTO user_workouts (user_id, date, sets, time_ms, goal, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, date) DO UPDATE SET
                            sets = excluded.sets,
                            time_ms = excluded.time_ms,
                            goal = excluded.goal,
                            updated_at = CURRENT_TIMESTAMP
                    """, (user_id, date_key, sets, time_ms, goal))

            # Upsert Water Logs
            water_logs = data.get("waterLogs", {})
            if isinstance(water_logs, dict):
                for date_key, glasses in water_logs.items():
                    cursor.execute("""
                        INSERT INTO user_water_logs (user_id, date, glasses, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, date) DO UPDATE SET
                            glasses = excluded.glasses,
                            updated_at = CURRENT_TIMESTAMP
                    """, (user_id, date_key, int(glasses or 0)))

        # Snapshot for safety
        if create_snapshot:
            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO user_snapshots (user_id, timestamp, payload)
                VALUES (?, ?, ?)
            """, (user_id, now_iso, json.dumps(payload)))

            # Keep only the last 20 snapshots per user
            cursor.execute("""
                DELETE FROM user_snapshots WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM user_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT 20
                )
            """, (user_id, user_id))

        conn.commit()


def get_system_stats():
    """Retrieve system-wide summary statistics (for Admin)."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*), COALESCE(SUM(sets), 0) FROM user_workouts")
        total_workout_records, total_sets = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM user_water_logs")
        total_water_logs = cursor.fetchone()[0]

    return {
        "total_users": total_users,
        "total_workout_records": total_workout_records,
        "total_sets_across_all_users": total_sets,
        "total_water_logs": total_water_logs,
        "db_file": "suryasarthi_users.db",
        "port": PORT
    }


class SuryasarthiRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP handler serving Multi-User SQLite REST APIs and PWA assets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_json(self, status_code, data_obj):
        """Helper to serialize and write JSON HTTP responses with CORS."""
        resp_bytes = json.dumps(data_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(resp_bytes)

    def _get_auth_token(self):
        """Extract session token from Authorization header or URL query."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if "token" in qs:
            return qs["token"][0]
        return ""

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        """Handle GET endpoints."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        token = self._get_auth_token()
        user = get_user_by_token(token)

        # 1. API: Validate Session / Get Current User
        if path == "/api/auth/me":
            if not user:
                self._send_json(401, {"success": False, "error": "Unauthorized / Session expired"})
                return
            self._send_json(200, {"success": True, "user": user})
            return

        # 2. API: Get User Practice Data (Strict User Privacy)
        if path == "/api/data":
            if not user:
                self._send_json(401, {"success": False, "error": "Authentication required to access user data"})
                return
            try:
                user_payload = load_user_data_from_db(user["id"])
                self._send_json(200, {
                    "success": True,
                    "user": user,
                    "cfg": user_payload["cfg"],
                    "data": user_payload["data"]
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        # 3. API: Admin — View All Users List & Stats (Admin Only!)
        if path == "/api/admin/users":
            if not user or user.get("role") != "admin":
                self._send_json(403, {"success": False, "error": "Forbidden: Admin access required"})
                return
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT u.id, u.username, u.name, u.role, u.created_at,
                           COALESCE(SUM(w.sets), 0) AS total_sets,
                           COUNT(w.date) AS workout_days,
                           MAX(w.date) AS last_active_date
                    FROM users u
                    LEFT JOIN user_workouts w ON u.id = w.user_id
                    GROUP BY u.id
                    ORDER BY u.id ASC
                """)
                users_list = [dict(r) for r in cursor.fetchall()]
            self._send_json(200, {"success": True, "users": users_list})
            return

        # 4. API: Admin — View Specific User Data (Admin Only!)
        if path == "/api/admin/user-data":
            if not user or user.get("role") != "admin":
                self._send_json(403, {"success": False, "error": "Forbidden: Admin access required"})
                return
            qs = parse_qs(parsed_url.query)
            target_user_id = qs.get("user_id", [None])[0]
            if not target_user_id:
                self._send_json(400, {"success": False, "error": "Missing user_id parameter"})
                return
            try:
                target_payload = load_user_data_from_db(int(target_user_id))
                self._send_json(200, {"success": True, "user_id": target_user_id, **target_payload})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        # 5. API: Admin — System-wide Stats
        if path == "/api/admin/stats":
            if not user or user.get("role") != "admin":
                self._send_json(403, {"success": False, "error": "Forbidden: Admin access required"})
                return
            stats = get_system_stats()
            self._send_json(200, {"success": True, "stats": stats})
            return

        # 6. API: Public Server Status
        if path == "/api/status":
            self._send_json(200, {
                "success": True,
                "status": "online",
                "app": "Suryasarthi 108",
                "port": PORT,
                "local_ip": get_local_ip(),
                "server_time": datetime.now().isoformat()
            })
            return

        # 7. API: Admin — Download Raw SQLite Database File
        if path == "/api/backup":
            if not user or user.get("role") != "admin":
                self._send_json(403, {"success": False, "error": "Forbidden: Admin access required"})
                return
            if not os.path.exists(DB_FILE):
                self._send_json(404, {"success": False, "error": "Database file not found."})
                return

            with open(DB_FILE, "rb") as f:
                db_bytes = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/x-sqlite3")
            self.send_header("Content-Disposition", 'attachment; filename="suryasarthi_users.db"')
            self.send_header("Content-Length", str(len(db_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(db_bytes)
            return

        # Standard Static File Serving
        super().do_GET()

    def do_POST(self):
        """Handle POST endpoints."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # Read JSON body
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len <= 0:
            self._send_json(400, {"success": False, "error": "Empty request body"})
            return

        try:
            body = self.rfile.read(content_len)
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"success": False, "error": f"Invalid JSON: {str(e)}"})
            return

        # 1. API: User Registration
        if path == "/api/auth/register":
            username = str(payload.get("username", "")).strip().lower()
            password = str(payload.get("password", "")).strip()
            name = str(payload.get("name", "")).strip() or username.capitalize()
            role = "user"  # regular user by default

            if not username or not password:
                self._send_json(400, {"success": False, "error": "Username and password are required"})
                return

            pwd_hash = hash_password(password)
            token = secrets.token_hex(24)

            try:
                with sqlite3.connect(DB_FILE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO users (username, password_hash, name, role)
                        VALUES (?, ?, ?, ?)
                    """, (username, pwd_hash, name, role))
                    user_id = cursor.lastrowid

                    cursor.execute("""
                        INSERT INTO user_sessions (token, user_id)
                        VALUES (?, ?)
                    """, (token, user_id))
                    conn.commit()

                user_obj = {"id": user_id, "username": username, "name": name, "role": role}
                self._send_json(200, {
                    "success": True,
                    "message": "User registered successfully",
                    "token": token,
                    "user": user_obj
                })
            except sqlite3.IntegrityError:
                self._send_json(409, {"success": False, "error": "Username already exists. Please choose another."})
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        # 2. API: User Login
        if path == "/api/auth/login":
            username = str(payload.get("username", "")).strip().lower()
            password = str(payload.get("password", "")).strip()

            if not username or not password:
                self._send_json(400, {"success": False, "error": "Username and password are required"})
                return

            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, username, password_hash, name, role
                    FROM users
                    WHERE username = ?
                """, (username,))
                row = cursor.fetchone()

                if not row or not verify_password(password, row["password_hash"]):
                    self._send_json(401, {"success": False, "error": "Invalid username or password"})
                    return

                user_id = row["id"]
                token = secrets.token_hex(24)

                cursor.execute("""
                    INSERT INTO user_sessions (token, user_id)
                    VALUES (?, ?)
                """, (token, user_id))
                conn.commit()

                user_obj = {
                    "id": user_id,
                    "username": row["username"],
                    "name": row["name"],
                    "role": row["role"]
                }
                self._send_json(200, {
                    "success": True,
                    "message": "Login successful",
                    "token": token,
                    "user": user_obj
                })
            return

        # 3. API: User Logout
        if path == "/api/auth/logout":
            token = self._get_auth_token()
            if token:
                with sqlite3.connect(DB_FILE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
                    conn.commit()
            self._send_json(200, {"success": True, "message": "Logged out successfully"})
            return

        # 4. API: Save User Practice Data (Strict User Privacy)
        if path == "/api/data":
            token = self._get_auth_token()
            user = get_user_by_token(token)
            if not user:
                self._send_json(401, {"success": False, "error": "Authentication required to save data"})
                return

            try:
                save_user_data_to_db(user["id"], payload, create_snapshot=False)
                self._send_json(200, {
                    "success": True,
                    "message": "Practice data saved to SQLite",
                    "user_id": user["id"]
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        self._send_json(404, {"success": False, "error": "Endpoint not found"})

    def end_headers(self):
        """Ensure proper CORS and security headers on every response."""
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def run_server():
    """Start the HTTP server on 0.0.0.0 at port 8088."""
    init_db()
    local_ip = get_local_ip()

    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(("0.0.0.0", PORT), SuryasarthiRequestHandler) as httpd:
        stats = get_system_stats()
        print("=" * 70)
        print(" 🌅 SURYASARTHI 108 — Multi-User SQLite Server")
        print("=" * 70)
        print(f" Dedicated Port    : {PORT} (Isolated from other applications)")
        print(f" Database File     : {DB_FILE}")
        print(f" Registered Users  : {stats['total_users']}")
        print(f" Total Workouts    : {stats['total_workout_records']} logs ({stats['total_sets_across_all_users']} total sets)")
        print(f" Local Machine URL : http://localhost:{PORT}")
        print(f" Network (LAN) URL : http://{local_ip}:{PORT}")
        print("-" * 70)
        print(f" 📲 Open 'http://{local_ip}:{PORT}' on any device on your Wi-Fi!")
        print(" Press Ctrl + C to stop the server.")
        print("=" * 70)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server gracefully...")
            httpd.shutdown()


if __name__ == "__main__":
    run_server()
