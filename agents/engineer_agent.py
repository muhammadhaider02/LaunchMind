import os
import json
import base64
import re
import requests
from openai import OpenAI
from message_bus import send_message, get_messages

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_MODELS_TOKEN"],
)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_STARTUPS_REPO = os.environ["GITHUB_STARTUPS_REPO"]
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def call_llm(system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def slugify(name: str) -> str:
    """Convert startup name to a safe branch/folder name."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    return name[:40]


def generate_landing_page_and_name(spec: dict, feedback: str | None = None) -> dict:
    """
    Single LLM call — generates:
    - A short 2-word startup name
    - A complete HTML landing page
    """
    system_prompt = """You are a frontend developer and startup naming expert.
Given a product specification, you will:
1. Come up with a short, catchy 2-word startup name (e.g. "NextBook", "BookCycle")
2. Generate a complete single-file HTML landing page for that startup

The landing page must include:
- A compelling headline using the value proposition
- A subheadline
- A features section listing all features
- A call-to-action button (e.g. 'Start Free Trial', 'See Demo')
- Basic inline CSS — clean, modern, professional

Respond ONLY with a valid JSON object:
{
  "startup_name": "<2-word startup name, no spaces, PascalCase e.g. NextBook>",
  "html": "<complete raw HTML string>"
}"""

    user_prompt = f"Product spec:\n{json.dumps(spec, indent=2)}"
    if feedback:
        user_prompt += f"\n\nRevision feedback from CEO: {feedback}\nAddress every point in the feedback."

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def generate_pr_content(spec: dict, startup_name: str) -> dict:
    """LLM call — generate GitHub issue description and PR title/body."""
    system_prompt = """You are a software engineer writing GitHub issue and pull request content.
Based on the product spec and startup name, generate:
- A GitHub issue description for the landing page
- A pull request title in conventional commit format: "feat: add {startup_name} landing page"
- A pull request body

Respond ONLY with a valid JSON object:
{
  "issue_description": "<markdown description>",
  "pr_title": "feat: add {startup_name} landing page",
  "pr_body": "<markdown PR body>"
}"""

    user_prompt = f"Startup name: {startup_name}\nProduct spec:\n{json.dumps(spec, indent=2)}"
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def get_default_branch_sha() -> str:
    """Get the SHA of the latest commit on main."""
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/git/refs/heads/main",
        headers=GITHUB_HEADERS,
    )
    r.raise_for_status()
    return r.json()["object"]["sha"]


def create_branch(branch_name: str, sha: str) -> None:
    """Create a new branch from the given SHA. Skip silently if already exists."""
    print(f"[Engineer] Creating branch: {branch_name}...")
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/git/refs",
        headers=GITHUB_HEADERS,
        json={"ref": f"refs/heads/{branch_name}", "sha": sha},
    )
    if r.status_code == 422:
        print(f"[Engineer] Branch {branch_name} already exists. Reusing it.")
        return
    r.raise_for_status()


def commit_file(branch_name: str, folder_name: str, html_content: str, startup_name: str) -> None:
    """Commit index.html — create or update if already exists on branch."""
    file_path = f"{folder_name}/index.html"
    print(f"[Engineer] Committing {file_path} to branch {branch_name}...")
    encoded = base64.b64encode(html_content.encode()).decode()

    # Check if file already exists to get its SHA (required for updates)
    existing = requests.get(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/contents/{file_path}",
        headers=GITHUB_HEADERS,
        params={"ref": branch_name},
    )
    payload = {
        "message": f"feat: add {startup_name} landing page",
        "content": encoded,
        "branch": branch_name,
        "author": {
            "name": "EngineerAgent",
            "email": "agent@launchmind.ai",
        },
    }
    if existing.status_code == 200:
        payload["sha"] = existing.json()["sha"]
        payload["message"] = f"fix: revise {startup_name} landing page per QA feedback"

    r = requests.put(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/contents/{file_path}",
        headers=GITHUB_HEADERS,
        json=payload,
    )
    r.raise_for_status()
    print(f"[Engineer] File committed.")


def create_issue(description: str, startup_name: str) -> str:
    """Create a GitHub issue. Returns issue URL."""
    print(f"[Engineer] Creating GitHub issue...")
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/issues",
        headers=GITHUB_HEADERS,
        json={
            "title": f"feat: add {startup_name} landing page",
            "body": description,
        },
    )
    r.raise_for_status()
    url = r.json()["html_url"]
    print(f"[Engineer] Issue created: {url}")
    return url


def open_pull_request(branch_name: str, pr_title: str, pr_body: str) -> str:
    """Open a pull request. Returns PR URL. If PR already exists, return existing URL."""
    print(f"[Engineer] Opening pull request...")
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/pulls",
        headers=GITHUB_HEADERS,
        json={
            "title": pr_title,
            "body": pr_body,
            "head": branch_name,
            "base": "main",
        },
    )
    if r.status_code == 422:
        # PR already exists — fetch and return existing PR URL
        print(f"[Engineer] PR already exists. Fetching existing PR URL...")
        existing = requests.get(
            f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/pulls",
            headers=GITHUB_HEADERS,
            params={"head": f"{GITHUB_STARTUPS_REPO.split('/')[0]}:{branch_name}", "state": "open"},
        )
        if existing.status_code == 200 and existing.json():
            url = existing.json()[0]["html_url"]
            print(f"[Engineer] Existing PR: {url}")
            return url

    r.raise_for_status()
    url = r.json()["html_url"]
    print(f"[Engineer] PR opened: {url}")
    return url


def run() -> dict | None:
    """Pick up product spec or revision_request from inbox and execute all GitHub actions."""
    messages = get_messages("engineer")
    if not messages:
        print("[Engineer] No messages in inbox.")
        return None

    msg = messages[-1]
    print(f"\n[Engineer] Received '{msg['message_type']}' from {msg['from_agent'].upper()}")

    # Handle both product spec and CEO revision requests
    if msg["message_type"] == "revision_request":
        spec = msg["payload"].get("spec", {})
        feedback = msg["payload"].get("feedback", "")
    else:
        spec = msg["payload"]
        feedback = None

    # --- Single LLM call: startup name + HTML ---
    print("[Engineer] Generating startup name and landing page...")
    generated = generate_landing_page_and_name(spec, feedback)
    startup_name = generated["startup_name"]
    html = generated["html"]
    folder_name = slugify(startup_name)
    branch_name = f"startup/{folder_name}"
    print(f"[Engineer] Startup name: {startup_name} | Branch: {branch_name}")

    # --- PR and issue content ---
    print("[Engineer] Generating PR and issue content...")
    pr_content = generate_pr_content(spec, startup_name)

    # --- GitHub actions ---
    sha = get_default_branch_sha()
    create_branch(branch_name, sha)
    commit_file(branch_name, folder_name, html, startup_name)
    issue_url = create_issue(pr_content["issue_description"], startup_name)
    pr_url = open_pull_request(branch_name, pr_content["pr_title"], pr_content["pr_body"])

    # --- Report back to CEO ---
    result = {
        "startup_name": startup_name,
        "folder_name": folder_name,
        "html": html,
        "repo": f"https://github.com/{GITHUB_STARTUPS_REPO}",
        "pr_url": pr_url,
        "issue_url": issue_url,
    }
    send_message(
        from_agent="engineer",
        to_agent="ceo",
        message_type="result",
        payload=result,
        parent_message_id=msg["message_id"],
    )
    print(f"[Engineer] Done. Results sent to CEO.")
    return result