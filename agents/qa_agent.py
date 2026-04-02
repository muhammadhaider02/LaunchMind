import os
import json
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


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def review_html(html: str, spec: dict) -> dict:
    """LLM call #1 — review HTML against product spec."""
    system_prompt = """You are a strict QA engineer reviewing an HTML landing page against a product specification.

Check the following:
- Does the headline reflect the value proposition?
- Are all features from the spec mentioned on the page?
- Is there a clear call-to-action button?
- Is the page specific to this product or does it feel generic?
- Is the HTML well-structured and complete?

Respond ONLY with a valid JSON object:
{
  "verdict": "pass" or "fail",
  "issues": ["<specific issue 1>", "<specific issue 2>"],
  "inline_comments": [
    {
      "line_note": "<comment text>",
      "context": "<short snippet of HTML this comment refers to>"
    }
  ],
  "summary": "<overall review summary>"
}

Rules:
- Always provide at least 2 inline_comments regardless of verdict
- Issues must be specific and actionable
- If verdict is pass, issues can be minor suggestions"""

    user_prompt = f"Product spec:\n{json.dumps(spec, indent=2)}\n\nHTML:\n{html}"
    return call_llm(system_prompt, user_prompt)


def review_marketing_copy(copy: dict, spec: dict) -> dict:
    """LLM call #2 — review marketing copy against product spec."""
    system_prompt = """You are a strict QA reviewer checking marketing copy against a product specification.

Check the following:
- Is the tagline compelling and specific to this product?
- Does the cold email have a clear call to action?
- Is the tone of the cold email appropriate for early users or investors?
- Do the social media posts match the product's value proposition?
- Is all copy specific to this product or does it feel generic?

Respond ONLY with a valid JSON object:
{
  "verdict": "pass" or "fail",
  "issues": ["<specific issue 1>", "<specific issue 2>"],
  "summary": "<overall review summary>"
}"""

    user_prompt = f"Product spec:\n{json.dumps(spec, indent=2)}\n\nMarketing copy:\n{json.dumps(copy, indent=2)}"
    return call_llm(system_prompt, user_prompt)


def get_pr_number(pr_url: str) -> int:
    """Extract PR number from URL."""
    return int(pr_url.rstrip("/").split("/")[-1])


def get_pr_commit_sha(pr_number: int) -> str:
    """Get the latest commit SHA on the PR."""
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/pulls/{pr_number}/commits",
        headers=GITHUB_HEADERS,
    )
    r.raise_for_status()
    commits = r.json()
    return commits[-1]["sha"]


def get_file_in_pr(pr_number: int, folder_name: str) -> tuple[str, int]:
    """
    Get HTML file content and line count from the PR.
    Returns (html_content, total_lines).
    """
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/pulls/{pr_number}/files",
        headers=GITHUB_HEADERS,
    )
    r.raise_for_status()
    files = r.json()
    for f in files:
        if f["filename"].endswith("index.html"):
            patch = f.get("patch", "")
            lines = patch.split("\n") if patch else []
            return f["filename"], len(lines)
    return f"{folder_name}/index.html", 10


def post_pr_review_comments(pr_number: int, commit_sha: str, filename: str, inline_comments: list) -> None:
    """Post inline review comments on the PR via GitHub API."""
    print(f"[QA] Posting {len(inline_comments)} inline comment(s) on PR #{pr_number}...")

    # Use at least 2 comments, cap at what we have
    comments_to_post = inline_comments[:max(2, len(inline_comments))]

    for i, comment in enumerate(comments_to_post):
        # Use different line positions for each comment
        line_position = 5 + (i * 10)
        r = requests.post(
            f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/pulls/{pr_number}/comments",
            headers=GITHUB_HEADERS,
            json={
                "body": comment["line_note"],
                "commit_id": commit_sha,
                "path": filename,
                "position": line_position,
            },
        )
        if r.status_code in (200, 201):
            print(f"[QA] Comment posted: {comment['line_note'][:60]}...")
        else:
            # Fallback: post as general PR comment if inline fails
            print(f"[QA] Inline comment failed (status {r.status_code}), posting as general comment...")
            requests.post(
                f"https://api.github.com/repos/{GITHUB_STARTUPS_REPO}/issues/{pr_number}/comments",
                headers=GITHUB_HEADERS,
                json={"body": f"**QA Review:** {comment['line_note']}"},
            )


def run() -> dict | None:
    """
    Pick up Engineer HTML + Marketing copy from CEO inbox.
    Review both, post PR comments, send verdict to CEO.
    """
    messages = get_messages("qa")
    if not messages:
        print("[QA] No messages in inbox.")
        return None

    # Find the task message from CEO
    task_msg = next((m for m in messages if m["from_agent"] == "ceo" and m["message_type"] == "task"), None)
    if not task_msg:
        print("[QA] No task from CEO found.")
        return None

    payload = task_msg["payload"]
    html = payload.get("html", "")
    spec = payload.get("spec", {})
    pr_url = payload.get("pr_url", "")
    marketing_copy = payload.get("marketing_copy", {})
    folder_name = payload.get("folder_name", "startup")

    print(f"\n[QA] Received review task from CEO.")
    print(f"[QA] PR URL: {pr_url}")

    # --- LLM Review #1: HTML ---
    print("[QA] Reviewing HTML landing page...")
    html_review = review_html(html, spec)
    print(f"[QA] HTML verdict: {html_review['verdict']}")
    if html_review.get("issues"):
        for issue in html_review["issues"]:
            print(f"  - {issue}")

    # --- LLM Review #2: Marketing copy ---
    print("[QA] Reviewing marketing copy...")
    copy_review = review_marketing_copy(marketing_copy, spec)
    print(f"[QA] Marketing copy verdict: {copy_review['verdict']}")
    if copy_review.get("issues"):
        for issue in copy_review["issues"]:
            print(f"  - {issue}")

    # --- Post inline PR comments ---
    if pr_url:
        try:
            pr_number = get_pr_number(pr_url)
            commit_sha = get_pr_commit_sha(pr_number)
            filename, _ = get_file_in_pr(pr_number, folder_name)
            inline_comments = html_review.get("inline_comments", [])
            if inline_comments:
                post_pr_review_comments(pr_number, commit_sha, filename, inline_comments)
        except Exception as e:
            print(f"[QA] PR comment error: {e}")

    # --- Overall verdict ---
    overall_verdict = "pass" if (html_review["verdict"] == "pass" and copy_review["verdict"] == "pass") else "fail"
    print(f"\n[QA] Overall verdict: {overall_verdict}")

    # --- Send review report to CEO ---
    report = {
        "verdict": overall_verdict,
        "html_review": html_review,
        "copy_review": copy_review,
        "pr_url": pr_url,
    }
    send_message(
        from_agent="qa",
        to_agent="ceo",
        message_type="result",
        payload=report,
        parent_message_id=task_msg["message_id"],
    )
    print("[QA] Review report sent to CEO.")
    return report