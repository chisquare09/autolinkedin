from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_profile_url(value: str) -> str:
    if not value or not isinstance(value, str):
        raise ValueError("LinkedIn profile URL is missing")
    raw = value.strip()
    if not raw:
        raise ValueError("LinkedIn profile URL is empty")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.netloc.lower() not in {"linkedin.com", "www.linkedin.com"}:
        raise ValueError(f"unsupported LinkedIn host: {parts.netloc}")
    path_parts = [part for part in parts.path.split("/") if part]
    if path_parts and path_parts[-1].lower() == "posts":
        path_parts.pop()
    path = "/" + "/".join(path_parts)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in {"trk", "originalsubdomain", "feedview"}]
    return urlunsplit(("https", "www.linkedin.com", path.lower(), urlencode(query), "")).rstrip("/")


def deduplicate_mappings(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        customer = str(row.get("customer_name", "")).strip()
        url = normalize_profile_url(str(row.get("linkedin_profile_url", "")))
        key = (customer, url)
        if not customer:
            raise ValueError("customer_name is required")
        if key not in seen:
            seen.add(key)
            result.append({"customer_name": customer, "linkedin_profile_url": url})
    return result
