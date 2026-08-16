"""用 Playwright 截图所有页面（wait networkidle，确保 JS fetch 完成）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

SHOTS = Path("/tmp/duck_shots")
SHOTS.mkdir(exist_ok=True)

PAGES = [
    ("01_child.png", "http://127.0.0.1:8000/", None),
    ("02_teacher_overview.png", "http://127.0.0.1:8000/teacher.html#overview", None),
    ("03_teacher_children.png", "http://127.0.0.1:8000/teacher.html#children", None),
    ("04_teacher_ducks.png", "http://127.0.0.1:8000/teacher.html#ducks", None),
    ("05_teacher_roster.png", "http://127.0.0.1:8000/teacher.html#roster", None),
    ("06_teacher_review.png", "http://127.0.0.1:8000/teacher.html#review", None),
    ("07_teacher_growth.png", "http://127.0.0.1:8000/teacher.html#growth", "child_id=1"),
    ("08_teacher_search.png", "http://127.0.0.1:8000/teacher.html#search", None),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        for name, url, query in PAGES:
            full = url + ("?" + query if query else "")
            page.goto(full, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(800)
            page.screenshot(path=str(SHOTS / name), full_page=False)
            print(f"✅ {name}")
        browser.close()
    print(f"\n截图保存至：{SHOTS}")


if __name__ == "__main__":
    main()