"""
LeetCode POTD Scraper — Playwright edition
Scrapes: problem, editorial, top solutions (per language)
Saves: data/YYYY-MM-DD.json + updates data/index.json

Usage:
    python scripts/scrape_potd.py
    python scripts/scrape_potd.py --date 2026-03-12
    python scripts/scrape_potd.py --force
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL  = "https://leetcode.com"
DATA_DIR  = Path(__file__).parent.parent / "data"
HEADLESS  = True          # set False locally to watch the browser
TIMEOUT   = 30_000        # ms — page load timeout
SLOW_MO   = 0             # ms between actions (increase if getting blocked)

# LeetCode session cookie (optional — improves editorial access)
LC_SESSION  = os.getenv("LEETCODE_SESSION", "")
LC_CSRF     = os.getenv("LEETCODE_CSRF_TOKEN", "")

# Languages to collect solutions for
TARGET_LANGS = ["C++", "Python3", "JavaScript", "Java"]
LANG_KEYS    = {"C++": "cpp", "Python3": "python3",
                "JavaScript": "javascript", "Java": "java"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    print(msg, flush=True)


def slugify_lang(lang: str) -> str:
    return LANG_KEYS.get(lang, lang.lower().replace(" ", ""))


def extract_code_blocks(text: str) -> list[dict]:
    """Pull fenced code blocks out of markdown text."""
    pattern = r"```(\w*)\n(.*?)```"
    blocks  = []
    for lang, code in re.findall(pattern, text, re.DOTALL):
        blocks.append({"language": lang.strip() or "text", "code": code.strip()})
    return blocks


def make_browser_context(playwright):
    """Launch Chromium with realistic headers. Inject cookies if provided."""
    browser = playwright.chromium.launch(
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Kolkata",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )

    # Inject auth cookies if available
    if LC_SESSION and LC_CSRF:
        log("🍪 Injecting LeetCode session cookies...")
        context.add_cookies([
            {
                "name": "LEETCODE_SESSION",
                "value": LC_SESSION,
                "domain": ".leetcode.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            },
            {
                "name": "csrftoken",
                "value": LC_CSRF,
                "domain": ".leetcode.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
            },
        ])
    else:
        log("⚠️  No session cookies — editorial may be limited")

    return browser, context


def wait_and_text(page, selector: str, timeout: int = TIMEOUT) -> str:
    """Wait for a selector and return its inner text, or empty string."""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return page.inner_text(selector).strip()
    except PWTimeout:
        return ""


def safe_goto(page, url: str, wait_until="domcontentloaded"):
    """Navigate with retry logic."""
    for attempt in range(3):
        try:
            page.goto(url, wait_until=wait_until, timeout=TIMEOUT)
            return True
        except Exception as e:
            log(f"  [attempt {attempt+1}] Navigation error: {e}")
            time.sleep(2 ** attempt)
    return False


# ── Step 1: Get today's POTD slug ─────────────────────────────────────────────

def get_potd_slug(page) -> dict | None:
    """
    Visit the problemset page and extract today's POTD.
    LeetCode shows a highlighted 'Daily' badge on the POTD row.
    Falls back to GraphQL as a secondary method.
    """
    log("📅 Finding today's POTD slug...")

    # Method A: GraphQL (fast, doesn't need full page render)
    try:
        response = page.request.post(
            f"{BASE_URL}/graphql",
            data=json.dumps({
                "query": """
                query questionOfToday {
                  activeDailyCodingChallengeQuestion {
                    date
                    link
                    question {
                      questionFrontendId
                      title
                      titleSlug
                      difficulty
                      topicTags { name }
                      hints
                      stats
                      likes
                      dislikes
                      exampleTestcases
                      codeSnippets { lang langSlug code }
                      similarQuestions
                    }
                  }
                }
                """
            }),
            headers={
                "Content-Type": "application/json",
                "Referer": BASE_URL,
                "x-csrftoken": LC_CSRF or "fetch",
            },
        )
        data = response.json()
        challenge = data["data"]["activeDailyCodingChallengeQuestion"]
        q = challenge["question"]

        # Parse stats
        stats = {}
        try:
            stats = json.loads(q.get("stats", "{}"))
        except Exception:
            pass

        # Parse similar questions
        similar = []
        try:
            for s in json.loads(q.get("similarQuestions", "[]")):
                similar.append({
                    "title": s["title"],
                    "slug": s["titleSlug"],
                    "difficulty": s["difficulty"],
                })
        except Exception:
            pass

        # Starter codes
        snippets = q.get("codeSnippets", [])
        starter_codes = {
            s["langSlug"]: s["code"]
            for s in snippets
            if s["langSlug"] in ("cpp", "python3", "javascript", "java")
        }

        log(f"  ✅ GraphQL POTD: #{q['questionFrontendId']} {q['title']}")
        return {
            "date": challenge["date"],
            "link": f"{BASE_URL}{challenge['link']}",
            "id": q["questionFrontendId"],
            "title": q["title"],
            "slug": q["titleSlug"],
            "difficulty": q["difficulty"],
            "tags": [t["name"] for t in q.get("topicTags", [])],
            "hints": q.get("hints", []),
            "stats": {
                "total_accepted": stats.get("totalAccepted", "N/A"),
                "total_submissions": stats.get("totalSubmission", "N/A"),
                "acceptance_rate": stats.get("acRate", "N/A"),
            },
            "likes": q.get("likes", 0),
            "dislikes": q.get("dislikes", 0),
            "similar_questions": similar,
            "example_testcases": q.get("exampleTestcases", ""),
            "starter_codes": starter_codes,
        }

    except Exception as e:
        log(f"  ⚠️  GraphQL failed ({e}), falling back to HTML scrape...")

    # Method B: Scrape the problemset page for the Daily badge
    try:
        safe_goto(page, f"{BASE_URL}/problemset/")
        page.wait_for_selector("a[href*='/problems/']", timeout=TIMEOUT)
        time.sleep(2)

        # Find the element with "Daily" label
        daily_link = page.query_selector("a:has-text('Daily')")
        if not daily_link:
            # Try to find via the calendar/daily challenge section
            daily_link = page.query_selector("[data-daily-question] a, .daily-question a")

        if daily_link:
            href = daily_link.get_attribute("href")
            slug = href.strip("/").split("/")[-1]
            log(f"  ✅ HTML scrape POTD slug: {slug}")
            return {"slug": slug, "link": f"{BASE_URL}/problems/{slug}/"}

    except Exception as e:
        log(f"  ❌ HTML fallback also failed: {e}")

    return None


# ── Step 2: Scrape problem description ────────────────────────────────────────

def scrape_problem(page, slug: str, meta: dict) -> dict:
    """Scrape the full problem description page."""
    log(f"\n📄 Scraping problem page for '{slug}'...")

    url = f"{BASE_URL}/problems/{slug}/"
    if not safe_goto(page, url, wait_until="networkidle"):
        log("  ❌ Failed to load problem page")
        return meta

    # Wait for the description to render
    try:
        page.wait_for_selector(
            "[data-track-load='description_content'], .elfjS, div[class*='description']",
            timeout=TIMEOUT
        )
    except PWTimeout:
        log("  ⚠️  Description selector timed out, continuing anyway...")

    time.sleep(2)  # let React finish rendering

    # Extract description HTML
    description_html = ""
    description_text = ""
    for sel in [
        "[data-track-load='description_content']",
        ".elfjS",
        "div[class*='description__']",
        "div[class*='content__']",
    ]:
        el = page.query_selector(sel)
        if el:
            description_html = el.inner_html()
            description_text = el.inner_text()
            log(f"  ✅ Description found via: {sel}")
            break

    # Extract difficulty if not already in meta
    difficulty = meta.get("difficulty", "")
    if not difficulty:
        for sel in ["[class*='difficulty']", "span:has-text('Easy')",
                    "span:has-text('Medium')", "span:has-text('Hard')"]:
            el = page.query_selector(sel)
            if el:
                difficulty = el.inner_text().strip()
                break

    # Extract tags if not already in meta
    tags = meta.get("tags", [])
    if not tags:
        tag_els = page.query_selector_all("a[href*='/tag/']")
        tags = list(set(el.inner_text().strip() for el in tag_els if el.inner_text().strip()))

    return {
        **meta,
        "difficulty": difficulty or meta.get("difficulty", ""),
        "tags": tags or meta.get("tags", []),
        "description": description_text.strip(),
        "description_html": description_html,
    }


# ── Step 3: Scrape editorial ───────────────────────────────────────────────────

def scrape_editorial(page, slug: str) -> dict:
    """Scrape the official editorial page."""
    log(f"\n📖 Scraping editorial for '{slug}'...")

    url = f"{BASE_URL}/problems/{slug}/editorial/"
    if not safe_goto(page, url, wait_until="networkidle"):
        return {"available": False, "reason": "navigation_failed"}

    time.sleep(3)  # editorial is slow to render

    # Check for paywall
    paywall = page.query_selector(
        "text='Subscribe to unlock', [class*='premium'], [class*='locked']"
    )
    if paywall:
        log("  🔒 Editorial is behind paywall")
        return {"available": False, "paid_only": True}

    # Check for "no editorial" state
    no_editorial = page.query_selector("text='No editorial'")
    if no_editorial:
        log("  ℹ️  No editorial available")
        return {"available": False, "reason": "no_editorial"}

    # Wait for editorial content
    content_text = ""
    content_html = ""
    for sel in [
        "[class*='solution-content']",
        "[class*='editorial']  div[class*='content']",
        "div[class*='SolutionArticleContent']",
        "article",
        "div[data-cy='editorial-content']",
        ".viewer-content",
    ]:
        try:
            page.wait_for_selector(sel, timeout=8000)
            el = page.query_selector(sel)
            if el:
                content_html = el.inner_html()
                content_text = el.inner_text()
                log(f"  ✅ Editorial found via: {sel}")
                break
        except PWTimeout:
            continue

    if not content_text:
        log("  ⚠️  Editorial content not found (may need login)")
        return {"available": False, "reason": "content_not_rendered"}

    code_blocks = extract_code_blocks(content_text)

    # Also grab code blocks directly from <pre><code> elements
    code_els = page.query_selector_all("pre code, div[class*='CodeMirror']")
    for el in code_els:
        code = el.inner_text().strip()
        if code and len(code) > 20:
            # Try to detect language from class
            cls = el.get_attribute("class") or ""
            lang = "unknown"
            for l in ["cpp", "python", "java", "javascript", "go", "rust"]:
                if l in cls.lower():
                    lang = l
                    break
            # Avoid duplicates
            if not any(b["code"] == code for b in code_blocks):
                code_blocks.append({"language": lang, "code": code})

    log(f"  ✅ Editorial scraped — {len(code_blocks)} code blocks found")
    return {
        "available": True,
        "paid_only": False,
        "content": content_text.strip(),
        "content_html": content_html,
        "code_blocks": code_blocks,
    }


# ── Step 4: Scrape community solutions ────────────────────────────────────────

def scrape_solutions(page, slug: str) -> dict:
    """Scrape top community solutions, filtered by language."""
    log(f"\n💡 Scraping community solutions for '{slug}'...")

    results = {key: [] for key in LANG_KEYS.values()}

    for lang_display, lang_key in LANG_KEYS.items():
        log(f"  → {lang_display}...")

        # Build URL with language filter
        url = (
            f"{BASE_URL}/problems/{slug}/solutions/"
            f"?languageTags={lang_display.lower().replace('+', 'p')}"
            f"&orderBy=hot"
        )
        # LeetCode uses specific lang slugs in URL
        lang_url_map = {
            "C++": "cpp", "Python3": "python3",
            "JavaScript": "javascript", "Java": "java",
        }
        url = (
            f"{BASE_URL}/problems/{slug}/solutions/"
            f"?languageTags={lang_url_map[lang_display]}&orderBy=hot"
        )

        if not safe_goto(page, url, wait_until="networkidle"):
            continue

        time.sleep(3)

        # Wait for solution cards to load
        try:
            page.wait_for_selector(
                "div[class*='solution-card'], a[href*='/solutions/']",
                timeout=12000
            )
        except PWTimeout:
            log(f"    ⚠️  No solutions loaded for {lang_display}")
            continue

        # Grab top 2 solution cards
        cards = page.query_selector_all(
            "div[class*='solution-card'], div[class*='SolutionCard']"
        )[:2]

        if not cards:
            # Try alternate structure — list of solution links
            cards = page.query_selector_all("a[href*='/solutions/'][class*='title']")[:2]

        for card in cards:
            try:
                # Get title
                title_el = card.query_selector("a[href*='/solutions/'], [class*='title']")
                title = title_el.inner_text().strip() if title_el else "Untitled"

                # Get vote count
                vote_el = card.query_selector(
                    "[class*='vote'], [class*='like'], span[class*='count']"
                )
                votes = 0
                if vote_el:
                    try:
                        votes = int(re.sub(r"[^\d]", "", vote_el.inner_text()) or "0")
                    except Exception:
                        pass

                # Get solution link and visit it
                link_el = card.query_selector("a[href*='/solutions/']")
                if not link_el:
                    continue

                href = link_el.get_attribute("href")
                sol_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                # Visit solution detail page
                sol_page = page.context.new_page()
                try:
                    sol_page.goto(sol_url, wait_until="networkidle", timeout=TIMEOUT)
                    time.sleep(2)

                    # Get full content
                    content = ""
                    for sel in [
                        "[class*='solution-content']",
                        "div[class*='post__content']",
                        "div[class*='content__']",
                        "article",
                    ]:
                        el = sol_page.query_selector(sel)
                        if el:
                            content = el.inner_text().strip()
                            break

                    # Extract code specifically
                    code_blocks = extract_code_blocks(content)
                    code_els = sol_page.query_selector_all("pre code")
                    for cel in code_els:
                        code = cel.inner_text().strip()
                        if code and not any(b["code"] == code for b in code_blocks):
                            code_blocks.append({"language": lang_key, "code": code})

                    if content or code_blocks:
                        results[lang_key].append({
                            "title": title,
                            "votes": votes,
                            "url": sol_url,
                            "content": content,
                            "code_blocks": code_blocks,
                        })
                        log(f"    ✅ Got solution: '{title}' ({votes} votes)")

                finally:
                    sol_page.close()

            except Exception as e:
                log(f"    ⚠️  Error scraping card: {e}")
                continue

        time.sleep(1)  # be polite between languages

    total = sum(len(v) for v in results.values())
    log(f"  ✅ Total solutions scraped: {total}")
    return results


# ── Step 5: Pick best solution ─────────────────────────────────────────────────

def pick_best_solution(editorial: dict, community: dict, starter_codes: dict) -> dict:
    """Choose the best available solution source."""

    if editorial.get("available") and editorial.get("code_blocks"):
        # Map editorial code blocks by language
        codes = {"cpp": "", "python": "", "javascript": "", "java": ""}
        for block in editorial["code_blocks"]:
            lang = block["language"].lower()
            if "cpp" in lang or "c++" in lang:
                codes["cpp"] = codes["cpp"] or block["code"]
            elif "python" in lang:
                codes["python"] = codes["python"] or block["code"]
            elif "javascript" in lang or lang == "js":
                codes["javascript"] = codes["javascript"] or block["code"]
            elif "java" in lang:
                codes["java"] = codes["java"] or block["code"]

        return {
            "source_type": "editorial",
            "explanation": editorial.get("content", ""),
            "codes": codes,
        }

    # Fall back to best community solution per language
    codes = {}
    lang_map = {"cpp": "cpp", "python3": "python", "javascript": "javascript", "java": "java"}
    for lc_key, display_key in lang_map.items():
        sols = community.get(lc_key, [])
        if sols:
            best = max(sols, key=lambda x: x.get("votes", 0))
            blocks = best.get("code_blocks", [])
            codes[display_key] = blocks[0]["code"] if blocks else ""
        else:
            # Fall back to empty starter code hint
            codes[display_key] = ""

    return {
        "source_type": "community" if any(codes.values()) else "none",
        "explanation": "",
        "codes": codes,
    }


# ── Step 6: Save output ────────────────────────────────────────────────────────

def save_result(date: str, problem: dict, editorial: dict,
                community: dict, best: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / f"{date}.json"

    result = {
        "meta": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "ai_explanation_status": "pending",
        },
        "problem": problem,
        "editorial": editorial,
        "community_solutions": community,
        "best_solution": best,
        "ai_explanation": None,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    log(f"\n✅ Saved → {output_path}")

    # Update index
    index_path = DATA_DIR / "index.json"
    index = []
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)

    index = [e for e in index if e["date"] != date]
    index.append({
        "date": date,
        "id": problem.get("id", ""),
        "title": problem.get("title", ""),
        "slug": problem.get("slug", ""),
        "difficulty": problem.get("difficulty", ""),
        "tags": problem.get("tags", []),
        "link": problem.get("link", ""),
        "solution_source": best.get("source_type", "none"),
        "has_editorial": editorial.get("available", False),
    })
    index.sort(key=lambda x: x["date"], reverse=True)

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    log(f"✅ Index updated ({len(index)} problems total)")
    return output_path


# ── Main ───────────────────────────────────────────────────────────────────────

def run(date_override: str = None, force: bool = False):
    today = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = DATA_DIR / f"{today}.json"

    if output_path.exists() and not force:
        log(f"✅ Data for {today} already exists. Use --force to re-scrape.")
        return

    log(f"\n{'='*55}")
    log(f"  LeetCode POTD Scraper — {today}")
    log(f"{'='*55}\n")

    with sync_playwright() as pw:
        browser, context = make_browser_context(pw)
        page = context.new_page()

        try:
            # ── 1. Get POTD metadata ─────────────────────────────────────
            problem_meta = get_potd_slug(page)
            if not problem_meta:
                log("❌ Could not find today's POTD. Exiting.")
                sys.exit(1)

            slug = problem_meta["slug"]

            # ── 2. Scrape full problem description ───────────────────────
            problem = scrape_problem(page, slug, problem_meta)
            log(f"\n✅ Problem: #{problem.get('id')} {problem.get('title')} [{problem.get('difficulty')}]")
            log(f"   Tags: {', '.join(problem.get('tags', []))}")

            # ── 3. Scrape editorial ──────────────────────────────────────
            editorial = scrape_editorial(page, slug)
            log(f"   Editorial: {'✅ available' if editorial.get('available') else '❌ ' + editorial.get('reason','unavailable')}")

            # ── 4. Scrape community solutions ────────────────────────────
            community = scrape_solutions(page, slug)
            total_sols = sum(len(v) for v in community.values())
            log(f"   Community solutions: {total_sols} found")

            # ── 5. Pick best solution ────────────────────────────────────
            best = pick_best_solution(editorial, community, problem.get("starter_codes", {}))
            log(f"   Best source: {best['source_type']}")

            # ── 6. Save ──────────────────────────────────────────────────
            save_result(today, problem, editorial, community, best)

        finally:
            context.close()
            browser.close()

    log("\n🎉 Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",  help="Override date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Re-scrape even if data exists")
    args = parser.parse_args()
    run(date_override=args.date, force=args.force)
