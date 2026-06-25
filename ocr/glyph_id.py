#!/usr/bin/env python3
"""
glyph_id.py — Single-glyph identification GUI with JSON-RPC 2.0 control socket.

Usage:
  python3 glyph_id.py [--socket PATH]

Default socket: /tmp/glyph_id.sock
"""

import argparse
import json
import os
import socket
import sys
import threading

import wx
from PIL import Image

DEFAULT_SOCKET = "/tmp/glyph_id.sock"
DEFAULT_ZOOM = 4

_SHIFT_MAP = {
    "`": "~", "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
    "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|",
    ";": ":", "'": '"', ",": "<", ".": ">", "/": "?", " ": " ",
}


class ImageCanvas(wx.Panel):
    SCROLL_RANGE = 2000

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.SetBackgroundColour(wx.Colour(150, 150, 150))
        self._bmp = None
        self._ox = 0
        self._oy = 0
        self._drag_start = None
        self._drag_origin = None
        self._placeholder = "Waiting for glyph…"

        self._hbar = wx.ScrollBar(parent, style=wx.SB_HORIZONTAL)
        self._vbar = wx.ScrollBar(parent, style=wx.SB_VERTICAL)
        self._sync_bars()

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh())
        self.Bind(wx.EVT_LEFT_DOWN, self._on_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_up)
        self.Bind(wx.EVT_MOTION, self._on_move)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self._hbar.Bind(wx.EVT_SCROLL, self._on_hscroll)
        self._vbar.Bind(wx.EVT_SCROLL, self._on_vscroll)

    def set_bitmap(self, bmp):
        self._bmp = bmp
        self._sync_bars()
        self.Refresh()

    def clear_bitmap(self):
        self._bmp = None
        self._sync_bars()
        self.Refresh()

    def _sync_bars(self):
        r = self.SCROLL_RANGE
        mid = r + self._ox
        self._hbar.SetScrollbar(max(0, min(2 * r, mid)), 1, 2 * r + 1, 20)
        mid = r - self._oy
        self._vbar.SetScrollbar(max(0, min(2 * r, mid)), 1, 2 * r + 1, 20)

    def _on_hscroll(self, evt):
        self._ox = evt.GetPosition() - self.SCROLL_RANGE
        self.Refresh()

    def _on_vscroll(self, evt):
        self._oy = -(evt.GetPosition() - self.SCROLL_RANGE)
        self.Refresh()

    def _on_paint(self, _evt):
        dc = wx.BufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(150, 150, 150)))
        dc.Clear()
        cw, ch = self.GetClientSize()
        if self._bmp:
            x = cw // 2 + self._ox - self._bmp.GetWidth() // 2
            y = ch // 2 + self._oy - self._bmp.GetHeight() // 2
            dc.DrawBitmap(self._bmp, x, y)
        else:
            dc.SetTextForeground(wx.Colour(80, 80, 80))
            font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            dc.SetFont(font)
            tw, th = dc.GetTextExtent(self._placeholder)
            dc.DrawText(self._placeholder, max(0, (cw - tw) // 2), max(0, (ch - th) // 2))

    def _on_down(self, evt):
        self._drag_start = evt.GetPosition()
        self._drag_origin = (self._ox, self._oy)
        self.CaptureMouse()
        self.SetFocus()

    def _on_up(self, _evt):
        self._drag_start = None
        if self.HasCapture():
            self.ReleaseMouse()

    def _on_move(self, evt):
        if self._drag_start is not None and evt.Dragging() and evt.LeftIsDown():
            pos = evt.GetPosition()
            self._ox = self._drag_origin[0] + pos.x - self._drag_start.x
            self._oy = self._drag_origin[1] + pos.y - self._drag_start.y
            self._sync_bars()
            self.Refresh()

    def _on_wheel(self, evt):
        evt.ResumePropagation(2)
        evt.Skip()

    def get_offset(self):
        return self._ox, self._oy


class ImagePanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self._pil = None
        self.zoom = float(DEFAULT_ZOOM)

        outer = wx.BoxSizer(wx.VERTICAL)
        self.canvas = ImageCanvas(self)
        self.canvas.SetMinSize((420, 360))

        grid = wx.GridBagSizer(0, 0)
        grid.Add(self.canvas, (0, 0), flag=wx.EXPAND)
        grid.Add(self.canvas._vbar, (0, 1), flag=wx.EXPAND)
        grid.Add(self.canvas._hbar, (1, 0), flag=wx.EXPAND)
        grid.AddGrowableRow(0)
        grid.AddGrowableCol(0)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 4)

        zrow = wx.BoxSizer(wx.HORIZONTAL)
        zrow.Add(wx.StaticText(self, label="Zoom:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self.slider = wx.Slider(self, minValue=1, maxValue=20, value=DEFAULT_ZOOM,
                                style=wx.SL_HORIZONTAL)
        zrow.Add(self.slider, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        self.zoom_lbl = wx.StaticText(self, label=f"{DEFAULT_ZOOM}×", size=(42, -1))
        zrow.Add(self.zoom_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(zrow, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 2)

        self.info = wx.StaticText(self, label="—", style=wx.ST_ELLIPSIZE_END)
        self.info.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.info, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.SetSizer(outer)

        self.slider.Bind(wx.EVT_SLIDER, self._on_slider)
        self.canvas.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)

    def load(self, path):
        self._pil = Image.open(path).convert("RGB")
        self._rebuild()

    def clear(self):
        self._pil = None
        self.canvas.clear_bitmap()
        self.info.SetLabel("—")

    def _rebuild(self):
        if self._pil is None:
            return
        w = max(1, int(self._pil.width * self.zoom))
        h = max(1, int(self._pil.height * self.zoom))
        scaled = self._pil.resize((w, h), Image.NEAREST)
        bmp = wx.Bitmap.FromBuffer(w, h, scaled.tobytes())
        self.canvas.set_bitmap(bmp)

    def _on_slider(self, _evt):
        self.zoom = float(self.slider.GetValue())
        self.zoom_lbl.SetLabel(f"{self.zoom:.0f}×")
        self._rebuild()

    def _on_wheel(self, evt):
        self.zoom = min(20, self.zoom * 1.15) if evt.GetWheelRotation() > 0 else max(1, self.zoom / 1.15)
        self.slider.SetValue(int(round(self.zoom)))
        self.zoom_lbl.SetLabel(f"{self.zoom:.1f}×")
        self._rebuild()


class GlyphFrame(wx.Frame):
    def __init__(self, socket_path):
        super().__init__(None, title="Glyph ID", size=(600, 560))
        self.socket_path = socket_path
        self._lock = threading.Lock()
        self._show_mutex = threading.Lock()
        self._pending = None
        self._result = None
        self._result_event = threading.Event()
        self._waiting_for_key = False
        self._shift_on = False
        self._shift_key_down = False
        self._closing = False
        self._build()
        self._start_socket()
        self._poll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll, self._poll_timer)
        self._poll_timer.Start(50)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build(self):
        p = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        self.image_panel = ImagePanel(p)
        outer.Add(self.image_panel, 1, wx.EXPAND | wx.ALL, 4)

        bot = wx.BoxSizer(wx.HORIZONTAL)
        self.shift_btn = wx.Button(p, label="SHIFT OFF", size=(120, 32))
        self.shift_btn.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self._shift_default_bg = self.shift_btn.GetBackgroundColour()
        self._shift_default_fg = self.shift_btn.GetForegroundColour()
        self.shift_btn.Bind(wx.EVT_BUTTON, lambda e: self._toggle_shift())
        bot.Add(self.shift_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        hint = wx.StaticText(p, label="Key = identify  |  Backspace/Delete = done")
        hint.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        bot.Add(hint, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        outer.Add(bot, 0, wx.EXPAND)
        p.SetSizer(outer)
        self.status_bar = self.CreateStatusBar(1)
        self.status_bar.SetStatusText("Waiting for glyph…")

    def _toggle_shift(self):
        self._shift_on = not self._shift_on
        if self._shift_on:
            self.shift_btn.SetLabel("SHIFT ON")
            self.shift_btn.SetBackgroundColour(wx.Colour(255, 235, 70))
            self.shift_btn.SetForegroundColour(wx.Colour(0, 0, 0))
        else:
            self.shift_btn.SetLabel("SHIFT OFF")
            self.shift_btn.SetBackgroundColour(self._shift_default_bg)
            self.shift_btn.SetForegroundColour(self._shift_default_fg)
        self.shift_btn.Refresh()
        self.SetFocus()

    def _on_key(self, evt):
        code = evt.GetKeyCode()

        if code == wx.WXK_SHIFT:
            if not self._shift_key_down:
                self._shift_key_down = True
                self._toggle_shift()
            evt.Skip()
            return

        if wx.WXK_F1 <= code <= wx.WXK_F12:
            self._toggle_shift()
            return

        if code in (wx.WXK_BACK, wx.WXK_DELETE):
            # Always handle done, even if not waiting
            self._dispatch_result({"done": True})
            wx.CallAfter(self.Close)
            return

        if not self._waiting_for_key:
            evt.Skip()
            return

        uni = evt.GetUnicodeKey()
        if uni is not None and uni != wx.WXK_NONE and 32 <= uni < 127:
            raw = chr(uni)
            if raw.isalpha():
                ch = raw.upper() if self._shift_on else raw.lower()
            elif self._shift_on:
                ch = _SHIFT_MAP.get(raw, raw)
            else:
                ch = raw
            self._dispatch_result({"char": ch, "shifted": self._shift_on})
            if self._shift_on:
                self._shift_on = False
                self.shift_btn.SetLabel("SHIFT OFF")
                self.shift_btn.SetBackgroundColour(self._shift_default_bg)
                self.shift_btn.SetForegroundColour(self._shift_default_fg)
                self.shift_btn.Refresh()
            self._waiting_for_key = False
            self.image_panel.clear()
            self.status_bar.SetStatusText("Waiting for glyph…")
        else:
            evt.Skip()

    def _on_key_up(self, evt):
        if evt.GetKeyCode() == wx.WXK_SHIFT:
            self._shift_key_down = False
        evt.Skip()

    def _dispatch_result(self, result):
        with self._lock:
            self._result = result
        self._result_event.set()

    def _poll(self, _evt):
        with self._lock:
            req = self._pending
            self._pending = None
        if req is None:
            return
        try:
            self.image_panel.load(req["glyph_path"])
        except Exception as e:
            self._dispatch_result({"error": str(e)})
            return
        label = req.get("label", "")
        hash_ = req.get("hash", "")
        status = req["glyph_path"]
        if label: status += f"  {label}"
        if hash_: status += f"  [{hash_}]"
        self.status_bar.SetStatusText(status)
        self._waiting_for_key = True
        self.Raise()
        self.SetFocus()

    def _start_socket(self):
        threading.Thread(target=self._socket_loop, daemon=True).start()

    def _socket_loop(self):
        path = os.path.expanduser(self.socket_path)
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(5)
        while True:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except Exception:
                break

    def _handle(self, conn):
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    resp = self._dispatch(line)
                    conn.sendall(json.dumps(resp).encode() + b"\n")
        except Exception:
            pass
        finally:
            try: conn.close()
            except: pass

    def _dispatch(self, raw):
        try:
            req = json.loads(raw)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})
        try:
            if method == "ping":
                result = "pong"
            elif method == "show":
                result = self._rpc_show(params)
            elif method == "quit":
                wx.CallAfter(self.Close)
                result = "bye"
            else:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {method}"}}
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}}

    def _rpc_show(self, params):
        with self._show_mutex:
            if isinstance(params, list):
                p = {"glyph_path": params[0] if params else ""}
            else:
                p = {"glyph_path": params.get("glyph_path", ""), "label": params.get("label", ""), "hash": params.get("hash", "")}
            if not p.get("glyph_path"):
                raise ValueError("show() requires glyph_path")
            self._result_event.clear()
            with self._lock:
                self._result = None
                self._pending = p
            self._result_event.wait()
            with self._lock:
                result = self._result
                self._result = None
            return result

    def _on_close(self, _evt):
        if self._closing:
            return
        self._closing = True
        try: self._poll_timer.Stop()
        except: pass
        with self._lock:
            if self._result is None:
                self._result = {"done": True}
        self._result_event.set()
        path = os.path.expanduser(self.socket_path)
        try:
            if os.path.exists(path): os.unlink(path)
        except: pass
        self.Destroy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    args = ap.parse_args()
    app = wx.App(False)
    frame = GlyphFrame(args.socket)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
