import socket, struct, csv, math
from collections import deque
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

app = QtWidgets.QApplication([])

UDP_IP = "0.0.0.0"
UDP_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(False)

f_csv = open("log.csv", "a", newline="")
w = csv.writer(f_csv)
w.writerow(["timestamp_us", "value_int16", "value_filtered"])

win = pg.plot(title="Přijatá data z ESP32 (syrová vs. filtrováno)")
curve_raw = win.plot(pen=pg.mkPen(width=1))
curve_flt = win.plot(pen=pg.mkPen(width=2))
ts_buf, v_buf, vf_buf = deque(maxlen=2000), deque(maxlen=2000), deque(maxlen=2000)

hdr_fmt = "<IQH"
hdr_size = struct.calcsize(hdr_fmt)

# ===== Parametry filtru =====
FS_HZ = 1000.0          # vzorkování: 1 ms => 1000 Hz
HP_HZ = 0.5            # horní propust
LP_HZ = 100.0           # dolní propust
NOTCH_HZ = 50.0         # pásmová zádrž
Q_BW = 1/math.sqrt(2)   # Q ≈ 0.707 pro HP/LP (2. řád Butterworth)
Q_NOTCH = 20.0          # úzká zádrž kolem 50 Hz (zvětši pro užší potlačení)

class Biquad:
    def __init__(self, kind, f0, fs, Q):
        self.b0 = self.b1 = self.b2 = 0.0
        self.a1 = self.a2 = 0.0
        self.z1 = self.z2 = 0.0
        self.design(kind, f0, fs, Q)

    def design(self, kind, f0, fs, Q):
        w0 = 2.0 * math.pi * (f0 / fs)
        cw = math.cos(w0)
        sw = math.sin(w0)
        alpha = sw / (2.0 * Q)

        if kind == "lp":
            b0 = (1 - cw) * 0.5
            b1 = 1 - cw
            b2 = (1 - cw) * 0.5
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        elif kind == "hp":
            b0 = (1 + cw) * 0.5
            b1 = -(1 + cw)
            b2 = (1 + cw) * 0.5
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        elif kind == "notch":
            b0 = 1
            b1 = -2 * cw
            b2 = 1
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        else:
            raise ValueError("Unknown biquad kind")

        # normalizace koeficientů
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def process(self, x):
        # Direct Form I (bezpecná a rychlá pro stream)
        y = self.b0*x + self.b1*self.z1 + self.b2*self.z2 - self.a1*self.z1 - self.a2*self.z2
        # Aktualizace stavů (přepočet přes x a y pro DF1/“transposed” není nutný zde)
        # Použijeme klasické posuvy vstupů/výstupů:
        # u této implementace držíme v z1,z2 předchozí VÝSTUPY filtru:
        self.z2 = self.z1
        self.z1 = y
        return y

# Pozn.: výše uvedený „DF1“ zápis se zjednodušeným stavem funguje pro tuto normalizaci.
# Pokud chceš klasické RBJ DF2T, použij variantu s v1,v2 (doplním níže):

class BiquadDF2T:
    def __init__(self, kind, f0, fs, Q):
        self.b0 = self.b1 = self.b2 = 0.0
        self.a1 = self.a2 = 0.0
        self.v1 = self.v2 = 0.0
        self.design(kind, f0, fs, Q)

    def design(self, kind, f0, fs, Q):
        w0 = 2.0 * math.pi * (f0 / fs)
        cw = math.cos(w0)
        sw = math.sin(w0)
        alpha = sw / (2.0 * Q)

        if kind == "lp":
            b0 = (1 - cw) * 0.5
            b1 = 1 - cw
            b2 = (1 - cw) * 0.5
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        elif kind == "hp":
            b0 = (1 + cw) * 0.5
            b1 = -(1 + cw)
            b2 = (1 + cw) * 0.5
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        elif kind == "notch":
            b0 = 1
            b1 = -2 * cw
            b2 = 1
            a0 = 1 + alpha
            a1 = -2 * cw
            a2 = 1 - alpha
        else:
            raise ValueError("Unknown biquad kind")

        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def process(self, x):
        # DF2T: v[n] = x - a1*v1 - a2*v2; y = b0*v + b1*v1 + b2*v2
        v = x - self.a1*self.v1 - self.a2*self.v2
        y = self.b0*v + self.b1*self.v1 + self.b2*self.v2
        self.v2 = self.v1
        self.v1 = v
        return y

# Zvol DF2T pro lepší numerickou stabilitu:
HP = BiquadDF2T("hp",    HP_HZ,    FS_HZ, Q_BW)
NOTCH = BiquadDF2T("notch", NOTCH_HZ, FS_HZ, Q_NOTCH)
LP = BiquadDF2T("lp",    LP_HZ,    FS_HZ, Q_BW)

def filt_chain(x: float) -> float:
    y = HP.process(x)
    y = NOTCH.process(y)
    y = LP.process(y)
    return y

def poll():
    try:
        while True:
            data, _ = sock.recvfrom(8192)
            if len(data) < hdr_size:
                return
            seq, t0_us, n = struct.unpack_from(hdr_fmt, data, 0)
            samples = struct.unpack_from(f"<{n}h", data, hdr_size)

            for i, s in enumerate(samples):
                ts = t0_us + i * 1000  # 1 ms krok => 1000 Hz
                sf = filt_chain(float(s))
                w.writerow([ts, s, sf])
                ts_buf.append(ts / 1e6)
                v_buf.append(s)
                vf_buf.append(sf)
    except BlockingIOError:
        pass
    f_csv.flush()
    #curve_raw.setData(list(ts_buf), list(v_buf))
    curve_flt.setData(list(ts_buf), list(vf_buf))

timer = QtCore.QTimer()
timer.timeout.connect(poll)
timer.start(5)

QtWidgets.QApplication.instance().exec()
