#!/usr/bin/env python3
from __future__ import annotations
import argparse, io, json, re, shutil, zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

try:
    import spacy
except ImportError:
    spacy = None
try:
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
except ImportError:
    pytesseract = Image = ImageDraw = ImageFont = ImageOps = ImageFilter = None

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\b")
IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PHONE = re.compile(r"(?<!\d)(?:\+\s*91[\s.-]*)?(?:[6-9]\d{4}[\s.-]?\d{5}|0?\d{2,4}[\s.-]\d{3,4}[\s.-]?\d{4}|0?\d{2,4}[\s.-]?\d{6,8})(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
CIN = re.compile(r"\b[LUFOP]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE = rf"(?:\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{1,2}}\s+{MONTH}\s+\d{{4}}|{MONTH}\s+\d{{1,2}},?\s+\d{{4}})"
DOB = re.compile(rf"(?i)\b(?:date\s+of\s+birth|dob|born(?:\s+on)?)\s*[:\-]?\s*({DATE})")
COMPANY = re.compile(r"\b[A-Z][A-Za-z0-9&.'’\-]*(?:\s+(?:&|and|of|the|[A-Z][A-Za-z0-9&.'’\-]*)){0,10}\s+(?:Limited|Ltd\.?|Private Limited|Pvt\.?\s*Ltd\.?|LLP|Inc\.?|Incorporated|Corporation|Corp\.?)\b")
ADDR_LABEL = re.compile(r"(?i)\b(?:registered|corporate|mailing|residential|permanent|correspondence|head|branch)\s+(?:office|address|location)\s*[:\-]\s*")
STREET = re.compile(r"(?i)\b(?:road|street|st\.|lane|nagar|building|tower|floor|plot|village|district|park|estate|highway|sector|taluka|colony)\b")
PIN = re.compile(r"\b[1-9]\d{5}\b")
PERSON_CUE = re.compile(r"(?i)\b(?:contact\s+person|director|promoter|promoters|chairman|chief\s+executive\s+officer|chief\s+financial\s+officer|mr\.?|ms\.?|mrs\.?)\b")

DENY = {
    "our board","registered office","corporate office","restated financial statements",
    "financial statements","book running lead managers","lead managers","promoter group",
    "promoter selling shareholders","general information","risk factors","equity shares",
    "stock exchanges","income tax department","government of india","permanent account number",
    "date of birth","red herring prospectus","offer price","our management","companies act",
    "securities and exchange board of india"
}
ORG_DENY = DENY | {"offer","board","company","issuer","india","maharashtra","goi","icai","sebi","bse","nse","roc","scrr","sebi icdr regulations"}

@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str
    text: str

def norm(s): return re.sub(r"\s+", " ", s).strip()

def add(out,a,b,k,t):
    if a < b and t: out.append(Entity(a,b,k,t))

def valid_ip(s):
    try: return len(s.split(".")) == 4 and all(0 <= int(x) <= 255 for x in s.split("."))
    except ValueError: return False

def luhn(s):
    d=[int(x) for x in s if x.isdigit()]
    if not 13 <= len(d) <= 19: return False
    total=0
    for i,n in enumerate(reversed(d)):
        if i%2:
            n*=2
            if n>9: n-=9
        total+=n
    return total%10==0

def resolve(items):
    priority={"email":100,"phone":99,"card":99,"ssn":99,"ip":99,"cin":99,"dob":98,"address":95,"person":80,"company":70}
    chosen=[]
    for e in sorted(items,key=lambda x:(-priority.get(x.kind,0),x.start,-(x.end-x.start))):
        if not any(not(e.end<=o.start or e.start>=o.end) for o in chosen): chosen.append(e)
    return sorted(chosen,key=lambda x:x.start)

class Detector:
    def __init__(self,model="en_core_web_sm"):
        self.nlp=None
        if spacy:
            try:
                self.nlp=spacy.load(model)
                self.nlp.max_length=max(self.nlp.max_length,2_000_000)
            except Exception: pass

    def detect(self,text):
        out=[]
        for rx,k in ((EMAIL,"email"),(SSN,"ssn"),(CIN,"cin"),(PHONE,"phone")):
            for m in rx.finditer(text): add(out,m.start(),m.end(),k,m.group())
        for m in IP.finditer(text):
            if valid_ip(m.group()): add(out,m.start(),m.end(),"ip",m.group())
        for m in CARD.finditer(text):
            if luhn(m.group()): add(out,m.start(),m.end(),"card",m.group())
        for m in DOB.finditer(text): add(out,m.start(1),m.end(1),"dob",m.group(1))

        for m in ADDR_LABEL.finditer(text):
            end=text.find("\n",m.end())
            if end<0: end=min(len(text),m.end()+300)
            candidate=text[m.end():end].strip()
            pin=PIN.search(candidate)
            if pin: add(out,m.end(),m.end()+pin.end(),"address",candidate[:pin.end()].strip(" ;,"))

        for pin in PIN.finditer(text):
            left=max(text.rfind("\n",0,pin.start()),text.rfind(";",0,pin.start()))+1
            candidate=text[left:pin.end()]
            if len(candidate)<=220 and STREET.search(candidate): add(out,left,pin.end(),"address",candidate.strip(" ;,"))

        for m in COMPANY.finditer(text):
            v=norm(m.group())
            if v.casefold() not in ORG_DENY: add(out,m.start(),m.end(),"company",v)

        if self.nlp:
            for e in self.nlp(text).ents:
                v=norm(e.text); key=v.casefold()
                if e.label_=="PERSON" and 2<=len(v.split())<=5 and key not in DENY and not any(c.isdigit() for c in v):
                    add(out,e.start_char,e.end_char,"person",v)
                elif e.label_=="ORG" and len(v.split())>=2 and key not in ORG_DENY and re.search(r"(?i)\b(limited|ltd|private|pvt|llp|inc|incorporated|corporation|corp)\b",v):
                    add(out,e.start_char,e.end_char,"company",v)

        for m in PERSON_CUE.finditer(text):
            tail=text[m.end():m.end()+100]
            x=re.match(r"\s*[:\-]?\s*([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})",tail)
            if x:
                v=norm(x.group(1))
                if v.casefold() not in DENY:
                    a=m.end()+x.start(1); add(out,a,a+len(v),"person",v)
        return resolve(out)

PERSON_POOL=["Bablu Sharma","Aarav Mehta","Kabir Kapoor","Riya Malhotra","Vikram Nair","Ananya Rao","Dev Khanna","Maya Iyer"]
COMPANY_POOL=["Acme Technologies Private Limited","Northstar Industries Limited","BluePeak Solutions Private Limited","Vertex Business Services LLP","Cedar Financial Services Limited"]
ADDRESS_POOL=["12 Example Road, Pune - 411001, India","42 Sample Street, Mumbai - 400001, India","18 Demo Park, Bengaluru - 560001, India","77 Placeholder Avenue, New Delhi - 110001, India"]

class ReplacementMap:
    def __init__(self):
        self.maps=defaultdict(dict)
        self.seed={"rahul":"Bablu","rahul mehta":"Bablu Sharma"}

    def get(self,k,source):
        key=norm(source).casefold()
        if key in self.maps[k]: return self.maps[k][key]
        n=len(self.maps[k])
        if k=="person": fake=self.seed.get(key,PERSON_POOL[n%len(PERSON_POOL)])
        elif k=="email":
            p=re.findall(r"[a-z]+",key.split("@")[0])
            fake=f"{p[0]}.{p[-1]}@example.com" if len(p)>=2 else f"person{n+1}@example.com"
        elif k=="phone": fake=f"+91 91234 {10000+n:05d}"
        elif k=="company": fake=COMPANY_POOL[n%len(COMPANY_POOL)]
        elif k=="address": fake=ADDRESS_POOL[n%len(ADDRESS_POOL)]
        elif k=="dob": fake="15 January 1990"
        elif k=="ssn": fake=f"111-22-{3300+n:04d}"
        elif k=="card": fake="4111 1111 1111 1111"
        elif k=="ip": fake=f"203.0.113.{10+n}"
        elif k=="cin": fake=f"U12345MH2000PTC{100000+n:06d}"
        else: fake="[REDACTED]"
        self.maps[k][key]=fake
        return fake

    def save(self,path): path.write_text(json.dumps(self.maps,indent=2),encoding="utf-8")

def all_paragraphs(doc):
    yield from doc.element.body.iter(qn("w:p"))
    for s in doc.sections:
        for c in (s.header,s.first_page_header,s.even_page_header,s.footer,s.first_page_footer,s.even_page_footer):
            yield from c._element.iter(qn("w:p"))

def ptext(p):
    nodes=list(p.iter(qn("w:t"))); text=""; ranges=[]; pos=0
    for node in nodes:
        v=node.text or ""; ranges.append((node,pos,pos+len(v))); text+=v; pos+=len(v)
    return text,ranges

def replace_paragraph(p,entities,maps):
    text,nodes=ptext(p)
    for e in sorted(entities,key=lambda x:x.start,reverse=True):
        hits=[(n,a,b) for n,a,b in nodes if not(b<=e.start or a>=e.end)]
        if not hits: continue
        n,a,_=hits[0]; v=n.text or ""; s=max(0,e.start-a); z=min(len(v),e.end-a)
        n.text=v[:s]+maps.get(e.kind,e.text)+v[z:]
        for n,a,b in hits[1:]:
            v=n.text or ""; n.text=v[min(len(v),max(0,e.end-a)):] if a<e.end else v

def setup_tesseract():
    if not pytesseract: return False
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe","/usr/bin/tesseract","/usr/local/bin/tesseract"):
        if Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd=p; return True
    return False

def font(size):
    for p in (r"C:\Windows\Fonts\arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            try: return ImageFont.truetype(p,max(12,size))
            except Exception: pass
    return ImageFont.load_default()

def fake_id(width,height):
    im=Image.new("RGB",(width,height),"white"); d=ImageDraw.Draw(im)
    d.rectangle((8,8,width-8,height-8),outline="black",width=3)
    d.text((25,25),"PII REDACTED - SYNTHETIC REPLACEMENT",fill="black",font=font(max(18,width//25)))
    lines=["Name: Bablu Sharma","ID Number: XXXX XXXX XXXX","Date of Birth: 15 January 1990","Address: 12 Example Road, Pune - 411001, India","Fabricated replacement - no real PII"]
    y=90
    for line in lines:
        d.text((30,y),line,fill="black",font=font(max(14,width//40))); y+=max(35,height//10)
    return im

def redact_image(data, detector, maps):
    if not Image or not pytesseract or not setup_tesseract():
        return data, 0, "ocr_unavailable"

    original = Image.open(io.BytesIO(data))
    original_format = original.format or "PNG"
    original = original.convert("RGB")

    # Upscale before OCR so small text in scanned cards is easier to read.
    work = original.resize((original.width * 2, original.height * 2))
    gray = ImageOps.autocontrast(ImageOps.grayscale(work))
    gray = gray.filter(ImageFilter.SHARPEN)

    try:
        text = pytesseract.image_to_string(gray, config="--psm 6")
    except Exception:
        return data, 0, "ocr_failed"

    low = text.casefold()
    signals = (
        "aadhaar", "uidai", "permanent account number",
        "income tax department", "government of india",
        "date of birth", "father's name", "dob",
    )

    # Identity cards contain several correlated PII fields, photos, signatures
    # and sometimes QR codes. If the image is clearly an identity document,
    # replacing the whole image is safer than leaving an undetected field behind.
    is_id = (
        sum(signal in low for signal in signals) >= 2
        or ("date of birth" in low and re.search(r"\d[\d\s-]{7,}\d", text))
    )

    if is_id:
        fake = fake_id(original.width, original.height)
        out = io.BytesIO()
        if original_format == "JPEG":
            fake.save(out, format="JPEG", quality=95)
        else:
            fake.save(out, format="PNG")
        return out.getvalue(), 1, "identity_document_replaced"

    # For ordinary images, use OCR coordinates to redact only the detected PII.
    try:
        ocr = pytesseract.image_to_data(
            gray, output_type=pytesseract.Output.DICT, config="--psm 6"
        )
    except Exception:
        return data, 0, "ocr_failed"

    lines = defaultdict(list)
    for i, token in enumerate(ocr["text"]):
        token = token.strip()
        if not token:
            continue
        key = (ocr["block_num"][i], ocr["par_num"][i], ocr["line_num"][i])
        lines[key].append({
            "t": token, "x": ocr["left"][i], "y": ocr["top"][i],
            "w": ocr["width"][i], "h": ocr["height"][i],
        })

    draw = ImageDraw.Draw(work)
    count = 0

    for words in lines.values():
        words.sort(key=lambda w: w["x"])
        line = " ".join(w["t"] for w in words)
        entities = detector.detect(line)

        spans = []
        cursor = 0
        for word in words:
            spans.append((cursor, cursor + len(word["t"]), word))
            cursor += len(word["t"]) + 1

        for entity in entities:
            touched = [
                word for start, end, word in spans
                if not (end <= entity.start or start >= entity.end)
            ]
            if not touched:
                continue

            x1 = max(0, min(w["x"] for w in touched) - 6)
            y1 = max(0, min(w["y"] for w in touched) - 6)
            x2 = max(w["x"] + w["w"] for w in touched) + 8
            y2 = max(w["y"] + w["h"] for w in touched) + 8

            fake = maps.get(entity.kind, entity.text)
            draw.rectangle((x1, y1, x2, y2), fill="white")
            draw.text(
                (x1 + 3, y1 + 2), fake, fill="black",
                font=font(max(w["h"] for w in touched)),
            )
            count += 1

    final = work.resize(original.size)
    out = io.BytesIO()
    if original_format == "JPEG":
        final.save(out, format="JPEG", quality=95)
    else:
        final.save(out, format="PNG")
    return out.getvalue(), count, "ocr_processed"

def redact_images(path,detector,maps):
    tmp=path.with_suffix(".tmp.docx"); count=0; status=defaultdict(int)
    with zipfile.ZipFile(path,"r") as zin,zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data=zin.read(item.filename)
            if item.filename.startswith("word/media/"):
                try:
                    data,n,s=redact_image(data,detector,maps); count+=n; status[s]+=1
                except Exception: status["image_error"]+=1
            zout.writestr(item,data)
    shutil.move(tmp,path); return count,dict(status)

def main():
    ap=argparse.ArgumentParser(description="Conservative generalized DOCX PII redactor.")
    ap.add_argument("input",type=Path); ap.add_argument("-o","--output",type=Path); ap.add_argument("--map",dest="map_file",type=Path)
    ap.add_argument("--model",default="en_core_web_sm"); ap.add_argument("--no-ocr",action="store_true")
    args=ap.parse_args()
    if not args.input.exists() or args.input.suffix.lower()!=".docx": raise SystemExit("Input must be an existing .docx file.")
    output=args.output or args.input.with_name(args.input.stem+"_redacted.docx"); shutil.copy2(args.input,output)
    detector=Detector(args.model); maps=ReplacementMap(); counts=defaultdict(int)
    doc=Document(str(output))
    for p in all_paragraphs(doc):
        text,_=ptext(p)
        if not text.strip(): continue
        entities=detector.detect(text)
        for e in entities: counts[e.kind]+=1
        replace_paragraph(p,entities,maps)
    doc.save(output)
    n,status=(0,{"ocr_disabled":1}) if args.no_ocr else redact_images(output,detector,maps)
    if args.map_file: maps.save(args.map_file)
    print(f"Created: {output}\nText redactions: {sum(counts.values())}")
    for k,v in sorted(counts.items()): print(f"  {k:10} {v}")
    print(f"OCR/image redactions: {n}\nImage status: {status}\nspaCy enabled: {detector.nlp is not None}")
    print("Stable map entries:",sum(len(v) for v in maps.maps.values()))

if __name__=="__main__": main()