"""Generate an add-on board schematic: addon-keys or addon-encoders.

Run from the repo root, once per build:
    python hardware/addon/gen_addon.py keys
    python hardware/addon/gen_addon.py encoders
    "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe" sch upgrade --force hardware/addon-keys/addon-keys.kicad_sch
    "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe" sch upgrade --force hardware/addon-encoders/addon-encoders.kicad_sch

Add-on for the Guition ESP32-S3-4848S040 panel: plugs into the 2x4 header on
its back (where the 230 V power/relay module would go) and hangs below the
display. Two boards from one script:
- keys: three MX switches in hot-swap sockets with a warm-white 1206 LED in
  each, the radar on a break-away piece at the bar's left end
- encoders: two Bourns PEC11R encoders with push, as far apart as the
  enclosure allows, the radar between them
Both: CH32V003A4M6 co-processor (I2C slave to the panel on GPIO1/GPIO2, UART
to the HLK-LD2402 radar), a bare SHT40 on a U-tab at the bar's right end,
3.3 V LDO, 5 V in from solder pads or an optional USB-C, and the panel powered
through the header. The co-processor's pins do the same jobs on both boards
(one firmware, told which board it is on). Hand-solder parts throughout (1206,
SOT-223, SOIC-16), apart from the SHT40 (1.5 mm DFN: hot air, or extended pads
and patience).
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "tools"))
from schgen import Schematic  # noqa: E402

BUILD = sys.argv[1] if len(sys.argv) > 1 else ""
if BUILD not in ("keys", "encoders"):
    sys.exit("usage: gen_addon.py keys|encoders")
PROJECT = f"addon-{BUILD}"
OUTDIR = ROOT / "hardware" / PROJECT

sch = Schematic(PROJECT, paper="A3", title=f"Guition 4848S040 add-on ({BUILD}): radar, SHT40")
R1206 = "Resistor_SMD:R_1206_3216Metric_Pad1.30x1.75mm_HandSolder"
C1206 = "Capacitor_SMD:C_1206_3216Metric_Pad1.33x1.80mm_HandSolder"
LED1206 = "LED_SMD:LED_1206_3216Metric_Pad1.42x1.75mm_HandSolder"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{:02d}_P2.54mm_Vertical"


def R(ref, val, lcsc, a, b, at, **kw):
    return sch.add("Device:R_Small", ref, val, at, fp=R1206, lcsc=lcsc, pins={"1": a, "2": b}, **kw)


def C(ref, val, lcsc, a, b, at, **kw):
    return sch.add("Device:C_Small", ref, val, at, fp=C1206, lcsc=lcsc, pins={"1": a, "2": b}, **kw)


# Co-processor pins for the keys or encoders (same pins on both boards):
# PC6/PC7/PC0 are TIM1 CH1-CH3 (remap 1): hardware PWM for the key LEDs, and PC6/PC7 are
# TIM1's encoder-mode inputs for encoder 1.
IO = {"keys": {"PC6": "LED1", "PC7": "LED2", "PC0": "LED3", "PC3": "K1", "PA1": "K2", "PC4": "K3"},
      "encoders": {"PC6": "E1_A", "PC7": "E1_B", "PC0": "E2_A", "PC3": "E1_SW", "PA1": "E2_B",
                   "PC4": "E2_SW"}}[BUILD]

# --- power: 5 V in, panel header, 3.3 V LDO -------------------------------------------------
sch.text("Power: 5 V from the solder pads (J2) or the optional USB-C (J3), never both and never with\n"
         "the panel's own USB. No reverse-polarity protection: mark + and - clearly. The panel is fed\n"
         "through J1; U1 makes 3.3 V for the co-processor, radar and SHT40.", (20, 20), size=1.5)
# Pin numbers are the panel's H1 (Guition schematic): 1/2 GND, 3 IO40 (relay 1), 4 U0RXD,
# 5 IO2 (relay 2), 6 U0TXD, 7 IO1 (relay 3), 8 5V. No 3.3 V on H1. IO40/IO2/IO1 reach H1
# through 0R links R25-R27 on the panel (R21-R23 instead send them to the audio amplifier).
sch.add("Connector_Generic:Conn_02x04_Odd_Even", "J1", "GUITION H1", (45, 60),
        fp="addon:Guition_H1_2x04_P2.54mm_Mating",
        pins={"1": "GND", "2": "GND", "5": "SCL", "7": "SDA", "8": "+5V"}, nc=["3", "4", "6"],
        fields={"Note": "plugs into the panel's H1; SDA = IO1 (pin 7), SCL = IO2 (pin 5); "
                        "IO40 and the ESP's UART0 (pins 4, 6) unused. Needs R25-R27 fitted on the panel."})
sch.add("Connector_Generic:Conn_01x02", "J2", "5V IN (+ -)", (45, 90),
        fp="Connector_Wire:SolderWire-0.5sqmm_1x02_P4.6mm_D0.9mm_OD2.1mm",
        pins={"1": "+5V", "2": "GND"}, fields={"Note": "wire pads on the wall side; tie the wires down for strain relief"})
sch.add("Connector:USB_C_Receptacle_PowerOnly_6P", "J3", "USB-C 5V (optional)", (45, 130),
        fp="addon:USB_C_Receptacle_SHOU-HAN_TYPE-C-6P", lcsc="C456012", dnp=True,
        pins={"A9": "+5V", "B9": "+5V", "A12": "GND", "B12": "GND", "SH": "GND",
              "A5": "CC1", "B5": "CC2"},
        fields={"Note": "optional, power only; fit instead of wiring J2"})
R("R1", "4.7k", "C17936", "CC1", "GND", (75, 140), dnp=True,
  fields={"Note": "USB-C sink Rd (5.1k +-20 %), only with J3"})
R("R2", "4.7k", "C17936", "CC2", "GND", (85, 140), dnp=True,
  fields={"Note": "USB-C sink Rd (5.1k +-20 %), only with J3"})
C("C1", "10u", "C7467044", "+5V", "GND", (100, 75))
sch.add("Regulator_Linear:AMS1117-3.3", "U1", "LDL1117S33R", (125, 70),
        fp="Package_TO_SOT_SMD:SOT-223-3_TabPin2", lcsc="C435835",
        pins={"1": "GND", "2": "+3V3", "3": "+5V"},
        fields={"Note": "ST LDL1117S33R: AMS1117 pinout, stable with ceramic capacitors"})
C("C2", "10u", "C7467044", "+3V3", "GND", (150, 75), fields={"Note": "LDO output"})
sch.add("power:PWR_FLAG", "#FLG01", "PWR_FLAG", (100, 100), pins={"1": "+5V"})
sch.add("power:PWR_FLAG", "#FLG02", "PWR_FLAG", (115, 100), pins={"1": "GND"})

# --- co-processor ------------------------------------------------------------------------------
sch.text("Co-processor: CH32V003A4M6 (SOP-16), I2C slave to the panel; the panel polls it.\n"
         "Same pins on both boards: PC6/PC7/PC0 = key LEDs (TIM1 remap 1 PWM) or encoder 1 A/B and\n"
         "encoder 2 A; PC3/PA1/PC4 = keys 1-3 or encoder 1 push / encoder 2 B / encoder 2 push.\n"
         "Flash with a WCH-LinkE on J4 (SWIO, 3V3, GND).", (190, 20), size=1.5)
sch.add("MCU_WCH_RiscV:CH32V003AxMx", "U2", "CH32V003A4M6", (225, 90),
        fp="addon:SOIC-16_3.9x9.9mm_P1.27mm_HandSolder", lcsc="C5346357",
        pins={"VDD": "+3V3", "VSS": "GND",
              "PC1": "SDA", "PC2": "SCL",
              "PD5": "RADAR_RX", "PD6": "RADAR_TX", "PD4": "RADAR_OUT",
              "PD1": "SWIO", **IO},
        nc=["PD7", "PA2"],
        fields={"Note": "PD5 = USART1 TX, PD6 = RX; PC1/PC2 = I2C1; PD7 (NRST) and PA2 spare"})
C("C3", "100n", "C24497", "+3V3", "GND", (255, 70), fields={"Note": "at U2 VDD"})
R("R3", "4.7k", "C17936", "+3V3", "SDA", (170, 110), fields={"Note": "I2C pull-up"})
R("R4", "4.7k", "C17936", "+3V3", "SCL", (180, 110), fields={"Note": "I2C pull-up"})
sch.add("Connector_Generic:Conn_01x03", "J4", "SWIO 3V3 GND", (275, 100), fp=HDR.format(3), dnp=True,
        pins={"1": "SWIO", "2": "+3V3", "3": "GND"}, fields={"Note": "WCH-LinkE programming pads"})
sch.add("Sensor_Humidity:SHT4x", "U5", "SHT40-AD1B-R2", (285, 130),
        fp="addon:Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_HandSolder", lcsc="C2909890",
        pins={"SDA": "SDA", "SCL": "SCL", "VDD": "+3V3", "VSS": "GND"},
        fields={"Note": "I2C 0x44; at the free end of the U-tab at the bar's right end"})
C("C4", "100n", "C24497", "+3V3", "GND", (265, 130), fields={"Note": "on the SHT40's U-tab"})

# --- radar ----------------------------------------------------------------------------------------
where = ("on a break-away piece at the bar's left end, under key 1 (snap it off to build\n"
         "without the radar)." if BUILD == "keys" else
         "between the two encoders (leave it off to build without the radar).")
sch.text("Radar: HLK-LD2402 soldered on its own 2.5 mm header, antenna side out, " + where + "\n"
         "Check the module's print: 1 VCC, 2 OUT, 3 GND, 4 TX, 5 RX (Hi-Link manual p. 7).",
         (190, 165), size=1.5)
sch.add("addon:HLK-LD2402", "U3", "HLK-LD2402", (215, 205), fp="addon:HLK-LD2402",
        pins={"1": "+3V3", "2": "RADAR_OUT", "3": "GND", "4": "RADAR_TX", "5": "RADAR_RX"},
        fields={"Variant": "optional"})

if BUILD == "keys":
    sch.text("Keys: MX switches (HanElectricity CPG151101D13,\n"
             "LCSC C49234235) in CPG151101S11-16 hot-swap sockets, a 1206\n"
             "warm-white LED in each switch's LED slot (3.3 V, 100 R: ~4-6 mA).",
             (320, 20), size=1.5)
    for i in range(3):
        y = 55 + 30 * i
        sch.add("Switch:SW_Push", f"SW{i + 1}", f"KEY {i + 1}", (335, y), fp="addon:SW_MX_Hotswap_CPG151101S11",
                lcsc="C41430893", pins={"1": f"K{i + 1}", "2": "GND"},
                fields={"Note": "LCSC is the socket; switch CPG151101D13 C49234235"})
        R(f"R{i + 5}", "100", "C17901", f"LED{i + 1}", f"LED{i + 1}_A", (365, y))
        sch.add("Device:LED", f"D{i + 1}", "warm white 1206", (390, y), fp=LED1206,
                pins={"1": "GND", "2": f"LED{i + 1}_A"},
                fields={"Note": "2700-3000 K 1206 white LED (not stocked by LCSC; e.g. Electrokit 40307556)"})
else:
    sch.text("Encoders: Bourns PEC11R-4215F-S0024 (24 pulses, push\n"
             "switch) for 25 mm knobs, as far apart as the enclosure's\n"
             "5 mm border and 1 mm gap allow.", (320, 20), size=1.5)
    for i in range(2):
        e = f"E{i + 1}"
        sch.add("Device:RotaryEncoder_Switch_MP", f"ENC{i + 1}", "PEC11R-4215F-S0024", (345 + 40 * i, 70),
                fp="addon:RotaryEncoder_Bourns_PEC11R-4xxxF-Sxxxx_Vertical", lcsc="C143790",
                pins={"A": f"{e}_A", "B": f"{e}_B", "C": "GND", "S1": f"{e}_SW", "S2": "GND", "MP": "GND"})

OUTDIR.mkdir(exist_ok=True)
for table in ("sym-lib-table", "fp-lib-table"):     # the project-local "addon" library
    shutil.copyfile(pathlib.Path(__file__).with_name(table), OUTDIR / table)
out = OUTDIR / f"{PROJECT}.kicad_sch"
sch.save(out)
print(f"wrote {out} ({len(sch.parts)} parts)")
