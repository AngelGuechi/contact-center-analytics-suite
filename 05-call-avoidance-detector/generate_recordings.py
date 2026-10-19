"""Developer-only creation of invented spoken recordings; no production dependency.

Requires piper-tts 1.8.0 and the documented local voice assets. Everyday users
use the included WAV files and do not install a speech synthesizer.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import wave

PROJECT = Path(__file__).resolve().parent
RATE = 22050


def generate(destination=None):
    import numpy as np
    from piper import PiperVoice
    from piper.config import SynthesisConfig
    destination = Path(destination or PROJECT / "recordings")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "Calls").mkdir(exist_ok=True)
    assets = PROJECT / "runtime/tts-models"
    voices = {lang: PiperVoice.load(assets / (name + ".onnx")) for lang,name in
              {"es": "es_MX-ald-medium", "en": "en_US-ljspeech-high"}.items()}
    cache = {}
    def say(lang, text):
        key = lang, text
        if key not in cache:
            stream = io.BytesIO()
            with wave.open(stream, "wb") as handle:
                voices[lang].synthesize_wav(text, handle, SynthesisConfig(length_scale=1.0))
            with wave.open(io.BytesIO(stream.getvalue()), "rb") as handle:
                assert handle.getframerate() == RATE
                cache[key] = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(np.float32)/32768
        return cache[key]

    definitions = [
        {"call_id":"70003501","duration":10,"name":"Brief greeting","scope":"transaction_leg","segments":[(.4,0,"en","Hello. Can you hear me?")]},
        {"call_id":"70003502","duration":10,"name":"Saludo breve","scope":"transaction_leg","segments":[(.4,0,"es","Buenas tardes. Gracias por llamar. ¿En qué puedo ayudarle?")]},
        {"call_id":"70003507","duration":45,"name":"Billing conversation","scope":"partial","segments":[(1,0,"en","Thank you for calling. How can I help you today?"),(8,0,"en","I have a question about the amount on my bill."),(16,0,"en","I can help with that. Please give me a moment to check the details."),(29,0,"en","The extra amount is a payment from last month."),(37,0,"en","Thank you for explaining. Have a good day.")]},
        {"call_id":"70003508","duration":45,"name":"Consulta de recibo","scope":"partial","segments":[(1,0,"es","Gracias por llamar. ¿En qué le puedo ayudar?"),(8,0,"es","Tengo una pregunta sobre el importe de mi recibo."),(16,0,"es","Claro. Permítame un momento para revisar los detalles."),(29,0,"es","El importe adicional corresponde al mes anterior."),(37,0,"es","Muchas gracias por la explicación. Que tenga buen día.")]},
        {"call_id":"70003509","duration":45,"name":"Verified separate channels","scope":"partial","channels":2,"roles":True,"segments":[(1,0,"es","Gracias por llamar. ¿En qué le puedo ayudar?"),(8,1,"es","Quiero saber cuándo vence el pago de mi recibo."),(17,0,"es","Permítame revisar la fecha. Le agradezco que espere un momento."),(34,0,"es","El pago vence el próximo viernes."),(40,1,"es","Gracias. Eso era todo.")]},
        {"call_id":"70003510","duration":45,"name":"Long quiet after greeting","scope":"partial","segments":[(1,0,"en","Hello. Thank you for calling. How can I help you?"),(34,0,"en","Hello? Are you still there?")]},
        {"call_id":"70003511","duration":45,"name":"Audible music and quiet","scope":"partial","segments":[(1,0,"en","Please hold while I check your account."),(34,0,"en","Thank you for waiting. Your account is up to date.")],"music":[12,25]},
        {"call_id":"70003512","duration":45,"name":"English and Spanish","scope":"partial","segments":[(1,0,"es","Hola. Tengo una pregunta sobre mi cuenta."),(10,0,"en","Yes, I can help you with your account."),(19,0,"es","Muchas gracias. Quiero confirmar la fecha de pago."),(32,0,"en","Your payment is due on Friday. Thank you for calling.")]},
        {"call_id":"70003503","duration":10,"name":"Recording with zero samples","scope":"transaction_leg","segments":[]},
        {"call_id":"70003513","duration":25,"name":"Opposite-phase channels","scope":"partial","channels":2,"opposite":True,"segments":[(1,0,"en","This recording has the same voice on both channels. Check the channel mapping before assigning speaker roles."),(16,0,"en","A quiet period does not prove intentional call avoidance.")]},
    ]
    rows, expected = [], []
    for definition in definitions:
        samples = round(definition["duration"]*RATE)
        channels = definition.get("channels",1)
        audio = np.zeros((samples,channels),dtype=np.float32)
        inserted = []
        for start,channel,lang,text in definition["segments"]:
            speech=say(lang,text)
            first=round(start*RATE)
            if first+len(speech)>samples: raise ValueError('Speech exceeds fixture duration: '+definition['name'])
            audio[first:first+len(speech),channel] += speech*.72
            inserted.append({"start_seconds":start,"end_seconds":(first+len(speech))/RATE,"channel":channel,"language":lang,"text":text})
        if definition.get("music"):
            first,last=[round(value*RATE) for value in definition["music"]]
            seconds=np.arange(last-first)/RATE
            # Invented instrumental chord; no copyrighted song or spoken words.
            chord=sum(np.sin(2*np.pi*f*seconds) for f in [261.63,329.63,392])/3
            envelope=.7+.3*np.sin(2*np.pi*2*seconds)**2
            audio[first:last,0] += (chord*envelope*.12).astype(np.float32)
        if definition.get("opposite"): audio[:,1]=-audio[:,0]
        path=destination/'Calls'/(definition['call_id']+'.wav')
        pcm=np.round(np.clip(audio,-1,1)*32767).astype('<i2')
        with wave.open(str(path),'wb') as handle:
            handle.setnchannels(channels);handle.setsampwidth(2);handle.setframerate(RATE);handle.writeframes(pcm.tobytes())
        roles=definition.get('roles',False)
        rows.append({'recording_file':'Calls/'+path.name,'call_id':definition['call_id'],'call_id_type':'transaction',
                     'recording_scope':definition['scope'],'channel_layout':'separate_roles' if roles else 'mono' if channels==1 else 'unknown',
                     'agent_channel':0 if roles else '', 'customer_channel':1 if roles else '',
                     'audio_start_seconds':0,'audio_end_seconds':definition['duration']})
        expected.append({'file':'Calls/'+path.name,'call_id':definition['call_id'],'name':definition['name'],
                         'duration_seconds':definition['duration'],'channels':channels,'segments':inserted,
                         'music_interval':definition.get('music'),'digital_zero':not definition['segments'],
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'reference_text':' '.join(item['text'] for item in inserted),
                         'expected_interpretation':'No agent/customer role attribution' if not roles else 'Roles are supplied explicitly in the generated CSV'})
    with (destination/'recordings.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    manifest={'schema_version':1,'synthetic':True,'origin':'Invented scripts, local synthetic voices and generated instrumental tones; no real calls or customer data.',
              'report_date':'2026-10-06','sample_rate':RATE,'generator':'piper-tts 1.8.0','voices':[
                  {'language':'es','model':'es_MX-ald-medium','source':'https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX/ald/medium','dataset_license':'Unlicense'},
                  {'language':'en','model':'en_US-ljspeech-high','source':'https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ljspeech/high'}],
              'files':expected,'reference_note':'Inserted speech ranges are generation landmarks, not perfect VAD ground truth. ASR text is measured separately and can differ from the scripts.'}
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'scripts.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Created {len(expected)} invented recordings in {destination}')


if __name__ == '__main__': generate()
