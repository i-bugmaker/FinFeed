#!/usr/bin/env python3
import threading
import time
import httpx

def run_server():
    from ui.web.server import start_web_server
    server = start_web_server(8888)
    print('Web server started on port 8888')
    server.serve_forever()

t = threading.Thread(target=run_server, daemon=True)
t.start()

time.sleep(3)

print('Sending request...')
try:
    r = httpx.get('http://localhost:8888/api/sentiment', timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Content: {r.text}')
except Exception as e:
    print(f'Error: {e}')

time.sleep(2)
print('Done')
