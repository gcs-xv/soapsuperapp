import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import List, Optional, Tuple
import streamlit as st
from dateutil import tz

# =========================
# Config
# =========================
TZ = tz.gettz("Asia/Jakarta")

DAY_ID = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu",
}

CASES = [
    "Impaksi",
    "Abses",
    "Selulitis",
    "Tumor",
    "Odontogenic cyst",
    "Fistula orocutaneous",
    "TMD",
    "Fraktur",
]

TEETH = ["18","17","16","15","14","13","12","11","21","22","23","24","25","26","27","28",
         "38","37","36","35","34","33","32","31","41","42","43","44","45","46","47","48"]

# =========================
# Utils
# =========================
def day_name_id(d: date) -> str:
    return DAY_ID.get(d.strftime("%A"), d.strftime("%A"))

def fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")

def clean(s: str) -> str:
    return (s or "").strip()

def normalize_bullets(s: str) -> str:
    if not s:
        return ""
    s = s.replace("•⁠", "•").replace("• ⁠", "• ").replace("•⁠  ⁠", "• ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s.strip()

def parse_hhmm(s: str) -> Optional[Tuple[int,int]]:
    s = clean(s).replace(".", ":")
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return (h, mi)
    return None

def fmt_time(h: int, mi: int) -> str:
    return f"{h:02d}.{mi:02d}"

def minus_minutes(h: int, mi: int, minutes: int) -> Tuple[int,int]:
    total = (h * 60 + mi - minutes) % (24*60)
    return (total//60, total%60)

def maintenance_ml_per_hr_421(weight_kg: float) -> float:
    w = max(0.0, float(weight_kg))
    if w <= 10:
        return 4.0 * w
    if w <= 20:
        return 40.0 + 2.0 * (w - 10.0)
    return 60.0 + 1.0 * (w - 20.0)

def tpm_from_ml_per_hr(ml_per_hr: float, drip_factor_gtt_per_ml: int = 20) -> int:
    return int(round((float(ml_per_hr) * int(drip_factor_gtt_per_ml)) / 60.0))

def join_bullets(lines: List[str], bullet: str="•⁠  ⁠") -> str:
    lines = [clean(x) for x in lines if clean(x)]
    return "\n".join([f"{bullet}{x}" for x in lines])

def split_people_list(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ", ".join(parts)

# =========================
# Parsing (Pre-Op only): SOAP mentah + MINLAP
# =========================
@dataclass
class ParsedSoap:
    sapaan: str = "Assalamualaikum dokter."
    pembuka: str = "Maaf mengganggu, izin melaporkan"
    rs: str = "RSGMP UNHAS"
    nama: str = ""
    jk: str = ""
    umur: str = ""
    jenis_perawatan: str = ""
    pembiayaan: str = ""
    kamar: str = ""
    rm: str = ""

    S: str = ""
    O_generalis: str = ""
    EO: str = ""
    IO: str = ""
    A: str = ""
    tindakan_hint: str = ""

    residen: str = ""
    dpjp: str = ""

def pick1(text: str, pattern: str, flags=0) -> str:
    m = re.search(pattern, text or "", flags)
    return clean(m.group(1)) if m else ""

def pick_block(text: str, start_pat: str, end_pat: str) -> str:
    flags = re.IGNORECASE | re.DOTALL
    m1 = re.search(start_pat, text or "", flags)
    if not m1:
        return ""
    start = m1.end()
    m2 = re.search(end_pat, (text or "")[start:], flags)
    end = start + (m2.start() if m2 else len((text or "")[start:]))
    return clean((text or "")[start:end])

def parse_raw_soap_preop_only(raw: str) -> ParsedSoap:
    raw = raw.strip()
    p = ParsedSoap()

    first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
    if first_line.lower().startswith("assalamualaikum"):
        p.sapaan = first_line

    p.rs = "RSGMP UNHAS" if re.search(r"RSGMP\s*UNHAS", raw, re.IGNORECASE) else (pick1(raw, r"(RSGMP[^\n/]+)", re.IGNORECASE) or "RSGMP UNHAS")

    ident = pick1(raw, r"^\s*(Tn\.|Ny\.|Nn\.|An\.)[^\n]+$", re.IGNORECASE | re.MULTILINE)
    if ident:
        parts = [x.strip() for x in ident.split("/") if x.strip()]
        if parts: p.nama = parts[0]
        if len(parts) > 1: p.jk = parts[1]
        if len(parts) > 2: p.umur = parts[2]
        for tok in parts:
            if re.search(r"\bBPJS\b|\bUMUM\b|\bBAKSOS\b|\bJasa\b", tok, re.IGNORECASE):
                p.pembiayaan = tok
            if re.search(r"rawat", tok, re.IGNORECASE):
                p.jenis_perawatan = tok
            if tok.lower().startswith("kamar"):
                p.kamar = tok
        p.rm = pick1(raw, r"\bRM\.?\s*([0-9.]+)", re.IGNORECASE)

    p.S = pick_block(raw, r"\bS\s*:\s*", r"\n\s*O\s*:\s*")
    o_block = pick_block(raw, r"\bO\s*:\s*", r"\n\s*A\s*:\s*")
    p.A = pick_block(raw, r"\bA\s*:\s*", r"\n\s*P\s*:\s*")

    p.O_generalis = normalize_bullets(pick_block(o_block, r"Status\s+Generalis\s*:\s*", r"Status\s+Lokalis\s*:")) \
        or normalize_bullets(pick_block(o_block, r"Status\s+Generalis\s*:\s*", r"\n\s*(Status\s+Lokalis|EO|E\.?O)\s*:"))
    p.EO = normalize_bullets(pick_block(o_block, r"\bEO\s*:\s*", r"\n\s*IO\s*:\s*")) or \
           normalize_bullets(pick_block(o_block, r"\bE\.?O\s*:\s*", r"\n\s*I\.?O\s*:\s*"))
    p.IO = normalize_bullets(pick_block(o_block, r"\bIO\s*:\s*", r"\n\s*(Pemeriksaan|A\s*:|$)")) or \
           normalize_bullets(pick_block(o_block, r"\bI\.?O\s*:\s*", r"\n\s*(Pemeriksaan|A\s*:|$)"))

    p_block = pick_block(raw, r"\bP\s*:\s*", r"\n\s*(Izin|Mohon|Residen|DPJP)\s*:|\Z")
    pro_lines = re.findall(r"Pro\s+([^\n]+)", p_block, re.IGNORECASE)
    if pro_lines:
        cand = pro_lines[-1]
        cand = re.sub(r"\(.*?\)", "", cand)
        cand = re.sub(r"dalam\s+.*", "", cand, flags=re.IGNORECASE).strip()
        p.tindakan_hint = clean(cand)

    p.residen = split_people_list(pick1(raw, r"Residen\s*:?\s*(.+)", re.IGNORECASE))
    p.dpjp = clean(pick1(raw, r"DPJP\s*:?\s*(.+)", re.IGNORECASE))
    return p

def parse_minlap_penunjang_block(minlap: str) -> str:
    minlap = minlap or ""
    blk = pick_block(minlap, r"Pemeriksaan\s+penunjang\s*:\s*", r"\n\s*A\s*:|\n\s*P\s*:|\Z")
    return blk.strip()

def parse_minlap_jam(minlap: str) -> str:
    jam = pick1(minlap or "", r"Pukul\s*:\s*\*?([0-9]{1,2}\.[0-9]{2})", re.IGNORECASE)
    return jam

# =========================
# Dynamic list widgets
# =========================
def list_editor(key: str, label: str, placeholder: str, add_label: str="Tambah", min_items: int=0):
    if key not in st.session_state:
        st.session_state[key] = [""] * max(0, min_items)

    items = st.session_state[key]
    st.caption(label)

    for i in range(len(items)):
        cols = st.columns([0.86, 0.14])
        with cols[0]:
            items[i] = st.text_input(f"{placeholder} {i+1}", value=items[i], key=f"{key}_{i}")
        with cols[1]:
            if st.button("✖", key=f"{key}_del_{i}", use_container_width=True):
                items.pop(i)
                st.session_state[key] = items
                st.rerun()

    if st.button(f"➕ {add_label}", key=f"{key}_add", use_container_width=True):
        items.append("")
        st.session_state[key] = items
        st.rerun()

    st.session_state[key] = items
    return [clean(x) for x in items if clean(x)]

# =========================
# Common history builder
# =========================
def history_blocks():
    st.subheader("Riwayat penting (klik-klik)")
    col1, col2 = st.columns(2)
    with col1:
        alergi_any = st.radio("Alergi?", ["Tidak ada alergi obat & makanan", "Ada alergi"], horizontal=False)
    with col2:
        sistemik_any = st.radio("Penyakit sistemik?", ["Disangkal", "Ada"], horizontal=False)

    alergi_items=[]
    if alergi_any == "Ada alergi":
        alergi_items = list_editor("alergi_list", "Isi alergi (bisa tambah banyak):", "Alergi", "Tambah alergi", 1)

    sistemik_items=[]
    obat_items=[]
    if sistemik_any == "Ada":
        sistemik_items = list_editor("sistemik_list", "Isi penyakit sistemik:", "Penyakit", "Tambah penyakit", 1)
        obat_items = list_editor("obat_rutin_list", "Obat rutin yang diminum:", "Obat", "Tambah obat", 0)

    st.caption("Kondisi saat ini")
    a1,a2,a3,a4 = st.columns(4)
    with a1: batuk = st.checkbox("Batuk", value=False)
    with a2: flu = st.checkbox("Flu", value=False)
    with a3: demam = st.checkbox("Demam", value=False)
    with a4: diare = st.checkbox("Diare", value=False)

    return {
        "alergi_any": alergi_any,
        "alergi_items": alergi_items,
        "sistemik_any": sistemik_any,
        "sistemik_items": sistemik_items,
        "obat_items": obat_items,
        "batuk": batuk, "flu": flu, "demam": demam, "diare": diare,
    }

def build_history_sentence(h: dict) -> str:
    parts=[]
    if h["alergi_any"].startswith("Tidak"):
        parts.append("Tidak ada riwayat alergi obat dan makanan.")
    else:
        parts.append("Ada riwayat alergi" + (": " + ", ".join(h["alergi_items"]) + "." if h["alergi_items"] else "."))
    if h["sistemik_any"] == "Disangkal":
        parts.append("Riwayat penyakit sistemik disangkal.")
    else:
        parts.append("Riwayat penyakit sistemik: " + (", ".join(h["sistemik_items"]) if h["sistemik_items"] else "ada") + ".")
        if h["obat_items"]:
            parts.append("Obat rutin: " + ", ".join(h["obat_items"]) + ".")
    # current condition
    if not any([h["batuk"], h["flu"], h["demam"], h["diare"]]):
        parts.append("Saat ini pasien tidak dalam kondisi batuk, demam, flu, dan diare.")
    else:
        pos=[]
        if h["batuk"]: pos.append("batuk")
        if h["flu"]: pos.append("flu")
        if h["demam"]: pos.append("demam")
        if h["diare"]: pos.append("diare")
        parts.append("Saat ini pasien dalam kondisi: " + ", ".join(pos) + ".")
    return " ".join(parts)

# =========================
# EO/IO smart builders for ALL cases
# =========================
def eo_common_face(prefix: str):
    """Common EO line: face symmetry + mouth opening. Prefix ensures unique widget keys."""
    face = st.selectbox(
        "Wajah",
        ["Wajah simetris", "Wajah asimetris"],
        index=0,
        key=f"{prefix}_wajah",
    )
    om = st.selectbox(
        "Bukaan mulut",
        ["bukaan mulut normal", "bukaan mulut terbatas"],
        index=0,
        key=f"{prefix}_bukaan_mulut",
    )
    return f"{face} dengan {om}"

def impaksi_builder():
    st.subheader("EO/IO Cepat — Impaksi")
    eo_lines=[eo_common_face("impaksi")]

    st.markdown("**Gigi impaksi**")
    selected = st.multiselect("Pilih gigi", options=["18","28","38","48"], default=["18","28","38","48"])
    erupt = st.selectbox("Status erupsi", ["Unerupted", "Partial erupted", "Fully erupted"], index=0)

    col1, col2, col3 = st.columns(3)
    with col1:
        hyper = st.checkbox("Hiperemis (+)", value=False)
    with col2:
        palp = st.checkbox("Nyeri palpasi (+)", value=False)
    with col3:
        perk = st.checkbox("Nyeri perkusi (+)", value=False)

    io_lines=[]
    if selected:
        tags=[
            "hiperemis (+)" if hyper else "hiperemis (-)",
            "palpasi (+)" if palp else "palpasi (-)",
            "perkusi (+)" if perk else "perkusi (-)",
        ]
        io_lines.append(f"{erupt} gigi {', '.join(selected)} dengan {', '.join(tags)}")

    # detail if positive
    if hyper:
        det = st.text_input("Hiperemis di bagian mana?", value="")
        if det: io_lines.append(f"Hiperemis: {det}")
    if palp:
        det = st.text_input("Nyeri palpasi di bagian mana?", value="")
        if det: io_lines.append(f"Nyeri palpasi: {det}")
    if perk:
        det = st.text_input("Nyeri perkusi di gigi mana?", value="")
        if det: io_lines.append(f"Nyeri perkusi: {det}")

    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=0)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=0)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional, 1 baris = 1 poin)", height=90)
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def infeksi_builder(kind: str):
    st.subheader(f"EO/IO Cepat — {kind}")
    eo_lines=[]
    side = st.selectbox("Sisi", ["dextra", "sinistra", "bilateral"], index=0)
    regio = st.selectbox("Regio", ["bukalis", "submandibula", "submental", "infraorbita", "masseter", "parotis"], index=0)
    ukuran = st.text_input("Ukuran (cm) (contoh: 4 x 3.5 x 1)", value="")
    kons = st.selectbox("Konsistensi", ["lunak", "keras", "kenyal"], index=0)
    nyeri = st.selectbox("Nyeri palpasi", ["(+)", "(-)"], index=0)
    fluk = st.selectbox("Fluktuasi", ["(+)", "(-)"], index=1)
    hiper = st.selectbox("Hiperemis", ["(+)", "(-)"], index=1)
    suhu = st.selectbox("Suhu", ["lebih hangat", "sama"], index=0)
    warna = st.selectbox("Warna", ["lebih merah", "sama"], index=0)

    base = f"Wajah asimetris dengan pembengkakan regio {regio} {side}"
    details=[]
    if ukuran: details.append(f"ukuran ± {ukuran} cm")
    details.append(f"konsistensi {kons}")
    details += [f"nyeri palpasi {nyeri}", f"fluktuasi {fluk}", f"hiperemis {hiper}", f"suhu {suhu}", f"warna {warna} dari jaringan sekitar"]
    eo_lines.append(base + " dengan " + ", ".join(details) + ".")

    kgb_k = st.selectbox("KGB kanan", ["tidak teraba, tidak sakit", "tidak teraba, sakit", "teraba, tidak sakit", "teraba, sakit"], index=0)
    kgb_l = st.selectbox("KGB kiri", ["tidak teraba, tidak sakit", "tidak teraba, sakit", "teraba, tidak sakit", "teraba, sakit"], index=0)
    eo_lines += [f"KGB Kanan: {kgb_k}", f"KGB Kiri: {kgb_l}"]

    trismus = st.checkbox("Trismus/terbatas bukaan mulut?", value=True)
    if trismus:
        bm = st.text_input("Bukaan mulut (mm) (contoh: 10)", value="")
        if bm: eo_lines.append(f"Bukaan mulut: ± {bm} mm")

    io_lines=[]
    gigi = st.multiselect("Gigi sumber/suspect", TEETH, default=["48"])
    dx = st.selectbox("Temuan utama", ["Karies profunda", "Karies media", "Sisa akar", "Gangren pulpa", "Lainnya"], index=0)
    dx_text = st.text_input("Isi temuan utama", value="") if dx=="Lainnya" else dx
    pus = st.selectbox("Pus discharge", ["(+)", "(-)", "tidak dinilai"], index=1)

    col1,col2,col3 = st.columns(3)
    with col1: hiper_io = st.checkbox("Hiperemis (+)", value=True)
    with col2: palp_io = st.checkbox("Nyeri palpasi (+)", value=False)
    with col3: perk_io = st.checkbox("Nyeri perkusi (+)", value=False)

    if gigi:
        tags=[
            "hiperemis (+)" if hiper_io else "hiperemis (-)",
            "nyeri palpasi (+)" if palp_io else "nyeri palpasi (-)",
            "nyeri perkusi (+)" if perk_io else "nyeri perkusi (-)",
        ]
        io_lines.append(f"{dx_text} ar gigi {', '.join(gigi)} dengan {', '.join(tags)}, pus discharge {pus}")
    else:
        io_lines.append(f"{dx_text} dengan pus discharge {pus}")

    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=0)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=2)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional, 1 baris = 1 poin)", height=90)
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def tumor_builder():
    st.subheader("EO/IO Cepat — Tumor jaringan lunak")
    eo_lines=[eo_common_face("tumor")]
    kgb_k = st.selectbox("KGB kanan", ["Tidak teraba, tidak sakit", "Teraba, tidak sakit", "Teraba, sakit"], index=0)
    kgb_l = st.selectbox("KGB kiri", ["Tidak teraba, tidak sakit", "Teraba, tidak sakit", "Teraba, sakit"], index=0)
    eo_lines += [f"KGB Kanan : {kgb_k}", f"KGB Kiri : {kgb_l}"]

    st.markdown("**Lesi intraoral**")
    lokasi = st.selectbox("Lokasi", ["gingiva", "palatum", "bukal", "lingual", "labial", "retromolar"], index=0)
    tooth_range = st.text_input("Area gigi (contoh: 35-37, 12-22) (opsional)", value="")
    size = st.text_input("Ukuran (cm) (contoh: 7 x 6 x 3)", value="")
    kons = st.selectbox("Konsistensi", ["kenyal", "keras", "lunak"], index=0)

    col1,col2,col3 = st.columns(3)
    with col1: ped = st.checkbox("Pedunculated (+)", value=False)
    with col2: nyeri = st.checkbox("Nyeri palpasi (+)", value=False)
    with col3: hiper = st.checkbox("Hiperemis (+)", value=False)

    col4,col5,col6 = st.columns(3)
    with col4: bleed = st.checkbox("Mudah berdarah (+)", value=False)
    with col5: ind = st.checkbox("Indurasi (+)", value=False)
    with col6: bite = st.checkbox("Bitemark (+)", value=False)

    warna = st.selectbox("Warna", ["sama dengan jaringan sekitar", "lebih merah", "lebih pucat"], index=0)

    io_lines=[]
    head = f"Benjolan ar {lokasi}"
    if tooth_range:
        head += f" ar gigi {tooth_range}"
    desc=[]
    if size: desc.append(f"ukuran ± {size} cm")
    desc.append(f"konsistensi {kons}")
    desc.append(f"pedunculated (+)" if ped else "pedunculated (-)")
    desc.append(f"nyeri palpasi (+)" if nyeri else "nyeri palpasi (-)")
    desc.append(f"hiperemis (+)" if hiper else "hiperemis (-)")
    desc.append(f"mudah berdarah (+)" if bleed else "mudah berdarah (-)")
    desc.append(f"indurasi (+)" if ind else "indurasi (-)")
    desc.append(f"bitemark (+)" if bite else "bitemark (-)")
    desc.append(f"warna {warna}")
    io_lines.append(head + " dengan " + ", ".join(desc) + ".")

    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=1)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=0)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional)", height=90)
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def cyst_builder():
    st.subheader("EO/IO Cepat — Odontogenic cyst")
    eo_lines=[]
    face = st.selectbox("Wajah", ["Wajah simetris", "Wajah asimetris"], index=0)
    eo_lines.append(face + " dengan bukaan mulut normal")
    kgb_k = st.selectbox("KGB kanan", ["Tidak teraba, tidak sakit", "Teraba, tidak sakit", "Teraba, sakit"], index=0)
    kgb_l = st.selectbox("KGB kiri", ["Tidak teraba, tidak sakit", "Teraba, tidak sakit", "Teraba, sakit"], index=0)
    eo_lines += [f"KGB Kanan: {kgb_k}", f"KGB Kiri: {kgb_l}"]

    st.markdown("**Pembesaran intraoral**")
    area = st.text_input("Area (contoh: ar gigi 33-34 / mandibula dextra 46-48)", value="")
    size = st.text_input("Ukuran (cm) (contoh: 1.5 x 1 x 0.5)", value="")
    kons = st.selectbox("Konsistensi", ["lunak", "keras", "kenyal"], index=0)
    fluk = st.selectbox("Fluktuasi", ["(+)", "(-)"], index=1)
    hiper = st.selectbox("Hiperemis", ["(+)", "(-)"], index=0)
    nyeri = st.selectbox("Nyeri palpasi", ["(+)", "(-)"], index=0)
    warna = st.selectbox("Warna", ["sama dengan jaringan sekitar", "lebih merah"], index=0)

    io_lines=[]
    desc=[]
    if size: desc.append(f"ukuran ± {size} cm")
    desc.append(f"konsistensi {kons}")
    desc.append(f"fluktuasi {fluk}")
    desc.append(f"hiperemis {hiper}")
    desc.append(f"nyeri palpasi {nyeri}")
    desc.append(f"warna {warna}")
    if area:
        io_lines.append(f"Pembesaran {area} dengan " + ", ".join(desc) + ".")
    else:
        io_lines.append("Pembesaran intraoral dengan " + ", ".join(desc) + ".")

    aspir = st.selectbox("Aspirasi test (jika ada)", ["-", "Pus", "Darah", "Cairan kekuningan"], index=0)
    if aspir != "-":
        io_lines.append(f"Aspirasi test: {aspir}")

    # tooth condition helpers
    t_tooth = st.multiselect("Gigi terkait (opsional)", TEETH, default=[])
    if t_tooth:
        disc = st.checkbox("Diskolorisasi (+)", value=False)
        kar = st.selectbox("Karies", ["-", "karies media", "karies profunda"], index=0)
        tags=[]
        if disc: tags.append("diskolorisasi (+)")
        if kar != "-": tags.append(kar)
        if tags:
            io_lines.append(f"Temuan gigi {', '.join(t_tooth)}: " + ", ".join(tags) + ".")

    ortho = st.checkbox("Ada piranti ortodontik?", value=False)
    if ortho:
        io_lines.append("Piranti ortodontik terpasang baik.")

    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=1)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=0)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional)", height=90)
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def tmd_builder():
    st.subheader("EO/IO Cepat — TMD")
    eo_lines=[]
    eo_lines.append("Wajah simetris dengan bukaan mulut normal")

    st.markdown("**TMJ**")
    c1,c2 = st.columns(2)
    with c1:
        click_d = st.selectbox("TMJ dextra clicking", ["(+)", "(-)"], index=0)
        pop_d = st.selectbox("TMJ dextra popping", ["(+)", "(-)"], index=1)
        del_d = st.selectbox("TMJ dextra delayed", ["(+)", "(-)"], index=1)
        pain_d = st.selectbox("TMJ dextra nyeri palpasi", ["(+)", "(-)"], index=1)
    with c2:
        click_s = st.selectbox("TMJ sinistra clicking", ["(+)", "(-)"], index=0)
        pop_s = st.selectbox("TMJ sinistra popping", ["(+)", "(-)"], index=1)
        del_s = st.selectbox("TMJ sinistra delayed", ["(+)", "(-)"], index=1)
        pain_s = st.selectbox("TMJ sinistra nyeri palpasi", ["(+)", "(-)"], index=1)

    dev = st.selectbox("Deviasi mandibula", ["(+)", "(-)"], index=0)
    dev_side = st.selectbox("Arah deviasi (kalau +)", ["sinistra", "dextra"], index=0)
    mouth_mm = st.text_input("Bukaan mulut (mm)", value="35")
    myalgia = st.selectbox("Myalgia", ["(+)", "(-)"], index=1)
    myof = st.selectbox("Myofascial pain", ["(+)", "(-)"], index=1)

    eo_lines.append(f"TMJ Dextra dengan clicking {click_d}, popping {pop_d}, delayed {del_d}, nyeri palpasi {pain_d}")
    eo_lines.append(f"TMJ Sinistra dengan clicking {click_s}, popping {pop_s}, delayed {del_s}, nyeri palpasi {pain_s}")
    if dev == "(+)":
        eo_lines.append(f"Deviasi mandibula (+) ke arah {dev_side}")
    else:
        eo_lines.append("Deviasi mandibula (-)")
    if mouth_mm:
        eo_lines.append(f"Bukaan mulut ± {mouth_mm} mm")
    eo_lines.append(f"Myalgia {myalgia}")
    eo_lines.append(f"Myofascial pain {myof}")

    io_lines=[]
    # dental status quick
    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=0)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=1)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional)", height=90, placeholder="Contoh:\nFully erupted gigi 18, 48 dengan hiperemis (+)...\nEdentulous a.r gigi 28, 38")
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def fraktur_builder():
    st.subheader("EO/IO Cepat — Fraktur/Trauma")
    eo_lines=[]
    face = st.selectbox("Wajah", ["Wajah asimetris", "Wajah simetris"], index=0)
    nasal_dev = st.selectbox("Deviasi nasal", ["(+)", "(-)"], index=0)
    nasal_side = st.selectbox("Arah deviasi (kalau +)", ["dextra", "sinistra"], index=0)
    mouth_open = st.selectbox("Bukaan mulut", ["normal", "terbatas"], index=0)

    eo_lines.append(f"{face}" + (f" dengan deviasi nasal ke arah {nasal_side}" if nasal_dev=="(+)" else "") + f" dan bukaan mulut {mouth_open}")

    st.markdown("**Tanda fraktur rahang**")
    c1,c2,c3,c4 = st.columns(4)
    with c1: malok = st.selectbox("Maloklusi", ["(+)", "(-)"], index=1)
    with c2: floatj = st.selectbox("Floating jaw", ["(+)", "(-)"], index=1)
    with c3: step = st.selectbox("Step deformity", ["(+)", "(-)"], index=1)
    with c4: trismus = st.selectbox("Trismus", ["(+)", "(-)"], index=1)
    eo_lines += [f"Maloklusi {malok}", f"Floating jaw {floatj}", f"Step deformity {step}"]
    if trismus=="(+)":
        bm = st.text_input("Bukaan mulut (mm)", value="")
        if bm: eo_lines.append(f"Bukaan mulut ± {bm} mm")

    st.markdown("**Cedera intraoral/dentoalveolar**")
    io_lines=[]
    # vulnus
    vulnus = st.checkbox("Vulnus laceratum?", value=True)
    if vulnus:
        area = st.text_input("Lokasi vulnus (contoh: ar gigi 12-22)", value="")
        hyper = st.selectbox("Hiperemis", ["(+)", "(-)"], index=0)
        clot = st.selectbox("Blood clot", ["(+)", "(-)"], index=1)
        bleed = st.selectbox("Active bleeding", ["(+)", "(-)"], index=1)
        line = "Vulnus laceratum"
        if area: line += f" {area}"
        line += f" dengan hiperemis {hyper}, blood clot {clot}, active bleeding {bleed}"
        io_lines.append(line)

    intrusion_teeth = st.multiselect("Intrusi gigi (opsional)", TEETH, default=[])
    if intrusion_teeth:
        io_lines.append(f"Intrusi gigi {', '.join(intrusion_teeth)}")

    avulsion = st.multiselect("Avulsi gigi (opsional)", TEETH, default=[])
    if avulsion:
        io_lines.append(f"Avulsi gigi {', '.join(avulsion)}")

    mobility = st.multiselect("Mobile gigi (opsional)", TEETH, default=[])
    if mobility:
        deg = st.selectbox("Derajat mobile", ["°1","°2","°3"], index=1)
        io_lines.append(f"Mobile {deg} gigi {', '.join(mobility)}")

    ellis2 = st.multiselect("Fraktur Ellis Klas II", TEETH, default=[])
    if ellis2:
        io_lines.append(f"Fraktur Ellis Klas II gigi {', '.join(ellis2)}")
    ellis5 = st.multiselect("Fraktur Ellis Klas V", TEETH, default=[])
    if ellis5:
        io_lines.append(f"Fraktur Ellis Klas V gigi {', '.join(ellis5)}")

    sisa = st.multiselect("Sisa akar", TEETH, default=[])
    if sisa:
        io_lines.append(f"Sisa akar ar gigi {', '.join(sisa)}")

    kalk = st.selectbox("Kalkulus", ["Kalkulus (+)", "Kalkulus (-)"], index=1)
    oh = st.selectbox("OH", ["OH Baik", "OH sedang", "OH buruk"], index=0)
    io_lines += [kalk, oh]

    extra = st.text_area("Tambahan IO (opsional)", height=90)
    io_lines += [clean(x) for x in extra.splitlines() if clean(x)]
    return eo_lines, io_lines

def fistula_builder():
    # reuse infection + add fistula note
    eo_lines, io_lines = infeksi_builder("Fistula orocutaneous")
    add = st.text_input("Tambahan fistula (opsional) (contoh: fistula ar bukalis sinistra)", value="")
    if add:
        eo_lines.insert(0, add)
    return eo_lines, io_lines

def generic_eo_io():
    st.subheader("EO/IO — Generic (fallback)")
    eo = st.text_area("EO (1 baris = 1 poin)", height=120)
    io = st.text_area("IO (1 baris = 1 poin)", height=120)
    return [clean(x) for x in eo.splitlines() if clean(x)], [clean(x) for x in io.splitlines() if clean(x)]

def build_eo_io(case_name: str):
    if case_name == "Impaksi":
        return impaksi_builder()
    if case_name in ["Abses", "Selulitis"]:
        return infeksi_builder(case_name)
    if case_name == "Fistula orocutaneous":
        return fistula_builder()
    if case_name == "Tumor":
        return tumor_builder()
    if case_name == "Odontogenic cyst":
        return cyst_builder()
    if case_name == "TMD":
        return tmd_builder()
    if case_name == "Fraktur":
        return fraktur_builder()
    return generic_eo_io()

# =========================
# Stage builders
# =========================
def build_awal(case_name: str, ident: dict, ttv: dict, eo_lines: List[str], io_lines: List[str], keluhan: str, h: dict, A_lines: List[str], plan_lines: List[str], residen: str, dpjp: str, rs: str, tgl: date) -> str:
    hari = day_name_id(tgl)
    header = f"Assalamualaikum dokter.\nMaaf mengganggu, izin melaporkan Pasien Rawat Jalan {rs}, {hari} ({fmt_ddmmyyyy(tgl)})\n\n"
    ident_line = f"{ident['nama']} / {ident['jk']} / {ident['umur']} / Rawat Jalan / {ident['pembiayaan']} / {rs} / RM {ident['rm']}\n\n"
    og = [
        f"KU : {ttv['ku']}",
        f"TD : {ttv['td']}",
        f"N   : {ttv['nadi']} x/menit",
        f"P   : {ttv['rr']} x/menit",
        f"S   : {ttv['temp']} °C",
        f"SpO2: {ttv['spo2']}% (free air)",
        f"BB : {ttv['bb']} kg",
        f"TB : {ttv['tb']} cm",
    ]
    S = f"Pasien {ident['jk_long']} datang dengan keluhan {keluhan}. " + build_history_sentence(h)
    return (
        header + ident_line +
        f"S: {S}\n\n"
        "O:\nStatus Generalis:\n" + "\n".join(og) + "\n\n"
        "Status Lokalis:\nE.O:\n" + join_bullets(eo_lines) + "\n\n"
        "I.O:\n" + join_bullets(io_lines) + "\n\n"
        "A:\n" + join_bullets(A_lines, bullet="•⁠  ⁠") + "\n\n"
        "P:\n" + join_bullets(plan_lines, bullet="•⁠  ⁠") + "\n\n"
        "Mohon instruksi selanjutnya dok.\nTerima kasih.\n\n"
        f"Residen: {residen}\n\nDPJP : {dpjp}\n"
    )

def build_preop(parsed: ParsedSoap, overrides: dict, penunjang_block_raw: str, plan_lines: List[str], tindakan: str, anestesi: str, jam_op: str, zona: str, tgl_lap: date, tgl_op: date, residen: str, dpjp: str, meds: List[str]) -> str:
    hari_lap = day_name_id(tgl_lap)
    hari_op = day_name_id(tgl_op)
    header = f"{parsed.sapaan}\n{parsed.pembuka} Pasien Rencana Operasi {overrides['rs']}, {hari_lap} ({fmt_ddmmyyyy(tgl_lap)})\n\n"
    ident = f"{overrides['nama']} / {overrides['jk']} / {overrides['umur']} / {overrides['pembiayaan']} / Rawat Inap / {overrides['kamar']} / {overrides['rs']} / RM {overrides['rm']}\n\n"
    pen = ("Pemeriksaan penunjang :\n" + penunjang_block_raw.strip() + "\n\n") if clean(penunjang_block_raw) else ""
    tindakan_final = f"•⁠  ⁠Pro {tindakan} dalam {anestesi} pada hari {hari_op}, {fmt_ddmmyyyy(tgl_op)} Pukul {jam_op} {zona} di {overrides['rs']}"
    meds = [x for x in meds if clean(x)]
    meds_block = ("\nMedikasi:\n" + join_bullets(meds, bullet="•⁠  ⁠") + "\n") if meds else ""
    return (
        header + ident +
        f"S: {overrides['S']}\n\n"
        "O:\nStatus Generalis:\n" + (overrides['O_generalis'] + "\n\n" if clean(overrides['O_generalis']) else "\n") +
        "Status Lokalis:\nEO:\n" + (overrides['EO'] + "\n\n" if clean(overrides['EO']) else "\n") +
        "IO:\n" + (overrides['IO'] + "\n\n" if clean(overrides['IO']) else "\n") +
        pen +
        "A:\n" + (overrides['A'] + "\n\n" if clean(overrides['A']) else "\n") +
        "P:\n" + join_bullets(plan_lines, bullet="•⁠  ⁠") + "\n" +
        tindakan_final + "\n\n" +
        meds_block +
        "Mohon instruksi selanjutnya dokter.\nTerima kasih.\n\n"
        f"Residen: {residen}\n\nDPJP : {dpjp}\n"
    )

# =========================
# UI
# =========================
st.set_page_config(page_title="SuperSOAP v5", layout="centered")
st.title("SuperSOAP v5 — EO/IO Smart Builder untuk Semua Kasus")

tab_awal, tab_preop, tab_pod0, tab_pod1, tab_lapop = st.tabs(["Awal", "Pre-Op", "POD 0", "POD 1", "Laporan Operasi"])

# ---- AWAL
with tab_awal:
    st.caption("Awal = pasien baru datang. Form + checklist EO/IO (semi otomatis).")
    case_name = st.selectbox("Kasus", CASES, index=CASES.index("Impaksi"), key="awal_case")

    st.subheader("Identitas")
    c1,c2 = st.columns(2)
    with c1:
        nama = st.text_input("Nama (Tn./Ny./Nn./An.)", value="", key="awal_nama")
        jk = st.selectbox("JK", ["L","P"], index=1, key="awal_jk")
        umur = st.text_input("Umur", value="", key="awal_umur")
        pembiayaan = st.text_input("Pembiayaan", value="BPJS", key="awal_pay")
    with c2:
        rm = st.text_input("RM", value="", key="awal_rm")
        rs = st.text_input("RS", value="RSGMP UNHAS", key="awal_rs")
        tanggal = st.date_input("Tanggal", value=datetime.now(TZ).date(), key="awal_tgl")

    jk_long = "laki-laki" if jk=="L" else "perempuan"
    keluhan = st.text_area("Keluhan utama", height=80, key="awal_keluhan")

    with st.expander("Riwayat (Alergi/Sistemik/Obat rutin/Kondisi sekarang)", expanded=True):
        hist = history_blocks()

    st.subheader("TTV")
    t1,t2,t3 = st.columns(3)
    with t1:
        ku = st.selectbox("KU", ["Baik/Compos Mentis", "Sedang", "Buruk"], index=0, key="awal_ku")
        td = st.text_input("TD", value="120/70 mmHg", key="awal_td")
        nadi = st.number_input("Nadi", min_value=0, max_value=220, value=80, step=1, key="awal_nadi")
    with t2:
        rr = st.number_input("RR", min_value=0, max_value=80, value=19, step=1, key="awal_rr")
        temp = st.number_input("Suhu", min_value=30.0, max_value=42.0, value=36.7, step=0.1, key="awal_temp")
        spo2 = st.number_input("SpO2", min_value=0, max_value=100, value=99, step=1, key="awal_spo2")
    with t3:
        bb = st.number_input("BB (kg)", min_value=0.0, max_value=200.0, value=0.0, step=0.1, key="awal_bb")
        tb = st.number_input("TB (cm)", min_value=0.0, max_value=230.0, value=0.0, step=0.5, key="awal_tb")

    st.divider()
    eo_lines, io_lines = build_eo_io(case_name)

    st.divider()
    st.subheader("A & Plan")
    A_text = st.text_area("Diagnosis (1 baris = 1 diagnosis)", height=110, key="awal_A")
    A_lines = [clean(x) for x in A_text.splitlines() if clean(x)]
    plan_text = st.text_area("Plan (1 baris = 1 item)", height=120, key="awal_plan")
    plan_lines = [clean(x) for x in plan_text.splitlines() if clean(x)]

    residen = split_people_list(st.text_area("Residen", height=60, key="awal_res"))
    dpjp = st.text_input("DPJP", value="", key="awal_dpjp")

    if st.button("Generate SOAP Awal", type="primary", use_container_width=True, key="awal_gen"):
        ident = {"nama": nama, "jk": jk, "jk_long": jk_long, "umur": umur, "pembiayaan": pembiayaan, "rm": rm}
        ttv = {"ku": ku, "td": td, "nadi": int(nadi), "rr": int(rr), "temp": float(temp), "spo2": int(spo2), "bb": float(bb), "tb": float(tb)}
        out = build_awal(case_name, ident, ttv, eo_lines, io_lines, keluhan, hist, A_lines, plan_lines, residen, dpjp, rs, tanggal)
        st.text_area("Output", value=out, height=520)
        st.download_button("Download .txt", data=out.encode("utf-8"), file_name="soap_awal.txt", mime="text/plain", use_container_width=True)

# ---- PRE-OP
with tab_preop:
    st.caption("Pre-Op = paste SOAP mentah + MINLAP. (BB/TB TIDAK diparse otomatis sesuai aturanmu).")
    case_name = st.selectbox("Kasus (untuk assist EO/IO)", CASES, index=CASES.index("Impaksi"), key="pre_case")

    raw = st.text_area("SOAP mentah (khusus Pre-Op)", height=200, key="pre_raw")
    minlap = st.text_area("MINLAP (khusus Pre-Op)", height=200, key="pre_minlap")

    parsed = ParsedSoap()
    if raw.strip():
        parsed = parse_raw_soap_preop_only(raw)

    st.subheader("Identitas (auto-fill, bisa override)")
    c1,c2 = st.columns(2)
    with c1:
        nama = st.text_input("Nama", value=parsed.nama, key="pre_nama")
        jk = st.text_input("JK", value=parsed.jk, key="pre_jk")
        umur = st.text_input("Umur", value=parsed.umur, key="pre_umur")
        pembiayaan = st.text_input("Pembiayaan", value=parsed.pembiayaan or "BPJS", key="pre_pay")
    with c2:
        rm = st.text_input("RM", value=parsed.rm, key="pre_rm")
        rs = st.text_input("RS", value=parsed.rs, key="pre_rs")
        kamar = st.text_input("Kamar/Bed", value=parsed.kamar or "", key="pre_kamar")
        residen = split_people_list(st.text_area("Residen", value=parsed.residen or "", height=60, key="pre_res"))
    dpjp = st.text_input("DPJP", value=parsed.dpjp or "", key="pre_dpjp")

    st.subheader("Jadwal operasi")
    today = datetime.now(TZ).date()
    tgl_lap = st.date_input("Tanggal laporan", value=today, key="pre_tgl_lap")
    tgl_op = st.date_input("Tanggal operasi", value=today + timedelta(days=1), key="pre_tgl_op")
    zona = st.text_input("Zona waktu", value="WITA", key="pre_zona")
    jam_from_minlap = parse_minlap_jam(minlap)
    jam_op = st.text_input("Jam operasi", value=jam_from_minlap or "08.00", key="pre_jam")
    anestesi = st.text_input("Anestesi", value="general anestesi", key="pre_an")

    puasa_default = ""
    ab_default = ""
    op_parsed = parse_hhmm(jam_op)
    if op_parsed:
        ph, pm = minus_minutes(op_parsed[0], op_parsed[1], 6*60)
        ah, am = minus_minutes(op_parsed[0], op_parsed[1], 60)
        puasa_default = fmt_time(ph, pm)
        ab_default = fmt_time(ah, am)

    st.subheader("Isi SOAP (auto dari mentah, edit)")
    S = st.text_area("S", value=parsed.S or "", height=110, key="pre_S")
    O_generalis = st.text_area("O - Status Generalis", value=parsed.O_generalis or "", height=110, key="pre_Og")
    EO = st.text_area("EO", value=parsed.EO or "", height=110, key="pre_EO")
    IO = st.text_area("IO", value=parsed.IO or "", height=110, key="pre_IO")
    A = st.text_area("A", value=parsed.A or "", height=90, key="pre_A")

    with st.expander("Assist EO/IO (opsional): checklist sesuai kasus", expanded=False):
        eo_lines, io_lines = build_eo_io(case_name)
        if st.button("➡️ Replace EO/IO dari checklist", use_container_width=True, key="pre_replace"):
            st.session_state["pre_EO_override"] = join_bullets(eo_lines, bullet="•⁠  ⁠")
            st.session_state["pre_IO_override"] = join_bullets(io_lines, bullet="•⁠  ⁠")
            st.rerun()
    EO = st.session_state.get("pre_EO_override", EO)
    IO = st.session_state.get("pre_IO_override", IO)

    st.divider()
    st.subheader("Penunjang (dari MINLAP, format dijaga)")
    penunjang_raw = parse_minlap_penunjang_block(minlap) if minlap.strip() else ""
    penunjang_preview = st.text_area("Penunjang", value=penunjang_raw, height=220, key="pre_pen")

    st.divider()
    st.subheader("Plan wajib (otomatis)")
    bb = st.number_input("BB (kg) untuk hitung IVFD (isi manual)", min_value=0.0, max_value=200.0, value=0.0, step=0.1, key="pre_bb")
    drip_factor = st.selectbox("Drip factor", [20,60], index=0, key="pre_df")
    suggested_tpm = tpm_from_ml_per_hr(maintenance_ml_per_hr_421(bb), drip_factor) if bb>0 else 0

    include_ivfd = st.checkbox("IVFD", value=True, key="pre_ivfd_on")
    include_puasa = st.checkbox("Puasa 6 jam", value=True, key="pre_puasa_on")
    include_ab = st.checkbox("Antibiotik 1 jam", value=True, key="pre_ab_on")

    plan_lines=[]
    plan_lines.append("ACC TS Anestesi")

    if include_ivfd:
        cairan = st.text_input("Cairan", value="RL", key="pre_cairan")
        tpm = st.number_input("tpm", min_value=0, max_value=250, value=int(suggested_tpm) if suggested_tpm else 0, step=1, key="pre_tpm")
        drip_label = "makrodrips" if drip_factor==20 else "mikrodrips"
        plan_lines.append(f"IVFD {cairan} {tpm} tpm ({drip_label})" if tpm>0 else f"IVFD {cairan} (isi tpm) ({drip_label})")

    if include_puasa:
        puasa_mulai = st.text_input("Mulai puasa (auto)", value=puasa_default, key="pre_puasa")
        if clean(puasa_mulai):
            plan_lines.append(f"Puasa 6 jam pre op atau sesuai instruksi dari TS. Anestesi yaitu mulai Pukul {puasa_mulai} {zona}")

    plan_lines += [
        "Pasien menyikat gigi sebelum tidur dan sebelum ke kamar operasi",
        "Gunakan masker bedah saat ke kamar operasi",
    ]

    if include_ab:
        ab_nama = st.text_input("Antibiotik", value="Ceftriaxone", key="pre_ab")
        ab_dosis = st.text_input("Dosis", value="1 gr", key="pre_ab_dose")
        ab_jam = st.text_input("Jam antibiotik (auto)", value=ab_default, key="pre_ab_time")
        skin = st.checkbox("Skin test terlebih dahulu", value=True, key="pre_skin")
        skin_phrase = " (skin test terlebih dahulu)" if skin else ""
        plan_lines.append(f"Pasien rencana diberikan antibiotik profilaksis {ab_nama} {ab_dosis}, 1 jam sebelum operasi{skin_phrase} pada Pukul {ab_jam} {zona}")

    extra_plan = st.text_area("Plan tambahan (opsional)", height=110, key="pre_extra")
    plan_lines += [clean(x) for x in extra_plan.splitlines() if clean(x)]

    tindakan = st.text_input("Tindakan (auto dari P)", value=parsed.tindakan_hint or "", key="pre_tind")
    meds = st.text_area("Medikasi (opsional)", height=110, key="pre_meds")
    meds_items = [clean(x) for x in meds.splitlines() if clean(x)]

    if st.button("Generate SOAP Pre-Op", type="primary", use_container_width=True, key="pre_gen"):
        overrides = {
            "nama": nama, "jk": jk, "umur": umur, "pembiayaan": pembiayaan,
            "kamar": kamar or "(isi kamar/bed)", "rm": rm, "rs": rs,
            "S": S, "O_generalis": O_generalis, "EO": EO, "IO": IO, "A": A
        }
        out = build_preop(parsed, overrides, penunjang_preview, plan_lines, tindakan or "(isi tindakan)", anestesi, jam_op, zona, tgl_lap, tgl_op, residen or "-", dpjp or "-", meds_items)
        st.text_area("Output", value=out, height=520)
        st.download_button("Download .txt", data=out.encode("utf-8"), file_name="soap_preop.txt", mime="text/plain", use_container_width=True)

# ---- POD 0/1 (unchanged simple, question-based)
def pod_builder(stage: str):
    st.caption(f"{stage} = SOAP pasca operasi. Tidak ada MINLAP/mentah.")
    rs = st.text_input("RS", value="RSGMP UNHAS", key=f"{stage}_rs")
    tanggal = st.date_input("Tanggal", value=datetime.now(TZ).date(), key=f"{stage}_tgl")
    nama = st.text_input("Nama", value="", key=f"{stage}_nama")
    jk = st.selectbox("JK", ["L","P"], index=0, key=f"{stage}_jk")
    umur = st.text_input("Umur", value="", key=f"{stage}_umur")
    pembiayaan = st.text_input("Pembiayaan", value="BPJS", key=f"{stage}_pay")
    kamar = st.text_input("Kamar/Bed", value="", key=f"{stage}_kamar")
    rm = st.text_input("RM", value="", key=f"{stage}_rm")

    st.subheader("Keluhan pasca operasi")
    nyeri = st.radio("Nyeri?", ["Tidak", "Ya"], horizontal=True, key=f"{stage}_nyeri")
    nyeri_lokasi=""
    nyeri_skala=""
    if nyeri=="Ya":
        nyeri_lokasi = st.text_input("Lokasi nyeri", value="", key=f"{stage}_nyeri_lokasi")
        nyeri_skala = st.selectbox("Skala nyeri (NRS)", ["1-3 (ringan)","4-6 (sedang)","7-10 (berat)"], index=1, key=f"{stage}_nyeri_skala")
    mual = st.radio("Mual/muntah?", ["Tidak", "Ya"], horizontal=True, key=f"{stage}_mual")
    perdarahan = st.radio("Perdarahan dari luka?", ["Tidak", "Ya"], horizontal=True, key=f"{stage}_darah")

    st.subheader("Kondisi luka")
    luka = st.selectbox("Kondisi luka", ["Kering", "Serosanguinous sedikit", "Pus/bernanah", "Bengkak/hiperemis"], index=0, key=f"{stage}_luka")
    bau = st.radio("Bau?", ["Tidak", "Ya"], horizontal=True, key=f"{stage}_bau")

    st.subheader("TTV")
    td = st.text_input("TD", value="120/70 mmHg", key=f"{stage}_td")
    nadi = st.number_input("Nadi", min_value=0, max_value=220, value=80, step=1, key=f"{stage}_nadi")
    rr = st.number_input("RR", min_value=0, max_value=80, value=19, step=1, key=f"{stage}_rr")
    temp = st.number_input("Suhu", min_value=30.0, max_value=42.0, value=36.7, step=0.1, key=f"{stage}_temp")
    spo2 = st.number_input("SpO2", min_value=0, max_value=100, value=99, step=1, key=f"{stage}_spo2")

    plan = st.text_area("Plan", height=100, key=f"{stage}_plan")
    meds = st.text_area("Medikasi", height=100, key=f"{stage}_meds")
    residen = split_people_list(st.text_area("Residen", height=60, key=f"{stage}_res"))
    dpjp = st.text_input("DPJP", value="", key=f"{stage}_dpjp")

    if st.button(f"Generate {stage}", type="primary", use_container_width=True, key=f"{stage}_gen"):
        hari = day_name_id(tanggal)
        header = f"Assalamualaikum dok,\nMaaf mengganggu, izin melaporkan Pasien Rawat Inap {rs}, {hari} ({fmt_ddmmyyyy(tanggal)})\n\n"
        ident = f"{nama} / {jk} / {umur} / {pembiayaan} / Rawat Inap / {kamar} / {rs} / RM {rm}\n\n"
        s_parts=[]
        s_parts.append("Tidak ada keluhan nyeri pada daerah operasi." if nyeri=="Tidak" else f"Ada keluhan nyeri pada {nyeri_lokasi or 'daerah operasi'} dengan skala {nyeri_skala}.")
        if mual=="Ya": s_parts.append("Keluhan mual/muntah (+).")
        if perdarahan=="Ya": s_parts.append("Perdarahan dari luka operasi (+).")
        s = " ".join(s_parts)
        o = (
            "Status Generalis:\n"
            f"TD : {td}\nN  : {int(nadi)} x/menit\nP  : {int(rr)} x/menit\nS  : {float(temp):.1f} °C\nSpO2: {int(spo2)}% (free air)\n\n"
            "Status Lokalis:\n"
            f"Luka operasi: {luka}\nBau: {bau}\n"
        )
        out = (
            header + ident +
            f"S: {s}\n\nO:\n{o}\n"
            "A:\n•⁠  ⁠Post operative state\n\n"
            "P:\n" + join_bullets([x for x in plan.splitlines() if clean(x)], bullet="•⁠  ⁠") + "\n\n"
            "Medikasi:\n" + join_bullets([x for x in meds.splitlines() if clean(x)], bullet="•⁠  ⁠") + "\n\n"
            "Mohon instruksi selanjutnya dokter.\nTerima kasih.\n\n"
            f"Residen: {residen}\n\nDPJP : {dpjp}\n"
        )
        st.text_area("Output", value=out, height=520)
        st.download_button("Download .txt", data=out.encode("utf-8"), file_name=f"{stage.lower().replace(' ','_')}.txt", mime="text/plain", use_container_width=True)

with tab_pod0:
    pod_builder("POD 0")
with tab_pod1:
    pod_builder("POD 1")

with tab_lapop:
    st.caption("Hanya tampilkan teks laporan operasi (paste → tampil).")
    lapop = st.text_area("Paste laporan operasi", height=280, key="lapop")
    if st.button("Tampilkan Laporan Operasi", use_container_width=True, key="lapop_btn"):
        st.text_area("Laporan Operasi", value=lapop, height=520)
