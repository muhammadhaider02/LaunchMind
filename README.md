<div align="center">

# LaunchMind

**Autonomous Multi-Agent Startup Launcher**

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9)](https://docs.astral.sh/uv/)
[![GitHub Models](https://img.shields.io/badge/GitHub_Models-LLM-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Slack](https://img.shields.io/badge/Slack-Bot-4A154B?logo=slack&logoColor=white)](https://api.slack.com/)
[![SendGrid](https://img.shields.io/badge/SendGrid-Email-1A82E2?logo=twilio&logoColor=white)](https://sendgrid.com/)

Takes a startup idea as plain text and autonomously runs a full micro-startup launch: product spec, landing page, GitHub PR, cold outreach email and Slack announcement. No human involvement after the idea is submitted.

</div>

---

## Table of Contents

- [Overview](#overview)
- [Agent Architecture](#agent-architecture)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Platform Integrations](#platform-integrations)
- [Project Structure](#project-structure)

---

## Overview

LaunchMind is a five-agent system where each agent owns a distinct role and communicates through a shared message bus. Every inter-agent message is a structured JSON object carrying `message_id`, `from_agent`, `to_agent`, `message_type`, `payload` and `timestamp`.

**Example run:** Input: *"A tool that tracks your expenses and tells you where you're wasting money"* → Named startup **SaasSweep**, complete product spec, landing page committed to GitHub, PR opened, email sent, two Slack messages posted. Fully autonomous.

Generated startup landing pages are published to [LaunchMind-Startups](https://github.com/muhammadhaider02/LaunchMind-Startups).

---

## Agent Architecture

```
Startup Idea (CLI input)
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │             CEO Agent (Orchestrator)        │
  │  - Decomposes idea into tasks (LLM)         │
  │  - Reviews every agent output (LLM)         │
  │  - Triggers revision loops on poor output   │
  │  - Posts final summary to Slack             │
  └──────────────┬──────────────────────────────┘
                 │ task
                 ▼
        ┌─────────────────┐
        │  Product Agent  │  → generates product spec (value prop,
        └────────┬────────┘    personas, features, user stories)
                 │ result (spec JSON)
        ┌────────┴────────┐
        │                 │  (parallel threads)
        ▼                 ▼
 ┌─────────────┐   ┌───────────────────┐
 │  Engineer   │   │  Marketing Agent  │
 │  Agent      │   │                   │
 │             │   │  - Generates copy │
 │  - Landing  │   │  - Sends email    │
 │    page     │   │  - Posts to Slack │
 │  - GitHub   │   └────────┬──────────┘
 │    branch,  │            │
 │    commit,  │            │
 │    issue, PR│            │
 └──────┬──────┘            │
        │ result            │
        └────────┬──────────┘
                 │
                 ▼
          ┌─────────────┐
          │   QA Agent  │  → reviews code + copy (LLM)
          │             │  → posts inline PR comments (GitHub API)
          └──────┬──────┘  → pass/fail verdict → CEO
                 │
                 ▼
         CEO reasons about QA verdict (LLM)
         → accept or send revision_request to Engineer/Marketing
                 │
                 ▼
         Marketing posts to Slack with approved PR link
         CEO posts final summary to Slack
```

### Message Flow

| From | To | Message Type |
|:---|:---|:---|
| CEO | Product | `task` |
| Product | Engineer | `result` (spec) |
| Product | Marketing | `result` (spec) |
| Product | CEO | `confirmation` |
| Engineer | CEO | `result` (PR + issue URLs) |
| Marketing | CEO | `result` (all copy) |
| CEO | QA | `task` (code + copy + PR URL) |
| QA | CEO | `result` (review report) |
| CEO | Engineer | `revision_request` (if QA fails) |
| CEO | Marketing | `revision_request` (if QA fails) |
| CEO | Marketing | `task` (PR URL after QA approves) |

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- GitHub account with a public repository for startup pages
- Slack workspace with a bot installed in `#launches`
- SendGrid account with a verified sender email

---

## Getting Started

```bash
git clone https://github.com/muhammadhaider02/LaunchMind.git
cd LaunchMind
uv sync
cp .env.example .env
```

Fill in all values in `.env` then run the system.

---

## Configuration

| Variable | Used By | Purpose |
|:---|:---|:---|
| `GITHUB_USERNAME` | Engineer | GitHub account owner |
| `GITHUB_STARTUPS_REPO` | Engineer, QA | `username/repo` where startups are committed |
| `GITHUB_MODELS_TOKEN` | All agents | Fine-grained PAT (Models read-only) for LLM calls via GitHub Models API |
| `GITHUB_TOKEN` | Engineer, QA | Classic PAT (repo scope) for GitHub API write access |
| `SLACK_BOT_TOKEN` | Marketing, CEO | `xoxb-` bot token for posting to Slack |
| `SENDGRID_API_KEY` | Marketing | SendGrid Mail Send API key |
| `SENDGRID_FROM_EMAIL` | Marketing | Verified sender address in SendGrid |
| `MARKETING_TEST_EMAIL` | Marketing | Recipient address for cold outreach email |

---

## Usage

```bash
# With a custom idea
uv run main.py "Your startup idea here"

# With the default demo idea
uv run main.py
```

Terminal output shows every agent action and every message sent in real time.

---

## Platform Integrations

| Platform | Agent | What it does |
|:---|:---|:---|
| **GitHub** | Engineer | Creates a new branch, commits the landing page, opens a GitHub issue and a PR with LLM-generated title and body. Commit is authored as `EngineerAgent <agent@launchmind.ai>`. |
| **GitHub** | QA | Posts at least 2 inline review comments on the Engineer's PR via the GitHub API. |
| **Slack (`#launches`)** | Marketing | Posts a Block Kit launch announcement with tagline, product description and a link to the GitHub PR after QA approves. |
| **Slack (`#launches`)** | CEO | Posts a final Block Kit summary with the startup name, original idea, tagline and PR link once the full pipeline completes. |
| **SendGrid** | Marketing | Sends a cold outreach email with LLM-generated subject and body to the configured test address. |

---

## Project Structure

```
LaunchMind/
├── agents/
│   ├── ceo_agent.py         <- orchestrator: task decomposition, output review, QA reasoning
│   ├── product_agent.py     <- generates structured product spec JSON
│   ├── engineer_agent.py    <- code generation, GitHub branch/commit/issue/PR
│   ├── marketing_agent.py   <- copy generation, SendGrid email, Slack Block Kit posts
│   └── qa_agent.py          <- code + copy review, inline PR comments, pass/fail verdict
├── main.py                  <- entry point: wires all agents and runs the pipeline
├── message_bus.py           <- shared bus: send, receive and log all agent messages
├── .env.example             <- template for required environment variables
└── pyproject.toml
```
