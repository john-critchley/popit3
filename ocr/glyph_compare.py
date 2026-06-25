#!/usr/bin/env python3
"""
glyph_compare.py — Side-by-side glyph comparison GUI with JSON-RPC 2.0 socket.

Usage:
  python3 glyph_compare.py [--socket PATH]

Default socket: /tmp/glyph_compare.sock

JSON-RPC 2.0 methods (line-delimited, no auth):

  ping()
    → "pong"

  show_pair(glyph_path, ref_path[, label, hash])
    Show two images. Blocks until user presses a key.
    Returns:
      { "key": "<char>",
        "glyph_zoom": <float>,  "glyph_offset_x": <int>, "glyph_offset_y": <int>,
        "ref_zoom":   <float>,  "ref_offset_x":   <int>, "ref_offset_y":   <int> }
    Press Escape to skip (returns key = "").

  quit()
    → "bye"  (then exits)

The zoom ratio ref_zoom/glyph_zoom encodes the size relationship between the
two images as the user aligned them visually.  Only the ratio matters — absolute
zoom just controls screen size.

Example via socat:
  echo '{"jsonrpc":"2.0","method":"ping","id":1}' | socat - UNIX-CONNECT:/tmp/glyph_compare.sock
"""

import argparse
import json
import os
import socket
import sys
import threading

import numpy as np
import wx
from PIL import Image

DEFAULT_SOCKET = '/tmp/glyph_compare.sock'
DEFAULT_ZOOM = 12

# Fixed scale factor for ref images relative to glyphs.
# Computed once on first pair from image dimensions; stored here.
_REF_ZOOM_FACTOR: float | None = None  # ref_zoom = DEFAULT_ZOOM * _REF_ZOOM_FACTOR


def _ink_centroid(pil_img, zoom):
    """Return (ox, oy) pan offsets so the ink centroid is at canvas centre.
    Works on any single-channel or RGB PIL image; ink = dark pixels (<128).
    zoom is the display zoom for this image.
    Returns (0, 0) if no ink found.
    """
    arr = np.array(pil_img.convert('L'))
    ink = arr < 128          # True where ink
    rows = np.any(ink, axis=1)
    cols = np.any(ink, axis=0)
    if not rows.any():
        return 0, 0
    ys, xs = np.where(ink)
    cy = ys.mean()           # centroid in original image pixels
    cx = xs.mean()
    h, w = arr.shape
    # Offset to move centroid to canvas centre:
    # canvas draws image at (cw//2 + ox - bmp_w//2, ...) so
    # ink pixel cx*zoom is at cw//2 + ox - bmp_w//2 + cx*zoom
    # We want that == cw//2, so ox = bmp_w//2 - cx*zoom = (w//2 - cx)*zoom
    ox = int(round((w / 2 - cx) * zoom))
    oy = int(round((h / 2 - cy) * zoom))
    return ox, oy


# ── Image panel ──────────────────────────────────────────────────────────────

class ImageCanvas(wx.Panel):
    """
    Free-pan canvas: image is drawn at (canvas_centre + ox, canvas_centre + oy).
    ox/oy are unconstrained — image can be dragged fully off any edge.
    Scrollbars provide fine-grained control on top of drag.
    """

    SCROLL_RANGE = 2000   # ± pixels each scrollbar covers

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.SetBackgroundColour(wx.Colour(18, 18, 36))
        self._bmp = None
        self._ox = 0   # pan offset x (pixels, unconstrained)
        self._oy = 0   # pan offset y
        self._drag_start = None
        self._drag_origin = None

        # Explicit scrollbars — wired to _ox/_oy, range ±SCROLL_RANGE
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
        self._ox = 0
        self._oy = 0
        self._sync_bars()
        self.Refresh()

    def _sync_bars(self):
        r = self.SCROLL_RANGE
        mid = r + self._ox
        self._hbar.SetScrollbar(max(0, min(2*r, mid)), 1, 2*r+1, 20)
        mid = r - self._oy
        self._vbar.SetScrollbar(max(0, min(2*r, mid)), 1, 2*r+1, 20)

    def _on_hscroll(self, evt):
        self._ox = evt.GetPosition() - self.SCROLL_RANGE
        self.Refresh()
        self._update_info()

    def _on_vscroll(self, evt):
        self._oy = -(evt.GetPosition() - self.SCROLL_RANGE)
        self.Refresh()
        self._update_info()

    def _update_info(self):
        # Signal parent to refresh its info label
        evt = wx.CommandEvent(wx.EVT_TEXT.typeId, self.GetId())
        wx.PostEvent(self.GetParent(), evt)

    def _on_paint(self, _evt):
        dc = wx.BufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(18, 18, 36)))
        dc.Clear()
        if self._bmp:
            cw, ch = self.GetClientSize()
            x = cw // 2 + self._ox - self._bmp.GetWidth() // 2
            y = ch // 2 + self._oy - self._bmp.GetHeight() // 2
            dc.DrawBitmap(self._bmp, x, y)

    def _on_down(self, evt):
        self._drag_start = evt.GetPosition()
        self._drag_origin = (self._ox, self._oy)
        self.CaptureMouse()

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
            self._update_info()

    def _on_wheel(self, evt):
        evt.ResumePropagation(2)
        evt.Skip()

    def get_offset(self):
        return self._ox, self._oy


class ImagePanel(wx.Panel):
    """Image panel: title + free-pan canvas with scrollbars + zoom slider + info."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.title = title
        self._pil = None
        self.zoom = float(DEFAULT_ZOOM)

        outer = wx.BoxSizer(wx.VERTICAL)

        # Title
        lbl = wx.StaticText(self, label=title)
        lbl.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        outer.Add(lbl, 0, wx.ALL, 4)

        # Canvas + scrollbars in a grid
        self.canvas = ImageCanvas(self)
        self.canvas.SetMinSize((280, 340))
        grid = wx.GridBagSizer(0, 0)
        grid.Add(self.canvas,           (0, 0), flag=wx.EXPAND)
        grid.Add(self.canvas._vbar,     (0, 1), flag=wx.EXPAND)
        grid.Add(self.canvas._hbar,     (1, 0), flag=wx.EXPAND)
        grid.AddGrowableRow(0)
        grid.AddGrowableCol(0)
        outer.Add(grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)

        # Zoom (resize) slider
        zrow = wx.BoxSizer(wx.HORIZONTAL)
        zrow.Add(wx.StaticText(self, label='Resize:'), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self.slider = wx.Slider(self, minValue=1, maxValue=60, value=DEFAULT_ZOOM,
                                style=wx.SL_HORIZONTAL)
        zrow.Add(self.slider, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        self.zoom_lbl = wx.StaticText(self, label=f'{DEFAULT_ZOOM:.0f}×', size=(42, -1))
        zrow.Add(self.zoom_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(zrow, 0, wx.EXPAND | wx.TOP, 2)

        # Info
        self.info = wx.StaticText(self, label='—', style=wx.ST_ELLIPSIZE_END)
        self.info.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        outer.Add(self.info, 0, wx.EXPAND | wx.ALL, 2)

        self.SetSizer(outer)

        self.slider.Bind(wx.EVT_SLIDER, self._on_slider)
        self.canvas.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_TEXT, lambda e: self._update_info())  # canvas pan signal

    def load(self, path):
        self._pil = Image.open(path).convert('RGB')
        self.zoom = float(DEFAULT_ZOOM)
        self.slider.SetValue(DEFAULT_ZOOM)
        self.zoom_lbl.SetLabel(f'{DEFAULT_ZOOM}×')
        self._rebuild()
        self._update_info()

    def set_zoom(self, z):
        self.zoom = float(max(1, min(60, z)))
        self.slider.SetValue(int(round(self.zoom)))
        self.zoom_lbl.SetLabel(f'{self.zoom:.1f}×')
        self._rebuild()
        self._update_info()

    def _rebuild(self):
        if self._pil is None:
            return
        w = max(1, int(self._pil.width * self.zoom))
        h = max(1, int(self._pil.height * self.zoom))
        scaled = self._pil.resize((w, h), Image.NEAREST)
        data = scaled.tobytes()
        bmp = wx.Bitmap.FromBuffer(w, h, data)
        self.canvas.set_bitmap(bmp)

    def _on_slider(self, _evt):
        self.zoom = float(self.slider.GetValue())
        self.zoom_lbl.SetLabel(f'{self.zoom:.0f}×')
        self._rebuild()
        self._update_info()

    def _on_wheel(self, evt):
        if evt.GetWheelRotation() > 0:
            self.zoom = min(60, self.zoom * 1.15)
        else:
            self.zoom = max(1, self.zoom / 1.15)
        self.slider.SetValue(int(round(self.zoom)))
        self.zoom_lbl.SetLabel(f'{self.zoom:.1f}×')
        self._rebuild()
        self._update_info()

    def _update_info(self):
        if self._pil is None:
            return
        ox, oy = self.canvas.get_offset()
        self.info.SetLabel(
            f'{self._pil.width}×{self._pil.height}px  '
            f'zoom={self.zoom:.1f}×  offset=({ox},{oy})'
        )

    def get_state(self):
        ox, oy = self.canvas.get_offset()
        return dict(zoom=round(self.zoom, 3), offset_x=ox, offset_y=oy)


# ── Main frame ────────────────────────────────────────────────────────────────

class GlyphFrame(wx.Frame):
    def __init__(self, socket_path):
        super().__init__(None, title='Glyph Compare', size=(760, 580))
        self.socket_path = socket_path

        # Inter-thread state
        self._lock = threading.Lock()
        self._pending = None        # request dict waiting to be shown
        self._result = None         # key-press result
        self._result_event = threading.Event()
        self._waiting_for_key = False
        self._shift_on = True       # Shift toggle: True=uppercase, False=lowercase

        self._build()
        self._start_socket()
        self._poll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._poll, self._poll_timer)
        self._poll_timer.Start(50)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build(self):
        self.SetBackgroundColour(wx.Colour(12, 12, 24))

        p = wx.Panel(self)
        p.SetBackgroundColour(wx.Colour(12, 12, 24))
        outer = wx.BoxSizer(wx.VERTICAL)

        # Status bar at top
        self.status = wx.StaticText(p, label='Waiting for pair…')
        self.status.SetFont(wx.Font(11, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.status.SetForegroundColour(wx.Colour(100, 220, 100))
        outer.Add(self.status, 0, wx.ALL, 8)

        # Two panels side by side
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.glyph_panel = ImagePanel(p, 'Glyph  (scan)')
        self.ref_panel = ImagePanel(p, 'Reference  (r2.png)')
        hbox.Add(self.glyph_panel, 1, wx.EXPAND | wx.ALL, 4)
        hbox.Add(wx.StaticLine(p, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
        hbox.Add(self.ref_panel, 1, wx.EXPAND | wx.ALL, 4)
        outer.Add(hbox, 1, wx.EXPAND)

        # Shift toggle + hint row
        bot = wx.BoxSizer(wx.HORIZONTAL)
        self.shift_btn = wx.Button(p, label='⇧ SHIFT: ON', size=(130, -1))
        self.shift_btn.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.shift_btn.SetBackgroundColour(wx.Colour(0, 180, 80))
        self.shift_btn.SetForegroundColour(wx.Colour(255, 255, 255))
        self.shift_btn.Bind(wx.EVT_BUTTON, self._on_shift_toggle)
        bot.Add(self.shift_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)

        self.hint = wx.StaticText(p, label='Press character key  (Esc = skip)')
        self.hint.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.hint.SetForegroundColour(wx.Colour(120, 120, 160))
        bot.Add(self.hint, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        outer.Add(bot, 0, wx.EXPAND)

        p.SetSizer(outer)

    # ── Shift toggle ─────────────────────────────────────────────────────────

    def _on_shift_toggle(self, _evt):
        self._shift_on = not self._shift_on
        if self._shift_on:
            self.shift_btn.SetLabel('⇧ SHIFT: ON')
            self.shift_btn.SetBackgroundColour(wx.Colour(0, 180, 80))
        else:
            self.shift_btn.SetLabel('⇧ SHIFT: OFF')
            self.shift_btn.SetBackgroundColour(wx.Colour(100, 100, 120))
        self.shift_btn.Refresh()

    # ── Key handler ──────────────────────────────────────────────────────────

    def _on_key(self, evt):
        if not self._waiting_for_key:
            # Allow shift_btn click through
            evt.Skip()
            return
        code = evt.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self._send_result('')
            return
        uni = evt.GetUnicodeKey()
        if uni and uni != wx.WXK_NONE and 32 <= uni < 127:
            ch = chr(uni)
            if ch.isalpha():
                ch = ch.upper() if self._shift_on else ch.lower()
            self._send_result(ch)
        else:
            evt.Skip()

    def _send_result(self, key):
        self._waiting_for_key = False
        result = {
            'key': key,
            'shift': self._shift_on,
            'glyph_zoom': self.glyph_panel.get_state()['zoom'],
            'glyph_offset_x': self.glyph_panel.get_state()['offset_x'],
            'glyph_offset_y': self.glyph_panel.get_state()['offset_y'],
            'ref_zoom': self.ref_panel.get_state()['zoom'],
            'ref_offset_x': self.ref_panel.get_state()['offset_x'],
            'ref_offset_y': self.ref_panel.get_state()['offset_y'],
        }
        with self._lock:
            self._result = result
        self._result_event.set()
        label = f'Key: {key!r}' if key else '(skipped)'
        self.status.SetLabel(f'{label}  — waiting for next pair')
        self.hint.SetLabel('—')

    # ── Poll for pending show_pair requests ──────────────────────────────────

    def _poll(self, _evt):
        with self._lock:
            req = self._pending
            self._pending = None
        if req is None:
            return
        glyph_path = req.get('glyph_path', '')
        ref_path = req.get('ref_path', '')
        label = req.get('label', os.path.basename(glyph_path))
        hash_ = req.get('hash', '')

        try:
            self.glyph_panel.load(glyph_path)
        except Exception as e:
            self.status.SetLabel(f'Error loading glyph: {e}')
            with self._lock:
                self._result = {'error': str(e)}
            self._result_event.set()
            return

        try:
            self.ref_panel.load(ref_path)
        except Exception as e:
            self.status.SetLabel(f'Error loading ref: {e}')
            with self._lock:
                self._result = {'error': str(e)}
            self._result_event.set()
            return

        # Compute fixed scale factor once from image dimensions
        global _REF_ZOOM_FACTOR
        glyph_h = self.glyph_panel._pil.height
        ref_h = self.ref_panel._pil.height
        if _REF_ZOOM_FACTOR is None and ref_h > 0:
            _REF_ZOOM_FACTOR = glyph_h / ref_h
        ref_zoom = DEFAULT_ZOOM * (_REF_ZOOM_FACTOR if _REF_ZOOM_FACTOR else 1.0)

        # Set ref zoom then apply centroid-based pan offsets to both panels
        self.ref_panel.set_zoom(ref_zoom)
        gox, goy = _ink_centroid(self.glyph_panel._pil, DEFAULT_ZOOM)
        rox, roy = _ink_centroid(self.ref_panel._pil, ref_zoom)
        self.glyph_panel.canvas._ox = gox
        self.glyph_panel.canvas._oy = goy
        self.glyph_panel.canvas._sync_bars()
        self.glyph_panel.canvas.Refresh()
        self.ref_panel.canvas._ox = rox
        self.ref_panel.canvas._oy = roy
        self.ref_panel.canvas._sync_bars()
        self.ref_panel.canvas.Refresh()

        info = f'Pair: {label}'
        if hash_:
            info += f'  [{hash_[:8]}]'
        self.status.SetLabel(info)
        self.hint.SetLabel('Resize / scroll to align, then press the character key  (Esc = skip)')
        self._waiting_for_key = True
        self.Raise()
        self.SetFocus()

    # ── Socket server ────────────────────────────────────────────────────────

    def _start_socket(self):
        t = threading.Thread(target=self._socket_loop, daemon=True)
        t.start()

    def _socket_loop(self):
        path = self.socket_path
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buf = b''
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    resp = self._dispatch(line)
                    conn.sendall(json.dumps(resp).encode() + b'\n')
        except Exception:
            pass
        finally:
            conn.close()

    def _dispatch(self, raw):
        try:
            req = json.loads(raw)
        except Exception as e:
            return {'jsonrpc': '2.0', 'id': None,
                    'error': {'code': -32700, 'message': str(e)}}
        rid = req.get('id')
        method = req.get('method', '')
        params = req.get('params') or {}
        try:
            if method == 'ping':
                result = 'pong'
            elif method == 'show_pair':
                result = self._rpc_show_pair(params)
            elif method == 'quit':
                wx.CallAfter(self.Close)
                result = 'bye'
            else:
                return {'jsonrpc': '2.0', 'id': rid,
                        'error': {'code': -32601, 'message': f'Unknown: {method}'}}
            return {'jsonrpc': '2.0', 'id': rid, 'result': result}
        except Exception as e:
            return {'jsonrpc': '2.0', 'id': rid,
                    'error': {'code': -32000, 'message': str(e)}}

    def _rpc_show_pair(self, params):
        """Queue the pair, wait for key press, return result."""
        self._result_event.clear()
        with self._lock:
            self._pending = params
        self._result_event.wait()   # blocks until _send_result() fires
        with self._lock:
            result = self._result
            self._result = None
        return result

    def _on_close(self, _evt):
        self._poll_timer.Stop()
        path = self.socket_path
        self.Destroy()
        if os.path.exists(path):
            os.unlink(path)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--socket', default=DEFAULT_SOCKET,
                    help=f'Unix socket path (default: {DEFAULT_SOCKET})')
    args = ap.parse_args()

    app = wx.App(False)
    frame = GlyphFrame(args.socket)
    frame.Show()
    app.MainLoop()


if __name__ == '__main__':
    main()
