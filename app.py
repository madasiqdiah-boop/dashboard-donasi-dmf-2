"""Dashboard Laporan Iklan Interaksi DMF 2 Kabupaten Serang."""
import pandas as pd
import streamlit as st

import io
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import data_source as ds

load_dotenv()

st.set_page_config(
    page_title="Dashboard DMF 2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Tampilan rapi di HP: judul kecil, kartu angka 2 per baris, jarak lebih rapat
st.markdown("""
<style>
.block-container { padding-top: 2.5rem; padding-bottom: 2rem; }
h1 { font-size: 1.9rem !important; padding-bottom: 0 !important; }
[data-testid="stMetricValue"] { font-size: 1.6rem; }
[data-testid="stMetric"] { padding: 0.7rem 1rem !important; }
[data-testid="stMetric"] > div,
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"] { padding: 0 !important; margin: 0 !important; min-height: 0 !important; }
[data-testid="stSelectbox"] { max-width: 320px; }
/* Jangan pudarkan tampilan saat update otomatis tiap menit */
[data-stale="true"], .stale-element { opacity: 1 !important; transition: none !important; }

@media (max-width: 640px) {
    .block-container { padding: 2.8rem 0.8rem 2rem 0.8rem; }
    h1 { font-size: 1.35rem !important; }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.5rem !important; }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 calc(50% - 0.5rem) !important;
        min-width: calc(50% - 0.5rem) !important;
        width: calc(50% - 0.5rem) !important;
    }
    [data-testid="stMetric"] { padding: 0.45rem 0.65rem !important; min-height: 0 !important; }
    [data-testid="stSelectbox"] { max-width: none; }
    .st-key-periode [data-testid="stColumn"] {
        flex: 1 1 100% !important; min-width: 100% !important; width: 100% !important;
    }
    [data-testid="stMetricLabel"] p { font-size: 0.75rem; }
    [data-testid="stMetricValue"] { font-size: 1.05rem; }
    button[data-baseweb="tab"] p { font-size: 0.85rem; }
    [data-baseweb="tab-list"] { gap: 0.6rem; }
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# ATURAN REKOMENDASI SCALE UP (bisa diubah)
# =========================================================

SCALE_UP_MIN_ROAS = 1.5          # donasi minimal 1,5x biaya iklan
SCALE_UP_MIN_CLOSING = 10        # closing rate minimal 10%
SCALE_UP_MIN_NOMOR = 30          # data cukup: minimal 30 nomor
EVALUASI_MAX_ROAS = 1.0          # di bawah 1 = rugi

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
    "Agustus", "September", "Oktober", "November", "Desember",
]


# =========================================================
# FORMAT ANGKA
# =========================================================

def nama_bulan(kode):
    tahun, bulan = kode.split("-")
    return f"{BULAN_ID[int(bulan)]} {tahun}"


def kosong(x):
    return isinstance(x, str) or pd.isna(x)


def rupiah(x):
    if kosong(x):
        return "–"
    tanda = "-" if x < 0 else ""
    return f"{tanda}{abs(round(x)):,.0f}".replace(",", ".")


def angka(x):
    if kosong(x):
        return "–"
    return f"{x:,.0f}".replace(",", ".")


def desimal(x):
    if kosong(x):
        return "–"
    return f"{x:.1f}".replace(".", ",")


# =========================================================
# HITUNGAN
# =========================================================

def rekomendasi(row):
    if row["biaya_iklan"] <= 0:
        return "–"
    if row["roas"] < EVALUASI_MAX_ROAS:
        return "🔴 Evaluasi"
    if (
        row["roas"] >= SCALE_UP_MIN_ROAS
        and row["closing_rate"] >= SCALE_UP_MIN_CLOSING
        and row["nomor"] >= SCALE_UP_MIN_NOMOR
    ):
        return "🟢 Layak Scale Up"
    return "🟡 Pertahankan"


def hitung(df):
    df = df.copy()
    df["cpr"] = df["biaya_iklan"] / df["nomor"].where(df["nomor"] > 0)
    df["all_resi"] = df["perdana"] + df["gulungan"]
    df["total_donasi"] = df["donasi_perdana"] + df["donasi_gulungan"]
    df["roas"] = df["total_donasi"] / df["biaya_iklan"].where(df["biaya_iklan"] > 0)
    df["closing_rate"] = df["perdana"] / df["nomor"].where(df["nomor"] > 0) * 100
    df["profit"] = df["total_donasi"] - df["biaya_iklan"]
    df["rekomendasi"] = df.apply(rekomendasi, axis=1)
    if "status_campaign" not in df:
        df["status_campaign"] = "⏳ Menunggu"
    return df


def baris_total(df):
    t = df[[
        "nomor", "biaya_iklan", "perdana", "gulungan",
        "donasi_perdana", "donasi_gulungan",
    ]].sum()
    total = pd.DataFrame([t])
    total["nama"] = "Jumlah"
    total = hitung(total)
    total["rekomendasi"] = ""
    total["status_campaign"] = ""
    return total


KOLOM_PERFORMA = ["nomor", "biaya_iklan", "perdana", "gulungan",
                  "donasi_perdana", "donasi_gulungan"]


def data_rentang(mulai, akhir, performa, cs):
    """Gabungkan daftar CS aktif + performa (dijumlah) untuk rentang tanggal."""
    aktif = cs[cs["aktif"]][["nama"]]
    pilih = performa[performa["tanggal"].between(pd.Timestamp(mulai), pd.Timestamp(akhir))]
    perf = pilih.groupby("nama", as_index=False)[KOLOM_PERFORMA].sum()
    df = aktif.merge(perf, on="nama", how="left")
    for kolom in KOLOM_PERFORMA:
        if kolom not in df:
            df[kolom] = 0
    df[KOLOM_PERFORMA] = df[KOLOM_PERFORMA].fillna(0)
    return hitung(df)


# =========================================================
# AMBIL DATA DARI GOOGLE SHEET
# =========================================================

def rahasia(kunci):
    try:
        nilai = st.secrets.get(kunci)
    except Exception:
        nilai = None
    return nilai or os.environ.get(kunci)


@st.cache_data(ttl=60, show_spinner=False)
def ambil_sheet(sheet_id):
    akun = rahasia("gcp_service_account")
    isi = ds.unduh_sheet(sheet_id, dict(akun) if akun else None)
    return isi, datetime.now(timezone(timedelta(hours=7)))


@st.cache_data(ttl=60, show_spinner=False)
def ambil_status(cs_csv):
    """{nama CS: jumlah iklan aktif}, atau None kalau Meta belum tersambung."""
    token = rahasia("META_ACCESS_TOKEN")
    akun = rahasia("META_AD_ACCOUNT_IDS")
    if not token or not akun:
        return None
    cs = pd.read_json(io.StringIO(cs_csv))
    return ds.status_campaign(token, str(akun).split(","), cs)


META_MULAI = "2026-05-01"


@st.cache_data(ttl=3600, show_spinner=False)
def ambil_meta_riwayat(kemarin, cs_json):
    """Biaya & nomor Meta sampai kemarin (jarang berubah, diambil ulang tiap jam)."""
    token = rahasia("META_ACCESS_TOKEN")
    cs = pd.read_json(io.StringIO(cs_json))
    return ds.iklan_meta_harian(token, META_MULAI, kemarin, cs)


@st.cache_data(ttl=60, show_spinner=False)
def ambil_meta_hari_ini(hari_ini, cs_json):
    """Biaya & nomor Meta hari ini (diambil ulang tiap menit)."""
    token = rahasia("META_ACCESS_TOKEN")
    cs = pd.read_json(io.StringIO(cs_json))
    return ds.iklan_meta_harian(token, hari_ini, hari_ini, cs)


@st.cache_data(ttl=60, show_spinner=False)
def olah_sheet(isi_xlsx, isi_recap, cs_json):
    return ds.siapkan(isi_xlsx, pd.read_json(io.StringIO(cs_json)), isi_recap)


def waktu_sekarang():
    return datetime.now(timezone(timedelta(hours=7)))


def muat_data(cs):
    """Ambil & gabungkan semua sumber. Hasil dict; peringatan dikumpulkan."""
    peringatan = []
    sheet_id = rahasia("SHEET_ID")
    isi_xlsx, _ = ambil_sheet(sheet_id)

    isi_recap = None
    recap_id = rahasia("SHEET_DONASI_ID")
    if recap_id:
        try:
            isi_recap, _ = ambil_sheet(recap_id)
        except Exception as e:
            peringatan.append(f"Sheet donasi (RECAP) tidak bisa diambil, pakai Rekap Admin: {e}")

    cs_json = cs.to_json()
    performa, dana, tak_dikenal = olah_sheet(isi_xlsx, isi_recap, cs_json)

    if rahasia("META_ACCESS_TOKEN"):
        hari_ini = waktu_sekarang().date()
        try:
            meta = pd.concat([
                ambil_meta_riwayat(f"{hari_ini - timedelta(days=1):%Y-%m-%d}", cs_json),
                ambil_meta_hari_ini(f"{hari_ini:%Y-%m-%d}", cs_json),
            ], ignore_index=True)
            performa = ds.timpa_dengan_meta(performa, meta)
        except Exception as e:
            peringatan.append(f"Biaya iklan dari Meta tidak bisa diambil, pakai data sheet: {e}")

    return {
        "sheet_id": sheet_id, "isi_xlsx": isi_xlsx, "performa": performa,
        "dana": dana, "tak_dikenal": tak_dikenal, "peringatan": peringatan,
    }


PILIHAN_TANGGAL = ["Bulan ini", "Bulan lalu", "7 hari terakhir", "Hari ini", "Kemarin", "Pilih tanggal"]


def pilih_tanggal(hari_ini):
    """Pilihan cepat atau rentang bebas. Hasil: (mulai, akhir) berupa date."""
    awal_bulan = hari_ini.replace(day=1)
    akhir_bulan_lalu = awal_bulan - timedelta(days=1)
    rentang = {
        "Bulan ini": (awal_bulan, hari_ini),
        "Bulan lalu": (akhir_bulan_lalu.replace(day=1), akhir_bulan_lalu),
        "7 hari terakhir": (hari_ini - timedelta(days=6), hari_ini),
        "Hari ini": (hari_ini, hari_ini),
        "Kemarin": (hari_ini - timedelta(days=1), hari_ini - timedelta(days=1)),
    }
    c1, c2 = st.container(key="periode").columns(2)
    pilihan = c1.selectbox("Periode", PILIHAN_TANGGAL)
    if pilihan in rentang:
        mulai, akhir = rentang[pilihan]
        c2.date_input("Tanggal", value=(mulai, akhir), format="DD/MM/YYYY", disabled=True)
    else:
        nilai = c2.date_input(
            "Tanggal", value=(awal_bulan, hari_ini), format="DD/MM/YYYY", max_value=hari_ini,
        )
        mulai, akhir = (nilai[0], nilai[-1]) if isinstance(nilai, tuple) and nilai else (nilai, nilai)
    return mulai, akhir


def pasang_status(df, status):
    df = df.copy()
    if status is None:
        df["status_campaign"] = "–"
    else:
        df["status_campaign"] = df["nama"].map(
            lambda n: f"🟢 Nyala ({status[n]} iklan)" if n in status else "⚫ Mati"
        )
    return df


# =========================================================
# AKSES ADMIN
# =========================================================

def password_admin():
    return rahasia("ADMIN_PASSWORD")


def is_admin():
    pw = password_admin()
    if not pw:
        # Belum ada password (mode lokal): edit dibuka
        return True
    return st.session_state.get("admin_ok", False)


def form_login():
    st.info("Menu ini khusus admin. Masukkan password untuk mengedit.", icon="🔒")
    with st.form("login"):
        pw = st.text_input("Password admin", type="password")
        if st.form_submit_button("Masuk"):
            if pw == password_admin():
                st.session_state["admin_ok"] = True
                st.rerun()
            else:
                st.error("Password salah.")


# =========================================================
# HALAMAN: LAPORAN
# =========================================================

FORMAT_KOLOM = {
    "Nomor": angka, "All Resi": angka, "Resi Perdana": angka, "Resi Gulungan": angka,
    "Biaya Iklan": rupiah, "Modal Iklan": rupiah, "Akumulasi Profit": rupiah,
    "Sisa Iklan": rupiah, "CPR": rupiah, "Donasi Perdana (Rp)": rupiah,
    "Donasi Gulungan (Rp)": rupiah, "Profit / Loss": rupiah, "ROAS": desimal,
    "Closing Rate (%)": desimal, "Total Topup": rupiah,
}
KOLOM_TEKS = ("Nama", "Campaign Hari Ini", "Rekomendasi")


def tampilkan_tabel(df, kolom, warna_kolom=(), pakai_total=True):
    """Tabel per CS dengan format rupiah, warna minus, dan baris Jumlah."""
    if pakai_total:
        tabel = pd.concat([df, baris_total(df)], ignore_index=True)
    else:
        tabel = df.reset_index(drop=True)

    kolom = {"nama": "Nama", **kolom}
    tabel = tabel[list(kolom)].rename(columns=kolom)
    angka_kolom = [k for k in tabel.columns if k not in KOLOM_TEKS]
    nilai = tabel[angka_kolom].apply(pd.to_numeric, errors="coerce")

    # Semua sel ditampilkan sebagai teks yang sudah diformat (kosong = "–"),
    # warna diambil dari nilai angkanya.
    tampil = tabel.copy()
    for k in angka_kolom:
        tampil[k] = nilai[k].map(FORMAT_KOLOM.get(k, angka))
    tampil = tampil.fillna("–").astype(str)

    def gaya(_):
        hasil = pd.DataFrame("", index=tampil.index, columns=tampil.columns)
        for k in warna_kolom:
            hasil[k] = nilai[k].map(
                lambda v: "" if pd.isna(v)
                else ("color: #c62828; font-weight: 600" if v < 0 else "color: #2e7d32")
            )
        total = tampil["Nama"] == "Jumlah"
        hasil.loc[total, :] = hasil.loc[total, :] + "; font-weight: 700; background-color: rgba(128,128,128,0.15)"
        return hasil

    styled = tampil.style.apply(gaya, axis=None)
    kanan = {k: st.column_config.TextColumn(k, alignment="right") for k in angka_kolom}

    st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        height=35 * (len(tabel) + 1) + 3,
        column_config={
            **kanan,
            "Nama": st.column_config.Column(pinned=True),
        },
    )


def tab_laporan(df, total):
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Biaya Iklan", f"Rp {rupiah(total['biaya_iklan'])}", border=True)
    k2.metric("Nomor Masuk", angka(total["nomor"]), border=True)
    k3.metric("CPR", f"Rp {rupiah(total['cpr'])}", border=True)
    k4.metric("All Resi", angka(total["all_resi"]), border=True)

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Total Donasi", f"Rp {rupiah(total['total_donasi'])}", border=True)
    k6.metric("Profit / Loss", f"Rp {rupiah(total['profit'])}", border=True)
    k7.metric("ROAS", desimal(total["roas"]), border=True)
    k8.metric("Closing Rate", f"{desimal(total['closing_rate'])}%", border=True)

    tampilkan_tabel(
        df,
        {
            "nomor": "Nomor",
            "biaya_iklan": "Biaya Iklan",
            "cpr": "CPR",
            "all_resi": "All Resi",
            "perdana": "Resi Perdana",
            "gulungan": "Resi Gulungan",
            "roas": "ROAS",
            "closing_rate": "Closing Rate (%)",
            "donasi_perdana": "Donasi Perdana (Rp)",
            "donasi_gulungan": "Donasi Gulungan (Rp)",
            "profit": "Profit / Loss",
        },
        warna_kolom=["Profit / Loss"],
    )

    with st.expander("Cara hitung"):
        st.markdown("""
- **CPR** = Biaya Iklan ÷ Nomor
- **All Resi** = Perdana + Gulungan
- **ROAS** = (Donasi Perdana + Donasi Gulungan) ÷ Biaya Iklan
- **Closing Rate** = Perdana ÷ Nomor × 100
- **Profit / Loss** = Donasi Perdana + Donasi Gulungan − Biaya Iklan
""")


def tab_jatah(dana, cs):
    aktif = cs[cs["aktif"]][["nama"]]
    df = aktif.merge(dana, on="nama", how="left")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Modal Iklan", f"Rp {rupiah(df['modal_iklan'].sum())}", border=True)
    k2.metric("Akumulasi Profit", f"Rp {rupiah(df['akumulasi'].sum())}", border=True)
    k3.metric("Total Sisa Iklan", f"Rp {rupiah(df['sisa_iklan'].sum())}", border=True)
    minus = int((df["sisa_iklan"] < 0).sum())
    k4.metric("CS Sisa Minus", f"{minus} CS", border=True)

    tampilkan_tabel(
        df.sort_values("sisa_iklan"),
        {
            "modal_iklan": "Modal Iklan",
            "akumulasi": "Akumulasi Profit",
            "sisa_iklan": "Sisa Iklan",
        },
        warna_kolom=["Akumulasi Profit", "Sisa Iklan"],
        pakai_total=False,
    )
    st.caption(
        "Akumulasi semua bulan, dari sheet **Dana Iklan**. Sisa Iklan = kolom "
        "Keterangan (merah = modal sudah habis/minus)."
    )


URUTAN_REKOMENDASI = {"🟢 Layak Scale Up": 0, "🟡 Pertahankan": 1, "🔴 Evaluasi": 2, "–": 3}


def tab_rekomendasi(df):
    jumlah = df["rekomendasi"].value_counts()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🟢 Layak Scale Up", f"{jumlah.get('🟢 Layak Scale Up', 0)} CS", border=True)
    k2.metric("🟡 Pertahankan", f"{jumlah.get('🟡 Pertahankan', 0)} CS", border=True)
    k3.metric("🔴 Evaluasi", f"{jumlah.get('🔴 Evaluasi', 0)} CS", border=True)
    nyala = int(df["status_campaign"].str.contains("Nyala").sum())
    k4.metric("Campaign Nyala Hari Ini", f"{nyala} CS", border=True)

    urut = df.assign(_u=df["rekomendasi"].map(URUTAN_REKOMENDASI)).sort_values(
        ["_u", "roas"], ascending=[True, False],
    )
    tampilkan_tabel(
        urut,
        {
            "status_campaign": "Campaign Hari Ini",
            "rekomendasi": "Rekomendasi",
            "roas": "ROAS",
            "closing_rate": "Closing Rate (%)",
            "nomor": "Nomor",
            "cpr": "CPR",
            "biaya_iklan": "Biaya Iklan",
            "profit": "Profit / Loss",
        },
        warna_kolom=["Profit / Loss"],
        pakai_total=False,
    )

    st.markdown(f"""
**Aturan rekomendasi:**
- 🟢 **Layak Scale Up**: ROAS ≥ {desimal(SCALE_UP_MIN_ROAS)}, Closing Rate ≥ {SCALE_UP_MIN_CLOSING}%, dan Nomor ≥ {SCALE_UP_MIN_NOMOR}
- 🔴 **Evaluasi**: ROAS < {desimal(EVALUASI_MAX_ROAS)} (donasi belum menutup biaya iklan)
- 🟡 **Pertahankan**: di antara keduanya
""")


def halaman_laporan(mulai, akhir, performa, dana, cs, status):
    df = pasang_status(data_rentang(mulai, akhir, performa, cs), status)
    total = baris_total(df).iloc[0]

    t1, t2, t3 = st.tabs(["📋 Laporan", "💰 Jatah & Sisa", "🚀 Rekomendasi"])
    with t1:
        tab_laporan(df, total)
    with t2:
        tab_jatah(dana, cs)
    with t3:
        tab_rekomendasi(df)


# =========================================================
# HALAMAN: KELOLA CS
# =========================================================

def halaman_kelola(cs, tak_dikenal):
    st.subheader("⚙️ Kelola CS")

    if not is_admin():
        form_login()
        return

    st.caption(
        "**Tambah CS**: klik baris kosong paling bawah. **Hapus CS**: centang kotak "
        "di kiri baris lalu tekan 🗑️. **Nonaktifkan**: hilangkan centang Aktif "
        "(disembunyikan dari laporan). **Nama lain**: tulisan nama CS yang berbeda "
        "di sheet (misal TRISMAN untuk Trisna), pisahkan dengan koma."
    )
    if tak_dikenal:
        st.warning(
            "Nama di sheet yang belum cocok dengan CS mana pun (datanya tidak "
            f"dihitung): **{', '.join(tak_dikenal)}**. Tambahkan sebagai CS baru "
            "atau sebagai nama lain dari CS yang ada.",
            icon="⚠️",
        )

    edit = st.data_editor(
        cs,
        num_rows="dynamic",
        hide_index=True,
        height=35 * (len(cs) + 2) + 3,
        width="stretch",
        column_config={
            "nama": st.column_config.TextColumn("Nama CS", required=True),
            "aktif": st.column_config.CheckboxColumn("Aktif", default=True),
            "nama_lain": st.column_config.TextColumn("Nama lain di sheet (pisah koma)"),
        },
        key="editor_cs",
    )

    if st.button("💾 Simpan perubahan", type="primary"):
        ds.save_cs(edit)
        st.success("Tersimpan.")
        st.rerun()


# =========================================================
# HALAMAN: TOPUP IKLAN
# =========================================================

def halaman_topup(cs, isi_xlsx, sheet_id):
    st.subheader("💳 Topup Iklan")

    if not is_admin():
        form_login()
        return

    akun = rahasia("gcp_service_account")
    akun = dict(akun) if akun else None
    if not akun:
        st.warning(
            "Akun layanan Google belum diatur: topup disimpan **sementara di server "
            "dashboard** (bisa hilang saat server restart). Setelah diatur, topup "
            "otomatis tersimpan di tab **Topup Iklan** di Google Sheet.",
            icon="⚠️",
        )

    daftar_cs = cs[cs["aktif"]]["nama"].tolist()
    hari_ini = datetime.now(timezone(timedelta(hours=7))).date()

    with st.form("form_topup", clear_on_submit=True):
        c1, c2 = st.columns(2)
        tanggal = c1.date_input("Tanggal topup", value=hari_ini, format="DD/MM/YYYY")
        nama = c2.selectbox("Nama CS", daftar_cs, index=None, placeholder="Pilih CS")
        nominal = st.number_input("Nominal (Rp)", min_value=0, step=50000, value=0)
        kirim = st.form_submit_button("💾 Simpan topup", type="primary", width="stretch")

    if kirim:
        if not nama:
            st.error("Pilih nama CS dulu.")
        elif nominal <= 0:
            st.error("Nominal harus lebih dari 0.")
        else:
            try:
                tempat = ds.simpan_topup(
                    {"tanggal": tanggal, "nama": nama, "nominal": nominal},
                    sheet_id, akun,
                )
            except Exception as e:
                st.error(f"Gagal menyimpan topup: {e}")
            else:
                ambil_sheet.clear()
                st.session_state["topup_ok"] = (
                    f"Topup **{nama}** Rp {rupiah(nominal)} tanggal {tanggal:%d/%m/%Y} tersimpan"
                    + (" di Google Sheet." if tempat == "sheet" else " (sementara).")
                )
                st.rerun()

    if st.session_state.get("topup_ok"):
        st.success(st.session_state.pop("topup_ok"), icon="✅")

    riwayat = ds.baca_topup(isi_xlsx, dari_sheet=bool(akun))
    if riwayat.empty:
        st.caption("Belum ada topup yang diinput lewat dashboard.")
        return

    daftar_bulan = sorted(riwayat["bulan"].dropna().unique(), reverse=True)
    bulan = st.selectbox("Riwayat bulan", daftar_bulan, format_func=nama_bulan, key="bulan_topup")
    data = riwayat[riwayat["bulan"] == bulan]

    k1, k2 = st.columns(2)
    k1.metric("Total topup", f"Rp {rupiah(data['nominal'].sum())}", border=True)
    k2.metric("Jumlah transaksi", f"{len(data)}x", border=True)

    per_cs = data.groupby("nama", as_index=False)["nominal"].sum().sort_values("nominal", ascending=False)
    st.markdown("**Total per CS**")
    tampilkan_tabel(per_cs, {"nominal": "Total Topup"}, pakai_total=False)

    st.markdown("**Riwayat**")
    daftar = data.sort_values(["tanggal", "diinput"], ascending=False).copy()
    daftar["tanggal"] = daftar["tanggal"].dt.strftime("%d/%m/%Y")
    daftar["nominal"] = daftar["nominal"].map(rupiah)
    st.dataframe(
        daftar[["tanggal", "nama", "nominal"]].rename(columns={
            "tanggal": "Tanggal", "nama": "Nama CS", "nominal": "Nominal",
        }),
        hide_index=True, width="stretch",
        column_config={"Nominal": st.column_config.TextColumn("Nominal", alignment="right")},
    )


# =========================================================
# MAIN
# =========================================================

st.title("📊 Laporan Iklan DMF 2")

if not rahasia("SHEET_ID"):
    st.error("SHEET_ID belum diatur di Secrets.")
    st.stop()

info, tombol = st.columns([3, 1], vertical_alignment="center")
info.caption("Interaksi · Kabupaten Serang · update otomatis tiap 1 menit")
if tombol.button("🔄 Muat ulang", width="stretch"):
    st.cache_data.clear()
    st.rerun()

menu = st.segmented_control(
    "Menu", ["📊 Laporan", "💳 Topup Iklan", "⚙️ Kelola CS"], default="📊 Laporan",
    label_visibility="collapsed",
) or "📊 Laporan"

cs = ds.load_cs()


@st.fragment(run_every=60)
def laporan_live(mulai, akhir, cs):
    """Bagian laporan yang menyegarkan diri tiap 60 detik."""
    try:
        data = muat_data(cs)
    except Exception as e:
        st.error(f"Gagal mengambil data dari Google Sheet: {e}")
        return
    for pesan in data["peringatan"]:
        st.warning(pesan, icon="⚠️")
    try:
        status = ambil_status(cs.to_json())
    except Exception as e:
        st.warning(f"Status campaign Meta tidak bisa diambil: {e}", icon="⚠️")
        status = None
    st.caption(f"🟢 Diperbarui {waktu_sekarang():%H:%M:%S} WIB")
    halaman_laporan(mulai, akhir, data["performa"], data["dana"], cs, status)


if menu == "📊 Laporan":
    mulai, akhir = pilih_tanggal(waktu_sekarang().date())
    laporan_live(mulai, akhir, cs)
else:
    try:
        data = muat_data(cs)
    except Exception as e:
        st.error(f"Gagal mengambil data dari Google Sheet: {e}")
        st.stop()
    if menu == "💳 Topup Iklan":
        halaman_topup(cs, data["isi_xlsx"], data["sheet_id"])
    else:
        halaman_kelola(cs, data["tak_dikenal"])
