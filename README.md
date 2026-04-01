# LaunchMind

A Multi-Agent System (MAS) that takes a startup idea and autonomously runs it — generating a product spec, building a landing page, opening a GitHub PR, sending a cold outreach email and posting to Slack. No human involvement after the idea is submitted.

## Agents

| Agent | Role |
|---|---|
| CEO | Orchestrates the pipeline, reviews outputs, triggers revision loops |
| Product | Generates value proposition, personas, features, and user stories |
| Engineer | Builds HTML landing page, creates GitHub repo, commits code, opens PR |
| Marketing | Writes copy, sends email via SendGrid, posts to Slack |
| QA | Reviews Engineer and Marketing outputs, posts PR comments, returns pass/fail |

## Setup
```bash
uv sync
cp .env.example .env
# Fill in your API keys in .env
uv run main.py
```

## Environment Variables

See `.env.example` for required keys.