"""
Sumber data dashboard: Google Sheet "Laporan Iklan Interaksi DMF 2".

Sheet yang dibaca:
- Madha        : biaya iklan & jumlah nomor per CS per hari
- Dana Iklan   : modal iklan per CS, akumulasi, dan sisa (kolom Keterangan)
- RECAP (spreadsheet donasi terpisah): data transfer donasi mentah, sumber
  resi & donasi. Bulan = bulan tanggal transfer.

Cara hitung mengikuti rumus sheet bulanan (versi September 2026), tapi
tanpa batas 1.000 baris yang membuat sheet Juli/Agustus kurang hitung.

Data donatur (nama, nomor WA) TIDAK pernah dikeluarkan dari modul ini,
hanya angka rekap per CS.

Daftar CS & nama lain (alias) disimpan di data/cs.csv (menu Kelola CS).
"""
import datetime as dt
import io
import os
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
CS_FILE = DATA_DIR / "cs.csv"

BULAN_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}


# =========================================================
# UTIL
# =========================================================

def norm(teks) -> str:
    """Nama dibandingkan tanpa beda huruf besar/kecil dan spasi."""
    if teks is None or (isinstance(teks, float) and pd.isna(teks)):
        return ""
    return " ".join(str(teks).split()).lower()


def kode_bulan(nilai):
    """Tanggal atau teks 'September 2026' -> '2026-09'."""
    if isinstance(nilai, (dt.datetime, dt.date, pd.Timestamp)):
        return f"{nilai.year}-{nilai.month:02d}"
    if isinstance(nilai, str):
        bagian = nilai.strip().lower().split()
        if len(bagian) == 2 and bagian[0] in BULAN_ID and bagian[1].isdigit():
            return f"{bagian[1]}-{BULAN_ID[bagian[0]]:02d}"
    return None


def angka(nilai) -> float:
    try:
        return float(nilai)
    except (TypeError, ValueError):
        return 0.0


# =========================================================
# AMBIL FILE SHEET
# =========================================================

def unduh_sheet(sheet_id: str, akun_layanan: dict | None = None) -> bytes:
    """Unduh spreadsheet sebagai .xlsx.

    Kalau ada akun layanan (service account) Google, dipakai supaya sheet
    tidak perlu dibuka untuk umum. Tanpa itu, sheet harus bisa dibuka
    "siapa saja yang punya link".
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    if akun_layanan:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            akun_layanan,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        resp = AuthorizedSession(creds).get(url, timeout=120)
    else:
        resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    if "spreadsheetml" not in resp.headers.get("Content-Type", ""):
        raise RuntimeError(
            "Sheet tidak bisa dibaca. Pastikan sheet dibagikan ke akun layanan "
            "dashboard (atau bisa dibuka lewat link)."
        )
    return resp.content


def baca_sheet(isi_xlsx: bytes) -> dict:
    return pd.read_excel(
        io.BytesIO(isi_xlsx),
        sheet_name=["Madha", "Rekap Admin", "Dana Iklan"],
        header=None,
        engine="openpyxl",
    )


# =========================================================
# OLAH DATA
# =========================================================

def olah_iklan(madha: pd.DataFrame) -> pd.DataFrame:
    """Madha: A=Bulan, B=Tanggal, C=Nama, D=Biaya Iklan, E=Data Iklan (nomor)."""
    df = madha.iloc[2:, :5].copy()
    df.columns = ["bulan", "tanggal", "nama", "biaya_iklan", "nomor"]
    df["tanggal"] = pd.to_datetime(df["tanggal"], errors="coerce").dt.normalize()
    df["kunci"] = df["nama"].map(norm)
    df = df[(df["kunci"] != "") & df["tanggal"].notna()]
    df["biaya_iklan"] = df["biaya_iklan"].map(angka)
    df["nomor"] = df["nomor"].map(angka)
    return df.groupby(["tanggal", "kunci"], as_index=False)[["nomor", "biaya_iklan"]].sum()


def olah_resi(rekap: pd.DataFrame) -> pd.DataFrame:
    """Rekap Admin.

    Cadangan kalau RECAP tidak tersedia.
    Kiri : D=Tanggal, E=Nama CS, I=Ket Nomor, K=Nominal, N=Keterangan
    Kanan: P=Tanggal, Q=Nama CS, U=Ket Nomor (untuk hitung resi Perdana)
    """
    df = rekap.iloc[2:].copy()
    kol = lambda huruf: df.iloc[:, ord(huruf) - ord("A")] if ord(huruf) - ord("A") < df.shape[1] else pd.Series(index=df.index, dtype=object)

    tgl_kiri = pd.to_datetime(kol("D"), errors="coerce").dt.normalize()
    tgl_kanan = pd.to_datetime(kol("P"), errors="coerce").dt.normalize()
    ket = kol("I").map(norm)
    ket_donasi = kol("N").map(norm)
    nominal = kol("K").map(angka)
    kiri = pd.DataFrame({
        "tanggal": tgl_kiri,
        "kunci": kol("E").map(norm),
        "gulungan": (ket == "gulungan").astype(int),
        "donasi_perdana": nominal.where(ket_donasi == "perdana", 0.0),
        "donasi_gulungan": nominal.where(ket_donasi == "gulungan", 0.0),
    })
    kanan = pd.DataFrame({
        "tanggal": tgl_kanan,
        "kunci": kol("Q").map(norm),
        "perdana": (kol("U").map(norm) == "perdana").astype(int),
    })

    kiri = kiri[(kiri["kunci"] != "") & kiri["tanggal"].notna()]
    kanan = kanan[(kanan["kunci"] != "") & kanan["tanggal"].notna()]
    a = kiri.groupby(["tanggal", "kunci"], as_index=False).sum()
    b = kanan.groupby(["tanggal", "kunci"], as_index=False).sum()
    return a.merge(b, on=["tanggal", "kunci"], how="outer").fillna(0)


def jenis_resi(teks) -> str:
    """'PERDANA' / 'PERRDANA' -> 'perdana', 'GULUNGAN' -> 'gulungan'."""
    k = norm(teks).replace(" ", "")
    if k.startswith("perd") or k.startswith("perrd"):
        return "perdana"
    if k.startswith("gul"):
        return "gulungan"
    return ""


def olah_recap(isi_xlsx: bytes) -> pd.DataFrame:
    """RECAP: Timestamp, TANGGAL, NAMA CS, ..., KET NOMOR, BANK, NOMINAL."""
    df = pd.read_excel(io.BytesIO(isi_xlsx), sheet_name="RECAP", header=0, engine="openpyxl")
    tanggal = pd.to_datetime(df["TANGGAL"], errors="coerce")
    tanggal = tanggal.fillna(pd.to_datetime(df["Timestamp"], errors="coerce"))
    jenis = df["KET NOMOR"].map(jenis_resi)
    nominal = df["NOMINAL"].map(angka)
    hasil = pd.DataFrame({
        "tanggal": tanggal.dt.normalize(),
        "kunci": df["NAMA CS"].map(norm),
        "perdana": (jenis == "perdana").astype(int),
        "gulungan": (jenis == "gulungan").astype(int),
        "donasi_perdana": nominal.where(jenis == "perdana", 0.0),
        "donasi_gulungan": nominal.where(jenis == "gulungan", 0.0),
    })
    hasil = hasil[(hasil["kunci"] != "") & hasil["tanggal"].notna()]
    return hasil.groupby(["tanggal", "kunci"], as_index=False).sum()


def olah_dana(dana: pd.DataFrame) -> pd.DataFrame:
    """Dana Iklan: C=Nama Akun, D..H=modal per bulan, I=Jumlah modal,
    J=Akumulasi (profit/loss total), K=Keterangan (sisa iklan)."""
    rows = []
    for _, r in dana.iloc[2:].iterrows():
        nama = r.iloc[2]
        if norm(nama) in ("", "jumlah"):
            continue
        rows.append({
            "kunci": norm(nama),
            "modal_iklan": angka(r.iloc[8]),
            "akumulasi": angka(r.iloc[9]),
            "sisa_iklan": angka(r.iloc[10]),
        })
    return pd.DataFrame(rows, columns=["kunci", "modal_iklan", "akumulasi", "sisa_iklan"])


# =========================================================
# DAFTAR CS & ALIAS
# =========================================================

def load_cs() -> pd.DataFrame:
    kolom = {"nama": str, "aktif": bool, "nama_lain": str}
    if not CS_FILE.exists():
        return pd.DataFrame({k: pd.Series(dtype=t) for k, t in kolom.items()})
    df = pd.read_csv(CS_FILE, encoding="utf-8-sig", dtype={"nama": str, "nama_lain": str})
    if "nama_lain" not in df:
        df["nama_lain"] = ""
    df["nama_lain"] = df["nama_lain"].fillna("")
    df["aktif"] = df["aktif"].astype(str).str.lower().isin(["true", "1", "ya"])
    return df[list(kolom)]


def save_cs(df: pd.DataFrame) -> None:
    df = df.copy()
    df["nama"] = df["nama"].astype(str).str.strip()
    df = df[df["nama"].ne("") & df["nama"].ne("nan") & df["nama"].ne("None")]
    df = df.drop_duplicates(subset="nama", keep="first")
    df["aktif"] = df["aktif"].fillna(True).astype(bool)
    df["nama_lain"] = df["nama_lain"].fillna("").astype(str).str.strip()
    df[["nama", "aktif", "nama_lain"]].to_csv(CS_FILE, index=False)


def peta_alias(cs: pd.DataFrame) -> dict:
    """{nama/alias ternormalisasi: nama CS}. Alias dipisah koma."""
    peta = {}
    for _, r in cs.iterrows():
        peta[norm(r["nama"])] = r["nama"]
        for alias in str(r.get("nama_lain") or "").split(","):
            if norm(alias):
                peta[norm(alias)] = r["nama"]
    return peta


# =========================================================
# GABUNG
# =========================================================

def siapkan(isi_xlsx: bytes, cs: pd.DataFrame, isi_recap: bytes | None = None):
    """Hasil: (performa per hari per CS, dana iklan per CS, nama tak dikenal).

    Resi & donasi dari RECAP kalau isi_recap ada, kalau tidak dari Rekap Admin.
    """
    sheet = baca_sheet(isi_xlsx)
    iklan = olah_iklan(sheet["Madha"])
    resi = olah_recap(isi_recap) if isi_recap else olah_resi(sheet["Rekap Admin"])
    dana = olah_dana(sheet["Dana Iklan"])

    peta = peta_alias(cs)
    tak_dikenal = set()

    def pasang_nama(df):
        df = df.copy()
        df["nama"] = df["kunci"].map(peta)
        tak_dikenal.update(df.loc[df["nama"].isna(), "kunci"])
        return df.dropna(subset=["nama"]).drop(columns="kunci")

    iklan, resi, dana = pasang_nama(iklan), pasang_nama(resi), pasang_nama(dana)

    performa = iklan.merge(resi, on=["tanggal", "nama"], how="outer")
    performa = performa.groupby(["tanggal", "nama"], as_index=False).sum(numeric_only=True)
    dana = dana.groupby("nama", as_index=False).sum(numeric_only=True)
    return performa, dana, sorted(tak_dikenal)


def sheet_id_default() -> str | None:
    return os.environ.get("SHEET_ID")


# =========================================================
# STATUS CAMPAIGN DARI META ADS
# =========================================================

META_API = "https://graph.facebook.com/v21.0"

# Sumber biaya & nomor iklan dari Meta (menggantikan catatan manual Madha).
#   kata=None : semua ad set, dicocokkan ke CS lewat nama ad set / campaign
#   kata="x"  : hanya ad set yang namanya memuat "x", dicatat atas nama `cs`
ATURAN_META = [
    # HKM 2: semua ad set, nama ad set = nama CS
    {"akun": "373308251987522", "kata": None, "cs": None},
    # HKM 3: hanya ad set "Bu Zakiyah/..." -> Madina (nomor WA lain diabaikan)
    {"akun": "346897904809464", "kata": "zakiyah", "cs": "Madina"},
]


def cs_untuk_iklan(akun: str, adset: str, campaign: str, peta: dict):
    """Nama CS pemilik iklan menurut ATURAN_META (None = diabaikan)."""
    aturan = next((a for a in ATURAN_META if a["akun"] == akun), None)
    if aturan and aturan["kata"]:
        return aturan["cs"] if aturan["kata"] in norm(adset) else None
    return cari_cs(adset, peta) or cari_cs(campaign, peta)


def iklan_aktif(token: str, akun_iklan: list[str]) -> list[dict]:
    """Semua iklan yang sedang tayang (ACTIVE) di akun-akun iklan."""
    hasil = []
    for akun in akun_iklan:
        url = f"{META_API}/act_{akun.strip()}/ads"
        params = {
            "access_token": token,
            "limit": 500,
            "fields": "adset{name},campaign{name}",
            "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
        }
        while url:
            data = requests.get(url, params=params, timeout=60).json()
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "Error Meta API"))
            for ad in data.get("data", []):
                hasil.append({
                    "akun": akun.strip(),
                    "adset": ad.get("adset", {}).get("name", ""),
                    "campaign": ad.get("campaign", {}).get("name", ""),
                })
            url, params = data.get("paging", {}).get("next"), None
    return hasil


def cari_cs(teks: str, peta: dict):
    """Cari nama CS (atau nama lain) sebagai kata utuh di teks, yang terpanjang dulu."""
    kata = f" {norm(''.join(c if c.isalnum() else ' ' for c in str(teks)))} "
    for kunci in sorted(peta, key=len, reverse=True):
        if f" {kunci} " in kata:
            return peta[kunci]
    return None


def status_campaign(token: str, akun_iklan: list[str], cs: pd.DataFrame) -> dict:
    """{nama CS: jumlah iklan aktif} dicocokkan dari nama ad set (lalu campaign)."""
    peta = peta_alias(cs)
    jumlah = {}
    for ad in iklan_aktif(token, akun_iklan):
        nama = cs_untuk_iklan(ad["akun"], ad["adset"], ad["campaign"], peta)
        if nama:
            jumlah[nama] = jumlah.get(nama, 0) + 1
    return jumlah


# =========================================================
# TOPUP IKLAN (INPUT ADMIN)
# =========================================================

TOPUP_TAB = "Topup Iklan"
TOPUP_KOLOM = ["Tanggal", "Nama CS", "Nominal", "Diinput"]
TOPUP_FILE = DATA_DIR / "topup.csv"


def _sesi_sheets(akun_layanan: dict):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        akun_layanan, scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return AuthorizedSession(creds)


def _pastikan_tab_topup(sesi, sheet_id: str) -> None:
    info = sesi.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}",
        params={"fields": "sheets.properties.title"}, timeout=60,
    )
    info.raise_for_status()
    judul = [s["properties"]["title"] for s in info.json().get("sheets", [])]
    if TOPUP_TAB in judul:
        return
    sesi.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}:batchUpdate",
        json={"requests": [{"addSheet": {"properties": {"title": TOPUP_TAB}}}]},
        timeout=60,
    ).raise_for_status()
    sesi.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/'{TOPUP_TAB}'!A1:D1",
        params={"valueInputOption": "RAW"},
        json={"values": [TOPUP_KOLOM]}, timeout=60,
    ).raise_for_status()


def simpan_topup(baris: dict, sheet_id: str | None, akun_layanan: dict | None) -> str:
    """Simpan satu topup. Ke Google Sheet kalau ada akun layanan, kalau tidak ke file lokal.

    baris: {"tanggal": date, "nama": str, "nominal": int}
    Hasil: tempat data disimpan ("sheet" / "lokal").
    """
    nilai = [
        baris["tanggal"].strftime("%Y-%m-%d"),
        baris["nama"],
        int(baris["nominal"]),
        dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M"),
    ]
    if akun_layanan and sheet_id:
        sesi = _sesi_sheets(akun_layanan)
        _pastikan_tab_topup(sesi, sheet_id)
        sesi.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/'{TOPUP_TAB}'!A:D:append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": [nilai]}, timeout=60,
        ).raise_for_status()
        return "sheet"

    baru = pd.DataFrame([nilai], columns=TOPUP_KOLOM)
    if TOPUP_FILE.exists():
        baru = pd.concat([pd.read_csv(TOPUP_FILE, encoding="utf-8-sig"), baru], ignore_index=True)
    baru.to_csv(TOPUP_FILE, index=False)
    return "lokal"


def baca_topup(isi_xlsx: bytes | None, dari_sheet: bool) -> pd.DataFrame:
    """Riwayat topup: dari tab 'Topup Iklan' di sheet, atau dari file lokal."""
    kosong = pd.DataFrame(columns=["tanggal", "nama", "nominal", "diinput", "bulan"])
    if dari_sheet and isi_xlsx:
        buku = pd.ExcelFile(io.BytesIO(isi_xlsx), engine="openpyxl")
        if TOPUP_TAB not in buku.sheet_names:
            return kosong
        df = buku.parse(TOPUP_TAB)
    elif TOPUP_FILE.exists():
        df = pd.read_csv(TOPUP_FILE, encoding="utf-8-sig")
    else:
        return kosong
    df = df.reindex(columns=TOPUP_KOLOM)
    df.columns = ["tanggal", "nama", "nominal", "diinput"]
    df["tanggal"] = pd.to_datetime(df["tanggal"], errors="coerce")
    df["nominal"] = df["nominal"].map(angka)
    df = df.dropna(subset=["tanggal"])
    df["bulan"] = df["tanggal"].map(kode_bulan)
    return df


def _hasil_meta(baris: dict) -> float:
    """'Hasil' iklan interaksi = percakapan pesan dimulai (sama dengan Ads Manager)."""
    aksi = {a["action_type"]: angka(a["value"]) for a in baris.get("actions", [])}
    return aksi.get("onsite_conversion.messaging_conversation_started_7d", aksi.get("lead", 0.0))


def _potong_per_minggu(mulai: str, sampai: str) -> list[tuple[str, str]]:
    """Rentang tanggal dipecah per 7 hari supaya bisa diambil bersamaan."""
    awal, akhir = pd.Timestamp(mulai), pd.Timestamp(sampai)
    potongan = []
    while awal <= akhir:
        ujung = min(awal + pd.Timedelta(days=6), akhir)
        potongan.append((f"{awal:%Y-%m-%d}", f"{ujung:%Y-%m-%d}"))
        awal = ujung + pd.Timedelta(days=1)
    return potongan


def _ambil_insights(token: str, akun: str, mulai: str, sampai: str) -> list[dict]:
    import json

    url = f"{META_API}/act_{akun}/insights"
    params = {
        "access_token": token, "level": "adset", "time_increment": 1,
        "time_range": json.dumps({"since": mulai, "until": sampai}),
        "fields": "adset_name,campaign_name,spend,actions,date_start",
        "limit": 500,
    }
    hasil = []
    while url:
        data = requests.get(url, params=params, timeout=120).json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Error Meta API"))
        hasil += data.get("data", [])
        url, params = data.get("paging", {}).get("next"), None
    return hasil


def iklan_meta_harian(token: str, mulai: str, sampai: str, cs: pd.DataFrame) -> pd.DataFrame:
    """Biaya & nomor per hari per CS dari akun-akun di ATURAN_META.

    Diambil per potongan 7 hari secara bersamaan (jauh lebih cepat dari satu
    permintaan panjang). Hari tanpa biaya tetap diambil karena Meta bisa
    mencatat percakapan (atribusi 7 hari) di hari itu.
    """
    from concurrent.futures import ThreadPoolExecutor

    peta = peta_alias(cs)
    tugas = [(a["akun"], m, s) for a in ATURAN_META for m, s in _potong_per_minggu(mulai, sampai)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        hasil = list(pool.map(lambda t: (t[0], _ambil_insights(token, *t)), tugas))

    baris = []
    for akun, data in hasil:
        for r in data:
            nama = cs_untuk_iklan(akun, r.get("adset_name"), r.get("campaign_name"), peta)
            if nama:
                baris.append({
                    "tanggal": pd.Timestamp(r["date_start"]), "nama": nama,
                    "biaya_iklan": angka(r.get("spend")), "nomor": _hasil_meta(r),
                })
    df = pd.DataFrame(baris, columns=["tanggal", "nama", "biaya_iklan", "nomor"])
    return df.groupby(["tanggal", "nama"], as_index=False).sum()


def timpa_dengan_meta(performa: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Biaya & nomor CS di ATURAN_META diganti data Meta, per bulan.

    Untuk (CS, bulan) yang punya data di Meta, catatan Madha bulan itu diabaikan
    (Madha sering dicatat borongan, misal satu baris untuk sebulan).
    """
    if meta.empty:
        return performa
    df = performa.copy()
    bulan_df = df["tanggal"].dt.to_period("M")
    ada = set(zip(meta["nama"], meta["tanggal"].dt.to_period("M")))
    ditimpa = [(n, b) in ada for n, b in zip(df["nama"], bulan_df)]
    df.loc[ditimpa, ["biaya_iklan", "nomor"]] = 0
    df = pd.concat([df, meta], ignore_index=True).fillna(0)
    return df.groupby(["tanggal", "nama"], as_index=False).sum(numeric_only=True)
