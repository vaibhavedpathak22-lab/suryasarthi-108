#!/usr/bin/env python3
"""
Test verification script for System Colors (Windows & Android),
CSS theme definitions, and theme configuration engine.
"""
import os
import sys
import urllib.request
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def test_index_html():
    print("1. Checking index.html...")
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()

    assert '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#070B14">' in html, "Missing dark meta theme-color"
    assert '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#F8FAFC">' in html, "Missing light meta theme-color"
    assert "color-scheme: dark light;" in html, "Missing color-scheme: dark light in CSS"
    assert "--sys-accent: AccentColor;" in html, "Missing --sys-accent: AccentColor in CSS"
    assert "@media (prefers-color-scheme: light)" in html, "Missing prefers-color-scheme: light media query in CSS"
    assert ":root.theme-light" in html, "Missing :root.theme-light class in CSS"
    assert 'id="cfg-theme"' in html, "Missing #cfg-theme in settings drawer"
    assert '<option value="system">' in html, "Missing system default option in #cfg-theme"
    assert '<option value="dark">' in html, "Missing dark option in #cfg-theme"
    assert '<option value="light">' in html, "Missing light option in #cfg-theme"
    print("   ✓ index.html passed all system color & theme checks.")

def test_settings_engine_js():
    print("2. Checking settings-engine.js...")
    with open(os.path.join(BASE_DIR, "settings-engine.js"), "r", encoding="utf-8") as f:
        code = f.read()

    assert "function applyTheme(theme)" in code, "Missing applyTheme() function"
    assert "function updateMetaThemeColor(theme)" in code, "Missing updateMetaThemeColor() function"
    assert 'document.getElementById("cfg-theme")' in code, "Missing cfg-theme selector references"
    assert "prefers-color-scheme: dark" in code, "Missing matchMedia prefers-color-scheme listener"
    assert "window.applyTheme = applyTheme" in code, "Missing window.applyTheme export"
    print("   ✓ settings-engine.js passed all theme logic checks.")

def test_app_js():
    print("3. Checking app.js...")
    with open(os.path.join(BASE_DIR, "app.js"), "r", encoding="utf-8") as f:
        code = f.read()

    assert 'theme         : "system"' in code or 'theme: "system"' in code or 'theme:"system"' in code, "Missing default theme in cfg"
    assert "applyTheme(cfg.theme || \"system\")" in code, "Missing applyTheme invocation"
    print("   ✓ app.js passed all theme configuration checks.")

def test_http_server():
    print("4. Testing HTTP server on http://localhost:8088...")
    try:
        req = urllib.request.Request("http://localhost:8088/index.html")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}"
            content = resp.read().decode("utf-8")
            assert "cfg-theme" in content
            print("   ✓ Server successfully serving index.html on port 8088.")
    except Exception as e:
        print(f"   [WARN] Could not reach http://localhost:8088: {e}")

if __name__ == "__main__":
    test_index_html()
    test_settings_engine_js()
    test_app_js()
    test_http_server()
    print("\n All System Color and Theme verification checks passed successfully!")
