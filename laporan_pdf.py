"""Buat laporan PDF (Laporan, Rekomendasi, Jatah & Sisa) untuk diunduh dari dashboard."""
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from fpdf import FPDF
from fpdf.fonts import FontFace

PINK = (255, 79, 163)
PINK_MUDA = (255, 227, 240)
ABU = (122, 109, 143)
MERAH = (198, 40, 40)
HIJAU = (46, 125, 50)


def _bersih(teks) -> str:
    """Font PDF standar tidak punya emoji -> buang emoji & karakter non-Latin."""
    teks = str(teks).replace("–", "-").replace("—", "-")
    teks = re.sub(r"[^\x20-\x7E -ÿ]", "", teks)
    return teks.strip()


def _rp(x) -> str:
    if x is None or pd.isna(x):
        return "-"
    tanda = "-" if x < 0 else ""
    return f"{tanda}{abs(round(x)):,.0f}".replace(",", ".")


def _angka(x) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:,.0f}".replace(",", ".")


def _des(x) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:.1f}".replace(".", ",")


class _PDF(FPDF):
    def __init__(self, judul_periode):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.judul_periode = judul_periode
        self.set_auto_page_break(auto=True, margin=12)
        self.set_margins(10, 10, 10)

    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*PINK)
        self.cell(0, 8, "Laporan Iklan DMF 2", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*ABU)
        dibuat = datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M")
        self.cell(0, 5, f"Interaksi - Kabupaten Serang  |  Periode {self.judul_periode}  |  dibuat {dibuat} WIB",
                  new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-9)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*ABU)
        self.cell(0, 5, f"Halaman {self.page_no()}", align="R")

    def subjudul(self, teks):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*PINK)
        self.cell(0, 7, teks, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def ringkasan(self, pasangan):
        """Kotak-kotak angka ringkasan, 4 per baris."""
        lebar = (self.w - self.l_margin - self.r_margin - 9) / 4
        for i, (label, nilai) in enumerate(pasangan):
            if i and i % 4 == 0:
                self.ln(15)
            x = self.l_margin + (i % 4) * (lebar + 3)
            y = self.get_y()
            self.set_fill_color(*PINK_MUDA)
            self.rect(x, y, lebar, 13, style="F")
            self.set_xy(x + 3, y + 1.5)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*ABU)
            self.cell(lebar - 6, 4, label)
            self.set_xy(x + 3, y + 6)
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(0, 0, 0)
            self.cell(lebar - 6, 6, nilai)
            self.set_xy(self.l_margin, y)
        self.ln(17)

    def tabel(self, kolom, baris, lebar, rata, warna_kolom=(), tebal_terakhir=False):
        self.set_font("Helvetica", "", 8)
        kepala = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=PINK)
        with self.table(col_widths=lebar, text_align=rata, headings_style=kepala,
                        line_height=5.2, cell_fill_color=(250, 245, 250), cell_fill_mode="ROWS",
                        borders_layout="HORIZONTAL_LINES") as t:
            r = t.row()
            for k in kolom:
                r.cell(k)
            for n, isi in enumerate(baris):
                akhir = tebal_terakhir and n == len(baris) - 1
                r = t.row()
                for j, (teks, nilai) in enumerate(isi):
                    gaya = None
                    if j in warna_kolom and nilai is not None and not pd.isna(nilai):
                        gaya = FontFace(color=MERAH if nilai < 0 else HIJAU, emphasis="BOLD" if akhir else None)
                    elif akhir:
                        gaya = FontFace(emphasis="BOLD")
                    r.cell(teks, style=gaya)
        self.ln(3)


def buat_pdf(df, total, dana, mulai, akhir) -> bytes:
    """df: data per CS (hasil hitung + status), total: baris Jumlah, dana: Dana Iklan per CS."""
    periode = f"{mulai:%d/%m/%Y}" + ("" if mulai == akhir else f" - {akhir:%d/%m/%Y}")
    pdf = _PDF(periode)

    # ---------- 1. Laporan ----------
    pdf.add_page()
    pdf.subjudul("Ringkasan")
    pdf.ringkasan([
        ("Biaya Iklan", f"Rp {_rp(total['biaya_iklan'])}"),
        ("Nomor Masuk", _angka(total["nomor"])),
        ("CPR", f"Rp {_rp(total['cpr'])}"),
        ("All Resi", _angka(total["all_resi"])),
        ("Total Donasi", f"Rp {_rp(total['total_donasi'])}"),
        ("Profit / Loss", f"Rp {_rp(total['profit'])}"),
        ("ROAS", _des(total["roas"])),
        ("Closing Rate", f"{_des(total['closing_rate'])}%"),
    ])
    pdf.subjudul("Performa per CS")
    baris = []
    for _, r in list(df.iterrows()) + [(None, total)]:
        baris.append([
            (_bersih(r["nama"]), None), (_angka(r["nomor"]), None), (_rp(r["biaya_iklan"]), None),
            (_rp(r["cpr"]), None), (_angka(r["all_resi"]), None), (_angka(r["perdana"]), None),
            (_angka(r["gulungan"]), None), (_des(r["roas"]), None), (_des(r["closing_rate"]), None),
            (_rp(r["donasi_perdana"]), None), (_rp(r["donasi_gulungan"]), None), (_rp(r["profit"]), r["profit"]),
        ])
    pdf.tabel(
        ["Nama", "Nomor", "Biaya Iklan", "CPR", "All Resi", "Resi Perdana", "Resi Gulungan",
         "ROAS", "Closing %", "Donasi Perdana", "Donasi Gulungan", "Profit / Loss"],
        baris, lebar=(22, 15, 25, 19, 16, 19, 20, 14, 17, 27, 27, 26),
        rata=("LEFT",) + ("RIGHT",) * 11, warna_kolom=(11,), tebal_terakhir=True,
    )
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*ABU)
    pdf.multi_cell(0, 4, "CPR = Biaya / Nomor  |  ROAS = Donasi Perdana / Biaya  |  Closing = Resi Perdana / Nomor x 100  |  "
                         "Profit = Donasi Perdana + Gulungan - Biaya. Biaya & nomor dari Meta Ads; resi & donasi dari sheet RECAP.")

    # ---------- 2. Rekomendasi ----------
    pdf.add_page()
    pdf.subjudul("Rekomendasi")
    urut = {"Layak Scale Up": 0, "Pertahankan": 1, "Evaluasi": 2}
    rek = df.assign(_r=df["rekomendasi"].map(_bersih))
    rek = rek.assign(_u=rek["_r"].map(urut).fillna(3)).sort_values(["_u", "roas"], ascending=[True, False])
    jumlah = rek["_r"].value_counts()
    pdf.ringkasan([
        ("Layak Scale Up", f"{jumlah.get('Layak Scale Up', 0)} CS"),
        ("Pertahankan", f"{jumlah.get('Pertahankan', 0)} CS"),
        ("Evaluasi", f"{jumlah.get('Evaluasi', 0)} CS"),
        ("Campaign Nyala", f"{int(df['status_campaign'].astype(str).str.contains('Nyala').sum())} CS"),
    ])
    baris = [[
        (_bersih(r["nama"]), None), (_bersih(r["status_campaign"]) or "-", None), (r["_r"] or "-", None),
        (_des(r["roas"]), None), (_des(r["closing_rate"]), None), (_angka(r["nomor"]), None),
        (_rp(r["cpr"]), None), (_rp(r["biaya_iklan"]), None), (_rp(r["profit"]), r["profit"]),
    ] for _, r in rek.iterrows()]
    pdf.tabel(["Nama", "Campaign Hari Ini", "Rekomendasi", "ROAS", "Closing %", "Nomor", "CPR", "Biaya Iklan", "Profit / Loss"],
              baris, lebar=(28, 38, 34, 18, 22, 20, 26, 34, 34),
              rata=("LEFT", "LEFT", "LEFT") + ("RIGHT",) * 6, warna_kolom=(8,))

    # ---------- 3. Jatah & Sisa ----------
    if dana is not None and not dana.empty:
        pdf.add_page()
        pdf.subjudul("Jatah & Sisa Iklan (akumulasi, dari sheet Dana Iklan)")
        d = df[["nama"]].merge(dana, on="nama", how="left").sort_values("sisa_iklan")
        pdf.ringkasan([
            ("Total Modal Iklan", f"Rp {_rp(d['modal_iklan'].sum())}"),
            ("Akumulasi Profit", f"Rp {_rp(d['akumulasi'].sum())}"),
            ("Total Sisa Iklan", f"Rp {_rp(d['sisa_iklan'].sum())}"),
            ("CS Sisa Minus", f"{int((d['sisa_iklan'] < 0).sum())} CS"),
        ])
        baris = [[(_bersih(r["nama"]), None), (_rp(r["modal_iklan"]), None),
                  (_rp(r["akumulasi"]), r["akumulasi"]), (_rp(r["sisa_iklan"]), r["sisa_iklan"])]
                 for _, r in d.iterrows()]
        pdf.tabel(["Nama", "Modal Iklan", "Akumulasi Profit", "Sisa Iklan"], baris,
                  lebar=(60, 60, 70, 60), rata=("LEFT", "RIGHT", "RIGHT", "RIGHT"), warna_kolom=(2, 3))

    return bytes(pdf.output())
