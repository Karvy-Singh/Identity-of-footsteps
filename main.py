# Arduino App Lab (UNO Q) - self-contained live Harsh/Karvy classifier.
# No .joblib or pip packages required: model is embedded below.
from arduino.app_utils import App, Bridge
from collections import Counter, deque
from pathlib import Path
import base64
import csv
import math
import struct
import time
import zlib

MIC_RATE = 500
MPU_RATE = 200
MISSING = -32768
MIN_GOOD = 0.98

# First 5 valid seconds are used to measure the QUIET environment.
# Nobody should walk during calibration.
QUIET_SECONDS = 5
ACTIVITY_MIN_MIC = 125.0    # 14-bit ADC counts, standard deviation
ACTIVITY_MIN_PIEZO = 35.0   # 14-bit ADC counts, standard deviation
ACTIVITY_MIN_MPU = 0.014    # g, standard deviation of acceleration magnitude
NEEDED_ACTIVE_WINDOWS = 2  # avoid reacting to a single random tap

# A 32-tree Random Forest retrained from the final 10 Harsh/Karvy trials.
# Binary tree nodes are compressed as ASCII so App Lab needs only main.py.
MODEL_DATA = """
c-oCvd3X)y8lN-!ewM_N2w8+kgv3(9%zSgsoW#;rl-
jBZX%M0WB~;>RiP$xkT2t;tsWf7_w6?3UC3Y_Nsjazs^`W<^ik(_=x$_}4lg_mF{B@pr-ub@YyZzqZJ5I#y;HL|j-Z2WR#-
mhu@I!g){AobM@GevG{2PjgtIv>^zsYJWL7qO=&{w!T=+#rC=I@5$7_~LcsCh@h?OV6xR|bfS<({m(<TKd9pW$4mAS$0O^?8=$
zB2F{FLoll13$@M*W#B{11E|lgna57;GbxL0$SH6_{~?QNDCvs1WuCK6kOy>uTO$-
icYWSC~d6HR}6?>{yir&RiargeOZ;VW8}NW!wgq67R0(OV|^9dM_L$cC@uy8dNjogQNz5x^@19XQd<%g>A$N!2ay=QJ|#>3{!*
&(#bAOw@x@Z_?#c+8utd|`ouZTA;n`(M1BT7Hks{50W4dhRGlB@bFzuHGeuGP9@JO)JgGZk9PHdj5M!DQ`IwdG^yN6l&VLE|9;
v8t?dudX1iqrT!2%~S51<1SdmH`nb)_SM<j}E<56WEg{-c&<KidwNx!pDwOe(zm}f-
At3UZ;bse`}fVojaTwi4x^MpHW)zex)^rpTF>vV(=P9**aLwDSCB9wz4hT<WysZPyPI~_tuDBYD<<Y`6O4-
{j)p)QKJR%Uqkc3=0rn!!;FX3(PO~}pBN!QYX+tE?cbvz$Y9ll;a46V@RjC|HwH0^AiK25Q=UA|vCN29C28(MkH-%W6B%}X-
ZsA(n_X21o{-
nS0q?xs2e?INr~ENqJt)Q)qb@gsjMr+lkRgE00|Jk1Z4ayq9U8!V(1rC1ecc;W0ujYd@)P{$tG6fyYZp$fsGzhJi$j$r1j!T(l
#dQgmH!Yt42qKx`)?@rt?H4k#<5&M)+lMxEuRqu!3%*U?j*f}fb|ImTLG5M)pnoxAS={Cu^~v2g!TB@2ouE#1WDIodNot5+ajK
#KjH@{ds9tB7s0SCMm?0)w^xj|496dMbVLg|JjR9~1jwf2W@mVJHX>9OB?61*XwfP2KpPAvN+-
)v<I`=LGoEB1^Il4ut;A4tznCh?%(2G&w`RHhDYpSWwo3j#BBXck&h}{%q<7;P7<=g62~eI~0s?Sq@|bl}Y!3;<6J*R^x5|)jE
MY1!G_$YjW7(Qynsi+V1dbnFwZm`6EXBYLQwF(y)=XL@QA|)aYI9p1GTv7oC+ZLSL>iIwmSPnEuNp`3=&VuFnWVldO*1Lo2K&^
!T;qLimRtDaA}?ei>j8lXuJ%)0iP7r<Ra$hm?d<nmO(?Lax2%eG=4b{v_!0Z-$S}Q)P-
1wiozkVHhatU(){RsqOqgI(7aYkT$PjJZnIwQxG=gMkZ!Y);_`Pl1Y6Uc7xlGOpR<8;(1jUB)IKAFjIB!Cy{Q~=R(~N=se@~lg
JUJSt;0(d)?NoF^>f7ysd}K(H@>|M0#v)^B=0VGH&3=ZMD7&eHE`2gc+S~6AU{Gvc^ct<!VAK<NXGnMHgOJXKrvN1>#4Gr%hbR
n|ixJn}ucH+_P6i%U=+L%Q%02w8jB-4J4A;bQ{r_wfm@@6w8-
V;?Op_o*#G_cJziUe2@`)zK!HL|m+ld(&88+1tK#A$dA!&Ez8W2Kr?rUcy{?uUwWmp6mq_tbr*EsbIfa>tV>1Pg`W`W=XovxUt
H#=rkjJLU%(bG#qI+=Iiz8+(u*YTO!aWDfk!0^S=9La>(l&46Nx-)&CtYiE0x#@&8RQ-5>xAH58t^lzo3%1FpIt(?|kcd-
V9C`kWvsNk%b&Ak2n_M+z&q*`uj;;44jJ_;eC#MA`mK^D<e1uO><9Xq$ce^P$e;H~MAye;(j^~mTGFdo^_53<js^oHPP&f#-
)wqU<l`D4x*n5-
bYEAa^01*`3KkWzUo^0qnq~@=wOc5kRuebO@$smAh0dm%GJxop%N{w%dDc!H<gBBRs>$^auL%|@mDNbZQn=1A0ooxftaB>*U%|
Gr|;5@C%uo-uE)S9P=wcw@%F>uRNfAXjt)xH7nt_f++HA^&#C5<ct2LdPB016>^DB6^-w?O6GI<Cl9o_t+-&ROqkx=S{t{u;{-
-rC03yLWFJ6tRMMCbzk-mf~pcblv`_1Av3Wj^BbD?8K6~GE90Lia{NEH~5$_4G}n%`TA37^XfecMv%)dPV}!9uUY7j+qXu`dTl
mZQ}PEeYf&qGt$4UME%p)MQLHfNvgQIG8m|t*sb#G^^2J#Vl}Lhw4QF5{dkN%V*mGIM{s;H7Z6vo7aXHxFRhS0VFo#kIlB~fkq
7jBSJAFdBnviU=CdjtCR>C}41Q7<@O*8#=rFdt*K`Pee6vT;n4Yx~o`ixgeUf78(_FGHGTFGH*A|#Ic4#c6vv0bUsF;72G55t$
A87H@CGuEcaVo0jz;Qz>2y#xzDwU`C!1vd6>;q&D&1|>=>L*<N&rXUK#hixmDO}kSq3S{6G;jg<@@lf=stTJhC%Z@eoh0}Smb?
oCgerZVqCAQS0)anbaH6PEA`b|nwb;%v}S(dl^^)j29txXX%HKbF-gT24X^A2Q#I1FdM$dNX6e$QwfNRZXlzjm}2{x6qnJ={iK
U|H_P&@Kknkq8sSd)bTRE<fbhEY}=@JJ<tV!;)Tn1HjUDm&r+C=Z(kdA`$PkMuPKOAjo-Wus`MDSqqT}m$tSv(|&TX!k%wj^Rz
s9gbj%@2<t!_7G`Tu4jP^}!|0N-a{xj1L4AsRdsMnVwE(mrNbKqf*{~%ojO<$T+N0TVigg+S5Z=Ke-
U$DTj|ar^o{N1|4f?3BVR+QrZl5lKY?dyPWZ1$l^==rg22*tV@Q2=Y-
K{2$LCZk@T%4<DAf@g7X$gqph4g2aWu4)S*rG+}jiYCQPA8TMz8IixkAAy9blUqi)$K&W9Xx24C*8bp12jdco6iPG-
5Zwx5hK^WRqlu7+YBd`cr!uhq|r4m-uz~QYVBwQ&Fw$<RGOJ|OmQ-7^@>ftHG8JlAU2Ki-
%!B)#3_iLm?gf<%uLmezXb=1Os?mL+QRTW3}Z7^ib`T)8HmTJuIsDiijyCJ0D=t9A1Rr>l9-
MQ(fK>*pfrE~qZ(|6z0NE%b>d(hG(W0DgIZl59dHRU5x?G^ICY`4$d~_PBQ=~L|K>@SX3d-lER~39^JVz$GN~Pmp9>r;m-
EjI|J+uc6hl~yDnf7-bvPoyeJE6PUfj4_t_9QD(f<LD4TS9
"""


def load_forest():
    payload = base64.b85decode("".join(MODEL_DATA.split()))
    raw = zlib.decompress(payload)
    forest, pos = [], 0
    for _ in range(32):
        count = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        nodes = []
        for _ in range(count):
            nodes.append(struct.unpack_from("<BBBff", raw, pos))
            pos += 11
        forest.append(nodes)
    if pos != len(raw):
        raise ValueError("Embedded model data is damaged")
    return forest


FOREST = load_forest()


def percentile_sorted(values, fraction):
    index = (len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def signal_features(values):
    # Exact feature order and formulas from training (NumPy linear percentiles).
    n = len(values)
    ordered = sorted(values)
    median = percentile_sorted(ordered, 0.50)
    centered = [v - median for v in values]
    avg = sum(centered) / n
    std = math.sqrt(sum((v - avg)**2 for v in centered) / n)
    rms = math.sqrt(sum(v*v for v in centered) / n)
    absolute = sorted(abs(v) for v in centered)
    diffs = [values[i] - values[i-1] for i in range(1, n)]
    return [
        std, rms,
        percentile_sorted(absolute, 0.50),
        percentile_sorted(absolute, 0.95),
        percentile_sorted(absolute, 0.99),
        percentile_sorted(ordered, 0.99) - percentile_sorted(ordered, 0.01),
        sum(abs(v) for v in diffs) / len(diffs),
        math.sqrt(sum(v*v for v in diffs) / len(diffs)),
        max(absolute) / max(rms, 1e-8)
    ]


def extract_features(mic, piezo, mpu):
    features = signal_features(mic) + signal_features(piezo)
    for axis in range(3):
        features += signal_features([row[axis] for row in mpu])
    features += signal_features([
        math.sqrt(x*x + y*y + z*z) for x, y, z in mpu
    ])
    return features  # 54 total, in exact training order


def predict(features):
    harsh_score = 0.0
    for tree in FOREST:
        node = 0
        while True:
            feature, left, right, threshold, p_harsh = tree[node]
            if feature == 255:  # leaf
                harsh_score += p_harsh
                break
            node = left if features[feature] <= threshold else right
    harsh_score /= len(FOREST)
    name = "harsh" if harsh_score >= 0.5 else "karvy"
    return name, harsh_score


def bridge_call(command, offset=0):
    result = Bridge.call(
        "footstep_live_rpc", int(command), int(offset), timeout=5
    )
    if result is None or len(result) != 41:
        raise RuntimeError("Unexpected Bridge reply; check sketch.ino")
    return [int(v) for v in result]


def signed16(number):
    number &= 65535
    return number - 65536 if number >= 32768 else number


class BufferOverrun(Exception):
    pass


def get_samples(command, start, count):
    readings = []
    position = start
    while len(readings) < count:
        result = bridge_call(command, position)
        n = result[0]
        if n == -2:
            raise BufferOverrun("MCU buffer overwritten before transfer finished")
        if n <= 0:
            raise RuntimeError(f"No MCU data at position {position}: {n}")
        n = min(n, count - len(readings))
        if command == 2:
            for i in range(n):
                packed = result[1+i] & 0xFFFFFFFF
                readings.append((signed16(packed >> 16), signed16(packed)))
        else:
            for i in range(n):
                j = 1 + 3*i
                readings.append((result[j], result[j+1], result[j+2]))
        position += n
    return readings


OUTPUT = Path(__file__).resolve().parent / "live_results"
OUTPUT.mkdir(parents=True, exist_ok=True)
log = (OUTPUT / "predictions.csv").open("a", newline="", buffering=1)
writer = csv.writer(log)
if log.tell() == 0:
    writer.writerow(["second", "prediction", "rolling_vote", "harsh_score",
                     "karvy_score", "mic_valid", "piezo_valid", "mpu_valid"])

next_second = None
last_check = 0.0
last_warning = 0.0
votes = deque(maxlen=5)
quiet_measurements = []
activity_thresholds = None
active_streak = 0


def std(values):
    average = sum(values) / len(values)
    return math.sqrt(sum((x - average)**2 for x in values) / len(values))


def measure_activity(mic, piezo, mpu):
    """Signal variability in a 1-second window, NOT the DC mean."""
    magnitudes = [math.sqrt(x*x + y*y + z*z) for x, y, z in mpu]
    return (std(mic), std(piezo), std(magnitudes))


def median(values):
    values = sorted(values)
    n = len(values)
    return (values[(n-1)//2] + values[n//2]) / 2.0


def make_thresholds(measurements):
    baseline = [median([m[i] for m in measurements]) for i in range(3)]
    return (
        max(ACTIVITY_MIN_MIC, baseline[0] * 1.8),
        max(ACTIVITY_MIN_PIEZO, baseline[1] * 2.0),
        max(ACTIVITY_MIN_MPU, baseline[2] * 2.5),
    )


def is_walking_activity(measured, thresholds):
    active = [measured[i] >= thresholds[i] for i in range(3)]
    # At least two independent sensors must detect activity.
    # Microphone noise alone must not trigger a person prediction.
    return sum(active) >= 2, active


def loop():
    global next_second, last_check, last_warning, activity_thresholds, active_streak
    now = time.monotonic()
    if now - last_check < 0.15:
        time.sleep(0.03)
        return
    last_check = now

    try:
        status = bridge_call(0)
        if status[0] != 2026:
            raise RuntimeError("Old or incompatible Arduino sketch running")
        produced_a, produced_m = status[1], status[2]
        if status[7] != MIC_RATE or status[8] != MPU_RATE:
            raise RuntimeError("Sample rates do not match the trained model")
        if not status[6]:
            if now - last_warning > 5:
                print("MPU6050 not responding: check SDA/SCL and power")
                last_warning = now
            return

        if next_second is None:
            next_second = max(produced_a // MIC_RATE,
                              produced_m // MPU_RATE) + 1
            print("Ready. First complete second:", next_second)
            return

        # Skip seconds already overwritten in the 8-second ring buffers.
        oldest_a = max(0, produced_a - status[9])
        oldest_m = max(0, produced_m - status[10])
        oldest_second = max((oldest_a + MIC_RATE - 1) // MIC_RATE,
                            (oldest_m + MPU_RATE - 1) // MPU_RATE)
        if next_second < oldest_second:
            print("Buffer overrun; skipping old windows")
            next_second = oldest_second
            votes.clear()

        if (produced_a < (next_second + 1) * MIC_RATE or
                produced_m < (next_second + 1) * MPU_RATE):
            return

        analog = get_samples(2, next_second * MIC_RATE, MIC_RATE)
        motion = get_samples(3, next_second * MPU_RATE, MPU_RATE)
        mic = [v[0] for v in analog if v[0] != MISSING]
        piezo = [v[1] for v in analog if v[1] != MISSING]
        mpu = [(x/16384.0, y/16384.0, z/16384.0)
               for x,y,z in motion if MISSING not in (x,y,z)]
        quality = (len(mic)/MIC_RATE, len(piezo)/MIC_RATE,
                   len(mpu)/MPU_RATE)

        if min(quality) < MIN_GOOD:
            print(f"{next_second}s: SKIP (missing samples) "
                  f"mic={quality[0]:.0%} piezo={quality[1]:.0%} "
                  f"MPU={quality[2]:.0%}; missed totals "
                  f"analog={status[3]} MPU={status[4]}")
            votes.clear()
            active_streak = 0
        else:
            measured = measure_activity(mic, piezo, mpu)

            # Calibrate using the first five *valid* windows after startup.
            if activity_thresholds is None:
                quiet_measurements.append(measured)
                votes.clear()
                if len(quiet_measurements) < QUIET_SECONDS:
                    print(f"{next_second}s | CALIBRATING QUIET "
                          f"({len(quiet_measurements)}/{QUIET_SECONDS}) - "
                          "please do not walk")
                else:
                    activity_thresholds = make_thresholds(quiet_measurements)
                    print("Quiet calibration complete. Thresholds "
                          f"mic={activity_thresholds[0]:.1f}, "
                          f"piezo={activity_thresholds[1]:.1f}, "
                          f"MPU={activity_thresholds[2]:.4f}g")
                    print("Start walking now.")
                writer.writerow([next_second, "calibrating", "", "", "",
                                 *[f"{v:.3f}" for v in quality]])

            else:
                moving, active = is_walking_activity(measured, activity_thresholds)
                active_streak = active_streak + 1 if moving else 0

                if not moving:
                    votes.clear()  # do not keep an old person's name during silence
                    print(f"{next_second}s | NO FOOTSTEPS | "
                          f"mic={measured[0]:.0f} "
                          f"piezo={measured[1]:.0f} "
                          f"MPU={measured[2]:.4f}g")
                    writer.writerow([next_second, "no_footsteps", "", "", "",
                                     *[f"{v:.3f}" for v in quality]])

                elif active_streak < NEEDED_ACTIVE_WINDOWS:
                    votes.clear()
                    print(f"{next_second}s | MOVEMENT DETECTED - "
                          "waiting for another second")
                    writer.writerow([next_second, "movement_detected", "", "", "",
                                     *[f"{v:.3f}" for v in quality]])

                else:
                    identity, harsh_score = predict(extract_features(mic, piezo, mpu))
                    votes.append(identity)
                    smoothed = Counter(votes).most_common(1)[0][0]
                    print(f"{next_second}s | LIVE: {identity.upper()} | "
                          f"5-window vote: {smoothed.upper()} | "
                          f"scores H={harsh_score:.2f} K={1-harsh_score:.2f} "
                          f"| mic={quality[0]:.0%} piezo={quality[1]:.0%} "
                          f"MPU={quality[2]:.0%}")
                    writer.writerow([next_second, identity, smoothed,
                                     f"{harsh_score:.5f}", f"{1-harsh_score:.5f}",
                                     *[f"{v:.3f}" for v in quality]])

        next_second += 1
    except BufferOverrun as exc:
        print("Resync:", exc)
        next_second = None
        votes.clear()
        active_streak = 0
    except Exception as exc:
        if now - last_warning > 2:
            print("Live classification error:", exc)
            last_warning = now
        time.sleep(0.3)


print("UNO Q live identity classification: Harsh / Karvy")
print("No joblib file required; compact model is embedded in main.py")
print("Stay still for the first 5 valid seconds for quiet calibration")
print("Saved predictions:", OUTPUT / "predictions.csv")


# ================================================================
# WEB DASHBOARD — paste this entire section immediately before
# the existing App.run(user_loop=loop) line.
# Requires the "WebUI - HTML" Brick in Arduino App Lab.
# No changes to sketch.ino or the existing classifier are needed.
# ================================================================
from collections import deque as _dashboard_deque
from arduino.app_bricks.web_ui import WebUI
from fastapi.responses import HTMLResponse

_dashboard_history = _dashboard_deque(maxlen=45)
_dashboard_state = {
    "status": "starting",
    "prediction": "STARTING",
    "vote": None,
    "harsh_score": None,
    "karvy_score": None,
    "mic_quality": None,
    "piezo_quality": None,
    "mpu_quality": None,
    "second": None,
    "updated_at": 0,
    "history": [],
}

class _DashboardWriter:
    """Observe CSV writes made by the already-working classifier."""
    def __init__(self, original):
        self.original = original

    def writerow(self, row):
        global _dashboard_state
        self.original.writerow(row)
        try:
            second, raw, vote, harsh, karvy, mic, piezo, mpu = row
            raw = str(raw).lower().strip()
            mapping = {
                "harsh": ("identified", "HARSH"),
                "karvy": ("identified", "KARVY"),
                "no_footsteps": ("idle", "NO FOOTSTEPS"),
                "calibrating": ("calibrating", "CALIBRATING"),
                "movement_detected": ("detecting", "MOVEMENT DETECTED"),
            }
            status, label = mapping.get(raw, ("unknown", raw.upper()))

            def number(value):
                return float(value) if str(value).strip() else None

            entry = {
                "second": int(second), "status": status,
                "prediction": label, "at": time.time(),
            }
            _dashboard_history.append(entry)
            _dashboard_state = {
                "status": status,
                "prediction": label,
                "vote": str(vote).upper() if vote else None,
                "harsh_score": number(harsh),
                "karvy_score": number(karvy),
                "mic_quality": number(mic),
                "piezo_quality": number(piezo),
                "mpu_quality": number(mpu),
                "second": int(second),
                "updated_at": entry["at"],
                "history": list(_dashboard_history),
            }
        except Exception as error:
            print("Dashboard update warning:", error)

# Wrap the existing csv.writer; do NOT replace the ML loop or add Bridge RPCs.
writer = _DashboardWriter(writer)

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Footstep ID | UNO Q Live Dashboard</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#090d17;color:#eef2ff;min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse 55% 35% at 68% 0%,#123b3f70,transparent),radial-gradient(ellipse 45% 25% at 0% 100%,#18284c55,transparent)}
main{position:relative;width:min(1100px,calc(100% - 36px));margin:0 auto;padding:35px 0 60px}
nav{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:38px}
.brand{display:flex;align-items:center;gap:14px;font-weight:750;letter-spacing:-.02em;font-size:21px}
.logo{width:44px;height:44px;display:grid;place-items:center;border-radius:13px;background:linear-gradient(140deg,#20d3c1,#3384fa);font-size:24px;box-shadow:0 5px 22px #20d3c133}
.pill{border:1px solid #313b4e;border-radius:99px;padding:8px 13px;background:#151c2bcc;color:#a8b8d2;font-size:12px;display:flex;align-items:center;gap:8px;letter-spacing:.04em}
.dot{height:8px;width:8px;background:#efad52;display:inline-block;border-radius:50%;box-shadow:0 0 0 4px #efad5222}
.dot.online{background:#34d6a5;box-shadow:0 0 0 4px #34d6a522}
.eyebrow{font-size:12px;letter-spacing:.17em;text-transform:uppercase;color:#8c9cb5;font-weight:700;margin:0 0 14px}
h1{font-size:clamp(33px,5.3vw,55px);letter-spacing:-.05em;line-height:1.06;margin:0 0 10px}
.sub{color:#92a5c3;font-size:15px;line-height:1.6;margin:0 0 28px}
.grid{display:grid;grid-template-columns:1.55fr 1fr;gap:17px}.card{background:linear-gradient(145deg,#192339f0,#101725f2);border:1px solid #34425880;border-radius:21px;padding:26px;box-shadow:0 14px 35px #0002}
.hero{min-height:310px;position:relative;overflow:hidden}.hero:before{content:"";position:absolute;right:-70px;top:-120px;height:300px;width:300px;background:#13b8bd1b;border-radius:50%;filter:blur(12px)}
.kicker{color:#a5b7d0;font-size:12px;text-transform:uppercase;letter-spacing:.16em;font-weight:700}
.prediction{font-size:clamp(40px,5.8vw,72px);font-weight:800;letter-spacing:-.06em;margin:42px 0 8px;line-height:1.04;word-break:break-word}
.prediction.harsh{color:#56dbb3}.prediction.karvy{color:#a9a4ff}.prediction.idle{color:#dce8f6}.prediction.calibrating,.prediction.detecting{color:#ffc87a}
.info{color:#98acc7;font-size:14px;line-height:1.5}.tag{display:inline-flex;margin-top:22px;font-size:12px;border:1px solid #415572;background:#1c2b43;padding:9px 13px;border-radius:99px;color:#d9e6fb}
.score{display:flex;justify-content:space-between;align-items:center;margin:24px 0 11px;font-size:14px;color:#bdd0e8}
.track{height:13px;border-radius:100px;overflow:hidden;background:#7373e8;display:flex}.fill{width:50%;height:100%;background:#32cfab;transition:width .45s}
.legend{display:flex;justify-content:space-between;font-size:12px;color:#a1b4cf;margin-top:12px}
.mini{font-size:12px;color:#8ba0bf;line-height:1.5;margin-top:22px}
.lower{display:grid;grid-template-columns:1fr 1fr;gap:17px;margin-top:17px}
h2{font-size:17px;letter-spacing:-.025em;margin:0 0 20px}.quality{margin:15px 0 18px}.qline{display:flex;justify-content:space-between;color:#b2c2db;font-size:13px;margin-bottom:8px}
.qbar{height:7px;border-radius:99px;background:#27334b;overflow:hidden}.qinner{height:100%;width:0%;background:linear-gradient(90deg,#389af1,#32d7ad);transition:width .5s}
.timeline{display:flex;align-items:flex-end;gap:4px;height:70px;margin:10px 0 18px}.tick{flex:1;min-width:3px;border-radius:4px 4px 1px 1px;background:#455675;opacity:.9;height:30%}.tick.harsh{background:#2fcd9c;height:85%}.tick.karvy{background:#9284fb;height:85%}.tick.idle{background:#6b809c;height:22%}.tick.detecting{background:#e7ae58;height:52%}.tick.calibrating{background:#b4a1ba;height:40%}
.events{list-style:none;padding:0;margin:0;max-height:180px;overflow:auto}.events li{padding:10px 1px;display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #ffffff0d;font-size:13px;color:#bccce3}.events li:last-child{border:0}.events small{color:#768baa}
footer{color:#7288a6;font-size:12px;margin-top:24px;line-height:1.7}
@media(max-width:720px){main{padding-top:22px}.grid,.lower{grid-template-columns:1fr}.hero{min-height:270px}.prediction{margin:32px 0 8px}.card{padding:22px}nav{margin-bottom:25px}}
</style></head><body><main>
<nav><div class="brand"><div class="logo">◈</div><div>FOOTSTEP<span style="color:#48d5bd"> ID</span></div></div><div class="pill"><span class="dot" id="dot"></span><span id="connection">Waiting for sensor data</span></div></nav>
<p class="eyebrow">Arduino UNO Q · Live gait identification</p>
<h1>Who's walking?</h1>
<p class="sub">Three sensors. One live identity prediction. The dashboard updates automatically after each 1-second inference window.</p>
<div class="grid"><section class="card hero"><div class="kicker">CURRENT DETECTION</div><div class="prediction" id="prediction">CONNECTING</div><div class="info" id="description">Waiting for the classifier to start...</div><div class="tag" id="vote">5-window consensus · —</div></section>
<section class="card"><div class="kicker">IDENTITY MODEL</div><div class="score"><span>Harsh</span><strong id="harsh-score">—</strong></div><div class="track"><div class="fill" id="harsh-fill"></div></div><div class="legend"><span>Harsh score</span><span>Karvy score</span></div><div class="score"><span>Karvy</span><strong id="karvy-score">—</strong></div><div class="tag" style="margin-top:18px" id="second">Recording second · —</div><p class="mini">Scores compare the two known identities only. No Footsteps is determined by a separate activity detector, not an additional ML class.</p></section></div>
<div class="lower"><section class="card"><h2>Sensor data completeness</h2><div class="quality"><div class="qline"><span>MEMS microphone · A0</span><strong id="mic-pct">—</strong></div><div class="qbar"><div class="qinner" id="mic-bar"></div></div></div><div class="quality"><div class="qline"><span>Piezoelectric disc · A1</span><strong id="piezo-pct">—</strong></div><div class="qbar"><div class="qinner" id="piezo-bar"></div></div></div><div class="quality"><div class="qline"><span>MPU6050 · I²C</span><strong id="mpu-pct">—</strong></div><div class="qbar"><div class="qinner" id="mpu-bar"></div></div></div><p class="mini">Completeness is the percentage of usable readings in the last processed window, not signal intensity.</p></section>
<section class="card"><h2>Recent detection history</h2><div class="timeline" id="timeline"></div><ul class="events" id="events"><li>Waiting for first reading...</li></ul></section></div>
<footer>Private local dashboard · Data is processed on the UNO Q · When the stream stops, the display automatically marks the data stale.</footer>
</main>
<script>
const el=id=>document.getElementById(id);
const safeText=(id,val)=>el(id).textContent=val;
function setQuality(name,value){const v=(typeof value==='number'&&isFinite(value))?Math.max(0,Math.min(1,value)):null;safeText(name+'-pct',v===null?'—':(v*100).toFixed(1)+'%');el(name+'-bar').style.width=v===null?'0%':(v*100)+'%';}
function update(d){const age=Date.now()/1000-(d.updated_at||0);const fresh=d.updated_at>0&&age<7;el('dot').className='dot'+(fresh?' online':'');safeText('connection',!d.updated_at?'Waiting for first reading':fresh?'Streaming live':'No recent updates');
 const st=fresh?d.status:'stale';const label=fresh?(d.prediction||'WAITING'):'WAITING FOR DATA';safeText('prediction',label);el('prediction').className='prediction '+(fresh?st:'calibrating');
 const messages={identified:'Footsteps detected · identity prediction active',idle:'No footsteps detected · identity classifier paused',calibrating:'Quiet calibration in progress · please do not walk',detecting:'Movement detected · waiting for confirmation',stale:'No new readings received · check the App Lab Python console',starting:'Waiting for sensor data'};
 safeText('description',messages[st]||'Waiting for readings');safeText('vote','5-window consensus · '+(fresh&&d.vote?d.vote:'—'));
 const scores=fresh&&st==='identified'&&typeof d.harsh_score==='number';safeText('harsh-score',scores?(100*d.harsh_score).toFixed(1)+'%':'—');safeText('karvy-score',scores?(100*d.karvy_score).toFixed(1)+'%':'—');el('harsh-fill').style.width=scores?(100*d.harsh_score)+'%':'50%';
 safeText('second','Recording second · '+(d.second??'—'));setQuality('mic',fresh?d.mic_quality:null);setQuality('piezo',fresh?d.piezo_quality:null);setQuality('mpu',fresh?d.mpu_quality:null);
 const h=d.history||[];const timeline=el('timeline');timeline.replaceChildren();h.slice(-35).forEach(x=>{const tick=document.createElement('div');tick.className='tick '+x.status;tick.title=x.second+'s · '+x.prediction;timeline.appendChild(tick)});
 const items=el('events');items.replaceChildren();h.slice(-5).reverse().forEach(x=>{const li=document.createElement('li');const a=document.createElement('span');a.textContent=x.prediction;const b=document.createElement('small');b.textContent=x.second+'s';li.append(a,b);items.appendChild(li)});if(!h.length){const li=document.createElement('li');li.textContent='Waiting for first reading...';items.appendChild(li)}
}
async function poll(){try{const r=await fetch('/api/live',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);update(await r.json())}catch(e){safeText('connection','Dashboard connection lost');el('dot').className='dot';safeText('description','Unable to reach the UNO Q WebUI API')}}
poll();setInterval(poll,1000);
</script></body></html>"""

# Route HTML directly from main.py: no extra files or assets tab needed.
_dashboard_web = WebUI(assets_dir_path="/app/_footstep_dashboard_no_assets")
_dashboard_web.expose_api(
    "GET", "/", lambda: HTMLResponse(content=_DASHBOARD_HTML)
)
_dashboard_web.expose_api(
    "GET", "/api/live", lambda: dict(_dashboard_state)
)
print("Footstep live dashboard will be available on WebUI port 7000")

App.run(user_loop=loop)
