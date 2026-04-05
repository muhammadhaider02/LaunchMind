# LaunchMind

A Multi-Agent System (MAS) that takes a startup idea as plain text and autonomously runs a full micro-startup launch: generating a product spec, building a landing page, opening a real GitHub pull request, sending a cold outreach email via SendGrid, and posting to Slack. No human involvement after the idea is submitted.

Generated startup landing pages are published to [LaunchMind-Startups](https://github.com/muhammadhaider02/LaunchMind-Startups).

> **Example run:** Input: *"A tool that tracks your expenses and tells you where you're wasting money"* → Output: Named startup **SaasSweep**, complete product spec, landing page committed to GitHub, PR opened, email sent, two Slack messages posted. fully autonomous.

---

## Agent Architecture

Five agents collaborate through a shared message bus. Every inter-agent message is a structured JSON object with `message_id`, `from_agent`, `to_agent`, `message_type`, `payload`, and `timestamp`.

```
Startup Idea (CLI input)
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │              CEO Agent (Orchestrator)        │
  │  - Decomposes idea into tasks (LLM)          │
  │  - Reviews every agent output (LLM)          │
  │  - Triggers revision loops on poor output    │
  │  - Posts final summary to Slack              │
  └──────────────┬──────────────────────────────┘
                 │ task
                 ▼
        ┌────────────────┐
        │  Product Agent  │ → generates product spec (value prop, personas,
        └────────┬────────┘   features, user stories)
                 │ result (spec JSON)
        ┌────────┴────────┐
        │                 │ (parallel threads)
        ▼                 ▼
 ┌─────────────┐   ┌──────────────────┐
 │  Engineer   │   │  Marketing Agent  │
 │  Agent      │   │                   │
 │             │   │ - Generates copy  │
 │ - HTML page │   │ - Sends email     │
 │ - GitHub    │   │ - Posts to Slack  │
 │   branch,   │   └────────┬──────────┘
 │   commit,   │            │
 │   issue, PR │            │
 └──────┬──────┘            │
        │ result            │
        └────────┬──────────┘
                 │
                 ▼
          ┌─────────────┐
          │   QA Agent   │ → reviews HTML + copy (LLM)
          │              │ → posts inline PR comments (GitHub API)
          └──────┬───────┘ → pass/fail verdict → CEO
                 │
                 ▼
         CEO reasons about QA verdict (LLM)
         → accept or send revision_request to Engineer/Marketing
                 │
                 ▼
         Marketing posts to Slack with approved PR link
         CEO posts final summary to Slack
```

### Which agent talks to which

| From | To | Message Type |
|---|---|---|
| CEO | Product | `task` |
| Product | Engineer | `result` (spec) |
| Product | Marketing | `result` (spec) |
| Product | CEO | `confirmation` |
| Engineer | CEO | `result` (PR + issue URLs) |
| Marketing | CEO | `result` (all copy) |
| CEO | QA | `task` (HTML + copy + PR URL) |
| QA | CEO | `result` (review report) |
| CEO | Engineer | `revision_request` (if QA fails) |
| CEO | Marketing | `revision_request` (if QA fails) |
| CEO | Marketing | `task` (PR URL after QA approves) |

---

## Setup Instructions

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- A GitHub account with a public repository
- A Slack workspace with a bot installed in `#launches`
- A SendGrid account with a verified sender email

### 1. Clone the repository

```bash
git clone https://github.com/muhammadhaider02/LaunchMind.git
cd LaunchMind
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Set environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in all values:

```env
GITHUB_USERNAME=your_github_username
GITHUB_STARTUPS_REPO=username/your-startups-repo
GITHUB_MODELS_TOKEN=your_fine_grained_pat_models_readonly
GITHUB_TOKEN=your_classic_pat_repo_scope
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SENDGRID_API_KEY=SG.your_sendgrid_key
SENDGRID_FROM_EMAIL=your_verified_sender@example.com
MARKETING_TEST_EMAIL=your_test_inbox@example.com
```

### 4. Run the system

```bash
# With a custom idea
uv run main.py "Your startup idea here"

# With the default demo idea
uv run main.py
```

The entire pipeline runs end-to-end. Terminal output shows every agent action and every message sent in real time.

---

## Platform Integrations

| Platform | Agent | What it does |
|---|---|---|
| **GitHub** | Engineer | Creates a new branch, commits the HTML landing page, opens a GitHub issue titled for the startup, opens a pull request with LLM-generated title and body. Commit is authored as `EngineerAgent <agent@launchmind.ai>`. |
| **GitHub** | QA | Posts at least 2 inline review comments on the Engineer's pull request via the GitHub API. |
| **Slack (`#launches`)** | Marketing | Posts a Block Kit launch announcement including tagline, product description, and a link to the GitHub PR — only after QA approves. |
| **Slack (`#launches`)** | CEO | Posts a final Block Kit summary message with the startup name, original idea, tagline, and PR link once the full pipeline completes. |
| **SendGrid (Email)** | Marketing | Sends a cold outreach email with LLM-generated subject and body to the configured test address. |

---

## Repository Structure

```
launchmind/
├── agents/
│   ├── ceo_agent.py         # Orchestrator — task decomposition, output review, QA reasoning
│   ├── product_agent.py     # Generates structured product spec JSON
│   ├── engineer_agent.py    # HTML generation, GitHub branch/commit/issue/PR
│   ├── marketing_agent.py   # Copy generation, SendGrid email, Slack Block Kit post
│   └── qa_agent.py          # HTML + copy review, inline PR comments, pass/fail verdict
├── message_bus.py           # Shared message bus — send, receive, and log all agent messages
├── main.py                  # Entry point — wires all agents together and runs the pipeline
├── pyproject.toml           # Dependencies (FastAPI, OpenAI, requests, sendgrid, python-dotenv)
├── .env.example             # Template for required environment variables
├── .gitignore               # Excludes .env, .venv, __pycache__
└── README.md
```

---

## Environment Variables Reference

| Variable | Used By | Purpose |
|---|---|---|
| `GITHUB_USERNAME` | Engineer | GitHub account owner |
| `GITHUB_STARTUPS_REPO` | Engineer, QA | `username/repo` where startups are committed |
| `GITHUB_MODELS_TOKEN` | All agents | Fine-grained PAT (Models read-only) — LLM calls via GitHub Models API |
| `GITHUB_TOKEN` | Engineer, QA | Classic PAT (repo scope) — GitHub API write access |
| `SLACK_BOT_TOKEN` | Marketing, CEO | `xoxb-` bot token for posting to Slack |
| `SENDGRID_API_KEY` | Marketing | SendGrid Mail Send API key |
| `SENDGRID_FROM_EMAIL` | Marketing | Verified sender address in SendGrid |
| `MARKETING_TEST_EMAIL` | Marketing | Recipient address for cold outreach email |
