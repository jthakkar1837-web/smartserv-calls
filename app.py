import os
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
import anthropic

app = Flask(__name__)

# ── Twilio + Anthropic clients ──────────────────────────────
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

DAD_NUMBER   = os.environ["DAD_PHONE_NUMBER"]   # e.g. +61412345678
TWILIO_NUMBER = os.environ["TWILIO_PHONE_NUMBER"] # e.g. +61290001234

# ── In-memory session store (good enough for single-user) ───
sessions = {}

def get_session(call_sid):
    if call_sid not in sessions:
        sessions[call_sid] = {"name": "", "suburb": "", "issue": "", "caller": ""}
    return sessions[call_sid]

# ── Step 1: Incoming call — ask for name ────────────────────
@app.route("/voice", methods=["POST"])
def voice():
    call_sid = request.form.get("CallSid")
    caller   = request.form.get("From", "Unknown")
    session  = get_session(call_sid)
    session["caller"] = caller

    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-name", timeout=6, speech_timeout="auto", language="en-AU")
    gather.say(
        "Hi, thanks for calling Smart Appliances Services. "
        "I'll take your details and have someone call you back shortly. "
        "Can I get your name please?",
        voice="Polly.Olivia-Neural"
    )
    resp.append(gather)
    resp.redirect("/voice")  # loop if no input
    return Response(str(resp), mimetype="text/xml")

# ── Step 2: Got name — ask for suburb ───────────────────────
@app.route("/got-name", methods=["POST"])
def got_name():
    call_sid = request.form.get("CallSid")
    name     = request.form.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["name"] = name or "Unknown"

    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-suburb", timeout=6, speech_timeout="auto", language="en-AU")
    gather.say(
        f"Thanks {session['name']}. And what suburb are you in?",
        voice="Polly.Olivia-Neural"
    )
    resp.append(gather)
    return Response(str(resp), mimetype="text/xml")

# ── Step 3: Got suburb — ask for issue ──────────────────────
@app.route("/got-suburb", methods=["POST"])
def got_suburb():
    call_sid = request.form.get("CallSid")
    suburb   = request.form.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["suburb"] = suburb or "Unknown"

    resp = VoiceResponse()
    gather = Gather(input="speech", action="/got-issue", timeout=8, speech_timeout="auto", language="en-AU")
    gather.say(
        "Great. And briefly, what's the issue with your appliance?",
        voice="Polly.Olivia-Neural"
    )
    resp.append(gather)
    return Response(str(resp), mimetype="text/xml")

# ── Step 4: Got issue — summarise + send SMS ─────────────────
@app.route("/got-issue", methods=["POST"])
def got_issue():
    call_sid = request.form.get("CallSid")
    issue    = request.form.get("SpeechResult", "").strip()
    session  = get_session(call_sid)
    session["issue"] = issue or "Not specified"

    # Use Claude to write a clean summary SMS
    summary = summarise_with_claude(session)

    # Send SMS to dad
    twilio_client.messages.create(
        body=summary,
        from_=TWILIO_NUMBER,
        to=DAD_NUMBER
    )

    # Clean up session
    sessions.pop(call_sid, None)

    # Thank the caller
    resp = VoiceResponse()
    resp.say(
        "Perfect, thank you. We've got your details and someone will be in touch with you shortly. Have a great day!",
        voice="Polly.Olivia-Neural"
    )
    return Response(str(resp), mimetype="text/xml")

# ── Claude summary ───────────────────────────────────────────
def summarise_with_claude(session):
    prompt = f"""
A client just called the Smart Appliances Services business voicemail.
Write a short, clear SMS to send to the business owner with the job details.

Details collected:
- Name: {session['name']}
- Suburb: {session['suburb']}
- Issue: {session['issue']}
- Called from: {session['caller']}

Format it like this (keep it under 160 characters if possible):
📞 New call — [Name], [Suburb]. Issue: [brief issue]. Call back: [number]

Just return the SMS text, nothing else.
"""
    message = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
