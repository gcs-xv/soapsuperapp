
# SuperSOAP Maker (Streamlit)

Ini MVP “superapp” untuk bikin SOAP **Awal**, **Pre-Op**, **POD 0**, **POD 1** berbasis:
1) paste SOAP mentah (opsional),
2) paste **MINLAP** (opsional, tapi paling membantu untuk penunjang & jam operasi),
3) form pertanyaan “YES/NO” biar cepat.

## File yang dibuat
- `supersoap_app.py` = aplikasi Streamlit
- `supersoap_schema_v1.json` = schema pertanyaan & (opsional) laporan operasi per kasus

## Cara jalanin (lokal)
1) Pastikan Python 3.10+ terinstall.
2) Buat environment (opsional tapi disarankan):
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Mac/Linux
   # atau Windows: .venv\Scripts\activate
   ```
3) Install dependency:
   ```bash
   pip install streamlit python-dateutil
   ```
4) Jalankan:
   ```bash
   streamlit run supersoap_app.py
   ```
5) Buka link yang muncul (biasanya `http://localhost:8501`).

## Cara pakai cepat (di HP juga bisa)
- Pilih **Kasus** dan **Stage**.
- Tab **1) Paste**
  - paste SOAP mentah (kalau ada)
  - paste MINLAP (kalau ada)
  - klik **Auto-fill dari paste**
- Tab **2) Form**
  - identitas cek/rapikan
  - isi pertanyaan (tinggal toggle / pilih)
  - kalau PreOp: isi antibiotik profilaksis & jam operasi. IVFD tpm akan disarankan otomatis dari BB.
- Tab **3) Output**
  - tinggal copy atau download.

## “Tutorial mode”
Di sidebar ada toggle **Tutorial mode**. Kalau ON, tiap field punya hint singkat biar orang awam bisa isi.

## Catatan penting (sesuai request)
- MINLAP: blok “Pemeriksaan penunjang” ditampilkan **apa adanya** (tanpa normalisasi spasi/bullet).
- Tindakan: app coba ambil otomatis dari baris **P: Pro ...** di SOAP mentah/minlap.
- IVFD tpm: app kasih saran dari BB menggunakan rule 4-2-1 (ini hanya “saran cepat”, tetap verifikasi klinis/aturan RS).
- Ini MVP. Nanti tinggal kita iterasi: tambah pertanyaan per kasus, tambah O/A/P yang lebih “template-aware”, dll.

## Update schema tanpa utak-atik kode
Edit `supersoap_schema_v1.json` untuk:
- tambah pertanyaan
- tambah kasus baru
- isi/ubah laporan operasi per kasus

