from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from ytmusicapi import YTMusic

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')
yt = YTMusic()

@app.route('/search')
def search():
    q = request.args.get('q', '')
    results = yt.search(q, filter='songs', limit=10)
    tracks = []
    for item in results:
        if not item.get('videoId'):
            continue
        tracks.append({
            'id': item['videoId'],
            'title': item.get('title', 'Без названия'),
            'artist': item['artists'][0]['name'] if item.get('artists') else 'Неизвестен',
            'cover': item['thumbnails'][-1]['url'] if item.get('thumbnails') else ''
        })
    return jsonify(tracks)

if __name__ == '__main__':
    app.run(port=5000)
