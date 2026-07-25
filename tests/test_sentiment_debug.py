#!/usr/bin/env python3
import threading
import time
import httpx
import sys

def run_server():
    sys.stdout = open('server_output.txt', 'w')
    sys.stderr = sys.stdout
    from ui.web.server import start_web_server
    server = start_web_server(8888)
    print('Web server started on port 8888')
    server.serve_forever()

t = threading.Thread(target=run_server, daemon=True)
t.start()

time.sleep(3)

print('Sending request to /api/sentiment...')
try:
    r = httpx.get('http://localhost:8888/api/sentiment', timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Content: {r.text[:500]}')
except Exception as e:
    print(f'Error: {e}')

time.sleep(2)

print('Checking server output...')
with open('server_output.txt', 'r') as f:
    output = f.read()
    print(f'Server output: {output}')

print('Done')
