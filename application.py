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
CORRECT_MSGS = ('あたりヽ(´ー｀)ノ', 'すごーい(´Д`)',
                '(´ー｀)v', 'ヽ(´ー｀)ノ')
INCORRECT_MSGS = ('(^Д^)', 'はずれ(^Д^)', 'poox(^Д^)', "(*'ｰ')ﾊﾞｶﾐﾀｲ",
                  "('ｰ'*)ﾊｽﾞｶｼｰ", "('ｰ'*)ｸｽｸｽ", "('ｰ'*)ｻｲﾃｰ", "('-'*)ﾊﾞｶｼﾞｬﾅｲﾉ",
                  "('ｰ'*)ﾌﾟｯ", "(*'ｰ')poooox")
ELASTICSEARCH_IDX = 'qwerty'
ELASTICSEARCH_DT_FORMAT = '%Y-%m-%dT%H:%M:%S'
REDIS_SETTING = {'host': 'localhost', 'port': 6379, 'db': 0}


def is_smartphone():
    category = woothee.parse(request.headers.get('User-Agent'))['category']
    return category.endswith('phone')


def compute_id():
    ua = request.headers.get('User-Agent')
    ip = request.remote_addr
    return hash(ua + ip)


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
    es = Elasticsearch()
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


def get_log_by_id(_id):
    es = Elasticsearch()
    log = es.get(ELASTICSEARCH_IDX, id=_id)
    dt_str = log['_source']['dt']
    dt = datetime.strptime(dt_str, ELASTICSEARCH_DT_FORMAT)
    return (dt, parse_log(log))


def parse_dt(dt):
    dt_str = KUZUHA_DT_FORMAT % (dt.year, dt.month, dt.day,
                                 WEEKDAYS[dt.weekday()],
                                 dt.hour, dt.minute, dt.second)
    return dt_str


def is_correct(t_delta, _input):
    if t_delta.total_seconds() > ALMOST_ONE_YEAR:
        return _input == 'past'
    else:
        return _input == 'now'


@app.route("/now_or_past/", methods=['POST', 'GET'])
def now_or_past():
    css_file = 'sp.css' if is_smartphone() else 'pc.css'
    css = url_for('static', filename=css_file)
    identifier = compute_id()
    if request.method == 'POST' and '_id' in request.form:
        _id = int(request.form['_id']) ^ identifier
        (post_dt, post) = get_log_by_id(_id)
        t_delta = datetime.now() - post_dt
        db = redis.StrictRedis(**REDIS_SETTING)
        if is_correct(t_delta, request.form['res']):
            win = db.incr('win:%s' % identifier)
            answer = '[%d おまんこ] ' % win + random.choice(CORRECT_MSGS)
            sound = 'right'
            db.expire('win:%s' % identifier, 300)
        else:
            answer = '[おちんぽ] ' + random.choice(INCORRECT_MSGS)
            sound = 'wrong'
            db.set('win:%s' % identifier, 0)
        return render_template('index.html', post_dt=Markup(parse_dt(post_dt)), css=css,
                               post=Markup(post), answer=Markup(answer), sound=sound)
    else:
        log = get_log()
        post = parse_log(log)
        encrypted_id = int(log['_id']) ^ identifier
        return render_template('index.html', post=Markup(post),
                               _id=encrypted_id, css=css)


@app.errorhandler(404)
def page_not_found(e):
    ua = request.headers.get('User-Agent')
    ip = request.remote_addr
    return render_template('404.html', ip=ip, ua=ua), 404

if __name__ == "__main__":
    app.run(host='0.0.0.0')
