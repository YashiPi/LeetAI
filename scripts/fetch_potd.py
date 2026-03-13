import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPHQL = "https://leetcode.com/graphql"

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SESSION = os.getenv("LEETCODE_SESSION", "")
CSRF = os.getenv("LEETCODE_CSRF_TOKEN", "")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://leetcode.com",
    "Origin": "https://leetcode.com",
    "x-csrftoken": CSRF,
    "x-requested-with": "XMLHttpRequest",
    "Cookie": f"LEETCODE_SESSION={SESSION}; csrftoken={CSRF}",
}


def gql(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    r = requests.post(GRAPHQL, json=payload, headers=HEADERS, timeout=20)
    data = r.json()

    if "errors" in data:
        print("GraphQL error:", data["errors"])

    return data


# ─────────────────────────────
# POTD QUERY
# ─────────────────────────────

POTD_QUERY = """
query questionOfToday {
  activeDailyCodingChallengeQuestion {
    date
    link
    question {
      questionFrontendId
      title
      titleSlug
      difficulty
      content
      topicTags { name }
      codeSnippets {
        lang
        langSlug
        code
      }
    }
  }
}
"""


def fetch_potd():
    print("Fetching POTD...")

    data = gql(POTD_QUERY)

    q = data["data"]["activeDailyCodingChallengeQuestion"]
    question = q["question"]

    return {
        "date": q["date"],
        "link": "https://leetcode.com" + q["link"],
        "id": question["questionFrontendId"],
        "title": question["title"],
        "slug": question["titleSlug"],
        "difficulty": question["difficulty"],
        "tags": [t["name"] for t in question["topicTags"]],
        "content_html": question["content"],
        "starter_code": question["codeSnippets"],
    }


# ─────────────────────────────
# EDITORIAL
# ─────────────────────────────

EDITORIAL_QUERY = """
query questionEditorial($slug: String!) {
  question(titleSlug: $slug) {
    solution {
      content
      paidOnly
    }
  }
}
"""


def fetch_editorial(slug):
    print("Fetching editorial...")

    data = gql(EDITORIAL_QUERY, {"slug": slug})
    solution = data["data"]["question"]["solution"]

    if not solution:
        return None

    if solution["paidOnly"]:
        return {"paid_only": True}

    return {
        "paid_only": False,
        "content": solution["content"]
    }


# ─────────────────────────────
# COMMUNITY SOLUTIONS
# ─────────────────────────────

SOLUTIONS_QUERY = """
query questionSolutions($slug: String!, $skip: Int!, $first: Int!) {
  questionSolutions(
    questionSlug: $slug
    skip: $skip
    first: $first
    orderBy: MOST_VOTES
  ) {
    edges {
      node {
        title
        url
        upvoteCount
        viewCount
      }
    }
  }
}
"""


def fetch_community(slug):
    print("Fetching community solutions...")

    data = gql(
        SOLUTIONS_QUERY,
        {
            "slug": slug,
            "skip": 0,
            "first": 5
        },
    )

    edges = data["data"]["questionSolutions"]["edges"]

    solutions = []

    for e in edges:
        n = e["node"]
        solutions.append({
            "title": n["title"],
            "url": "https://leetcode.com" + n["url"],
            "votes": n["upvoteCount"],
            "views": n["viewCount"]
        })

    return solutions


# ─────────────────────────────
# MAIN
# ─────────────────────────────

def run():

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"{today}.json"

    if output_file.exists():
        print("Already fetched today.")
        return

    potd = fetch_potd()
    slug = potd["slug"]

    editorial = fetch_editorial(slug)
    community = fetch_community(slug)

    result = {
        "meta": {
            "date": today,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        },
        "problem": potd,
        "editorial": editorial,
        "community_solutions": community
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print("Saved:", output_file)


if __name__ == "__main__":
    run()
