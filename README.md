# 🧠 LeetCode POTD Auto-Explainer

Fully automated daily pipeline that fetches LeetCode's Problem of the Day,
finds the best solution, and generates teacher-style AI explanations — for free.

---

## 📁 Project Structure

```
├── .github/
│   └── workflows/
│       ├── daily_fetch.yml       # Step 1: Fetch POTD at 5:30 AM IST
│       └── daily_explain.yml     # Step 2: AI explanation (coming next)
│
├── scripts/
│   ├── fetch_potd.py             # Fetches POTD + editorial + solutions
│   ├── generate_explanation.py   # AI explanation generator (coming next)
│   └── requirements.txt
│
├── data/
│   ├── index.json                # Rolling index of all problems
│   ├── 2025-03-12.json           # One file per day
│   └── ...
│
└── web/                          # Next.js website (coming next)
```

---

## ⚙️ How It Works

### Step 1 — Daily Fetch (5:30 AM IST / 00:00 UTC)
GitHub Actions runs `fetch_potd.py` which:
1. Queries LeetCode's public GraphQL API for today's POTD
2. Tries to fetch the official editorial (free if available)
3. Falls back to top community solutions (sorted by votes)
4. Picks the best solution source
5. Saves everything to `data/YYYY-MM-DD.json`
6. Updates `data/index.json`
7. Commits and pushes to the repo automatically

### Step 2 — AI Explanation (runs after Step 1)
Uses free Groq API (Llama 3.3 70B) to generate:
- Problem intuition
- Data structures used and why
- How to think about the solution
- Full solution code (C++, Python, JavaScript, Java)
- Line-by-line code walkthrough
- Time & Space complexity with justification

---

## 🚀 Setup

### 1. Fork this repo

### 2. Enable GitHub Actions
Go to your repo → Actions tab → Enable workflows

### 3. (Optional) Add Groq API key for AI explanations
Go to Settings → Secrets → Actions → New secret:
- Name: `GROQ_API_KEY`
- Value: your key from [console.groq.com](https://console.groq.com) (free)

### 4. Test manually
Actions tab → `Daily LeetCode POTD Fetch` → `Run workflow`

---

## 📊 Output Format (`data/YYYY-MM-DD.json`)

```json
{
  "meta": {
    "date": "2025-03-12",
    "fetched_at": "2025-03-12T00:01:23Z",
    "ai_explanation_status": "done"
  },
  "problem": {
    "id": "3",
    "title": "Longest Substring Without Repeating Characters",
    "difficulty": "Medium",
    "tags": ["Hash Table", "Sliding Window"],
    "description": "...",
    "hints": ["..."],
    "starter_codes": { "cpp": "...", "python3": "...", "javascript": "..." }
  },
  "editorial": { "available": true, "content": "...", "code_blocks": [] },
  "community_solutions": { "cpp": [...], "python3": [...] },
  "best_solution": {
    "source_type": "editorial",
    "codes": { "cpp": "...", "python": "...", "javascript": "..." }
  },
  "ai_explanation": {
    "intuition": "...",
    "data_structures": "...",
    "thinking_process": "...",
    "solution_flow": "...",
    "code_walkthrough": "...",
    "complexity": { "time": "O(n)", "space": "O(n)", "justification": "..." }
  }
}
```

---

## 🛠️ Local Development

```bash
git clone https://github.com/YOUR_USERNAME/leetcode-potd-explainer
cd leetcode-potd-explainer
pip install -r scripts/requirements.txt
python scripts/fetch_potd.py
```

---

## ⏰ Cron Schedule

| Time | Action |
|------|--------|
| 00:00 UTC (5:30 AM IST) | Fetch POTD, editorial, solutions |
| 00:15 UTC (5:45 AM IST) | Generate AI explanation |
| 00:30 UTC (6:00 AM IST) | Website auto-redeploys on Vercel |

---

## 📄 License
MIT
