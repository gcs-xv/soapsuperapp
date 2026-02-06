
import re
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from dateutil import tz
import streamlit as st

TZ = tz.gettz("Asia/Makassar")
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
    # MUST preserve formatting
    return text.strip("\n")

# -------------------------
# Minimal parsers (ONLY for PreOp)
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
    m = re.search(r"^(Tn\.|Ny\.|Nn\.|An\.)[^\n]+", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    ident = m.group(0).strip()
    parts = [p.strip() for p in ident.split("/") if p.strip()]
    return parts

def extract_tindakan_from_P(raw: str) -> tuple[str,str]:
    m = re.search(r"\n\s*P\s*:\s*(.*)$", raw, re.IGNORECASE | re.DOTALL)
    if not m:
        return "", ""
    pblock = m.group(1)
    lines = [ln.strip() for ln in pblock.splitlines() if ln.strip()]
    pro_lines = [ln for ln in lines if re.search(r"\bPro\b", ln, re.IGNORECASE)]
    if not pro_lines:
        return "", ""
    last = pro_lines[-1]
    m2 = re.search(r"\bPro\b\s*(.+?)(?:\s+dalam\s+([^.]+?))?(?:\(|$|\.)", last, re.IGNORECASE)
    if not m2:
        return "", ""
    tindakan = clean(m2.group(1))
    anestesi = clean(m2.group(2)) if m2.group(2) else ""
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
        for x in parts:
            if "rawat" in x.lower():
                p.perawatan = x
        for x in parts:
            if x.upper() in ["BPJS", "UMUM", "JASA RAHARJA", "BAKSOS", "BAKSOS CCC", "CCC"]:
                p.pembiayaan = x
        mrm = re.search(r"RM\.?\s*([0-9.]+)", t, re.IGNORECASE)
        if mrm: p.rm = mrm.group(1).strip()
    p.bb, p.tb = parse_bb_tb(t)
    mpen = re.search(r"Pemeriksaan\s+penunjang\s*:\s*(.*?)(?:\n\s*A\s*:|\n\s*A\s*：|\n\s*A\s*\n|$)", t, re.IGNORECASE | re.DOTALL)
    if mpen:
        block = "Pemeriksaan penunjang :\n" + mpen.group(1).rstrip()
        p.penunjang_raw = normalize_minlap_block(block)
    mt = re.search(r"\n\s*P\s*:\s*(.+)", t, re.IGNORECASE)
    if mt:
        tindakan_line = mt.group(1).strip()
        tindakan_line = re.sub(r"^\W*\bPro\b\s*", "", tindakan_line, flags=re.IGNORECASE).strip()
        tindakan_line = re.sub(r"\s+dalam\s+.*$", "", tindakan_line, flags=re.IGNORECASE).strip()
        p.tindakan = tindakan_line
    mj = re.search(r"Pukul\s*:\s*\*?([0-9]{1,2}\.[0-9]{2})\s*([A-Z]{3,4})\*?", t, re.IGNORECASE)
    if mj:
        p.jam_operasi = mj.group(1)
        p.zona = mj.group(2).upper()
    md = re.search(r"DPJP\s*:\s*(.+)", t, re.IGNORECASE)
    if md:
        p.dpjp = md.group(1).strip()
    mr = re.search(r"Residen\s*:\s*(.*?)(?:\n\s*DPJP\s*:|$)", t, re.IGNORECASE | re.DOTALL)
    if mr:
        p.residen = mr.group(1).strip()
    return p

def parse_rawsoap_preop(raw: str) -> ParsedInfo:
    p = ParsedInfo()
    t = raw.strip()
    if not t:
        return p
    parts = parse_identity_line(t)
    if parts:
        p.nama = parts[0]
        if len(parts) > 1: p.jk = parts[1]
        if len(parts) > 2: p.umur = parts[2]
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
# Schema-driven UI
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

# -------------------------
# Generators (simple but coherent)
# -------------------------
def build_header(stage, laporan_date: date, info: ParsedInfo):
    hari = day_name_id(laporan_date)
    if stage=="PreOp":
        return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rencana Operasi {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"
    if stage=="Awal":
        return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Jalan {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"
    if stage=="POD0":
        return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Inap {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"
    return f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Inap {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n"

def build_ident_line(info: ParsedInfo, perawatan_override=""):
    pemb = info.pembiayaan or "BPJS"
    per = perawatan_override or info.perawatan or "Rawat Jalan"
    kamar = f" / {info.kamar}" if info.kamar else ""
    rm = f"RM {info.rm}" if info.rm else "RM -"
    return f"{info.nama} / {info.jk} / {info.umur} / {pemb} / {per}{kamar} / {info.rs} / {rm}\n"

def build_awal_S(case, a):
    # Short, first-visit oriented
    if case=="Impaksi":
        kel = clean(a.get("keluhan","gigi tidak tumbuh"))
        dur = clean(a.get("durasi",""))
        s = f"Pasien datang dengan keluhan {kel}"
        if dur: s += f" sejak ± {dur}."
        else: s += "."
        if a.get("menjalar", False):
            s += f" Nyeri menjalar hingga ke {clean(a.get('menjalar_ke','kepala'))}."
        if not a.get("alergi", False):
            s += " Tidak ada riwayat alergi obat dan makanan."
        if a.get("sistemik", True):
            s += " Riwayat penyakit sistemik disangkal."
        if not a.get("batuk_flu_demam", False):
            s += " Pasien tidak dalam keadaan batuk, flu dan demam."
        return s

    if case in ["Abses","Selulitis"]:
        loc = clean(a.get("lokasi_bengkak",""))
        dur = clean(a.get("durasi",""))
        s = f"Pasien datang dengan keluhan pembengkakan pada {loc}"
        if a.get("nyeri", True):
            s += " disertai rasa nyeri"
        if dur: s += f" sejak ± {dur}."
        else: s += "."
        return s

    # fallback
    kel = clean(a.get("keluhan",""))
    dur = clean(a.get("durasi",""))
    return f"Pasien datang dengan keluhan {kel} sejak ± {dur}."

def build_TTV(a):
    # Standard TTV block builder from answers
    td = clean(a.get("td","-/-"))
    n = clean(a.get("n","-"))
    p = clean(a.get("p","-"))
    s = clean(a.get("s","-"))
    spo2 = clean(a.get("spo2","99"))
    ku = clean(a.get("ku","Baik/Compos Mentis"))
    bb = clean(a.get("bb",""))
    tb = clean(a.get("tb",""))
    lines = [
        f"KU : {ku}",
        f"TD : {td} mmHg",
        f"N   : {n} x/menit",
        f"P   : {p} x/menit",
        f"S   : {s} °C",
        f"SpO2: {spo2}% (free air)",
    ]
    if bb: lines.append(f"BB : {bb} kg")
    if tb: lines.append(f"TB : {tb} cm")
    return "\n".join(lines)

def build_preop_plan(a, bb_value):
    plan=[]
    plan.append("Acc TS Anestesi")
    # IVFD
    if a.get("ivfd_on", True):
        cairan = clean(a.get("ivfd_cairan","RL")) or "RL"
        drip = int(a.get("drip_factor",20))
        tpm = int(a.get("ivfd_tpm",0) or 0)
        if tpm <= 0 and bb_value > 0:
            mlhr = maintenance_ml_per_hr_421(bb_value)
            tpm = tpm_from_ml_per_hr(mlhr, drip)
        drip_label = "makrodrips" if drip==20 else "mikrodrips"
        plan.append(f"IVFD {cairan} {tpm} tpm ({drip_label})" if tpm>0 else f"IVFD {cairan} (isi tpm) ({drip_label})")
    # times
    jam = clean(a.get("jam_operasi","08.00"))
    zona = clean(a.get("zona_waktu","WITA"))
    op = parse_hhmm(jam)
    puasa_jam = "(isi)"
    ab_jam = "(isi)"
    if op:
        ph, pm = minus_minutes(op[0], op[1], 6*60)
        ah, am = minus_minutes(op[0], op[1], 60)
        puasa_jam = fmt_time(ph, pm)
        ab_jam = fmt_time(ah, am)
    if a.get("puasa_on", True):
        plan.append(f"Puasa 6 jam pre op atau sesuai instruksi dari TS. Anestesi yaitu mulai Pukul {puasa_jam} {zona}")
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
        plan.append(f"Pasien rencana diberikan antibiotik profilaksis {ab}, 1 jam sebelum operasi{skin} pada Pukul {ab_jam} {zona}")
    return plan

def build_pod_S(stage, a):
    # POD0/1 standardized questions → standardized sentences
    sents=[]
    if not a.get("pain_present"):
        sents.append("Tidak ada keluhan nyeri pada daerah operasi.")
    else:
        loc = clean(a.get("pain_location","daerah operasi"))
        sc = a.get("pain_score",0)
        sents.append(f"Ada keluhan nyeri pada {loc} dengan skala VAS {sc}/10.")
    if stage=="POD0":
        flags=[]
        if a.get("dizzy"): flags.append("pusing")
        if a.get("nausea"): flags.append("mual")
        if a.get("vomit"): flags.append("muntah")
        if flags:
            sents.append("Ada keluhan " + ", ".join(flags) + ".")
        else:
            sents.append("Tidak ada keluhan pusing, mual, dan muntah.")
    ed = a.get("eat_drink","baik")
    if ed=="baik": sents.append("Pasien makan dan minum dengan baik.")
    elif ed=="kurang": sents.append("Pasien makan dan minum namun masih kurang.")
    else: sents.append("Pasien belum makan dan minum.")
    if a.get("rest","cukup")=="cukup": sents.append("Istirahat dirasa cukup." if stage=="POD0" else "Istirahat malam dirasa cukup.")
    else: sents.append("Istirahat dirasa kurang." if stage=="POD0" else "Istirahat malam dirasa kurang.")
    return " ".join(sents)

def build_pod_O(a):
    # minimal O local for PODs (editable later)
    sw=a.get("swelling","ada")
    eo = "- Wajah simetris" if sw=="tidak ada" else f"- Wajah asimetris dengan oedem ar {clean(a.get('swelling_location',''))}"
    suture = "intak" if a.get("suture_intact", True) else "tidak intak"
    hyp = "(+)" if a.get("hyperemia", True) else "(-)"
    bc = a.get("blood_clot","(-)")
    ab = "(+)" if a.get("active_bleeding", False) else "(-)"
    io = f"- Jahitan {suture} ar daerah operasi dengan hiperemis {hyp}, blood clot {bc}, active bleeding {ab}"
    return eo, io

# -------------------------
# Streamlit App
# -------------------------
st.set_page_config(page_title="SuperSOAP RSGMP", layout="centered")
st.title("🧩 SuperSOAP Maker (Awal → Pre-Op → POD0 → POD1)")

schema_path = st.sidebar.text_input("Schema file", value="supersoap_schema_v2.json")
tutorial = st.sidebar.toggle("Tutorial mode", value=True)

try:
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
except Exception as e:
    st.error(f"Gagal baca schema: {e}")
    st.stop()

case_names = list(schema["cases"].keys())
stage_names = schema["stages"]
stage_rules = schema.get("stage_rules", {})

c1, c2 = st.columns(2)
with c1:
    case = st.selectbox("Kasus", case_names, index=0)
with c2:
    stage = st.selectbox("Stage", stage_names, index=0)

# Laporan operasi (terpisah)
st.sidebar.divider()
if st.sidebar.button("🧾 GET LAPORAN OPERASI", use_container_width=True):
    lo = schema.get("laporan_operasi", {}).get(case)
    if lo:
        st.sidebar.text_area(f"Laporan Operasi — {case}", value=lo, height=320)
    else:
        st.sidebar.info("Belum ada laporan operasi untuk kasus ini di schema.")

st.divider()
if tutorial:
    if stage=="PreOp":
        st.info("Pre-Op: paste SOAP poli + MINLAP (kalau ada) → Auto-fill → isi antibiotik/IVFD → Output.")
    elif stage=="Awal":
        st.info("Awal: pasien baru datang. Tidak perlu paste. Cukup isi form pertanyaan + TTV + pemeriksaan lokal.")
    else:
        st.info(f"{stage}: evaluasi pasca operasi. Tidak perlu paste/minlap. Cukup checklist keluhan & luka.")

# Session state
if "answers" not in st.session_state:
    st.session_state["answers"] = {}
if "info" not in st.session_state:
    st.session_state["info"] = ParsedInfo()

tab1, tab2, tab3 = st.tabs(["1) Input", "2) Form", "3) Output"])

# -------------------------
# TAB 1: Input (ONLY PreOp)
# -------------------------
with tab1:
    rules = stage_rules.get(stage, {"allow_paste": False, "allow_minlap": False})
    if not rules.get("allow_paste") and not rules.get("allow_minlap"):
        st.success("Untuk stage ini tidak perlu paste apa pun ✅")
    else:
        st.subheader("Paste khusus Pre-Op")
        raw = st.text_area("SOAP mentah (SOAP poli/awal terjaring) — opsional", height=220)
        minlap = st.text_area("MINLAP — rekomendasi (format dipertahankan)", height=260)

        if st.button("Auto-fill dari paste", type="primary", use_container_width=True):
            parsed = ParsedInfo()
            if raw.strip():
                pr = parse_rawsoap_preop(raw)
                for k,v in pr.__dict__.items():
                    if v:
                        setattr(parsed, k, v)
            if minlap.strip():
                pm = parse_minlap(minlap)
                for k,v in pm.__dict__.items():
                    if v:
                        setattr(parsed, k, v)

            st.session_state["info"] = parsed
            # prefill common answer keys
            a = st.session_state["answers"]
            if parsed.tindakan: a["tindakan"] = parsed.tindakan
            if parsed.anestesi: a["anestesi"] = parsed.anestesi
            if parsed.jam_operasi: a["jam_operasi"] = parsed.jam_operasi
            if parsed.zona: a["zona_waktu"] = parsed.zona
            st.session_state["answers"] = a
            st.success("Auto-fill selesai. Lanjut ke tab 2) Form.")

        with st.expander("Preview hasil auto-fill"):
            st.write(st.session_state["info"])

# -------------------------
# TAB 2: Form
# -------------------------
with tab2:
    info = st.session_state["info"]
    a = st.session_state["answers"]

    st.subheader("Identitas")
    nama = st.text_input("Nama (Tn./Ny./Nn./An.)", value=info.nama)
    jk = st.text_input("JK", value=info.jk)
    umur = st.text_input("Umur", value=info.umur)
    pembiayaan = st.text_input("Pembiayaan", value=info.pembiayaan or "BPJS")
    if stage=="PreOp":
        perawatan_default = "Rawat Inap"
    elif stage in ["POD0","POD1"]:
        perawatan_default = "Rawat Inap"
    else:
        perawatan_default = "Rawat Jalan"
    perawatan = st.text_input("Jenis Perawatan", value=info.perawatan or perawatan_default)
    kamar = st.text_input("Kamar/Bed (opsional)", value=info.kamar)
    rm = st.text_input("RM", value=info.rm)
    rs = st.text_input("RS", value=info.rs or "RSGMP UNHAS")

    bb = st.number_input("BB (kg)", min_value=0.0, max_value=250.0, value=float(info.bb or 0.0), step=0.1)
    tb = st.number_input("TB (cm)", min_value=0.0, max_value=250.0, value=float(info.tb or 0.0), step=0.1)

    st.divider()

    # TTV for Awal/PODs (PreOp typically already has it, but we can keep optional)
    if stage in ["Awal","POD0","POD1"]:
        st.subheader("TTV (isi cepat)")
        a["ku"] = st.text_input("KU", value=a.get("ku","Baik/Compos Mentis"))
        a["td"] = st.text_input("TD", value=a.get("td","-/-"))
        a["n"]  = st.text_input("N", value=a.get("n","-"))
        a["p"]  = st.text_input("P", value=a.get("p","-"))
        a["s"]  = st.text_input("S", value=a.get("s","36.7"))
        a["spo2"] = st.text_input("SpO2", value=a.get("spo2","99"))
        a["bb"] = str(bb) if bb else a.get("bb","")
        a["tb"] = str(tb) if tb else a.get("tb","")

        st.subheader("Pemeriksaan lokal (ringkas)")
        a["eo_text"] = st.text_area("EO (1–3 poin)", value=a.get("eo_text",""), height=90, placeholder="Contoh: Wajah simetris, bukaan mulut normal")
        a["io_text"] = st.text_area("IO (1–5 poin)", value=a.get("io_text",""), height=120, placeholder="Contoh: Unerupted 38, kalkulus (+), OH sedang")

    st.divider()
    st.subheader(f"Form kasus — {case} ({stage})")

    # Render case-stage questions
    stage_questions = schema["cases"][case]["stage"][stage]["questions"]
    # Inject defaults for dates in PreOp
    if stage=="PreOp":
        for q in stage_questions:
            if q["type"]=="date" and q["key"] not in a:
                today = datetime.now(TZ).date()
                a[q["key"]] = today if q.get("default")=="today" else (today + timedelta(days=1))

    for q in stage_questions:
        if should_show(q, a):
            # Suggested tpm from BB
            if q["key"]=="ivfd_tpm" and (not a.get("ivfd_tpm")) and bb>0:
                drip = int(a.get("drip_factor", q.get("default",20)))
                mlhr = maintenance_ml_per_hr_421(bb)
                a["ivfd_tpm"] = tpm_from_ml_per_hr(mlhr, drip)
            render_question(q, a, tutorial=tutorial)

    st.divider()
    st.subheader("DPJP & Residen")
    dpjp = st.text_input("DPJP", value=info.dpjp)
    residen = st.text_area("Residen", value=info.residen, height=80)

    st.session_state["answers"] = a
    st.session_state["info"] = ParsedInfo(
        nama=nama, jk=jk, umur=umur, pembiayaan=pembiayaan, perawatan=perawatan, kamar=kamar, rs=rs, rm=rm,
        bb=bb, tb=tb, tindakan=info.tindakan, anestesi=info.anestesi, penunjang_raw=info.penunjang_raw,
        jam_operasi=info.jam_operasi, zona=info.zona, dpjp=dpjp, residen=residen
    )

# -------------------------
# TAB 3: Output
# -------------------------
with tab3:
    info = st.session_state["info"]
    a = st.session_state["answers"]

    laporan_date = datetime.now(TZ).date()
    if stage=="PreOp":
        laporan_date = a.get("tanggal_laporan", laporan_date)

    header = build_header(stage, laporan_date, info)
    ident = build_ident_line(info, perawatan_override=info.perawatan)

    # S
    if stage=="Awal":
        S = build_awal_S(case, a)
    elif stage in ["POD0","POD1"]:
        S = build_pod_S(stage, a)
    else:
        # PreOp S is usually from raw SOAP; for MVP we let user paste later (next iteration)
        S = "Pasien rencana tindakan dalam general anestesi. (isi S dari SOAP poli atau ringkas manual)."

    # O
    if stage=="Awal":
        O = "O:\nStatus Generalis:\n" + build_TTV(a) + "\n\nStatus Lokalis:\nE.O:\n" + (clean(a.get("eo_text","")) or "-") + "\n\nI.O:\n" + (clean(a.get("io_text","")) or "-") + "\n\n"
    elif stage in ["POD0","POD1"]:
        eo, io = build_pod_O(a)
        O = "O:\nStatus Generalis:\n" + build_TTV(a) + "\n\nStatus Lokalis:\nE.O:\n" + eo + "\n\nI.O:\n" + io + "\n\n"
    else:
        O = "O:\n(Status Generalis & Lokalis ambil dari SOAP poli / isi manual)\n\n"

    # Penunjang (ONLY PreOp, from Minlap)
    penunjang = ""
    if stage=="PreOp" and info.penunjang_raw:
        penunjang = info.penunjang_raw + "\n\n"

    # A (simple placeholder MVP)
    A = "A:\n(isi diagnosis)\n\n"

    # P
    if stage=="PreOp":
        op_date = a.get("tanggal_operasi", laporan_date + timedelta(days=1))
        jam = clean(a.get("jam_operasi","08.00"))
        zona = clean(a.get("zona_waktu","WITA"))
        tindakan = clean(a.get("tindakan","")) or info.tindakan or "(isi tindakan)"
        anestesi = clean(a.get("anestesi","general anestesi")) or "general anestesi"

        plan = build_preop_plan(a, info.bb)
        plan_lines = "\n".join([f"•⁠  ⁠{x}" for x in plan if clean(x)])
        op_day = day_name_id(op_date)
        tindakan_line = f"•⁠  ⁠Pro {tindakan} dalam {anestesi} pada hari {op_day}, {fmt_ddmmyyyy(op_date)} Pukul {jam} {zona} di {info.rs}"
        P = "P:\n" + plan_lines + "\n" + tindakan_line + "\n\n"
    elif stage=="Awal":
        P = "P:\n•⁠  ⁠Rencana pemeriksaan penunjang sesuai kasus\n•⁠  ⁠Rencana konsultasi/anestesi bila indikasi\n\n"
    else:
        P = "P:\n•⁠  ⁠Observasi kondisi umum & luka operasi\n•⁠  ⁠Terapi sesuai instruksi DPJP\n\n"

    footer = (
        "Mohon instruksi selanjutnya dokter.\n"
        "Terima kasih.\n\n"
        f"Residen: {clean(info.residen) or '-'}\n\n"
        f"DPJP: {clean(info.dpjp) or '-'}\n"
    )

    output = header + "\n" + ident + "\n" + "S : " + S + "\n\n" + O + (penunjang if penunjang else "") + A + P + footer

    st.subheader("Output (siap copy)")
    st.text_area("SOAP", value=output, height=560)
    st.download_button("Download .txt", data=output.encode("utf-8"), file_name=f"soap_{case}_{stage}.txt", mime="text/plain", use_container_width=True)
