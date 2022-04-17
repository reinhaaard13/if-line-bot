import json
import os
from flask import Flask, request, abort
from linebot.models.actions import MessageAction, URIAction
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from constants import TZ_JAKARTA, HEADER_IMAGE_URL

from linebot.models.template import CarouselColumn, CarouselTemplate

from linebot import (
    LineBotApi, WebhookHandler
)

from linebot.exceptions import (
    InvalidSignatureError
)

from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, TemplateSendMessage, ButtonsTemplate
)

app = Flask(__name__)

sched = BackgroundScheduler(timezone="Asia/Jakarta")
sched.start()

jadwal = open('schedule.json', 'r')
jadwal = json.load(jadwal)

line_bot_api = LineBotApi(os.environ['CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['CHANNEL_SECRET'])

days_on = ['senin','selasa','rabu','kamis','jumat','monday','tuesday','wednesday','thursday','friday']

@app.route('/')
def home():
    return "Hello. I am alive!"

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    message = event.message.text.lower()

    if '!today' in message:
        reply_today(event)
    elif 'jdw?' in message:
        try:
            hari = message.split(' ')[1]
            reply_day(event, hari) if hari in days_on else reply_today(event)
        except IndexError:
            reply_today(event)
    elif '!notifygroup' in message:
        add_group(event)
    elif '!dbg' in message:
        notify_groups()
    elif '!pdt' in message:
        line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=datetime.now(TZ_JAKARTA).strftime("%c")))
    
def reply_today(event):
    today = datetime.now(TZ_JAKARTA).strftime("%A").lower()
    buttons_template_message = make_carousel_template_jadwal(today)

    line_bot_api.reply_message(
        event.reply_token,
        buttons_template_message)

def reply_day(event, hari):
    buttons_template_message = make_carousel_template_jadwal(hari)

    line_bot_api.reply_message(
        event.reply_token,
        buttons_template_message)

def notify_groups():
    today = datetime.now(TZ_JAKARTA).strftime("%A").lower()
    buttons_template_message = make_carousel_template_jadwal(today)

    with open ('groups.json', 'r') as f:
        groups = json.load(f)
        for group in groups['groups']:
            line_bot_api.push_message(group, buttons_template_message)

def make_carousel_template_jadwal(hari):
    date = datetime.now(TZ_JAKARTA).strftime("%A, %d %B %Y")

    try:
        columns = [
            CarouselColumn(
                thumbnail_image_url=HEADER_IMAGE_URL,
                title=x['matkul'],
                text=f"{x['start']} - {x['end']}",
                actions=[
                    URIAction(
                        label='Attendance',
                        uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{x['kode']}/attendance?openExternalBrowser=1"
                    ),
                    URIAction(
                        label='TLM',
                        uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{x['kode']}/teaching-learning-materials?openExternalBrowser=1"
                    ),
                    URIAction(
                        label='Assignments',
                        uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{x['kode']}/assignments?openExternalBrowser=1"
                    )
                ],
                imageSize='contain'
            )
            for x in jadwal[hari]
        ]
    except KeyError:
        columns = [
            CarouselColumn(
                thumbnail_image_url=HEADER_IMAGE_URL,
                title='No lecture today',
                text=f'{date}',
                actions=[
                    MessageAction(
                        label='Happy holiday!',
                        text='Happy holiday!'
                    )
                ]
            )
        ]

    carousel_template_message = TemplateSendMessage(
        alt_text='Jadwal hari ini',
        template=CarouselTemplate(
            columns=columns
        )
    )

    return carousel_template_message

def add_group(event):
    with open ('groups.json', 'r+') as f:
        groups = json.load(f)
        if event.source.group_id in groups['groups']:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'This group had been added to reminder list!'))
            return
        groups['groups'].append(event.source.group_id)
        f.seek(0)
        json.dump(groups, f)
        f.truncate()
    summary = line_bot_api.get_group_summary(event.source.group_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'Group {summary.group_name} has been added to reminder list!'))
        
sched.add_job(notify_groups, 'cron', hour=7, minute=0, day_of_week='mon-fri')

def register_jobs():
    # for every class in schedule.json
    for hari in jadwal:
        for kelas in jadwal[hari]:
            # add job to scheduler (class start)
            cron_time = convert_cron(hari, kelas['start'], True)
            if not cron_time:
                break
            day, hour, minute = map(passing, list(cron_time))
            sched.add_job(lambda i=kelas: class_reminder(i,'start'), 'cron', hour=hour, minute=minute, day_of_week=day)

            # add job to scheduler (class end)
            cron_time = convert_cron(hari, kelas['end'], False)
            day, hour, minute = map(passing, list(cron_time))
            
            sched.add_job(lambda i=kelas: class_reminder(i,'end'), 'cron', hour=hour, minute=minute, day_of_week=day)
            print(f"Job added {kelas['matkul']} ({kelas['start']} - {kelas['end']})")

def class_reminder(kelas, condition):
    text = 'Class will start in 15 minutes!' if condition == 'start' else 'Class is over!'
    alt_text = 'Class is starting!' if condition == 'start' else 'Class ended!'
    buttons_template_message = TemplateSendMessage(
        alt_text=alt_text,
        template=ButtonsTemplate(
            thumbnail_image_url=HEADER_IMAGE_URL,
            title=f"{kelas['matkul']}",
            text=text,
            actions=[
                URIAction(
                    label='Attendance',
                    uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{kelas['kode']}/attendance?openExternalBrowser=1"
                ),
                URIAction(
                    label='TLM',
                    uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{kelas['kode']}/teaching-learning-materials?openExternalBrowser=1"
                ),
                URIAction(
                    label='Assignments',
                    uri=f"http://leaps.kalbis.ac.id/LMS/lectures/detail/{kelas['kode']}/assignments?openExternalBrowser=1"
                )
            ]
        )
    )
    with open ('groups.json', 'r') as f:
        groups = json.load(f)
        for group in groups['groups']:
            line_bot_api.push_message(group, buttons_template_message)

def convert_cron(day, time, early):
    hour, minute = map(int, time.split('.'))

    if early == True:
      # -15 menit
      if minute >= 15:
          minute -= 15
      else:
          minute = 60 - (15 - minute)
          hour -= 1

    skipped_days = ['senin', 'selasa', 'rabu', 'kamis', 'jumat']
    if day in skipped_days:
        return None
    day = day[:3]

    return [day, hour, minute]

def passing(x):
    return x

register_jobs()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)