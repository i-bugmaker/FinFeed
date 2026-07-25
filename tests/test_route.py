#!/usr/bin/env python3
from urllib.parse import urlparse

paths = ["/api/sentiment", "/api/news", "/api/search", "/sentiment", "/"]

for path in paths:
    parsed = urlparse(path)
    print(f"路径: {path}")
    
    if parsed.path == "/" or parsed.path.startswith("/index"):
        print("  -> _serve_html")
    elif parsed.path.startswith("/api/news"):
        print("  -> _serve_news")
    elif parsed.path.startswith("/api/search"):
        print("  -> _serve_search")
    elif parsed.path.startswith("/api/detail"):
        print("  -> _serve_detail")
    elif parsed.path.startswith("/api/health"):
        print("  -> _serve_health")
    elif parsed.path.startswith("/api/stats"):
        print("  -> _serve_stats")
    elif parsed.path.startswith("/api/sentiment"):
        print("  -> _serve_sentiment_api")
    elif parsed.path.startswith("/api/"):
        print("  -> _serve_news (通用)")
    elif parsed.path.startswith("/dashboard"):
        print("  -> _serve_dashboard")
    elif parsed.path.startswith("/about"):
        print("  -> _serve_about")
    elif parsed.path.startswith("/sentiment"):
        print("  -> _serve_sentiment")
    else:
        print("  -> 404")
    print()
