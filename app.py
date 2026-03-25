import os
import json
import urllib.request
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client

app = Flask(__name__)

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
DAD_NUMBER    = os.environ["DAD_PHONE_NUMBER"]
TWILIO_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

sessions = {}

def get_session(call_sid):
    if call_sid not in sessions:
        sessions[call_sid] = {"name": "", "suburb": "", "issue": "", "caller": ""}
    return sessions[call_sid]

@app.route("/voice", methods=["GET", "POST"])
def voice():
    call_sid = request.values.get("CallSid", "test")
    caller   = request.values.get("From", "Unknown")
    session  = get_session(call_sid)
    session["caller"] = caller
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-name", method="POST", timeout=6, speech_timeout="auto", language="en-AU")
    gather.say("Hi, thanks for calling Smart Appliances Services. I will take your details and have someone call you back shortly. Can I get your name please?", voice="alice")
    resp.append(gather)
    resp.redirect("/voice", method="POST")
    return Response(str(resp), mimetype="text/xml")

@app.route("/got-name", methods=["GET", "POST"])
def got_name():
    call_sid = request.values.get("CallSid", "test")
    name     = request.values.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["name"] = name or "Unknown"
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-suburb", method="POST", timeout=6, speech_timeout="auto", language="en-AU")
    gather.say(f"Thanks. And what suburb are you in?", voice="alice")
    resp.append(gather)
    return Response(str(resp), mimetype="text/xml")

@app.route("/got-suburb", methods=["GET", "POST"])
def got_suburb():
    call_sid = request.values.get("CallSid", "test")
    suburb   = request.values.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["suburb"] = suburb or "Unknown"
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-issue", method="POST", timeout=8, speech_timeout="auto", language="en-AU")
    gather.say("Great. And briefly, what is the issue with your appliance?", voice="alice")
    resp.append(gather)
    return Response(str(resp), mimetype="text/xml")

@app.route("/got-issue", methods=["GET", "POST"])
def got_issue():
    call_sid = request.values.get("CallSid", "test")
    issue    = request.values.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["issue"] = issue or "Not specified"

    summary = summarise(session)

    twilio_client.messages.create(body=summary, from_=TWILIO_NUMBER, to=DAD_NUMBER)
    sessions.pop(call_sid, None)

    resp = VoiceResponse()
    resp.say("Perfect, thank you. We have got your details and someone will be in touch shortly. Have a great day!", voice="alice")
    return Response(str(resp), mimetype="text/xml")

def summarise(session):
    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "messages": [{
                "role": "user",
                "content": f"Write a short SMS for a smart appliances business owner. Client: {session['name']}, Suburb: {session['suburb']}, Issue: {session['issue']}, Phone: {session['caller']}. Format: New call - [Name], [Suburb]. Issue: [brief issue]. Call back: [number]. Return SMS text only, no emoji."
            }]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read())
            return data["content"][0]["text"].strip()
    except Exception as e:
        return f"New call - {session['name']}, {session['suburb']}. Issue: {session['issue']}. Call back: {session['caller']}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
