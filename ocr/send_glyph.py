#!/usr/bin/env python3
"""Send one glyph to glyph_id GUI and print the result.
Usage: python3 send_glyph.py GLYPH_PATH [label] [hash]
"""
import sys, socket, json

SOCK = '/tmp/glyph_id.sock'

path = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else ''
hash_ = sys.argv[3] if len(sys.argv) > 3 else ''

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SOCK)
req = json.dumps({"jsonrpc":"2.0","method":"show","params":{
    "glyph_path": path, "label": label, "hash": hash_
}, "id": 1}) + '\n'
s.sendall(req.encode())
s.shutdown(socket.SHUT_WR)
buf = b''
while True:
    d = s.recv(4096)
    if not d: break
    buf += d
result = json.loads(buf.split(b'\n')[0])
print(json.dumps(result.get('result', result)))
s.close()
