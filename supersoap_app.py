
import re
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from dateutil import tz
import streamlit as st

TZ = tz.gettz("Asia/Makassar")  # sesuai user timezone
DAY_ID = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu",
}

# -------------------------
# Utilities
# -------------------------
def day_name_id(d: date) -> str:
    return DAY_ID.get(d.strftime("%A"), d.strftime("%A"))

def fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def clean(s: str) -> str:
    return (s or "").strip()

def parse_hhmm(s: str):
    s = clean(s).replace(".", ":")
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi

def fmt_time(h: int, mi: int) -> str:
    return f"{h:02d}.{mi:02d}"

def minus_minutes(h: int, mi: int, minutes: int):
    total = (h * 60 + mi - minutes) % (24 * 60)
    return total // 60, total % 60

def maintenance_ml_per_hr_421(weight_kg: float) -> float:
    w = max(0.0, float(weight_kg))
    if w <= 10:
        return 4.0 * w
    if w <= 20:
        return 40.0 + 2.0 * (w - 10.0)
    return 60.0 + 1.0 * (w - 20.0)

def tpm_from_ml_per_hr(ml_per_hr: float, drip_factor_gtt_per_ml: int = 20) -> int:
    return int(round((float(ml_per_hr) * int(drip_factor_gtt_per_ml)) / 60.0))

def normalize_minlap_block(text: str) -> str:
    # NOTE: user minta "jangan ubah spasi/bullet". Jadi kita simpan apa adanya.
    return text.strip("\n")

# -------------------------
# Minimal parsers (SOAP raw + MINLAP)
# -------------------------
@dataclass
class ParsedInfo:
    nama: str = ""
    jk: str = ""
    umur: str = ""
    pembiayaan: str = ""
    perawatan: str = ""
    kamar: str = ""
    rs: str = "RSGMP UNHAS"
    rm: str = ""
    bb: float = 0.0
    tb: float = 0.0
    tindakan: str = ""
    anestesi: str = ""
    penunjang_raw: str = ""
    jam_operasi: str = ""
    zona: str = ""
    dpjp: str = ""
    residen: str = ""

def parse_identity_line(text: str):
    # contoh: "Nn. X / P / 24 Tahun / Rawat Jalan / BPJS / RSGMP UNHAS / RM 10.82.79"
    m = re.search(r"^(Tn\.|Ny\.|Nn\.|An\.)[^\n]+", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    ident = m.group(0).strip()
    parts = [p.strip() for p in ident.split("/") if p.strip()]
    return parts

def extract_tindakan_from_P(raw: str) -> tuple[str,str]:
    # cari blok P:
    m = re.search(r"\n\s*P\s*:\s*(.*)$", raw, re.IGNORECASE | re.DOTALL)
    if not m:
        return "", ""
    pblock = m.group(1)
    # ambil baris "Pro ...."
    lines = [ln.strip() for ln in pblock.splitlines() if ln.strip()]
    pro_lines = [ln for ln in lines if re.search(r"\bPro\b", ln, re.IGNORECASE)]
    if not pro_lines:
        return "", ""
    last = pro_lines[-1]
    # contoh: "Pro Odontektomi ... dalam general anestesi (menunggu penjadwalan)"
    m2 = re.search(r"\bPro\b\s*(.+?)(?:\s+dalam\s+([^.]+?))?(?:\(|$|\.)", last, re.IGNORECASE)
    if not m2:
        return "", ""
    tindakan = clean(m2.group(1))
    anestesi = clean(m2.group(2)) if m2.group(2) else ""
    # bersihkan "menunggu penjadwalan" dll
    tindakan = re.sub(r"\s*\(.*?\)\s*$", "", tindakan).strip()
    return tindakan, anestesi

def parse_bb_tb(raw: str):
    bb = 0.0
    tb = 0.0
    mb = re.search(r"\bBB\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*kg\b", raw, re.IGNORECASE)
    mt = re.search(r"\bTB\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*cm\b", raw, re.IGNORECASE)
    if mb:
        bb = float(mb.group(1))
    if mt:
        tb = float(mt.group(1))
    return bb, tb

def parse_minlap(minlap: str) -> ParsedInfo:
    p = ParsedInfo()
    t = minlap.strip()
    if not t:
        return p
    parts = parse_identity_line(t)
    if parts:
        p.nama = parts[0]
        if len(parts) > 1: p.jk = parts[1]
        if len(parts) > 2: p.umur = parts[2]
        # minlap kadang urutan rawat jalan/inap dan BPJS bisa kebalik
        # kita ambil yang mengandung "Rawat"
        for x in parts:
            if "rawat" in x.lower():
                p.perawatan = x
        for x in parts:
            if x.upper() in ["BPJS", "UMUM", "JASA RAHARJA", "BAKSOS", "BAKSOS CCC", "CCC"]:
                p.pembiayaan = x
        mrm = re.search(r"RM\.?\s*([0-9.]+)", t, re.IGNORECASE)
        if mrm: p.rm = mrm.group(1).strip()
    # BB/TB dari baris "BB:  49 kg, TB: 159  cm"
    p.bb, p.tb = parse_bb_tb(t)
    # Penunjang raw block (dari "Pemeriksaan penunjang" sampai sebelum "A :")
    mpen = re.search(r"Pemeriksaan\s+penunjang\s*:\s*(.*?)(?:\n\s*A\s*:|\n\s*A\s*：|\n\s*A\s*\n|$)", t, re.IGNORECASE | re.DOTALL)
    if mpen:
        block = mpen.group(0).strip()
        p.penunjang_raw = normalize_minlap_block(block)
    # Tindakan dari "P : Pro ...."
    mt = re.search(r"\n\s*P\s*:\s*(.+)", t, re.IGNORECASE)
    if mt:
        tindakan_line = mt.group(1).strip()
        tindakan_line = re.sub(r"^\W*\bPro\b\s*", "", tindakan_line, flags=re.IGNORECASE).strip()
        tindakan_line = re.sub(r"\s+dalam\s+.*$", "", tindakan_line, flags=re.IGNORECASE).strip()
        p.tindakan = tindakan_line
    # Jam operasi dari "Pukul : *08.00 WITA*"
    mj = re.search(r"Pukul\s*:\s*\*?([0-9]{1,2}\.[0-9]{2})\s*([A-Z]{3,4})\*?", t, re.IGNORECASE)
    if mj:
        p.jam_operasi = mj.group(1)
        p.zona = mj.group(2).upper()
    # DPJP
    md = re.search(r"DPJP\s*:\s*(.+)", t, re.IGNORECASE)
    if md:
        p.dpjp = md.group(1).strip()
    return p

def parse_rawsoap(raw: str) -> ParsedInfo:
    p = ParsedInfo()
    t = raw.strip()
    if not t:
        return p
    parts = parse_identity_line(t)
    if parts:
        p.nama = parts[0]
        if len(parts) > 1: p.jk = parts[1]
        if len(parts) > 2: p.umur = parts[2]
        # ambil perawatan & pembiayaan dari parts
        for x in parts:
            if "rawat" in x.lower():
                p.perawatan = x
        for x in parts:
            if x.upper() in ["BPJS", "UMUM", "JASA RAHARJA", "BAKSOS", "BAKSOS CCC", "CCC"]:
                p.pembiayaan = x
        mrm = re.search(r"RM\.?\s*([0-9.]+)", t, re.IGNORECASE)
        if mrm: p.rm = mrm.group(1).strip()
    p.bb, p.tb = parse_bb_tb(t)
    tindakan, anest = extract_tindakan_from_P(t)
    if tindakan:
        p.tindakan = tindakan
    if anest:
        p.anestesi = anest
    md = re.search(r"DPJP\s*:?\s*(.+)", t, re.IGNORECASE)
    if md: p.dpjp = md.group(1).strip()
    mr = re.search(r"Residen\s*:?\s*(.+)", t, re.IGNORECASE)
    if mr: p.residen = mr.group(1).strip()
    return p

# -------------------------
# Schema-driven renderer
# -------------------------
def should_show(q, answers):
    cond = q.get("show_if")
    if not cond:
        return True
    key = cond.get("key")
    if "equals" in cond:
        return answers.get(key) == cond["equals"]
    if "in" in cond:
        return answers.get(key) in cond["in"]
    return True

def render_question(q, answers, tutorial=False):
    k = q["key"]
    label = q["label"]
    help_txt = q.get("help") if tutorial else None
    t = q["type"]

    if t == "bool":
        answers[k] = st.toggle(label, value=bool(answers.get(k, q.get("default", False))), help=help_txt)
    elif t == "text":
        answers[k] = st.text_input(label, value=str(answers.get(k, q.get("default",""))), help=help_txt)
    elif t == "int":
        answers[k] = st.slider(label, min_value=int(q.get("min",0)), max_value=int(q.get("max",10)),
                              value=int(answers.get(k, q.get("default",0))), help=help_txt)
    elif t == "select":
        options = q["options"]
        current = answers.get(k, q.get("default", options[0] if options else ""))
        if current not in options and options:
            current = options[0]
        answers[k] = st.selectbox(label, options=options, index=options.index(current) if options else 0, help=help_txt)
    elif t == "date":
        today = datetime.now(TZ).date()
        default = today if q.get("default")=="today" else (today + timedelta(days=1) if q.get("default")=="tomorrow" else today)
        val = answers.get(k, default)
        answers[k] = st.date_input(label, value=val, help=help_txt)
    else:
        st.warning(f"Tipe pertanyaan belum didukung: {t}")

def build_S(stage, case_name, a):
    # Subjective templates by stage
    if stage in ["POD0","POD1"]:
        sents = []
        if not a.get("pain_present"):
            sents.append("Tidak ada keluhan nyeri pada daerah operasi.")
        else:
            loc = clean(a.get("pain_location","daerah operasi"))
            sc = a.get("pain_score",0)
            sents.append(f"Ada keluhan nyeri pada {loc} dengan skala VAS {sc}/10.")
        if not a.get("numb_present"):
            sents.append("Tidak ada keluhan tebal dan kebas.")
        else:
            loc = clean(a.get("numb_location","daerah operasi"))
            sents.append(f"Ada keluhan tebal dan kebas pada {loc}.")
        if stage=="POD0":
            # pusing/mual/muntah
            flags = []
            if a.get("dizzy"): flags.append("pusing")
            if a.get("nausea"): flags.append("mual")
            if a.get("vomit"): flags.append("muntah")
            if flags:
                sents.append("Ada keluhan " + ", ".join(flags) + ".")
            else:
                sents.append("Tidak ada keluhan pusing, mual, dan muntah.")
        # makan-minum & istirahat
        ed = a.get("eat_drink","baik")
        if ed=="baik":
            sents.append("Pasien makan dan minum dengan baik.")
        elif ed=="kurang":
            sents.append("Pasien makan dan minum namun masih kurang.")
        else:
            sents.append("Pasien belum makan dan minum.")
        if a.get("rest","cukup")=="cukup":
            sents.append("Istirahat dirasa cukup." if stage=="POD0" else "Istirahat malam dirasa cukup.")
        else:
            sents.append("Istirahat dirasa kurang." if stage=="POD0" else "Istirahat malam dirasa kurang.")
        return " ".join(sents)

    if stage=="Awal":
        if case_name=="Impaksi":
            kel = clean(a.get("keluhan",""))
            dur = clean(a.get("durasi",""))
            gigi = clean(a.get("gigi_list",""))
            menjalar = a.get("menjalar", False)
            menjalar_ke = clean(a.get("menjalar_ke",""))
            s = f"Pasien datang dengan keluhan {kel} sejak ± {dur}."
            if menjalar:
                s += f" Keluhan nyeri menjalar hingga ke {menjalar_ke}."
            if gigi:
                s += f" Gigi terkait: {gigi}."
            # sistemik
            if not a.get("alergi", False):
                s += " Tidak ada riwayat alergi obat dan makanan."
            else:
                s += " Ada riwayat alergi obat dan/atau makanan."
            if a.get("sistemik", True):
                s += " Riwayat penyakit sistemik disangkal."
            if not a.get("batuk_flu_demam", False):
                s += " Pasien tidak dalam keadaan batuk, flu dan demam."
            else:
                s += " Pasien sedang batuk/flu/demam."
            return s

        if case_name in ["Abses","Selulitis"]:
            loc = clean(a.get("lokasi_bengkak",""))
            dur = clean(a.get("durasi",""))
            s = f"Pasien datang dengan keluhan pembengkakan pada {loc}"
            if a.get("nyeri", True):
                s += " disertai rasa nyeri"
            s += f" sejak ± {dur}."
            # red flags
            rf = []
            if a.get("trismus"): rf.append("trismus (+)")
            if a.get("hoarseness"): rf.append("hoarseness (+)")
            if a.get("hot_potato"): rf.append("hot potato voice (+)")
            if a.get("neck_stiff"): rf.append("neck stiffness (+)")
            if a.get("difficult_swallow"): rf.append("difficult on swallowing (+)")
            if a.get("pain_swallow"): rf.append("pain on swallowing (+)")
            if rf:
                s += " Riwayat " + ", ".join(rf) + "."
                if a.get("trismus"):
                    s += f" Bukaan mulut ± {a.get('bukaan_mulut_mm',10)} mm."
            if a.get("demam"): s += " Ada riwayat demam."
            else: s += " Tidak ada riwayat demam."
            if not a.get("alergi", False):
                s += " Tidak ada riwayat alergi obat dan makanan."
            else:
                s += " Ada riwayat alergi obat dan/atau makanan."
            if a.get("sistemik", True):
                s += " Riwayat penyakit sistemik disangkal."
            if not a.get("batuk_flu", False):
                s += " Pasien tidak sedang batuk dan flu."
            else:
                s += " Pasien sedang batuk/flu."
            return s

        if case_name=="TMD":
            dur=clean(a.get("durasi",""))
            s=(f"Pasien datang dengan keluhan nyeri pada daerah sendi rahang {a.get('nyeri_tmj','')} "
               f"pada saat {clean(a.get('pencetus','mengunyah'))} sejak ± {dur}.")
            if a.get("klik"): s += " Terdapat clicking (+)."
            if a.get("popping"): s += " Terdapat popping (+)."
            if a.get("deviasi"): s += f" Terdapat deviasi mandibula (+) ke arah {clean(a.get('deviasi_ke',''))}."
            s += f" Bukaan mulut ± {a.get('bukaan_mm',35)} mm."
            if not a.get("alergi", False): s += " Tidak ada riwayat alergi obat dan makanan."
            else: s += " Ada riwayat alergi obat dan/atau makanan."
            if a.get("sistemik", True): s += " Riwayat penyakit sistemik disangkal."
            if not a.get("batuk_flu_demam", False): s += " Saat ini pasien tidak dalam kondisi demam, flu dan batuk."
            else: s += " Saat ini pasien dalam kondisi demam/flu/batuk."
            return s

        if case_name=="Fraktur":
            s = f"Pasien datang dengan keluhan {clean(a.get('keluhan',''))} sejak ± {clean(a.get('durasi',''))}."
            s += f" Kronologis kejadian: {clean(a.get('mekanisme',''))}."
            s += f" Riwayat pingsan ({'-' if not a.get('pingsan') else '+'}), muntah ({'-' if not a.get('muntah') else '+'})."
            s += f" Perdarahan lewat hidung ({'-' if not a.get('perdarahan_hidung') else '+'}), lewat telinga ({'-' if not a.get('perdarahan_telinga') else '+'}), dari mulut ({'-' if not a.get('perdarahan_mulut') else '+'})."
            if not a.get("alergi", False): s += " Tidak ada riwayat alergi obat dan makanan."
            else: s += " Ada riwayat alergi obat dan/atau makanan."
            if a.get("sistemik", True): s += " Riwayat penyakit sistemik disangkal."
            if not a.get("batuk_flu_demam", False): s += " Saat ini pasien tidak sedang batuk, flu, demam, dan diare."
            else: s += " Saat ini pasien sedang batuk/flu/demam."
            return s

        # fallback
        kel = clean(a.get("keluhan",""))
        dur = clean(a.get("durasi",""))
        s = f"Pasien datang dengan keluhan {kel} sejak ± {dur}."
        return s

    return ""

def build_O_local(stage, a):
    if stage not in ["POD0","POD1"]:
        return ""
    lines=[]
    sw=a.get("swelling","ada")
    if sw!="tidak ada":
        lines.append(f"- Wajah asimetris dengan oedem ar {clean(a.get('swelling_location',''))}")
    else:
        lines.append("- Wajah simetris")
    # IO
    suture = "intak" if a.get("suture_intact", True) else "tidak intak"
    hyp = "(+)" if a.get("hyperemia", True) else "(-)"
    bc = a.get("blood_clot","(-)")
    ab = "(+)" if a.get("active_bleeding", False) else "(-)"
    io = f"- Jahitan {suture} ar daerah operasi dengan hiperemis {hyp}, blood clot {bc}, active bleeding {ab}"
    return "\n".join(lines), io

def build_preop_plan(a, bb_value):
    plan=[]
    # ACC always
    plan.append("ACC TS Anestesi")
    # IVFD suggestion
    if a.get("ivfd_on", True):
        cairan = clean(a.get("ivfd_cairan","RL")) or "RL"
        drip = int(a.get("drip_factor",20))
        tpm = int(a.get("ivfd_tpm",0) or 0)
        if tpm <= 0 and bb_value > 0:
            mlhr = maintenance_ml_per_hr_421(bb_value)
            tpm = tpm_from_ml_per_hr(mlhr, drip)
        drip_label = "makrodrips" if drip==20 else "mikrodrips"
        plan.append(f"IVFD {cairan} {tpm} tpm ({drip_label})" if tpm>0 else f"IVFD {cairan} (isi tpm) ({drip_label})")

    jam = clean(a.get("jam_operasi","08.00"))
    zona = clean(a.get("zona_waktu","WITA"))
    op = parse_hhmm(jam)
    if op:
        ph, pm = minus_minutes(op[0], op[1], 6*60)
        ah, am = minus_minutes(op[0], op[1], 60)
        puasa_jam = fmt_time(ph, pm)
        ab_jam = fmt_time(ah, am)
    else:
        puasa_jam = ""
        ab_jam = ""
    if a.get("puasa_on", True):
        plan.append(f"Puasa 6 jam pre op atau sesuai instruksi dari TS. Anestesi yaitu mulai Pukul {puasa_jam or '(isi)'} {zona}")
    if a.get("sikat_gigi", True):
        plan.append("Pasien menyikat gigi sebelum tidur dan sebelum ke kamar operasi")
    if a.get("masker", True):
        plan.append("Gunakan masker bedah saat ke kamar operasi")
    if a.get("washlap", False):
        plan.append("Washlap badan dan wajah pasien sebelum masuk ke kamar operasi")
    if a.get("siap_prc", False):
        plan.append("Siap darah 1 bag PRC")
    if a.get("ab_on", True):
        ab = " ".join([clean(a.get("ab_nama","")), clean(a.get("ab_dosis",""))]).strip() or "(isi antibiotik)"
        skin = " (skin test terlebih dahulu)" if a.get("ab_skin_test", True) else ""
        plan.append(f"Pasien rencana diberikan antibiotik profilaksis {ab}, 1 jam sebelum operasi{skin} pada Pukul {ab_jam or '(isi)'} {zona}")
    return plan

def build_header(stage, laporan_date: date, info: ParsedInfo, tindakan="", op_day=None):
    hari = day_name_id(laporan_date)
    if stage=="PreOp":
        return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rencana Operasi {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"
    elif stage=="Awal":
        return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien {info.perawatan or 'Rawat Jalan'} {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"
    else:
        tag = "POD 0" if stage=="POD0" else "POD I"
        t = tindakan or info.tindakan
        extra = f" *{tag} {t}*" if t else f" *{tag}*"
        return f"Assalamualaikum dokter,\nMaaf mengganggu, izin melaporkan Pasien Rawat Inap {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n{extra}\n"

def build_ident_line(info: ParsedInfo, pembiayaan_override=""):
    pemb = pembiayaan_override or info.pembiayaan or "BPJS"
    per = info.perawatan or "Rawat Inap"
    kamar = f" / {info.kamar}" if info.kamar else ""
    rm = f"RM {info.rm}" if info.rm else "RM -"
    return f"{info.nama} / {info.jk} / {info.umur} / {pemb} / {per}{kamar} / {info.rs} / {rm}\n"

# -------------------------
# Streamlit App
# -------------------------
st.set_page_config(page_title="SuperSOAP RSGMP", layout="centered")
st.title("🧩 SuperSOAP Maker (Awal → Pre-Op → POD0 → POD1)")

schema_path = st.sidebar.text_input("Schema file", value="supersoap_schema_v1.json")
tutorial = st.sidebar.toggle("Tutorial mode", value=True)

try:
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
except Exception as e:
    st.error(f"Gagal baca schema: {e}")
    st.stop()

case_names = list(schema["cases"].keys())
stage_names = schema["stages"]

c1, c2 = st.columns(2)
with c1:
    case = st.selectbox("Kasus", case_names, index=0)
with c2:
    stage = st.selectbox("Stage", stage_names, index=0)

# Laporan operasi widget
st.sidebar.divider()
if st.sidebar.button("🧾 GET LAPORAN OPERASI", use_container_width=True):
    lo = schema.get("laporan_operasi", {}).get(case)
    if lo:
        st.sidebar.text_area(f"Laporan Operasi — {case}", value=lo, height=320)
    else:
        st.sidebar.info("Belum ada laporan operasi untuk kasus ini di schema.")

st.divider()

if tutorial:
    st.info("Alur cepat: 1) Paste SOAP mentah &/atau Minlap → 2) Isi pertanyaan → 3) Output siap copy.")

tabA, tabB, tabC = st.tabs(["1) Paste", "2) Form", "3) Output"])

# Session storage
if "answers" not in st.session_state:
    st.session_state["answers"] = {}
if "parsed" not in st.session_state:
    st.session_state["parsed"] = ParsedInfo()

with tabA:
    st.subheader("Paste (opsional tapi bikin cepat)")
    raw = st.text_area("SOAP mentah (kalau ada)", height=220, placeholder="Paste SOAP awal terjaring / POD / apa saja.")
    minlap = st.text_area("MINLAP (kalau ada) — formatnya dipertahankan", height=220, placeholder="Paste Minlap di sini.")

    if st.button("Auto-fill dari paste", type="primary", use_container_width=True):
        parsed = ParsedInfo()
        if raw.strip():
            pr = parse_rawsoap(raw)
            parsed.__dict__.update({k:v for k,v in pr.__dict__.items() if v})
        if minlap.strip():
            pm = parse_minlap(minlap)
            # Minlap lebih dipercaya untuk jam/penujang
            for k,v in pm.__dict__.items():
                if v:
                    setattr(parsed, k, v)
        st.session_state["parsed"] = parsed

        # prefill answers that match schema keys
        a = st.session_state["answers"]
        if parsed.tindakan and "tindakan" in [q["key"] for q in schema["cases"][case]["stage"]["PreOp"]["questions"]]:
            a["tindakan"] = parsed.tindakan
        if parsed.anestesi:
            a["anestesi"] = parsed.anestesi
        if parsed.jam_operasi:
            a["jam_operasi"] = parsed.jam_operasi
        if parsed.zona:
            a["zona_waktu"] = parsed.zona

        # Suggest IVFD tpm if bb available
        if parsed.bb and parsed.bb > 0:
            # keep; computed later
            pass

        # if stage is PreOp, we want penunjang raw from minlap
        st.success("Auto-fill selesai. Lanjut ke tab 2) Form.")

    parsed = st.session_state["parsed"]
    with st.expander("Lihat hasil auto-fill"):
        st.write(parsed)

with tabB:
    parsed = st.session_state["parsed"]
    st.subheader("Identitas (cepat)")
    nama = st.text_input("Nama (Tn./Ny./Nn./An.)", value=parsed.nama)
    jk = st.text_input("JK", value=parsed.jk)
    umur = st.text_input("Umur", value=parsed.umur)
    pembiayaan = st.text_input("Pembiayaan", value=parsed.pembiayaan or "BPJS")
    perawatan_default = "Rawat Inap" if stage in ["PreOp","POD0","POD1"] else (parsed.perawatan or "Rawat Jalan")
    perawatan = st.text_input("Jenis Perawatan", value=perawatan_default)
    kamar = st.text_input("Kamar/Bed (opsional)", value=parsed.kamar)
    rm = st.text_input("RM", value=parsed.rm)
    rs = st.text_input("RS", value=parsed.rs or "RSGMP UNHAS")

    bb = st.number_input("BB (kg) — untuk saran IVFD", min_value=0.0, max_value=250.0, value=float(parsed.bb or 0.0), step=0.1)
    tb = st.number_input("TB (cm)", min_value=0.0, max_value=250.0, value=float(parsed.tb or 0.0), step=0.1)

    st.divider()
    st.subheader(f"Form — {case} / {stage}")
    answers = st.session_state["answers"]
    # inject some defaults for PreOp date fields
    for q in schema["cases"][case]["stage"][stage]["questions"]:
        if q["type"]=="date":
            if q["default"]=="today" and q["key"] not in answers:
                answers[q["key"]] = datetime.now(TZ).date()
            if q["default"]=="tomorrow" and q["key"] not in answers:
                answers[q["key"]] = datetime.now(TZ).date() + timedelta(days=1)
    # render questions
    for q in schema["cases"][case]["stage"][stage]["questions"]:
        if should_show(q, answers):
            # prefill from parsed for some keys
            if q["key"]=="tindakan" and not answers.get("tindakan") and parsed.tindakan:
                answers["tindakan"] = parsed.tindakan
            if q["key"]=="jam_operasi" and not answers.get("jam_operasi") and parsed.jam_operasi:
                answers["jam_operasi"] = parsed.jam_operasi
            if q["key"]=="zona_waktu" and not answers.get("zona_waktu") and parsed.zona:
                answers["zona_waktu"] = parsed.zona
            # suggested tpm
            if q["key"]=="ivfd_tpm" and (not answers.get("ivfd_tpm")) and bb>0:
                drip = int(answers.get("drip_factor", q.get("default",20)))
                mlhr = maintenance_ml_per_hr_421(bb)
                answers["ivfd_tpm"] = tpm_from_ml_per_hr(mlhr, drip)
            render_question(q, answers, tutorial=tutorial)

    st.divider()
    st.subheader("DPJP & Residen")
    dpjp = st.text_input("DPJP", value=parsed.dpjp)
    residen = st.text_area("Residen (bebas, nanti copy aja)", value=parsed.residen, height=80)

    st.session_state["answers"] = answers
    st.session_state["parsed"] = ParsedInfo(
        nama=nama, jk=jk, umur=umur, pembiayaan=pembiayaan, perawatan=perawatan, kamar=kamar, rs=rs, rm=rm,
        bb=bb, tb=tb, tindakan=parsed.tindakan, anestesi=parsed.anestesi, penunjang_raw=parsed.penunjang_raw,
        jam_operasi=parsed.jam_operasi, zona=parsed.zona, dpjp=dpjp, residen=residen
    )

with tabC:
    parsed = st.session_state["parsed"]
    a = st.session_state["answers"]

    # Determine dates
    laporan_date = datetime.now(TZ).date()
    if stage=="PreOp":
        laporan_date = a.get("tanggal_laporan", laporan_date)
    if stage=="PreOp":
        op_date = a.get("tanggal_operasi", laporan_date + timedelta(days=1))
        jam = clean(a.get("jam_operasi","08.00"))
        zona = clean(a.get("zona_waktu","WITA"))
        tindakan = clean(a.get("tindakan","")) or parsed.tindakan
        anestesi = clean(a.get("anestesi","general anestesi"))
    else:
        tindakan = parsed.tindakan
        anestesi = parsed.anestesi

    header = build_header(stage, laporan_date, parsed, tindakan=tindakan)
    ident = build_ident_line(parsed, pembiayaan_override=parsed.pembiayaan)

    S = build_S(stage, case, a)

    # O (minimal)
    O = ""
    if stage in ["POD0","POD1"]:
        eo, io = build_O_local(stage, a)
        vas = a.get("pain_score",0) if a.get("pain_present") else 0
        O = (
            "O :\n"
            "Status Generalis:\n"
            f"KU : Baik/Compos Mentis\nSpO2 : 99% (Free Air)\nVAS : {vas}/10\n\n"
            "Status Lokalis:\nE.O:\n" + eo + "\n\nI.O:\n" + io + "\n"
        )
    else:
        O = "O:\n(Status generalis & lokalis isi/paste sesuai kebutuhan)\n"

    # Penunjang (pakai mentah dari minlap kalau ada)
    penunjang_text = ""
    if stage=="PreOp" and parsed.penunjang_raw:
        penunjang_text = parsed.penunjang_raw + "\n\n"

    # A
    A = "A:\n(isi diagnosis)\n\n"

    # P
    P = ""
    if stage=="PreOp":
        plan = build_preop_plan(a, parsed.bb)
        plan_lines = "\n".join([f"•⁠  ⁠{x}" for x in plan if clean(x)])
        tindakan_line = clean(a.get("tindakan","")) or "(isi tindakan)"
        anestesi_line = clean(a.get("anestesi","general anestesi"))
        op_day = day_name_id(op_date)
        P = (
            "P:\n"
            + plan_lines + "\n"
            + f"•⁠  ⁠Pro {tindakan_line} dalam {anestesi_line} pada hari {op_day}, {fmt_ddmmyyyy(op_date)} "
              f"Pukul {jam} {zona} di {parsed.rs}\n\n"
        )
    else:
        P = "P:\n(isi plan)\n\n"

    footer = (
        "Mohon instruksi selanjutnya dokter.\n"
        "Terima kasih.\n\n"
        f"Residen: {clean(parsed.residen) or '-'}\n\n"
        f"DPJP: {clean(parsed.dpjp) or '-'}\n"
    )

    output = header + "\n" + ident + "\n" + "S : " + S + "\n\n" + O + "\n" + (penunjang_text if penunjang_text else "") + A + P + footer

    st.subheader("Output (siap copy)")
    st.text_area("SOAP", value=output, height=520)
    st.download_button("Download .txt", data=output.encode("utf-8"), file_name=f"soap_{case}_{stage}.txt", mime="text/plain", use_container_width=True)
