import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from ytmusicapi import YTMusic

app = Flask(__name__)
CORS(app)
yt = YTMusic()
BASE = os.path.dirname(os.path.abspath(__file__))


def cover(item, fb=''):
    th = (item or {}).get('thumbnails') or []
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


@app.route('/lyrics')
def lyrics():
    try:
        w = yt.get_watch_playlist(request.args.get('id', ''))
        lid = w.get('lyrics')
        if not lid:
            return jsonify(lyrics=None)
        l = yt.get_lyrics(lid)
        return jsonify(lyrics=(l.get('lyrics') if l else None))
    except Exception:
        return jsonify(lyrics=None)


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
