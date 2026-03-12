"""
LeetCode Problem of the Day (POTD) Fetcher
Fetches daily problem, editorial (if available), and top solutions
Saves structured JSON to /data/YYYY-MM-DD.json and updates index.json
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Constants ────────────────────────────────────────────────────────────────

LEETCODE_GRAPHQL = "https://leetcode.com/graphql"
DATA_DIR = Path(__file__).parent.parent / "data"

_session = os.getenv("LEETCODE_SESSION", "")
_csrf    = os.getenv("LEETCODE_CSRF_TOKEN", "")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; POTD-Bot/1.0)",
    "Referer": "https://leetcode.com",
    "x-csrftoken": _csrf,
    "Cookie": f"LEETCODE_SESSION={_session}; csrftoken={_csrf}",
}

# ─── GraphQL Queries ───────────────────────────────────────────────────────────

POTD_QUERY = """
query questionOfToday {
  activeDailyCodingChallengeQuestion {
    date
    link
    question {
      questionId
      questionFrontendId
      title
      titleSlug
      difficulty
      content
      hints
      topicTags {
        name
        slug
      }
      codeSnippets {
        lang
        langSlug
        code
      }
      stats
      likes
      dislikes
      similarQuestions
      exampleTestcases
    }
  }
}
"""

EDITORIAL_QUERY = """
query ugcArticleOfficialSolution($titleSlug: String!) {
  ugcArticleOfficialSolution(titleSlug: $titleSlug) {
    uuid
    title
    content
    contentTypeId
    paidOnly
    hasVideoSolution
  }
}
"""

SOLUTIONS_QUERY = """
query communitySolutions($questionSlug: String!, $skip: Int!, $first: Int!, $orderBy: TopicSortingOption, $languageTags: [String!]) {
  questionSolutions(
    filters: {
      questionSlug: $questionSlug
      skip: $skip
      first: $first
      orderBy: $orderBy
      languageTags: $languageTags
    }
  ) {
    hasDirectResults
    totalNum
    solutions {
      id
      title
      commentCount
      topLevelCommentCount
      viewCount
      pinned
      isFavorite
      solutionTags {
        name
        slug
      }
      post {
        id
        status
        voteCount
        creationDate
        author {
          username
          profile {
            reputation
            userAvatar
          }
        }
        content
      }
      question {
        questionTitleSlug
      }
    }
  }
}
"""

SOLUTION_DETAIL_QUERY = """
query communitySolution($topicId: Int!) {
  topic(id: $topicId) {
    id
    title
    post {
      id
      content
      voteCount
      author {
        username
      }
    }
  }
}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def gql(query: str, variables: dict = None) -> dict:
    """Execute a GraphQL query against LeetCode."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(3):
        try:
            resp = requests.post(
                LEETCODE_GRAPHQL,
                json=payload,
                headers=HEADERS,
                timeout=15
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"  [attempt {attempt+1}] GQL error: {e}")
            time.sleep(2 ** attempt)

    raise RuntimeError("GraphQL request failed after 3 attempts")


def clean_html(html: str) -> str:
    """Strip HTML tags, keep readable text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n").strip()


def extract_code_blocks(content: str) -> list[dict]:
    """Extract code blocks from markdown/HTML solution content."""
    blocks = []

    # Match ```lang ... ``` style
    pattern = r"```(\w+)?\n(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)
    for lang, code in matches:
        blocks.append({
            "language": lang.strip() if lang else "unknown",
            "code": code.strip()
        })

    return blocks


def parse_stats(stats_json: str) -> dict:
    """Parse the stats JSON string from LeetCode."""
    try:
        return json.loads(stats_json)
    except Exception:
        return {}


def get_starter_code(snippets: list, lang_slug: str) -> str:
    """Get starter code for a specific language."""
    for snippet in snippets:
        if snippet.get("langSlug") == lang_slug:
            return snippet.get("code", "")
    return ""


# ─── Core Fetchers ─────────────────────────────────────────────────────────────

def fetch_potd() -> dict:
    """Fetch today's Problem of the Day."""
    print("📥 Fetching POTD...")
    data = gql(POTD_QUERY)

    challenge = data["data"]["activeDailyCodingChallengeQuestion"]
    q = challenge["question"]

    stats = parse_stats(q.get("stats", "{}"))

    # Parse similar questions (it's a JSON string)
    similar = []
    try:
        similar_raw = json.loads(q.get("similarQuestions", "[]"))
        similar = [
            {"title": s["title"], "slug": s["titleSlug"], "difficulty": s["difficulty"]}
            for s in similar_raw
        ]
    except Exception:
        pass

    # Parse topic tags
    tags = [t["name"] for t in q.get("topicTags", [])]

    # Get starter code for target languages
    snippets = q.get("codeSnippets", [])
    starter_codes = {
        "cpp": get_starter_code(snippets, "cpp"),
        "python3": get_starter_code(snippets, "python3"),
        "javascript": get_starter_code(snippets, "javascript"),
        "java": get_starter_code(snippets, "java"),
    }

    return {
        "date": challenge["date"],
        "link": f"https://leetcode.com{challenge['link']}",
        "id": q["questionFrontendId"],
        "title": q["title"],
        "slug": q["titleSlug"],
        "difficulty": q["difficulty"],
        "description": clean_html(q.get("content", "")),
        "description_html": q.get("content", ""),
        "hints": q.get("hints", []),
        "tags": tags,
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


def fetch_editorial(slug: str) -> dict | None:
    """Fetch official editorial if available and not paywalled."""
    print(f"📖 Fetching editorial for '{slug}'...")
    try:
        data = gql(EDITORIAL_QUERY, {"titleSlug": slug})
        editorial = data["data"].get("ugcArticleOfficialSolution")

        if not editorial:
            print("  ℹ️  No editorial available.")
            return None

        if editorial.get("paidOnly"):
            print("  🔒 Editorial is behind paywall.")
            return {"available": False, "paid_only": True}

        content = editorial.get("content", "")
        return {
            "available": True,
            "paid_only": False,
            "title": editorial.get("title", ""),
            "content": clean_html(content),
            "content_raw": content,
            "has_video": editorial.get("hasVideoSolution", False),
            "code_blocks": extract_code_blocks(content),
        }
    except Exception as e:
        print(f"  ⚠️  Editorial fetch failed: {e}")
        return None


def fetch_top_solutions(slug: str, max_per_lang: int = 2) -> dict:
    """Fetch top community solutions for key languages."""
    print(f"💡 Fetching community solutions for '{slug}'...")

    target_langs = ["cpp", "python3", "javascript", "java"]
    results = {}

    for lang in target_langs:
        print(f"  → {lang}...")
        try:
            data = gql(SOLUTIONS_QUERY, {
                "questionSlug": slug,
                "skip": 0,
                "first": max_per_lang,
                "orderBy": "HOT",
                "languageTags": [lang]
            })

            solutions_data = data["data"].get("questionSolutions", {})
            solutions = solutions_data.get("solutions", [])

            lang_solutions = []
            for sol in solutions:
                post = sol.get("post", {})
                content = clean_html(post.get("content", ""))
                code_blocks = extract_code_blocks(post.get("content", ""))

                lang_solutions.append({
                    "id": sol["id"],
                    "title": sol.get("title", ""),
                    "votes": post.get("voteCount", 0),
                    "author": post.get("author", {}).get("username", "anonymous"),
                    "content": content,
                    "code_blocks": code_blocks,
                    "tags": [t["name"] for t in sol.get("solutionTags", [])],
                    "created_at": post.get("creationDate", ""),
                })

            results[lang] = lang_solutions
            time.sleep(0.5)  # be polite

        except Exception as e:
            print(f"    ⚠️  Failed for {lang}: {e}")
            results[lang] = []

    return results


def pick_best_solution(editorial: dict | None, community: dict) -> dict:
    """
    Determine the best solution source.
    Priority: editorial > highest-voted community solution
    """
    source = "none"
    solution_data = {}

    if editorial and editorial.get("available") and editorial.get("code_blocks"):
        source = "editorial"
        # Map code blocks by language
        lang_map = {"cpp": [], "python": [], "javascript": [], "java": []}
        for block in editorial["code_blocks"]:
            lang = block["language"].lower()
            if "cpp" in lang or "c++" in lang:
                lang_map["cpp"].append(block["code"])
            elif "python" in lang:
                lang_map["python"].append(block["code"])
            elif "java" in lang and "javascript" not in lang:
                lang_map["java"].append(block["code"])
            elif "javascript" in lang or "js" in lang:
                lang_map["javascript"].append(block["code"])

        solution_data = {
            "source": "editorial",
            "explanation": editorial.get("content", ""),
            "codes": {
                "cpp": lang_map["cpp"][0] if lang_map["cpp"] else "",
                "python": lang_map["python"][0] if lang_map["python"] else "",
                "javascript": lang_map["javascript"][0] if lang_map["javascript"] else "",
                "java": lang_map["java"][0] if lang_map["java"] else "",
            }
        }

    elif community:
        source = "community"
        codes = {}
        lang_display = {"cpp": "cpp", "python3": "python", "javascript": "javascript", "java": "java"}

        for lc_lang, display_lang in lang_display.items():
            sols = community.get(lc_lang, [])
            if sols:
                best = max(sols, key=lambda x: x["votes"])
                blocks = best.get("code_blocks", [])
                codes[display_lang] = blocks[0]["code"] if blocks else ""
            else:
                codes[display_lang] = ""

        solution_data = {
            "source": "community",
            "explanation": "",
            "codes": codes,
        }

    solution_data["source_type"] = source
    return solution_data


# ─── Main Orchestrator ─────────────────────────────────────────────────────────

def run():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = DATA_DIR / f"{today}.json"

    # Skip if already fetched today
    if output_path.exists():
        print(f"✅ Data for {today} already exists. Skipping.")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch POTD
    potd = fetch_potd()
    slug = potd["slug"]
    print(f"✅ Got POTD: {potd['title']} [{potd['difficulty']}]")

    # Step 2: Try editorial
    editorial = fetch_editorial(slug)

    # Step 3: Try community solutions
    community = fetch_top_solutions(slug)

    # Step 4: Pick best solution source
    best_solution = pick_best_solution(editorial, community)
    print(f"✅ Solution source: {best_solution['source_type']}")

    # Step 5: Build final output
    result = {
        "meta": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "date": today,
            "ai_explanation_status": "pending",  # updated by AI step
        },
        "problem": potd,
        "editorial": editorial,
        "community_solutions": community,
        "best_solution": best_solution,
        "ai_explanation": None,  # populated by next script
    }

    # Step 6: Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved to {output_path}")
    print(f"   Problem: #{potd['id']} - {potd['title']}")
    print(f"   Tags: {', '.join(potd['tags'])}")
    print(f"   Editorial: {'✅' if editorial and editorial.get('available') else '❌'}")
    print(f"   Community solutions: {sum(len(v) for v in community.values())} found")

    # Step 7: Update index.json
    update_index(today, potd)


def update_index(date: str, potd: dict):
    """Maintain a rolling index of all problems."""
    index_path = DATA_DIR / "index.json"

    index = []
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)

    # Avoid duplicates
    index = [e for e in index if e["date"] != date]

    index.append({
        "date": date,
        "id": potd["id"],
        "title": potd["title"],
        "slug": potd["slug"],
        "difficulty": potd["difficulty"],
        "tags": potd["tags"],
        "link": potd["link"],
    })

    # Sort newest first
    index.sort(key=lambda x: x["date"], reverse=True)

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    print(f"✅ Index updated ({len(index)} problems total)")


if __name__ == "__main__":
    run()
