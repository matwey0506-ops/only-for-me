import os
import re
import requests
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from ytmusicapi import YTMusic

app = Flask(__name__)
CORS(app)
yt = YTMusic()
BASE = os.path.dirname(os.path.abspath(__file__))


def cover(item, fb=''):
    th = (item or {}).get('thumbnails') or (item or {}).get('thumbnail') or []
    return th[-1]['url'] if th else fb


def artist_name(item):
    a = item.get('artists')
    if a and isinstance(a, list):
        names = [x.get('name') for x in a if isinstance(x, dict) and x.get('name')]
        if names:
            return ', '.join(names)
    return item.get('artist') or 'Неизвестен'


def artist_list(item):
    out = []
    a = item.get('artists')
    if a and isinstance(a, list):
        for x in a:
            if isinstance(x, dict) and x.get('name'):
                out.append({'name': x['name'], 'id': x.get('id')})
    return out


def song(item, fb='', fa=None):
    arts = artist_list(item) or (fa or [])
    return {
        'id': item['videoId'],
        'title': item.get('title', 'Без названия'),
        'artist': ', '.join(x['name'] for x in arts) if arts else artist_name(item),
        'artists': arts,
        'cover': cover(item, fb),
    }


def album_card(x, artist=''):
    return {
        'id': x['browseId'],
        'title': x.get('title', ''),
        'artist': artist or artist_name(x),
        'cover': cover(x),
        'year': x.get('year', ''),
    }


@app.route('/')
def status():
    return jsonify({'status': 'OK'})


@app.route('/app')
def index():  # необязательно: отдаёт index.html, если он лежит рядом с server.py
    return send_from_directory(BASE, 'index.html')


@app.route('/health')
def health():
    return jsonify(ok=True)


@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    t = request.args.get('type', 'songs')
    if t not in ('songs', 'albums', 'artists'):
        t = 'songs'
    if not q:
        return jsonify([])
    try:
        res = yt.search(q, filter=t, limit=15 if t == 'songs' else 20)
    except Exception as e:
        return jsonify(error=str(e)), 502
    out = []
    for it in res:
        if t == 'songs':
            if it.get('videoId'):
                out.append(song(it))
        elif t == 'albums':
            if it.get('browseId'):
                out.append(album_card(it))
        else:
            if it.get('browseId'):
                out.append({'id': it['browseId'],
                            'title': it.get('artist') or it.get('title', ''),
                            'cover': cover(it)})
    return jsonify(out)


@app.route('/album')
def album():
    try:
        a = yt.get_album(request.args.get('id', ''))
    except Exception as e:
        return jsonify(error=str(e)), 502
    c = cover(a)
    return jsonify({
        'id': request.args.get('id', ''),
        'title': a.get('title', ''),
        'artist': artist_name(a),
        'year': a.get('year', ''),
        'cover': c,
        'tracks': [song(t, c, artist_list(a)) for t in a.get('tracks', []) if t.get('videoId')],
    })


@app.route('/artist')
def artist():
    try:
        a = yt.get_artist(request.args.get('id', ''))
    except Exception as e:
        return jsonify(error=str(e)), 502
    name = a.get('name', '')
    songs = (a.get('songs') or {}).get('results') or []
    albums = ((a.get('albums') or {}).get('results') or []) + ((a.get('singles') or {}).get('results') or [])
    return jsonify({
        'id': request.args.get('id', ''),
        'title': name,
        'cover': cover(a),
        'tracks': [song(s, '', [{'name': name, 'id': request.args.get('id', '')}]) for s in songs if s.get('videoId')],
        'albums': [album_card(x, name) for x in albums if x.get('browseId')],
    })


_TS = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')
_UA = {'User-Agent': 'TriXXDe/1.0 (music web player)'}


def parse_lrc(txt):
    out = []
    for ln in (txt or '').splitlines():
        ts = _TS.findall(ln)
        if not ts:
            continue
        text = _TS.sub('', ln).strip()
        for m, sec in ts:
            out.append({'t': round(int(m) * 60 + float(sec), 2), 'x': text})
    out.sort(key=lambda z: z['t'])
    return out


def yt_lyrics(video_id):
    """-> (строки с таймингами | None, обычный текст | None) из YouTube Music"""
    try:
        w = yt.get_watch_playlist(video_id)
        lid = w.get('lyrics')
        if not lid:
            return None, None
        try:
            l = yt.get_lyrics(lid, timestamps=True)
        except TypeError:  # старая версия ytmusicapi без таймингов
            l = yt.get_lyrics(lid)
        if not l:
            return None, None
        data = l.get('lyrics')
        if l.get('hasTimestamps') and isinstance(data, list):
            lines = []
            for x in data:
                g = (lambda k: x[k] if isinstance(x, dict) else getattr(x, k))
                lines.append({'t': round(g('start_time') / 1000, 2), 'x': g('text')})
            return lines, None
        return None, (data if isinstance(data, str) else None)
    except Exception:
        return None, None


def clean_title(t):
    return re.sub(r'\s*[\(\[].*?[\)\]]', '', t or '').strip() or t


def lrclib(title, artist, dur):
    """-> (строки с таймингами | None, обычный текст | None) из открытой базы LRCLIB"""
    try:
        d = None
        params = {'track_name': title, 'artist_name': artist}
        if dur:
            params['duration'] = int(dur)
        r = requests.get('https://lrclib.net/api/get', params=params, timeout=6, headers=_UA)
        if r.status_code == 200:
            d = r.json()
        if not d:
            r = requests.get('https://lrclib.net/api/search',
                             params={'track_name': clean_title(title), 'artist_name': artist}, timeout=6, headers=_UA)
            arr = r.json() if r.status_code == 200 else []
            if dur:
                near = [a for a in arr if abs((a.get('duration') or 0) - dur) <= 5]
                arr = near or arr
            d = next((a for a in arr if a.get('syncedLyrics')), arr[0] if arr else None)
        if not d:
            return None, None
        return (parse_lrc(d.get('syncedLyrics')) or None), d.get('plainLyrics')
    except Exception:
        return None, None


@app.route('/lyrics')
def lyrics():
    vid = request.args.get('id', '')
    title = request.args.get('title', '').strip()
    artist = request.args.get('artist', '').strip()
    try:
        dur = float(request.args.get('dur', '') or 0)
    except ValueError:
        dur = 0
    lines, plain = yt_lyrics(vid)
    if not lines and title:
        l2, p2 = lrclib(title, artist, dur)
        lines = l2 or lines
        plain = plain or p2
    if lines and not plain:
        plain = '\n'.join(x['x'] for x in lines)
    return jsonify(lines=lines or None, lyrics=plain)


@app.route('/track')
def track():
    try:
        d = yt.get_song(request.args.get('id', ''))['videoDetails']
        th = d['thumbnail']['thumbnails']
        return jsonify({'id': d['videoId'], 'title': d.get('title', ''),
                        'artist': d.get('author', ''), 'cover': th[-1]['url'],
                        'artists': [{'name': d.get('author', ''), 'id': d.get('channelId')}]})
    except Exception as e:
        return jsonify(error=str(e)), 502


def _items(v):
    return (v.get('items') if isinstance(v, dict) else v) or []


@app.route('/charts')
def charts():
    try:
        c = yt.get_charts(request.args.get('country', 'ZZ'))
    except Exception as e:
        return jsonify(error=str(e)), 502
    items = _items(c.get('songs')) or _items(c.get('videos'))
    return jsonify([song(x) for x in items if x.get('videoId')][:30])


@app.route('/radio')
def radio():
    try:
        w = yt.get_watch_playlist(videoId=request.args.get('id', ''), radio=True, limit=25)
    except Exception as e:
        return jsonify(error=str(e)), 502
    return jsonify([song(x) for x in w.get('tracks', []) if x.get('videoId')][1:])


@app.route('/img')
def img():  # прокси обложек (только хосты YouTube), чтобы страница могла считать цвет
    u = request.args.get('u', '')
    h = urlparse(u).hostname or ''
    if not u.startswith('https://') or not h.endswith(('googleusercontent.com', 'ggpht.com', 'ytimg.com')):
        return ('', 400)
    try:
        r = requests.get(u, timeout=8)
    except Exception:
        return ('', 502)
    return Response(r.content, mimetype=r.headers.get('Content-Type', 'image/jpeg'),
                    headers={'Cache-Control': 'public, max-age=86400'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
