# -*- coding: utf-8 -*-
import random
from datetime import datetime, timedelta
import calendar
from elasticsearch import Elasticsearch
from flask import Flask, request, render_template, Markup, url_for
import woothee
import redis


app = Flask(__name__)
QWERTY_START_YEAR = 2005
ALMOST_ONE_YEAR = 60 * 60 * 24 * 365 - 3600
KUZUHA_DT_FORMAT = '投稿日：<em>%s</em>/%02d/%02d(%s)%02d時%02d分%02d秒'
WEEKDAYS = '月火水木金土日'
USAMIN_URL = 'http://usamin.mine.nu/cgi/swlog?id=%d&b=qwerty'
CORRECT_MSGS = ('あたりヽ(´ー｀)ノ', 'すごーい(´Д`)',
                '(´ー｀)v', 'ヽ(´ー｀)ノ')
INCORRECT_MSGS = ('(^Д^)', 'はずれ(^Д^)', 'poox(^Д^)', "(*'ｰ')ﾊﾞｶﾐﾀｲ",
                  "('ｰ'*)ﾊｽﾞｶｼｰ", "('ｰ'*)ｸｽｸｽ", "('ｰ'*)ｻｲﾃｰ", "('-'*)ﾊﾞｶｼﾞｬﾅｲﾉ",
                  "('ｰ'*)ﾌﾟｯ", "(*'ｰ')poooox")
HIGHSCORE_FORMAT = '<tr><td>%s</td><td style="text-align: center;">%s</td><td>%s まんこ</td></tr>\n'
NUM_RANKING = 20
ELASTICSEARCH_SETTING = [{'host': '192.168.100.2', 'port': 9200}]
ELASTICSEARCH_IDX = 'qwerty'
ELASTICSEARCH_DT_FORMAT = '%Y-%m-%dT%H:%M:%S'
REDIS_SETTING = {'host': 'localhost', 'port': 6379, 'db': 0}
SHELVE_PATH = '/work/now_or_past/score.shelve'


def is_smartphone(ua):
    category = woothee.parse(ua)['category']
    return category.endswith('phone')


def determine_css(ua):
    css_file = 'sp.css' if is_smartphone(ua) else 'pc.css'
    return url_for('static', filename=css_file)


def compute_id():
    ua = request.headers.get('User-Agent')
    ip = request.remote_addr
    return hash(ua + ip)


def get_log_by_id(_id):
    es = Elasticsearch(ELASTICSEARCH_SETTING)
    log = es.get(ELASTICSEARCH_IDX, id=_id)
    dt_str = log['_source']['dt']
    dt = datetime.strptime(dt_str, ELASTICSEARCH_DT_FORMAT)
    return (dt, parse_log(log))


def parse_dt(dt):
    dt_str = KUZUHA_DT_FORMAT % (dt.year, dt.month, dt.day,
                                 WEEKDAYS[dt.weekday()],
                                 dt.hour, dt.minute, dt.second)
    return dt_str


def gen_usamin_link(_id):
    url = USAMIN_URL % _id
    return ' <a href="%s">◇</a>' % url


def is_correct(t_delta, _input):
    if t_delta.total_seconds() > ALMOST_ONE_YEAR:
        return _input == 'past'
    else:
        return _input == 'now'


def is_highscore(score):
    db = redis.StrictRedis(**REDIS_SETTING)
    highscores = db.zrangebyscore('score', 0, 0x01 << 64, withscores=True, score_cast_func=int)
    if len(highscores) < NUM_RANKING:
        return True
    unique_scores = set()
    for (name, highscore) in highscores:
        if score > int(highscore):
            return True
        unique_scores.add(highscore)
    return len(unique_scores) < NUM_RANKING


def check_answer(identifier, form, ua):
    highscore = False
    _id = int(form['_id']) ^ identifier
    (post_dt, post) = get_log_by_id(_id)
    t_delta = datetime.now() - post_dt
    db = redis.StrictRedis(**REDIS_SETTING)
    if is_correct(t_delta, form['res']):
        prev = db.get('prev:%s' % identifier) or ''
        if _id != prev:
            score = db.incr('win:%s' % identifier)
            answer = '[%d おまんこ] ' % score + random.choice(CORRECT_MSGS)
            sound = 'right'
            db.expire('win:%s' % identifier, 300)
            db.set('prev:%s' % identifier, _id)
            db.expire('prev:%s' % identifier, 300)
        else:
            answer = 'リロードしたので正解数をリセットします(ﾟД`)'
            sound = 'wrong'
            db.set('win:%s' % identifier, 0)
    else:
        answer = '[おちんぽ] ' + random.choice(INCORRECT_MSGS)
        sound = 'wrong'
        score = db.get('win:%s' % identifier) or 0
        score = int(score)
        if score and is_highscore(score):
            db.set('highscore:%s' % identifier, score)
            db.expire('highscore:%s' % identifier, 3000)
            highscore = score
        db.set('win:%s' % identifier, 0)
    post_dt = Markup(parse_dt(post_dt) + gen_usamin_link(_id))
    return render_template('index.html', post_dt=post_dt, css=determine_css(ua),
                           highscore=highscore, post=Markup(post), answer=Markup(answer),
                           sound=sound)


def entry_highscore(identifier, user_name):
    db = redis.StrictRedis(**REDIS_SETTING)
    score = db.get('highscore:%s' % identifier) or 0
    score = int(score)
    if not score:
        return False
    user_name += datetime.now().strftime('___(%Y/%m/%d___%H:%M:%S)')
    db.zadd('score', score, user_name)
    highscores = db.zrevrangebyscore('score', 0x01 << 64, 0, withscores=True, score_cast_func=int)
    unique_scores = set()
    for (name, highscore) in highscores:
        if score > highscore and highscore not in unique_scores and len(unique_scores) > NUM_RANKING - 1:
            db.zrem('score', name)
        else:
            unique_scores.add(highscore)
    db.bgsave()
    return True


def get_log():
    now = datetime.now()
    if random.randint(0, 1):
        year_range = now.year - QWERTY_START_YEAR
        year = now.year - random.randint(1, year_range)
        if not calendar.isleap(year) and now.month == 2 and now.day == 29:
            day = 28
        else:
            day = now.day
        dt = datetime(year, now.month, day, now.hour, now.minute, now.second)
    else:
        dt = now
    start = (dt - timedelta(minutes=60)).strftime(ELASTICSEARCH_DT_FORMAT)
    end = dt.strftime(ELASTICSEARCH_DT_FORMAT)
    es = Elasticsearch(ELASTICSEARCH_SETTING)
    query = {"query": {"range": {"dt": {"gt": start, "lt": end}}}, "size": 1000}
    result = es.search(index=ELASTICSEARCH_IDX, body=query)
    return random.choice(result['hits']['hits'])


def parse_log(log):
    body = ''
    for (i, idx) in enumerate(('q2', 'q1')):
        if idx in log['_source']:
            for line in log['_source'][idx].splitlines():
                body += '> ' * (2 - i) + line + '\n'
    if 'text' in log['_source']:
        body += '\n' + log['_source']['text']
    return '\n' + body.strip()


@app.route("/now_or_past/", methods=['POST', 'GET'])
def now_or_past():
    ua = request.headers.get('User-Agent')
    identifier = compute_id()
    if request.method == 'POST':
        if '_id' in request.form:
            return check_answer(identifier, request.form, ua)
        elif 'name' in request.form:
            entry_highscore(identifier, request.form['name'])
    log = get_log()
    post = parse_log(log)
    encrypted_id = int(log['_id']) ^ identifier
    return render_template('index.html', post=Markup(post),
                           _id=encrypted_id, css=determine_css(ua))


@app.route("/now_or_past/ranking", methods=['GET'])
def ranking():
    ua = request.headers.get('User-Agent')
    db = redis.StrictRedis(**REDIS_SETTING)
    highscores = ''
    unique_scores = set()
    for (name, score) in db.zrevrangebyscore('score', 0x01 << 64, 0, withscores=True,
                                             score_cast_func=int):
        unique_scores.add(score)
        rank = len(unique_scores)
        name = name.decode('utf8').replace('___', ' ')
        highscores += HIGHSCORE_FORMAT % (rank, name, score)
    return render_template('ranking.html', highscores=Markup(highscores), css=determine_css(ua))


@app.errorhandler(404)
def page_not_found(e):
    ua = request.headers.get('User-Agent')
    ip = request.remote_addr
    return render_template('404.html', ip=ip, ua=ua), 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
