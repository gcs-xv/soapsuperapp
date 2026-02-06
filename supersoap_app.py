
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
    # Convenience only; verify clinically
    w = max(0.0, float(weight_kg))
    if w <= 10:
        return 4.0 * w
    if w <= 20:
        return 40.0 + 2.0 * (w - 10.0)
    return 60.0 + 1.0 * (w - 20.0)

def tpm_from_ml_per_hr(ml_per_hr: float, drip_factor_gtt_per_ml: int = 20) -> int:
    return int(round((float(ml_per_hr) * int(drip_factor_gtt_per_ml)) / 60.0))

def split_names(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ", ".join(parts)

# -------------------------
# Minimal parsers (PreOp only)
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
    penunjang_raw: str = ""   # keep formatting
    jam_operasi: str = ""
    zona: str = ""
    dpjp: str = ""
    residen: str = ""
    S: str = ""
    O: str = ""
    A: str = ""

def parse_identity_line(text: str):
    m = re.search(r"^(Tn\.|Ny\.|Nn\.|An\.)[^\n]+", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    ident = m.group(0).strip()
    parts = [p.strip() for p in ident.split("/") if p.strip()]
    return parts

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

def extract_soa_blocks(raw: str):
    # best-effort
    def block(start, end):
        m1 = re.search(start, raw, re.IGNORECASE)
        if not m1:
            return ""
        s = m1.end()
        m2 = re.search(end, raw[s:], re.IGNORECASE)
        e = s + (m2.start() if m2 else len(raw[s:]))
        return raw[s:e].strip()
    S = block(r"\bS\s*:\s*", r"\n\s*O\s*:\s*")
    O = block(r"\bO\s*:\s*", r"\n\s*A\s*:\s*")
    A = block(r"\bA\s*:\s*", r"\n\s*P\s*:\s*")
    return S, O, A

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
            if "rawat" in x.lower() or x.strip().upper() in ["IGD"]:
                p.perawatan = x
        for x in parts:
            if x.upper() in ["BPJS", "UMUM", "JASA RAHARJA", "BAKSOS", "BAKSOS CCC", "CCC"]:
                p.pembiayaan = x
        mrm = re.search(r"RM\.?\s*([0-9.]+)", t, re.IGNORECASE)
        if mrm: p.rm = mrm.group(1).strip()
    p.bb, p.tb = parse_bb_tb(t)
    tindakan, anest = extract_tindakan_from_P(t)
    if tindakan: p.tindakan = tindakan
    if anest: p.anestesi = anest
    md = re.search(r"DPJP\s*:?\s*(.+)", t, re.IGNORECASE)
    if md: p.dpjp = md.group(1).strip()
    mr = re.search(r"Residen\s*:?\s*(.+)", t, re.IGNORECASE)
    if mr: p.residen = mr.group(1).strip()
    S, O, A = extract_soa_blocks(t)
    p.S, p.O, p.A = S, O, A
    return p

def normalize_minlap_block(text: str) -> str:
    # DO NOT change spacing
    return text.strip("\n")

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
            if "rawat" in x.lower() or x.strip().upper() in ["IGD"]:
                p.perawatan = x
        for x in parts:
            if x.upper() in ["BPJS", "UMUM", "JASA RAHARJA", "BAKSOS", "BAKSOS CCC", "CCC"]:
                p.pembiayaan = x
        mrm = re.search(r"RM\.?\s*([0-9.]+)", t, re.IGNORECASE)
        if mrm: p.rm = mrm.group(1).strip()
    p.bb, p.tb = parse_bb_tb(t)
    # Penunjang block keep formatting
    mpen = re.search(r"Pemeriksaan\s+penunjang\s*:\s*(.*?)(?:\n\s*A\s*:|\n\s*A\s*：|\n\s*A\s*\n|$)", t, re.IGNORECASE | re.DOTALL)
    if mpen:
        block = "Pemeriksaan penunjang :\n" + mpen.group(1).rstrip()
        p.penunjang_raw = normalize_minlap_block(block)
    # tindakan from P line
    mt = re.search(r"\n\s*P\s*:\s*(.+)", t, re.IGNORECASE)
    if mt:
        tindakan_line = mt.group(1).strip()
        tindakan_line = re.sub(r"^\W*\bPro\b\s*", "", tindakan_line, flags=re.IGNORECASE).strip()
        tindakan_line = re.sub(r"\s+dalam\s+.*$", "", tindakan_line, flags=re.IGNORECASE).strip()
        p.tindakan = tindakan_line
    # jam & zona
    mj = re.search(r"Pukul\s*:\s*\*?([0-9]{1,2}\.[0-9]{2})\s*([A-Z]{3,4})\*?", t, re.IGNORECASE)
    if mj:
        p.jam_operasi = mj.group(1)
        p.zona = mj.group(2).upper()
    # dpjp
    md = re.search(r"DPJP\s*:\s*(.+)", t, re.IGNORECASE)
    if md: p.dpjp = md.group(1).strip()
    # residen block
    mr = re.search(r"Residen\s*:\s*(.*?)(?:\n\s*DPJP\s*:|$)", t, re.IGNORECASE | re.DOTALL)
    if mr:
        p.residen = mr.group(1).strip()
    return p

# -------------------------
# Schema UI engine
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

def render_question(q, answers, compact=False):
    k = q["key"]
    t = q["type"]
    label = q["label"]
    help_txt = q.get("help", None)

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
        answers[k] = st.radio(label, options=options, index=options.index(current), horizontal=True)
    elif t == "date":
        today = datetime.now(TZ).date()
        default = today if q.get("default")=="today" else (today + timedelta(days=1) if q.get("default")=="tomorrow" else today)
        val = answers.get(k, default)
        answers[k] = st.date_input(label, value=val)
    else:
        st.warning(f"Tipe pertanyaan belum didukung: {t}")

# -------------------------
# Text builders (semi-automated)
# -------------------------
def build_ident(info: ParsedInfo, perawatan_default: str):
    pemb = info.pembiayaan or "BPJS"
    per = info.perawatan or perawatan_default
    kamar = f" / {info.kamar}" if info.kamar else ""
    rm = f"RM {info.rm}" if info.rm else "RM -"
    return f"{info.nama} / {info.jk} / {info.umur} / {pemb} / {per}{kamar} / {info.rs} / {rm}"

def build_awal_S(case, a):
    if case=="Impaksi":
        kel = a.get("keluhan_pilihan","Gigi belakang tidak tumbuh dan nyeri")
        if kel=="Keluhan lain":
            kel = clean(a.get("keluhan_lain","gigi belakang tidak tumbuh"))
        sisi = a.get("laterality","kanan dan kiri")
        dur = clean(a.get("durasi",""))
        s = f"Pasien datang dengan keluhan {kel.lower()} pada sisi {sisi}"
        if dur: s += f" sejak ± {dur}."
        else: s += "."
        if a.get("menjalar", False):
            s += f" Nyeri menjalar hingga ke {a.get('menjalar_ke','kepala')}."
        s += " Tidak ada riwayat alergi obat dan makanan." if not a.get("alergi", False) else " Ada riwayat alergi obat/makanan."
        if a.get("sistemik", True):
            s += " Riwayat penyakit sistemik disangkal."
        if not a.get("batuk_flu_demam", False):
            s += " Pasien tidak dalam keadaan batuk, flu dan demam."
        return s

    if case in ["Abses","Selulitis"]:
        loc = clean(a.get("lokasi_bengkak","pipi"))
        dur = clean(a.get("durasi",""))
        s = f"Pasien datang dengan keluhan pembengkakan pada {loc}"
        if a.get("meluas", True):
            s += f" meluas ke {clean(a.get('meluas_ke',''))}"
        s += f" sejak ± {dur}." if dur else "."
        # flags
        flag_names=[k for k in a.keys() if k.startswith("flag_")]
        if flag_names:
            items=[]
            for k in flag_names:
                name=k.replace("flag_","")
                items.append(f"{name} {a.get(k,'(-)')}")
            s += " Riwayat " + ", ".join(items) + "."
        if a.get("demam", False):
            s += " Ada riwayat demam."
        s += " Tidak ada riwayat alergi obat dan makanan." if not a.get("alergi", False) else " Ada riwayat alergi obat/makanan."
        if a.get("sistemik", True):
            s += " Riwayat penyakit sistemik disangkal."
        return s

    if case=="TMD":
        sisi=a.get("sisi_tmd","kanan dan kiri")
        dur=clean(a.get("durasi",""))
        s=f"Pasien datang dengan keluhan nyeri pada daerah sendi rahang sisi {sisi} saat mengunyah"
        if dur: s+=f" sejak ± {dur}."
        else: s+="."
        if a.get("riwayat_mengunci", False):
            s+=" Pasien pernah mengalami kesulitan menutup mulut setelah menguap lebar."
        s+=f" Riwayat kebiasaan mengunyah sebelah {a.get('kebiasaan_mengunyah','kiri')}."
        s += " Tidak ada riwayat alergi obat dan makanan." if not a.get("alergi", False) else " Ada riwayat alergi obat/makanan."
        if a.get("sistemik", True):
            s += " Riwayat penyakit sistemik disangkal."
        if not a.get("batuk_flu_demam", False):
            s += " Saat ini pasien tidak dalam kondisi demam, flu dan batuk."
        return s

    if case=="Fraktur":
        kel=clean(a.get("keluhan_fraktur",""))
        dur=clean(a.get("durasi",""))
        s=f"Pasien datang dengan keluhan {kel}"
        if dur: s+=f" sejak ± {dur} SMRS."
        else: s+="."
        flag_names=[k for k in a.keys() if k.startswith("flag_")]
        if flag_names:
            items=[]
            for k in flag_names:
                name=k.replace("flag_","")
                items.append(f"{name} {a.get(k,'(-)')}")
            s += " Riwayat " + ", ".join(items) + "."
        s += f" Kronologis kejadian: {clean(a.get('mekanisme',''))}."
        s += " Tidak ada riwayat alergi obat dan makanan." if not a.get("alergi", False) else " Ada riwayat alergi obat/makanan."
        if a.get("sistemik", True):
            s += " Riwayat penyakit sistemik disangkal."
        if not a.get("batuk_flu_demam", False):
            s += " Saat ini pasien tidak sedang batuk, flu, demam, dan diare."
        return s

    return f"Pasien datang dengan keluhan {clean(a.get('keluhan',''))} sejak ± {clean(a.get('durasi',''))}."

def build_ttv_block(ku, td, n, p, s, spo2, bb, tb):
    lines=[
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
    sents.append("Pasien makan dan minum dengan baik." if ed=="baik" else ("Pasien makan dan minum namun masih kurang." if ed=="kurang" else "Pasien belum makan dan minum."))
    rest = a.get("rest","cukup")
    sents.append("Istirahat dirasa cukup." if rest=="cukup" else "Istirahat dirasa kurang.")
    return " ".join(sents)

def build_pod_O(a):
    sw=a.get("swelling","ada")
    eo = "•⁠  ⁠Wajah simetris" if sw=="tidak ada" else f"•⁠  ⁠Wajah asimetris dengan oedem ar {clean(a.get('swelling_location','daerah operasi'))}"
    suture = "intak" if a.get("suture_intact", True) else "tidak intak"
    hyp = "(+)" if a.get("hyperemia", True) else "(-)"
    bc = a.get("blood_clot","(-)")
    ab = "(+)" if a.get("active_bleeding", False) else "(-)"
    io = f"•⁠  ⁠Jahitan {suture} ar daerah operasi dengan hiperemis {hyp}, blood clot {bc}, active bleeding {ab}"
    return eo, io

# -------------------------
# App UI (Mobile-first)
# -------------------------
st.set_page_config(page_title="SuperSOAP", layout="centered")
st.markdown("## 🧠 SuperSOAP Maker")
st.caption("Semi-otomatis, mobile-friendly. Pilih Kasus → Pilih Stage → Isi sedikit → Output siap copy.")

schema_path = st.sidebar.text_input("Schema file", value="supersoap_schema_v3.json")
with open(schema_path, "r", encoding="utf-8") as f:
    schema = json.load(f)

case_names = list(schema["cases"].keys())
stage_names = schema["stages"]
stage_rules = schema.get("stage_rules", {})

# --- Top selectors (big + friendly)
st.markdown("### 1) Pilih Kasus & Stage")
c1, c2 = st.columns(2)
with c1:
    case = st.selectbox("Kasus", case_names, index=0)
with c2:
    stage = st.selectbox("Stage", stage_names, index=0)

# Sidebar tools
st.sidebar.divider()
st.sidebar.markdown("### Tools")
if st.sidebar.button("🧾 GET LAPORAN OPERASI", use_container_width=True):
    lo = schema.get("laporan_operasi", {}).get(case)
    st.sidebar.text_area(f"Laporan Operasi — {case}", value=lo or "Belum ada", height=320)

# State
if "answers" not in st.session_state:
    st.session_state["answers"] = {}
if "info" not in st.session_state:
    st.session_state["info"] = ParsedInfo()

tabs = st.tabs(["① Input", "② Isi Form", "③ Output"])

# -------------------------
# TAB ① Input (ONLY PreOp)
# -------------------------
with tabs[0]:
    rules = stage_rules.get(stage, {"allow_paste": False, "allow_minlap": False})
    if stage != "PreOp":
        st.success("Stage ini tidak membutuhkan paste (lebih cepat ✅). Lanjut ke tab ② Isi Form.")
    else:
        st.markdown("### Paste Pre-Op (opsional tapi bikin cepat)")
        st.caption("Paste SOAP poli (mentah) untuk ambil S/O/A & tindakan. Paste MINLAP untuk ambil penunjang & jam operasi.")
        raw = st.text_area("SOAP mentah (Rawat Jalan / terjaring)", height=220)
        minlap = st.text_area("MINLAP (format akan dipertahankan)", height=280)

        if st.button("⚡ Auto-fill", type="primary", use_container_width=True):
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

            a = st.session_state["answers"]
            if parsed.tindakan: a["tindakan"] = parsed.tindakan
            if parsed.anestesi: a["anestesi"] = parsed.anestesi
            if parsed.jam_operasi: a["jam_operasi"] = parsed.jam_operasi
            if parsed.zona: a["zona_waktu"] = parsed.zona
            st.session_state["answers"] = a
            st.success("Auto-fill selesai. Lanjut ke tab ② Isi Form.")

        with st.expander("Preview hasil Auto-fill"):
            st.write(st.session_state["info"])

# -------------------------
# TAB ② Form (Wizard-style)
# -------------------------
with tabs[1]:
    info = st.session_state["info"]
    a = st.session_state["answers"]

    st.markdown("### 2) Isi Form (yang penting saja)")
    st.progress(0.33)

    with st.expander("A. Identitas (tap untuk buka)", expanded=True):
        nama = st.text_input("Nama (Tn./Ny./Nn./An.)", value=info.nama)
        jk = st.text_input("JK", value=info.jk)
        umur = st.text_input("Umur", value=info.umur)
        pembiayaan = st.text_input("Pembiayaan", value=info.pembiayaan or "BPJS")

        perawatan_default = "Rawat Jalan" if stage=="Awal" else "Rawat Inap"
        perawatan = st.text_input("Jenis Perawatan", value=info.perawatan or perawatan_default)
        kamar = st.text_input("Kamar/Bed (opsional)", value=info.kamar)
        rm = st.text_input("RM", value=info.rm)
        rs = st.text_input("RS", value=info.rs or "RSGMP UNHAS")

        cbb, ctb = st.columns(2)
        with cbb:
            bb = st.number_input("BB (kg)", min_value=0.0, max_value=250.0, value=float(info.bb or 0.0), step=0.1)
        with ctb:
            tb = st.number_input("TB (cm)", min_value=0.0, max_value=250.0, value=float(info.tb or 0.0), step=0.1)

    # Case-specific questions
    st.progress(0.66)
    with st.expander("B. Pertanyaan Kasus (tap untuk buka)", expanded=True):
        qs = schema["cases"][case]["stage"][stage]["questions"]

        # smart defaults
        if stage=="PreOp":
            today = datetime.now(TZ).date()
            a.setdefault("tanggal_laporan", today)
            a.setdefault("tanggal_operasi", today + timedelta(days=1))

        for q in qs:
            # suggested tpm from BB
            if q["key"]=="ivfd_tpm" and (not a.get("ivfd_tpm")) and bb>0:
                drip = int(a.get("drip_factor", q.get("default",20)))
                mlhr = maintenance_ml_per_hr_421(bb)
                a["ivfd_tpm"] = tpm_from_ml_per_hr(mlhr, drip)

            if should_show(q, a):
                render_question(q, a)

        # For Awal/POD: quick EO/IO + TTV (minimal typing)
        if stage in ["Awal","POD0","POD1"]:
            st.markdown("**TTV (singkat)**")
            c1, c2 = st.columns(2)
            with c1:
                a["ku"] = st.text_input("KU", value=a.get("ku","Baik/Compos Mentis"))
                a["td"] = st.text_input("TD", value=a.get("td","-/-"))
                a["n"]  = st.text_input("N", value=a.get("n","-"))
            with c2:
                a["p"]  = st.text_input("P", value=a.get("p","-"))
                a["s"]  = st.text_input("S", value=a.get("s","36.7"))
                a["spo2"] = st.text_input("SpO2", value=a.get("spo2","99"))

            st.markdown("**EO / IO (cukup 2–5 poin)**")
            a["eo_text"] = st.text_area("EO", value=a.get("eo_text",""), height=80, placeholder="Contoh: Wajah simetris, bukaan mulut normal")
            a["io_text"] = st.text_area("IO", value=a.get("io_text",""), height=120, placeholder="Contoh: Unerupted 38, kalkulus (+), OH sedang")

    st.progress(1.0)
    with st.expander("C. DPJP & Residen", expanded=True):
        dpjp = st.text_input("DPJP", value=info.dpjp)
        residen = st.text_area("Residen (paste apa aja, nanti dirapihin)", value=info.residen, height=80)

    # Save
    st.session_state["answers"] = a
    st.session_state["info"] = ParsedInfo(
        nama=nama, jk=jk, umur=umur, pembiayaan=pembiayaan, perawatan=perawatan, kamar=kamar, rs=rs, rm=rm,
        bb=bb, tb=tb, tindakan=info.tindakan, anestesi=info.anestesi, penunjang_raw=info.penunjang_raw,
        jam_operasi=info.jam_operasi, zona=info.zona, dpjp=dpjp, residen=residen,
        S=info.S, O=info.O, A=info.A
    )

    st.success("✅ Selesai isi form. Lanjut ke tab ③ Output.")

# -------------------------
# TAB ③ Output
# -------------------------
with tabs[2]:
    info = st.session_state["info"]
    a = st.session_state["answers"]

    # Header dates
    today = datetime.now(TZ).date()
    laporan_date = a.get("tanggal_laporan", today) if stage=="PreOp" else today
    hari = day_name_id(laporan_date)

    if stage=="Awal":
        header = f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Jalan {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n\n"
    elif stage=="PreOp":
        header = f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rencana Operasi {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n\n"
    else:
        header = f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Inap {info.rs}, {hari} ({fmt_ddmmyyyy(laporan_date)})\n\n"

    ident = build_ident(info, "Rawat Inap" if stage!="Awal" else "Rawat Jalan") + "\n\n"

    # S
    if stage=="Awal":
        S = build_awal_S(case, a)
    elif stage in ["POD0","POD1"]:
        S = build_pod_S(stage, a)
    else:
        # PreOp: prefer S from raw soap if available; else fallback sentence
        S = info.S if info.S else "Pasien rencana tindakan dalam general anestesi. (ringkas keluhan di sini)."

    # O
    if stage in ["Awal","POD0","POD1"]:
        ku=a.get("ku","Baik/Compos Mentis"); td=a.get("td","-/-"); n=a.get("n","-"); p=a.get("p","-"); s=a.get("s","36.7"); spo2=a.get("spo2","99")
        ttv = build_ttv_block(ku, td, n, p, s, spo2, f"{info.bb:g}" if info.bb else "", f"{info.tb:g}" if info.tb else "")
        if stage=="Awal":
            O = "O:\nStatus Generalis:\n" + ttv + "\n\nStatus Lokalis:\nE.O:\n" + (clean(a.get("eo_text","")) or "-") + "\n\nI.O:\n" + (clean(a.get("io_text","")) or "-") + "\n\n"
        else:
            eo, io = build_pod_O(a)
            O = "O:\nStatus Generalis:\n" + ttv + "\n\nStatus Lokalis:\nE.O:\n" + eo + "\n\nI.O:\n" + io + "\n\n"
    else:
        O = "O:\n" + (info.O.strip() + "\n\n" if info.O.strip() else "(Isi O dari SOAP poli / pemeriksaan)\n\n")

    # Penunjang (ONLY PreOp, from MINLAP)
    penunjang = ""
    if stage=="PreOp" and info.penunjang_raw:
        penunjang = info.penunjang_raw + "\n\n"

    # A
    A = "A:\n" + (info.A.strip() + "\n\n" if stage=="PreOp" and info.A.strip() else "(Isi diagnosis)\n\n")

    # P
    if stage=="PreOp":
        op_date = a.get("tanggal_operasi", laporan_date + timedelta(days=1))
        jam = clean(a.get("jam_operasi", info.jam_operasi or "08.00"))
        zona = clean(a.get("zona_waktu", info.zona or "WITA"))
        tindakan = clean(a.get("tindakan","")) or info.tindakan or "(isi tindakan)"
        anestesi = clean(a.get("anestesi", info.anestesi or "general anestesi")) or "general anestesi"

        plan = build_preop_plan(a, info.bb)
        plan_lines = "\n".join([f"•⁠  ⁠{x}" for x in plan if clean(x)])
        op_day = day_name_id(op_date)
        tindakan_line = f"•⁠  ⁠Pro {tindakan} dalam {anestesi} pada hari {op_day}, {fmt_ddmmyyyy(op_date)} Pukul {jam} {zona} di {info.rs}"
        P = "P:\n" + plan_lines + "\n" + tindakan_line + "\n\n"
    elif stage=="Awal":
        P = "P:\n•⁠  ⁠Pro pemeriksaan penunjang sesuai indikasi\n•⁠  ⁠Pro konsultasi TS Anestesi bila direncanakan GA\n\n"
    else:
        P = "P:\n•⁠  ⁠Observasi kondisi umum & luka operasi\n•⁠  ⁠Terapi sesuai instruksi DPJP\n\n"

    footer = (
        "Mohon instruksi selanjutnya dokter.\n"
        "Terima kasih.\n\n"
        f"Residen: {split_names(info.residen) or '-'}\n\n"
        f"DPJP: {clean(info.dpjp) or '-'}\n"
    )

    output = header + ident + "S : " + S + "\n\n" + O + penunjang + A + P + footer

    st.markdown("### Output (siap copy)")
    st.text_area("SOAP", value=output, height=560)
    st.download_button("Download .txt", data=output.encode("utf-8"), file_name=f"soap_{case}_{stage}.txt", mime="text/plain", use_container_width=True)
