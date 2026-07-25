#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from config.sources import get_forum_sources
from config.settings import get_display_name
from storage.database import db_get_recent_news

class TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        print(f"Received request: {self.path}")
        
        if parsed.path.startswith("/api/sentiment"):
            self._serve_sentiment_api()
        else:
            self.send_error(404)
    
    def _serve_sentiment_api(self):
        print("DEBUG: _serve_sentiment_api called")
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit = int(qs.get("limit", ["2000"])[0])
            source = qs.get("source", ["all"])[0]
            if limit > 10000:
                limit = 10000

            forum_source_names = [get_display_name(s.name) for s in get_forum_sources()]
            print(f"DEBUG: forum_source_names={forum_source_names}")
            
            if source != "all":
                news = db_get_recent_news(limit=limit, source=source)
            else:
                news = []
                for src_name in forum_source_names:
                    src_news = db_get_recent_news(limit=limit // max(len(forum_source_names), 1) + 50, source=src_name)
                    news.extend(src_news)

            news.sort(key=lambda x: x.publish_ts, reverse=True)
            news = news[:limit]
            print(f"DEBUG: found {len(news)} news items")

            news_dicts = [n.to_dict() for n in news]
            result = {
                "news": news_dicts,
                "stats": {},
                "cycle": 0,
                "total": len(news),
                "new_count": 0,
                "status": "运行中",
                "sources": forum_source_names,
                "last_update": "",
                "server_ts": time.time(),
            }
            data = json.dumps(result, ensure_ascii=False).encode("utf-8")
            print(f"DEBUG: response length={len(data)}")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            print("DEBUG: response sent successfully")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode("utf-8"))
    
    def log_message(self, fmt, *args):
        pass

print("Starting test server on port 8889...")
server = HTTPServer(("localhost", 8889), TestHandler)
server.serve_forever()
