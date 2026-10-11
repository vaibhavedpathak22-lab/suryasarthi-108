#!/usr/bin/env python3
"""
Test script for verifying Multi-User SQLite database, authentication,
data privacy isolation, and admin endpoints in server.py
"""
import os
import sys
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import server

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def test_multi_user_sqlite():
    print("Testing Multi-User SQLite initialization and operations...")
    server.init_db()

    assert os.path.exists(server.DB_FILE), "Database file was not created!"
    print(f"✓ {server.DB_FILE} exists.")

    # 1. Test Admin Seeding
    with sqlite3.connect(server.DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = 'admin'")
        admin = c.fetchone()
        assert admin is not None, "Default admin user not seeded!"
        assert admin["role"] == "admin", "Admin role mismatch!"
        assert server.verify_password("admin108", admin["password_hash"]), "Admin password verification failed!"
        print("✓ Default Admin account initialized and verified.")

    # 2. Test User Registration & Password Hashing
    user1_hash = server.hash_password("password123")
    user2_hash = server.hash_password("secret456")

    with sqlite3.connect(server.DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE username IN ('user1', 'user2')")
        c.execute("INSERT INTO users (username, password_hash, name, role) VALUES ('user1', ?, 'User One', 'user')", (user1_hash,))
        user1_id = c.lastrowid
        c.execute("INSERT INTO users (username, password_hash, name, role) VALUES ('user2', ?, 'User Two', 'user')", (user2_hash,))
        user2_id = c.lastrowid
        conn.commit()

    print(f"✓ Registered User 1 (ID: {user1_id}) and User 2 (ID: {user2_id}).")

    # 3. Test User 1 Data Persistence
    user1_payload = {
        "cfg": {"userName": "User One", "dailyIncrease": 4, "maxSets": 108},
        "data": {
            "history": {
                "2026-09-20": {"sets": 32, "timeMs": 800000, "goal": 32},
                "2026-09-21": {"sets": 36, "timeMs": 900000, "goal": 36}
            },
            "totalAllTime": 68,
            "waterLogs": {"2026-09-21": 6}
        }
    }
    server.save_user_data_to_db(user1_id, user1_payload)
    print("✓ Saved User 1 workout data.")

    # 4. Test User 2 Data Persistence (Different data)
    user2_payload = {
        "cfg": {"userName": "User Two", "dailyIncrease": 2, "maxSets": 50},
        "data": {
            "history": {
                "2026-09-21": {"sets": 12, "timeMs": 300000, "goal": 12}
            },
            "totalAllTime": 12,
            "waterLogs": {"2026-09-21": 4}
        }
    }
    server.save_user_data_to_db(user2_id, user2_payload)
    print("✓ Saved User 2 workout data.")

    # 5. Verify Strict Data Privacy (User 1 can only load User 1 data)
    loaded_user1 = server.load_user_data_from_db(user1_id)
    assert loaded_user1["cfg"]["userName"] == "User One", "User 1 config mismatch!"
    assert loaded_user1["data"]["totalAllTime"] == 68, "User 1 total sets mismatch!"
    assert "2026-09-20" in loaded_user1["data"]["history"], "User 1 missing 2026-09-20 workout!"
    assert loaded_user1["data"]["waterLogs"]["2026-09-21"] == 6, "User 1 water log mismatch!"

    loaded_user2 = server.load_user_data_from_db(user2_id)
    assert loaded_user2["cfg"]["userName"] == "User Two", "User 2 config mismatch!"
    assert loaded_user2["data"]["totalAllTime"] == 12, "User 2 total sets mismatch!"
    assert "2026-09-20" not in loaded_user2["data"]["history"], "User 2 erroneously saw User 1's history!"
    assert loaded_user2["data"]["waterLogs"]["2026-09-21"] == 4, "User 2 water log mismatch!"

    print("✓ Strict User Privacy verified: User data is completely isolated.")

    # 6. Test System Stats (Admin View)
    stats = server.get_system_stats()
    assert stats["total_users"] >= 3, f"Expected at least 3 users (admin, user1, user2), got {stats['total_users']}"
    assert stats["total_sets_across_all_users"] >= 80, f"Expected aggregate sets >= 80, got {stats['total_sets_across_all_users']}"
    print(f"✓ Admin system stats verified: {stats}")

    print("\nAll Multi-User SQLite tests passed with 100% success!")

if __name__ == "__main__":
    test_multi_user_sqlite()
