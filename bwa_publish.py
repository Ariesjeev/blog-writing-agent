"""One-click publishing. Credentials come from environment variables (.env):
DEVTO_API_KEY | HASHNODE_TOKEN + HASHNODE_PUBLICATION_ID | MEDIUM_TOKEN | GITHUB_TOKEN + GITHUB_REPO (owner/repo)
Local images (images/...) are NOT uploaded; host them first or replace the links."""
from __future__ import annotations

import base64
import os
import re
from typing import Dict, List

import requests

T = 30
ENV = {
    "Dev.to": ["DEVTO_API_KEY"],
    "Hashnode": ["HASHNODE_TOKEN", "HASHNODE_PUBLICATION_ID"],
    "Medium": ["MEDIUM_TOKEN"],
    "GitHub": ["GITHUB_TOKEN", "GITHUB_REPO"],
}


def status() -> Dict[str, List[str]]:
    """platform -> list of missing env vars (empty list = ready)."""
    return {p: [v for v in vs if not os.getenv(v)] for p, vs in ENV.items()}


def _ok(r: requests.Response) -> dict:
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


def _tag(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def publish(platform: str, title: str, md: str, tags: List[str], description: str = "",
            slug: str = "post", live: bool = False) -> str:
    tags = [x for x in (_tag(t) for t in tags) if x]
    body = re.sub(r"\A# .*\n+", "", md, count=1)  # platforms render the title themselves

    if platform == "Dev.to":
        r = requests.post("https://dev.to/api/articles", timeout=T,
                          headers={"api-key": os.environ["DEVTO_API_KEY"]},
                          json={"article": {"title": title, "body_markdown": body, "published": live,
                                            "tags": tags[:4], "description": description[:160]}})
        return _ok(r).get("url", "created")

    if platform == "Hashnode":  # publishes immediately
        q = "mutation($i: PublishPostInput!){ publishPost(input:$i){ post{ url } } }"
        r = requests.post("https://gql.hashnode.com", timeout=T,
                          headers={"Authorization": os.environ["HASHNODE_TOKEN"]},
                          json={"query": q, "variables": {"i": {
                              "title": title, "contentMarkdown": body,
                              "publicationId": os.environ["HASHNODE_PUBLICATION_ID"],
                              "tags": [{"slug": t, "name": t} for t in tags[:5]]}}})
        data = _ok(r)
        if data.get("errors"):
            raise RuntimeError(str(data["errors"])[:300])
        return data["data"]["publishPost"]["post"]["url"]

    if platform == "Medium":  # Medium no longer issues new API tokens; works only for existing ones
        h = {"Authorization": f"Bearer {os.environ['MEDIUM_TOKEN']}"}
        uid = _ok(requests.get("https://api.medium.com/v1/me", headers=h, timeout=T))["data"]["id"]
        r = requests.post(f"https://api.medium.com/v1/users/{uid}/posts", headers=h, timeout=T,
                          json={"title": title, "contentFormat": "markdown", "content": f"# {title}\n\n{body}",
                                "tags": tags[:5], "publishStatus": "public" if live else "draft"})
        return _ok(r)["data"]["url"]

    if platform == "GitHub":
        repo, path = os.environ["GITHUB_REPO"], f"posts/{slug}.md"
        h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        existing = requests.get(url, headers=h, timeout=T)
        payload = {"message": f"Add post: {title}", "content": base64.b64encode(md.encode()).decode()}
        if existing.ok:
            payload["sha"] = existing.json()["sha"]
        return _ok(requests.put(url, headers=h, json=payload, timeout=T))["content"]["html_url"]

    raise ValueError(f"Unknown platform: {platform}")