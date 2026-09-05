"""Hoyt Axton jukebox backend: playlist lookup + private-bucket audio proxy.

Audio lives in a PRIVATE GCS bucket (twomanspades-hoyt, us-central1). Nothing is
public; the App Engine service account reads objects and this route streams them
to the browser with HTTP Range support so <audio> can seek. Object layout:
    hoyt/<album_id>/<NN>.m4a      hoyt/<album_id>/cover.jpg (covers also ship in static/)
Only ids present in static/jukebox/playlist.json are served, so the route cannot
be used to read arbitrary objects.
"""
import json
import os
import re
from flask import Response, request, abort

BUCKET = os.environ.get('HOYT_BUCKET', 'twomanspades-hoyt')
_PLAYLIST = None
_client = None


def playlist():
    global _PLAYLIST
    if _PLAYLIST is None:
        path = os.path.join(os.path.dirname(__file__), '..', 'static', 'jukebox', 'playlist.json')
        _PLAYLIST = json.load(open(path))
    return _PLAYLIST


def _known(album_id, n):
    for a in playlist()['albums']:
        if a['id'] == album_id:
            return any(t['n'] == n for t in a['tracks'])
    return False


def _bucket():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(BUCKET)


def stream_track(album_id, n):
    """Proxy one m4a from the private bucket. Honors a single-range Range header."""
    if not re.fullmatch(r'[a-z0-9-]{4,80}', album_id) or not _known(album_id, n):
        abort(404)
    blob = _bucket().get_blob(f'hoyt/{album_id}/{n:02d}.m4a')
    if blob is None:
        abort(404)
    size = blob.size
    headers = {'Accept-Ranges': 'bytes', 'Content-Type': 'audio/mp4',
               'Cache-Control': 'private, max-age=86400'}
    rng = request.headers.get('Range')
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
    if m and rng:
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        end = int(m.group(2)) if (m.group(1) and m.group(2)) else size - 1
        end = min(end, size - 1)
        if start > end:
            return Response(status=416, headers={'Content-Range': f'bytes */{size}'})
        data = blob.download_as_bytes(start=start, end=end)
        headers.update({'Content-Range': f'bytes {start}-{end}/{size}', 'Content-Length': str(len(data))})
        return Response(data, status=206, headers=headers)
    data = blob.download_as_bytes()
    headers['Content-Length'] = str(len(data))
    return Response(data, status=200, headers=headers)
